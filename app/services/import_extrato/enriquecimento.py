"""Enriquecimento do preview de extrato (Batch 2) — as peças que precisam do BANCO.

Por linha, o que a revisão precisa para decidir — SEM decidir nada e SEM escrever:

1. `debito`/`receita` -> `categoria_sugerida`: uma chamada ÚNICA ao Gemini para
   TODAS as linhas (gemini.categorizar_linhas), com a MESMA lista de categorias e
   o MESMO guarda-corpo do /ai/suggest-category (services/categorias).
2. `pagamento_fatura` -> `fatura_proposta`: PROPÕE cartão+competência (match
   único / ambíguo / sem-match). O valor é sinal de confiança, NÃO filtro — o
   usuário confirma na revisão (Batch 4). NADA de PagamentoFatura é gravado aqui.
3. `receita` -> `provavel_recorrencia`: flag da armadilha do salário — a receita
   casa com uma recorrência vigente (≈valor + ≈dia)? Só FLAG; o default "não
   importar" é da revisão.
4. TODOS os baldes -> `data_suspeita`: a data cai fora do período do documento
   (#46). Puro, sem banco, sem modelo — a única peça daqui que não precisa de
   I/O, e mora neste módulo porque o CANAL de saída é o mesmo.

STATELESS: só SELECT, sempre filtrado por usuario_id. Zero escrita — nem add, nem
flush, nem commit (garantido por teste com listener de before_flush).

Orçamento de queries FIXO (independente do nº de linhas, zero N+1):
cartões 1 · totais de fatura 2 por ano tocado · PagamentoFatura 1 ·
recorrências+vigências 2 · categorias 2. Cada bloco só roda se o balde existir.

PII/logs: descrição e valor NUNCA vão para log — só contadores.
"""

from __future__ import annotations

import datetime as dt
import logging
import unicodedata
from collections import defaultdict
from decimal import Decimal
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models.card import Cartao
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.schemas.import_extrato import (
    Balde,
    EnriquecimentoLinha,
    ExtratoExtraido,
    FaturaCandidataOut,
    FaturaPropostaOut,
    LinhaExtrato,
    RecorrenciaCasadaOut,
)
from app.services.categorias import casar_categoria, nomes_categorias_do_usuario
from app.services.estatisticas import _recorrencias_com_vigencias
from app.services.faturas import (
    faturas_pagas_atingidas,
    totais_fatura_por_cartao_ano,
    vencimento_avulsa,
)
from app.services.import_extrato import gemini
from app.services.import_extrato.reconciliacao import CENT, TOLERANCIA
from app.services.recorrencias import data_ocorrencia, valor_no_mes

logger = logging.getLogger(__name__)

# Janela entre a DATA do pagamento no extrato e o VENCIMENTO da fatura. Pagar
# alguns dias antes/depois do vencimento é o normal. Chute calibrado, constante
# de módulo (mesma decisão da TOLERANCIA da reconciliação): pagamento muito
# atrasado cai em sem_match — conservador, o usuário corrige na revisão.
JANELA_DIAS_PAGAMENTO = 10

# Casamento receita×recorrência. Salário líquido varia mês a mês (INSS/IR/faltas)
# e cai em dia útil — por isso tolerância RELATIVA no valor e janela no dia.
# Errar para MAIS (flagar um freelance de valor parecido) é recuperável na
# revisão — a flag é default com override; errar para MENOS duplica o salário.
TOLERANCIA_VALOR_RECORRENCIA_PCT = Decimal("0.05")
JANELA_DIAS_RECORRENCIA = 5

# Nome curto demais casaria qualquer coisa por contenção ("Nu" em "Nubank").
_MIN_CHARS_NOME_CARTAO = 3

_MOTIVO_SEM_CARTOES = "Você não tem cartões cadastrados."
_MOTIVO_FATURA_NAO_IMPORTADA = (
    "Fatura não importada — importe a fatura desse cartão para ver o detalhe."
)

# Balde -> tipo de categoria. pagamento_fatura NÃO entra: não é consumo, não tem
# categoria (vira PagamentoFatura).
_TIPO_POR_BALDE = {Balde.debito: "despesa", Balde.receita: "receita"}


# --- Matchers PUROS (sem I/O) — testáveis isolados e alvos da mutação ---------


