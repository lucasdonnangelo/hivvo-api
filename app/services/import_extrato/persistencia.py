"""Materialização do extrato importado — Batch 3 (a primeira escrita do fluxo).

Os três baldes do extrato NÃO viram a mesma coisa (PLANO_IMPORTACAO — "extrato e
fatura se RECONCILIAM, não se somam"):

- `receita`  → Transacao(tipo="receita", forma_pagamento="PIX") pela data da
  linha — entrada por transferência na conta, não "Débito";
- `debito`   → Transacao(tipo="despesa", forma_pagamento="Débito") — o dinheiro
  JÁ SAIU na data: SEM cartao_id e SEM fatura_mes/ano. É o que faz a projeção
  tratá-la como consumo realizado (Fonte 3 de services/estatisticas: `a_pagar`
  False por construção) em vez de dívida de cartão a pagar;
- `pagamento_fatura` → NÃO é lançamento: vira PagamentoFatura, registrado pelo
  boundary (routers/import_extrato) com o valor e a data REAIS do extrato.

Mais o `rendimento` do RESUMO (ACHADO 1 do spike), que não é linha e vira uma
receita "Rendimentos" na data final do período.

Nada aqui commita: constrói na sessão e o boundary (router) commita tudo numa
transação única (atomicidade), espelhando services/import_fatura/persistencia.py.
Decimal sempre.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from sqlmodel import Session

from app.models.transaction import Transacao
from app.schemas.import_extrato import Balde, ExtratoCommit, LinhaCommit
from app.services.categorias import casar_categoria, nomes_categorias_do_usuario
from app.services.estatisticas import _recorrencias_com_vigencias
from app.services.import_extrato.enriquecimento import casar_recorrencia

# Proveniência: a MESMA do import de fatura — "veio de importação" é um filtro
# só, e o balde já se distingue por cartao_id/fatura_mes (o extrato nunca os
# preenche). `origem` é string livre no banco (sem CHECK), então reusar não
# custa migration. Distinguir o LOTE de origem exige o link transacao→lote, que
# nenhuma das duas batches tem ainda.
from app.services.import_fatura.persistencia import ORIGEM_IMPORT

# ACHADO 1: o "Rendimento líquido" do resumo é receita de categoria PRÓPRIA —
# hoje uma categoria padrão do produto (services/categorias.CATEGORIAS_PADRAO),
# para o picker conhecê-la e casar_categoria não a rebaixar a "Outros".
CATEGORIA_RENDIMENTO = "Rendimentos"
DESCRICAO_RENDIMENTO = "Rendimento líquido"

# Balde -> tipo de categoria, para revalidar a categoria contra a lista DO
# USUÁRIO. pagamento_fatura não entra: não é consumo, não tem categoria (gêmeo
# do _TIPO_POR_BALDE do enriquecimento, que faz o mesmo recorte no preview).
_TIPO_POR_BALDE = {Balde.debito: "despesa", Balde.receita: "receita"}


@dataclass
class ResultadoMaterializacaoExtrato:
    receitas_criadas: int = 0  # linhas do balde receita (o rendimento tem flag própria)
    debitos_criados: int = 0
    rendimento_importado: bool = False
    linhas_ignoradas: int = 0
    receitas_puladas_recorrencia: int = 0
    # Preenchidos pelo boundary (o PagamentoFatura não é lançamento — ver módulo).
    pagamentos_registrados: int = 0
    pagamentos_sobrescritos: int = 0


def normalizar_banco(bruto: str) -> str:
    """Nome do banco em forma canônica para a CHAVE do lote de idempotência.

    casefold + sem acento + só alfanumérico ("Nubank ", "NUBANK", "Nubank" ->
    "nubank"): o nome vem de texto livre extraído pelo LLM e sem isso o mesmo
    extrato reimportado com caixa/espaço diferente furaria o UNIQUE. Mesma
    normalização de casar_cartoes_por_nome (enriquecimento), pela mesma razão.
    """
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", bruto) if unicodedata.category(c) != "Mn"
    )
    return "".join(ch for ch in sem_acento.casefold() if ch.isalnum())


def resolver_indecisos(
    session: Session, usuario_id: int, linhas: list[LinhaCommit]
) -> tuple[dict[int, bool], int]:
    """{indice: importar?} + quantas receitas o DEFAULT SEGURO deixou de fora.

    `importar` explícito (True/False) SEMPRE vale — o usuário decidiu. Só o
    indeciso (None) passa por aqui, e a regra é a armadilha do salário
    duplicado: uma receita que casa com uma recorrência vigente (≈valor + ≈dia)
    já é contada pela projeção como realizada — importá-la duplicaria o salário.

    O casamento é RECOMPUTADO no servidor (mesmo matcher do preview,
    enriquecimento.casar_recorrencia), nunca lido de uma flag do request: o
    default de segurança não pode depender de o front ter mandado a flag certa.
    Quem quer importar mesmo assim manda `importar: true` — o explícito vence.

    2 queries fixas (cabeçalhos + vigências), e só quando há receita indecisa.
    """
    decisoes: dict[int, bool] = {}
    indecisas_receita = [
        i
        for i, linha in enumerate(linhas)
        if linha.importar is None and linha.balde is Balde.receita
    ]
    for i, linha in enumerate(linhas):
        if linha.importar is not None:
            decisoes[i] = linha.importar
        elif linha.balde is not Balde.receita:
            decisoes[i] = True  # débito/pagamento indeciso entra (não há armadilha)

    if not indecisas_receita:
        return decisoes, 0

    recs = _recorrencias_com_vigencias(session, usuario_id)
    puladas = 0
    for i in indecisas_receita:
        linha = linhas[i]
        casada = (
            casar_recorrencia(
                recs, dt.date.fromisoformat(linha.data), Decimal(linha.valor)
            )
            if recs
            else None
        )
        decisoes[i] = casada is None
        if casada is not None:
            puladas += 1
    return decisoes, puladas


def validar_categorias(
    session: Session, usuario_id: int, linhas: list[LinhaCommit], decisoes: dict[int, bool]
) -> dict[int, str]:
    """{indice: categoria VÁLIDA} para as linhas que serão materializadas.

    Guarda-corpo do "não confia cego no que o front editou": a categoria do
    request passa por casar_categoria contra as categorias DO USUÁRIO (padrão +
    customizadas ativas) — nome desconhecido (payload adulterado, categoria
    apagada no meio do fluxo) vira "Outros" em vez de sujar o banco. É o MESMO
    guarda-corpo que o preview aplica na sugestão do modelo.

    2 queries fixas (uma por tipo), e só quando há linha categorizável.
    """
    indices = [
        i
        for i, linha in enumerate(linhas)
        if decisoes.get(i, True) and linha.balde in _TIPO_POR_BALDE
    ]
    if not indices:
        return {}
    nomes = {
        tipo: nomes_categorias_do_usuario(session, usuario_id, tipo)
        for tipo in ("despesa", "receita")
    }
    return {
        i: casar_categoria(linhas[i].categoria, nomes[_TIPO_POR_BALDE[linhas[i].balde]])
        for i in indices
    }


def agrupar_pagamentos(
    linhas: list[LinhaCommit], decisoes: dict[int, bool]
) -> dict[tuple[int, int, int], tuple[Decimal, dt.date]]:
    """{(cartao_id, fatura_mes, fatura_ano): (valor_total, data_mais_recente)}.

    Função PURA (sem banco), determinística na ordem das chaves. Duas linhas do
    MESMO extrato confirmadas para a MESMA fatura SOMAM num único
    PagamentoFatura: pagar uma fatura em duas transferências (parcial + resto) é
    real, e sobrescrever com a última linha subnotificaria o pago. A data fica
    sendo a MAIS RECENTE — a fatura só foi quitada quando o último valor saiu.
    """
    agrupados: dict[tuple[int, int, int], tuple[Decimal, dt.date]] = {}
    for i, linha in enumerate(linhas):
        if linha.balde is not Balde.pagamento_fatura or not decisoes.get(i, True):
            continue
        chave = (linha.cartao_id, linha.fatura_mes, linha.fatura_ano)
        data = dt.date.fromisoformat(linha.data)
        valor_anterior, data_anterior = agrupados.get(chave, (Decimal("0.00"), data))
        agrupados[chave] = (
            valor_anterior + Decimal(linha.valor),
            max(data_anterior, data),
        )
    return dict(sorted(agrupados.items()))


def materializar_extrato(
    session: Session,
    usuario_id: int,
    extrato: ExtratoCommit,
    decisoes: dict[int, bool],
    categorias: dict[int, str],
    importar_rendimento: bool,
) -> ResultadoMaterializacaoExtrato:
    """Cria as transações dos baldes receita/debito + o rendimento NA SESSÃO.

    Pagamento de fatura NÃO passa por aqui (não é lançamento — vira
    PagamentoFatura no boundary). Linha com decisão "não importar" é contada em
    linhas_ignoradas; linha de valor 0 sai calada (o CHECK `valor > 0` da
    Transacao não a aceitaria e ela não é decisão do usuário, é lixo de
    extração) — a mesma regra da materialização da fatura.
    """
    if extrato.periodo is None:  # o boundary já barrou; defensivo (chave do lote)
        raise ValueError("extrato sem período não pode ser materializado")

    res = ResultadoMaterializacaoExtrato()

    for i, linha in enumerate(extrato.linhas):
        if not decisoes.get(i, True):
            res.linhas_ignoradas += 1
            continue
        if linha.balde is Balde.pagamento_fatura:
            continue
        valor = Decimal(linha.valor)
        if valor == 0:
            continue  # linha degenerada, sai calada
        if linha.balde is Balde.receita:
            _criar_transacao(
                session, usuario_id, "receita",
                dt.date.fromisoformat(linha.data), linha.descricao, valor,
                categorias.get(i, "Outros"), forma_pagamento="PIX",
            )
            res.receitas_criadas += 1
        else:
            _criar_transacao(
                session, usuario_id, "despesa",
                dt.date.fromisoformat(linha.data), linha.descricao, valor,
                categorias.get(i, "Outros"), forma_pagamento="Débito",
            )
            res.debitos_criados += 1

    rendimento = Decimal(extrato.rendimento)
    if importar_rendimento and rendimento > 0:
        # Data = fim do período: o rendimento é do CICLO, não de um dia — e o
        # extrato só o imprime consolidado no resumo.
        # Rendimento NÃO é transferência recebida (não é PIX): é rendimento da
        # própria conta — fica no default de caixa "Débito", como uma receita
        # criada à mão.
        _criar_transacao(
            session, usuario_id, "receita",
            dt.date.fromisoformat(extrato.periodo.ate), DESCRICAO_RENDIMENTO,
            rendimento, CATEGORIA_RENDIMENTO, forma_pagamento="Débito",
        )
        res.rendimento_importado = True

    return res


def _criar_transacao(
    session: Session,
    usuario_id: int,
    tipo: str,
    data: dt.date,
    descricao: str,
    valor: Decimal,
    categoria: str,
    *,
    forma_pagamento: str,
) -> None:
    """Uma avulsa de CAIXA — o denominador comum dos três casos que escrevem.

    SEM cartao_id e SEM fatura_mes/fatura_ano, sempre: extrato é conta, não
    cartão. É o que mantém a linha na Fonte 3 da projeção (à vista, realizada,
    nunca `a_pagar`) — derivar fatura aqui transformaria caixa que JÁ SAIU em
    dívida de crédito, o oposto do balde.

    `forma_pagamento` é decisão do CHAMADOR: débito é a saída pela conta
    ("Débito"); receita de linha é transferência recebida ("PIX" — o valor
    canônico do front; "Débito" numa entrada era simplesmente errado);
    rendimento fica em "Débito" (é da própria conta, não transferência). Só a
    materialização do EXTRATO fixa isso — o default "Débito" do MODELO continua
    valendo para a despesa manual. Refinamento futuro (não agora): detectar PIX
    vs TED pela descrição em vez de fixar "PIX".
    """
    session.add(
        Transacao(
            usuario_id=usuario_id,
            tipo=tipo,
            data=data,
            descricao=descricao,
            valor=valor,
            categoria=categoria,
            forma_pagamento=forma_pagamento,
            tipo_gasto="Variável",
            origem=ORIGEM_IMPORT,
            cartao_id=None,
            fatura_mes=None,
            fatura_ano=None,
            parcelado=False,
            total_parcelas=None,
        )
    )