def _normalizar_nome(bruto: str) -> str:
    """casefold + sem acento + só alfanumérico ("Itaú Uniclass" -> "itauuniclass")."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", bruto) if unicodedata.category(c) != "Mn"
    )
    return "".join(ch for ch in sem_acento.casefold() if ch.isalnum())


def casar_cartoes_por_nome(
    cartoes: Iterable[Cartao], cartao_citado: Optional[str]
) -> list[Cartao]:
    """Cartões do usuário que podem ser o emissor citado na linha.

    `cartao_citado` é o banco NOMEADO no extrato ("Nubank"); `Cartao.nome` é
    texto livre do usuário ("Nubank Ultravioleta"). Contenção nos DOIS sentidos
    cobre os dois lados serem mais específicos que o outro.

    Citado ausente (a linha não nomeia banco) ou curto demais para discriminar
    -> TODOS os cartões entram como candidatos: quem desempata é a competência
    (data ≈ vencimento) e o valor. Filtrar aqui esconderia o match verdadeiro.
    """
    cartoes = list(cartoes)
    alvo = _normalizar_nome(cartao_citado) if cartao_citado else ""
    if len(alvo) < _MIN_CHARS_NOME_CARTAO:
        return cartoes
    casados = []
    for cartao in cartoes:
        nome = _normalizar_nome(cartao.nome)
        if len(nome) >= _MIN_CHARS_NOME_CARTAO and (alvo in nome or nome in alvo):
            casados.append(cartao)
    return casados


def _competencia_deslocada(mes: int, ano: int, delta: int) -> tuple[int, int]:
    total = ano * 12 + (mes - 1) + delta
    return total % 12 + 1, total // 12


def competencias_candidatas(
    cartao: Cartao, data: dt.date, janela_dias: int = JANELA_DIAS_PAGAMENTO
) -> list[tuple[int, int, int]]:
    """[(fatura_mes, fatura_ano, distancia_em_dias)] que um pagamento em `data` quita.

    `fatura_mes/fatura_ano` JÁ SÃO o mês do VENCIMENTO (materializados por
    _fatura_cartao_avulso) — então a competência sai invertendo o vencimento com
    `vencimento_avulsa` (fonte única, trata dia ausente como fim do mês), sem
    reimplementar ciclo de fatura. Varre a competência da data e as duas
    vizinhas: paga-se no fim do mês a fatura do mês seguinte e vice-versa.
    """
    candidatas = []
    for delta in (-1, 0, 1):
        mes, ano = _competencia_deslocada(data.month, data.year, delta)
        distancia = abs((vencimento_avulsa(cartao, mes, ano) - data).days)
        if distancia <= janela_dias:
            candidatas.append((mes, ano, distancia))
    return candidatas


def datas_suspeitas(extrato: ExtratoExtraido) -> dict[int, str]:
    """{indice: motivo} das linhas com data FORA do período do documento (#46).

    Aqui vale o intervalo INTEIRO — `data < periodo.de` ou `data > periodo.ate` —,
    regra mais forte que a da fatura (que só tem limite superior). A diferença
    não é rigor arbitrário: o período do extrato é um intervalo REAL impresso no
    documento, sem parcela antiga esticando a faixa para trás, então o limite
    inferior é confiável e não é circular.

    Motiva: a extração já devolveu a MESMA compra do MESMO PDF com um mês de
    diferença, e a reconciliação passou (ela soma valores; o valor estava certo).
    Uma data fora do período vira lançamento no mês errado sem nenhum sinal.

    SINALIZA, nunca corrige, nunca bloqueia.

    DEGRADA EM SILÊNCIO SEGURO em DOIS casos, e nenhum deles é erro:
    - `periodo` ausente (opcional no contrato: o commit exige, o preview tolera);
    - período INVERTIDO (`de > ate`). O preview não o rejeita — só o commit o
      faz. Sem esta guarda, uma âncora incoerente flagaria TODAS as linhas, o
      falso positivo mais barulhento possível. Âncora que não se sustenta não
      opina.
    """
    if extrato.periodo is None:
        return {}
    de = dt.date.fromisoformat(extrato.periodo.de)
    ate = dt.date.fromisoformat(extrato.periodo.ate)
    if de > ate:
        return {}

    suspeitas: dict[int, str] = {}
    for i, linha in enumerate(extrato.linhas):
        data = dt.date.fromisoformat(linha.data)
        if data < de:
            suspeitas[i] = "antes_do_periodo"
        elif data > ate:
            suspeitas[i] = "depois_do_periodo"
    return suspeitas


def casar_recorrencia(
    recs_com_vigencias: Iterable[tuple[Recorrencia, list[RecorrenciaVigencia]]],
    data: dt.date,
    valor: Decimal,
) -> Optional[tuple[Recorrencia, Decimal, int, int]]:
    """A recorrência que provavelmente já explica esta receita, ou None.

    Devolve (recorrência, valor_vigente, competencia_mes, competencia_ano).
    Três condições, TODAS necessárias:
    - vige na competência: `valor_no_mes` devolve None quando nenhuma vigência a
      cobre — o "dentro da vigência" sai de graça, sem reimplementar período;
    - ≈valor: |valor − vigente| <= vigente × TOLERANCIA_VALOR_RECORRENCIA_PCT;
    - ≈dia: |data − data_ocorrencia| <= JANELA_DIAS_RECORRENCIA (data_ocorrencia
      já clampa dia 31 ao último dia do mês).

    Só recorrência de RECEITA: uma despesa recorrente não explica entrada de
    caixa. Testa as competências vizinhas (o salário do dia 1 pode cair no dia
    30 anterior). Empate: menor distância de dia, depois de valor, depois id
    (determinístico — a busca de recorrências não é ordenada).
    """
    melhor: Optional[tuple[tuple, Recorrencia, Decimal, int, int]] = None
    for rec, vigencias in recs_com_vigencias:
        if rec.tipo != "receita":
            continue
        for delta in (-1, 0, 1):
            mes, ano = _competencia_deslocada(data.month, data.year, delta)
            vigente = valor_no_mes(rec, vigencias, mes, ano)
            if vigente is None:
                continue
            diferenca_valor = abs(valor - vigente)
            if diferenca_valor > vigente * TOLERANCIA_VALOR_RECORRENCIA_PCT:
                continue
            distancia = abs((data - data_ocorrencia(rec, mes, ano)).days)
            if distancia > JANELA_DIAS_RECORRENCIA:
                continue
            chave = (distancia, diferenca_valor, str(rec.id))
            if melhor is None or chave < melhor[0]:
                melhor = (chave, rec, vigente, mes, ano)
    if melhor is None:
        return None
    return melhor[1], melhor[2], melhor[3], melhor[4]


# --- Blocos de enriquecimento (leem o banco) ---------------------------------


def _sugerir_categorias(
    session: Session, usuario_id: int, linhas: list[LinhaExtrato], indices: list[int]
) -> dict[int, Optional[str]]:
    """{indice: categoria} para débitos e receitas — UMA chamada ao Gemini.

    DEDUP por (tipo, descrição normalizada) antes de enviar: extrato repete muito
    a mesma descrição ("Compra no débito UBER" ×8) e o pedido encolhe sem perda
    relevante (assumido: mesma descrição com valores diferentes recebe a mesma
    categoria).

    DEGRADAÇÃO GRACIOSA: falha da categorização NÃO derruba o preview — a
    extração (cara) já foi paga. Cai para None em todas as linhas ("não foi
    possível sugerir", distinto de "Outros", que é palpite). É o que torna
    seguro estender o preview em vez de criar um /enrich separado.
    """
    if not indices:
        return {}

    nomes = {
        "despesa": nomes_categorias_do_usuario(session, usuario_id, "despesa"),
        "receita": nomes_categorias_do_usuario(session, usuario_id, "receita"),
    }

    pedidos: list[gemini.PedidoCategoria] = []
    indice_do_pedido: dict[tuple[str, str], int] = {}
    chave_da_linha: dict[int, tuple[str, str]] = {}
    for i in indices:
        linha = linhas[i]
        tipo = _TIPO_POR_BALDE[linha.balde]
        chave = (tipo, linha.descricao.strip().casefold())
        chave_da_linha[i] = chave
        if chave not in indice_do_pedido:
            indice_do_pedido[chave] = len(pedidos)
            pedidos.append(
                gemini.PedidoCategoria(
                    indice=len(pedidos),
                    descricao=linha.descricao,
                    valor=linha.valor,
                    tipo=tipo,
                )
            )

    try:
        crus = gemini.categorizar_linhas(pedidos, nomes["despesa"], nomes["receita"])
    except HTTPException as e:
        # Degradação DELIBERADA (preview sem sugestão é melhor que preview
        # nenhum), mas nunca cega. Loga-se `detail`, não a classe: TODO caminho
        # de falha de `categorizar_linhas` levanta HTTPException — as 6 causas de
        # API viram 503 e o schema rejeitado vira 502 —, então `__class__` era
        # uma CONSTANTE, uma linha com cara de diagnóstico e zero bits. O
        # `detail` é string NOSSA (app/core/gemini_erros), não da API: diz a
        # causa sem risco de PII. A causa crua já saiu no log do gemini_erros.
        logger.warning(
            "[import] categorização indisponível (%s: %s) — preview segue sem sugestão",
            e.status_code, e.detail,
        )
        return {i: None for i in indices}
    except Exception:
        # O que NENHUM handler acima viu — aqui o traceback é a única pista, e a
        # ausência dele foi o que travou o diagnóstico do #38. Não loga a
        # exceção formatada por nós; o exc_info não expande locals (o Sentry roda
        # com include_local_variables=False).
        logger.warning(
            "[import] categorização indisponível por falha inesperada — "
            "preview segue sem sugestão",
            exc_info=True,
        )
        return {i: None for i in indices}

    sugeridas: dict[int, Optional[str]] = {}
    for i in indices:
        tipo, _ = chave = chave_da_linha[i]
        cru = crus.get(indice_do_pedido[chave])
        # Item omitido pela resposta: a chamada funcionou, só falta este ->
        # "Outros" (a lista do usuário sempre o tem), não None.
        sugeridas[i] = casar_categoria(cru, nomes[tipo]) if cru is not None else "Outros"
    return sugeridas


def _propor_faturas(
    session: Session, usuario_id: int, linhas: list[LinhaExtrato], indices: list[int]
) -> dict[int, FaturaPropostaOut]:
    """{indice: proposta} para as linhas de pagamento_fatura — PROPÕE, não decide."""
    if not indices:
        return {}

    cartoes = session.exec(
        select(Cartao).where(Cartao.usuario_id == usuario_id).order_by(Cartao.id)  # type: ignore[arg-type]
    ).all()

    # 1) Candidatas PURAS (sem banco): cartão do emissor × competência na janela.
    brutas: list[tuple[int, Cartao, int, int, int]] = []
    sem_cartao: dict[int, str] = {}
    for i in indices:
        linha = linhas[i]
        data = dt.date.fromisoformat(linha.data)
        do_emissor = casar_cartoes_por_nome(cartoes, linha.cartao_citado)
        if not do_emissor:
            sem_cartao[i] = (
                f'Nenhum cartão seu corresponde a "{linha.cartao_citado}".'
                if linha.cartao_citado
                else _MOTIVO_SEM_CARTOES
            )
            continue
        for cartao in do_emissor:
            for mes, ano, distancia in competencias_candidatas(cartao, data):
                brutas.append((i, cartao, mes, ano, distancia))

    # 2) Totais das faturas: variante ANUAL (2 queries por ano; o caso normal é
    #    UM ano) em vez de uma consulta por competência.
    totais_por_ano = {
        ano: totais_fatura_por_cartao_ano(session, usuario_id, ano)
        for ano in {ano for _, _, _, ano, _ in brutas}
    }

    # 3) Só fatura que EXISTE (foi importada) vira candidata: ausente do dict de
    #    totais = nenhum lançamento na competência -> "importe a fatura".
    existentes = [
        (i, cartao, mes, ano, distancia, totais_por_ano[ano][(mes, cartao.id)])
        for i, cartao, mes, ano, distancia in brutas
        if (mes, cartao.id) in totais_por_ano[ano]
    ]

    # 4) `ja_paga` em 1 query (reúso da detecção read-only do #9).
    pagas = set(
        faturas_pagas_atingidas(
            session,
            usuario_id,
            {(cartao.id, mes, ano) for _, cartao, mes, ano, _, _ in existentes},
        )
    )

    # 5) Monta e ORDENA por confiança. O valor NÃO filtra: só ranqueia.
    por_linha: dict[int, list[tuple[tuple, FaturaCandidataOut]]] = defaultdict(list)
    for i, cartao, mes, ano, distancia, total in existentes:
        diferenca = (Decimal(linhas[i].valor) - total).quantize(CENT)
        valor_bate = abs(diferenca) <= TOLERANCIA
        chave = (not valor_bate, not cartao.ativo, abs(diferenca), distancia, cartao.id)
        por_linha[i].append(
            (
                chave,
                FaturaCandidataOut(
                    cartao_id=cartao.id,
                    cartao_nome=cartao.nome,
                    fatura_mes=mes,
                    fatura_ano=ano,
                    total_fatura=str(Decimal(total).quantize(CENT)),
                    diferenca=str(diferenca),
                    valor_bate=valor_bate,
                    ja_paga=(cartao.id, mes, ano) in pagas,
                ),
            )
        )

    propostas: dict[int, FaturaPropostaOut] = {}
    for i in indices:
        if i in sem_cartao:
            propostas[i] = FaturaPropostaOut(status="sem_match", motivo=sem_cartao[i])
            continue
        candidatas = [c for _, c in sorted(por_linha.get(i, []), key=lambda item: item[0])]
        if not candidatas:
            propostas[i] = FaturaPropostaOut(
                status="sem_match", motivo=_MOTIVO_FATURA_NAO_IMPORTADA
            )
        else:
            # N candidatas continua AMBÍGUO mesmo com uma de valor exato (ela só
            # vem primeiro): colapsar para match_unico seria usar o valor como
            # filtro rígido. Dois cartões do mesmo banco exigem o usuário dizer
            # qual — o sistema não sabe.
            propostas[i] = FaturaPropostaOut(
                status="match_unico" if len(candidatas) == 1 else "ambiguo",
                candidatas=candidatas,
            )
    return propostas


def _flagar_recorrencias(
    session: Session, usuario_id: int, linhas: list[LinhaExtrato], indices: list[int]
) -> dict[int, tuple[bool, Optional[RecorrenciaCasadaOut]]]:
    """{indice: (provavel, recorrência casada)} para as receitas — só FLAG."""
    if not indices:
        return {}

    # 2 queries fixas (cabeçalhos + vigências), sem N+1 — a MESMA carga da
    # projeção. Não filtra `ativa`: quem governa é a vigência.
    recs = _recorrencias_com_vigencias(session, usuario_id)
    if not recs:
        return {i: (False, None) for i in indices}

    flags: dict[int, tuple[bool, Optional[RecorrenciaCasadaOut]]] = {}
    for i in indices:
        linha = linhas[i]
        casada = casar_recorrencia(
            recs, dt.date.fromisoformat(linha.data), Decimal(linha.valor)
        )
        if casada is None:
            flags[i] = (False, None)
            continue
        rec, vigente, mes, ano = casada
        flags[i] = (
            True,
            RecorrenciaCasadaOut(
                id=rec.id,
                descricao=rec.descricao,
                categoria=rec.categoria,
                valor_vigente=str(Decimal(vigente).quantize(CENT)),
                dia_do_mes=rec.dia_do_mes,
                competencia_mes=mes,
                competencia_ano=ano,
            ),
        )
    return flags


def enriquecer(
    session: Session, usuario_id: int, extrato: ExtratoExtraido
) -> list[EnriquecimentoLinha]:
    """Array PARALELO a extrato.linhas, um item por linha, na mesma ordem.

    Fora de LinhaExtrato de propósito: ela é o response_schema do Gemini de
    extração — engordá-la faria o modelo tentar preencher o enriquecimento.
    """
    linhas = extrato.linhas
    indices_categoria = [i for i, l in enumerate(linhas) if l.balde in _TIPO_POR_BALDE]
    indices_pagamento = [
        i for i, l in enumerate(linhas) if l.balde is Balde.pagamento_fatura
    ]
    indices_receita = [i for i, l in enumerate(linhas) if l.balde is Balde.receita]

    categorias = _sugerir_categorias(session, usuario_id, linhas, indices_categoria)
    faturas = _propor_faturas(session, usuario_id, linhas, indices_pagamento)
    recorrencias = _flagar_recorrencias(session, usuario_id, linhas, indices_receita)
    # Sem banco e sem recorte de balde: a data de QUALQUER linha importada vira a
    # data do lançamento, então todas são checadas.
    suspeitas = datas_suspeitas(extrato)

    enriquecimento = []
    for i in range(len(linhas)):
        provavel, casada = recorrencias.get(i, (False, None))
        enriquecimento.append(
            EnriquecimentoLinha(
                indice=i,
                categoria_sugerida=categorias.get(i),
                fatura_proposta=faturas.get(i),
                provavel_recorrencia=provavel,
                recorrencia_casada=casada,
                data_suspeita=suspeitas.get(i),
            )
        )
    return enriquecimento
