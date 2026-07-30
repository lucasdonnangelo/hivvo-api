"""Auto-categoria da fatura — a peça do preview que precisa do BANCO.

A fatura nascia com TODA linha em "Outros" (o extrato já tinha enriquecimento;
a fatura não). Importar seis meses de histórico e ver o Resumo, o donut de
categorias e "maior despesa por categoria" continuarem vazios é o primeiro
contato do usuário com o produto.

TRÊS CAMADAS, aplicadas em ordem, por linha:

1. HISTÓRICO DO USUÁRIO — a descrição da fatura casada contra as Transacao que
   ele JÁ categorizou. Determinístico, personalizado, melhora a cada import.
2. REGRA — `categorias.casar_categoria_detalhado`: prefixo de adquirente
   ("IFD*..." é iFood) e palavra-chave de lojista. É a única camada que funciona
   na PRIMEIRA importação, quando o histórico está vazio.
3. "Outros" — o neutro. `categoria_sugerida=None`; a tela mostra "Outros".

REGRAS QUE NÃO SE NEGOCIAM (e que têm teste, incluindo por MUTAÇÃO):

- A camada 1 NUNCA aprende de "Outros". Um histórico com "Outros" é
  indistinguível de "nunca categorizado" — é o default, não uma decisão.
  Incluí-lo faria o sistema aprender o próprio silêncio.
- A camada 1 filtra por TIPO. Categoria é por tipo no produto; sugerir categoria
  de receita para uma compra é bug.
- EMPATE entre duas categorias não-"Outros" no histórico cai para a camada 2.
  Não se desempata por acaso (nem por id, nem por ordem de query).

STATELESS: só SELECT, sempre filtrado por usuario_id. Zero escrita — nem add,
nem flush, nem commit (garantido por teste com listener de before_flush), igual
ao enriquecimento do extrato.

Orçamento de queries FIXO, independente do nº de linhas: 1 para as categorias
customizadas do usuário + 1 para o histórico (agregado no banco por GROUP BY, o
que limita o custo ao nº de descrições DISTINTAS, não ao de transações). Zero
N+1. A camada 2 é Python puro.

PII/logs: descrição e valor NUNCA vão para log — só contadores.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.models.transaction import Transacao as TransacaoDB
from app.schemas.import_fatura import (
    EnriquecimentoFaturaLinha,
    FaturaCommit,
    FaturaExtraida,
    TipoTransacao,
)
from app.services.categorias import (
    CATEGORIA_NEUTRA,
    casar_categoria,
    casar_categoria_detalhado,
    nomes_categorias_do_usuario,
    validar_nome_categoria,
)
from app.services.import_fatura.descricao import chave_descricao

# Só compra e IOF materializam (persistencia._TIPOS_GASTO). Repetido aqui em vez
# de importado para não criar ciclo entre os dois módulos do pacote.
_TIPOS_GASTO = (TipoTransacao.compra, TipoTransacao.iof)

# Fatura é de CARTÃO DE CRÉDITO: não existe receita nela. Toda linha, inclusive
# o estorno, é categorizada no universo de DESPESA.
TIPO_CATEGORIA_FATURA = "despesa"

# tipo de CATEGORIA -> tipos de Transacao que contam como histórico dele.
# "estorno" entra junto com "despesa" porque a categoria de um estorno É uma
# categoria de despesa (é uma compra devolvida) — ignorá-lo jogaria fora
# histórico bom.
_TIPOS_DB_POR_CATEGORIA = {
    "despesa": ("despesa", "estorno"),
    "receita": ("receita",),
}


def _norm_descricao(descricao: str) -> str:
    """Descrição canônica para o match do histórico — a MESMA chave da dedup de
    parcelada (`descricao.chave_descricao`), e pela mesma razão.

    O rabo " CATEGORIA.CIDADE" que o emissor cola (#40) entra e sai da extração
    sozinho: sem tirá-lo, "SONDAJACANA" no histórico não casaria
    "SONDAJACANA ALIMENTAÇÃO.SAOPAULO" na fatura nova e a camada 1 perderia o
    aprendizado. Aqui o dano é fraco (sugestão pior); na identidade de parcela é
    corrupção — mas é o mesmo drift, então é a mesma função.
    """
    return chave_descricao(descricao)


def categoria_do_historico(
    session: Session, usuario_id: int, tipo_categoria: str
) -> dict[str, str]:
    """{descrição normalizada: categoria} — o que o usuário JÁ decidiu.

    UMA query, agregada NO BANCO (GROUP BY + COUNT): o custo é o número de
    descrições DISTINTAS do usuário, não o de transações. A normalização é feita
    em Python de propósito — `lower(trim(...))` com remoção de acento não é
    portátil entre SQLite e Postgres.

    Voto por MAIORIA de ocorrências por descrição. Duas regras no filtro, e as
    duas são o coração da camada:

    - `categoria != "Outros"`: o default não é decisão. Sem isso o sistema
      aprenderia o próprio silêncio — todo lojista voltaria "Outros" e a camada 2
      nunca seria alcançada.
    - `tipo IN (...)`: categoria é por tipo no produto.

    EMPATE devolve nada para aquela descrição (a chave some do dict) — a linha
    desce para a camada 2 em vez de ser desempatada por acaso.

    Lê só `transacoes`: `Parcela.categoria` é cópia da transação-mãe, e somá-la
    contaria a mesma decisão N vezes (uma por parcela).
    """
    linhas = session.exec(
        select(TransacaoDB.descricao, TransacaoDB.categoria, func.count())
        .where(
            TransacaoDB.usuario_id == usuario_id,
            TransacaoDB.categoria != CATEGORIA_NEUTRA,
            col(TransacaoDB.tipo).in_(_TIPOS_DB_POR_CATEGORIA[tipo_categoria]),
        )
        .group_by(TransacaoDB.descricao, TransacaoDB.categoria)
    ).all()

    votos: dict[str, dict[str, int]] = {}
    for descricao, categoria, quantas in linhas:
        votos.setdefault(_norm_descricao(descricao), {})
        por_categoria = votos[_norm_descricao(descricao)]
        por_categoria[categoria] = por_categoria.get(categoria, 0) + quantas

    vencedores: dict[str, str] = {}
    for chave, por_categoria in votos.items():
        ranking = sorted(por_categoria.items(), key=lambda item: item[1], reverse=True)
        if len(ranking) > 1 and ranking[0][1] == ranking[1][1]:
            continue  # empate: não desempata por acaso — desce para a camada 2
        vencedores[chave] = ranking[0][0]
    return vencedores


def indices_materializaveis(fatura: FaturaExtraida) -> list[int]:
    """Índices das linhas que VIRAM lançamento — as únicas que têm categoria.

    Espelha o recorte de `materializar_fatura`: compra/iof com valor != 0.
    Valor negativo ENTRA (vira Transacao(tipo="estorno") e leva categoria);
    pagamento/ajuste_saldo e linha degenerada (valor 0) ficam de fora.
    """
    return [
        i
        for i, t in enumerate(fatura.transacoes)
        if t.tipo in _TIPOS_GASTO and Decimal(t.valor_brl) != 0
    ]


def _sugerir(
    session: Session, usuario_id: int, fatura: FaturaExtraida, indices: list[int]
) -> dict[int, tuple[Optional[str], Optional[str]]]:
    """{indice: (categoria, origem)} — as três camadas, em ordem.

    `(None, None)` = camada 3: nenhuma camada teve o que dizer.
    """
    if not indices:
        return {}

    nomes = nomes_categorias_do_usuario(session, usuario_id, TIPO_CATEGORIA_FATURA)
    historico = categoria_do_historico(session, usuario_id, TIPO_CATEGORIA_FATURA)

    sugestoes: dict[int, tuple[Optional[str], Optional[str]]] = {}
    for i in indices:
        descricao = fatura.transacoes[i].descricao

        # Camada 1. O vencedor ainda passa por validar_nome_categoria: o usuário
        # pode ter DESATIVADO a categoria depois de usá-la, e aí o histórico
        # aponta para um nome que o picker não oferece mais.
        aprendida = historico.get(_norm_descricao(descricao))
        if aprendida is not None:
            valida = validar_nome_categoria(aprendida, nomes)
            if valida is not None:
                sugestoes[i] = (valida, "historico")
                continue

        # Camada 2.
        categoria, passe = casar_categoria_detalhado(descricao, nomes)
        sugestoes[i] = (categoria, "regra") if passe is not None else (None, None)
    return sugestoes


def enriquecer_fatura(
    session: Session, usuario_id: int, fatura: FaturaExtraida
) -> list[EnriquecimentoFaturaLinha]:
    """Array de auto-categoria do preview, um item por linha MATERIALIZÁVEL.

    Endereçado por `indice` em fatura.transacoes — join explícito, nunca por
    posição: as linhas não-materializáveis (pagamento, ajuste_saldo) não têm item
    e os índices dos que têm continuam sendo os da lista original.
    """
    indices = indices_materializaveis(fatura)
    sugestoes = _sugerir(session, usuario_id, fatura, indices)
    return [
        EnriquecimentoFaturaLinha(
            indice=i,
            categoria_sugerida=sugestoes[i][0],
            origem_sugestao=sugestoes[i][1],
        )
        for i in indices
    ]


def resolver_categorias(
    session: Session, usuario_id: int, fatura: FaturaCommit
) -> dict[int, str]:
    """{indice: categoria FINAL} para o commit — o servidor decide de novo.

    O tri-estado de `TransacaoCommit.categoria`:

    - PRESENTE (inclusive "Outros"): decisão do usuário. Passa pelo guarda-corpo
      `casar_categoria` contra as categorias DO USUÁRIO no tipo da fatura —
      nome desconhecido (payload adulterado, categoria apagada no meio do fluxo)
      vira "Outros" em vez de sujar o banco. Antes deste batch a fatura gravava a
      string do cliente SEM revalidar; o extrato já revalidava.
    - AUSENTE (None): não decidido → RECOMPUTA as camadas 1+2, com as MESMAS
      funções do preview. Nunca lê uma flag do request: o default de segurança
      não pode depender de o front ter mandado a categoria certa.

    É o que dá categoria de verdade ao ESTORNO, que a tela mostra na seção cinza
    sem seletor e portanto nunca decide.

    Custo: as 2 queries do preview só quando há linha indecisa; 1 (as categorias
    do usuário) quando o cliente mandou tudo explícito.
    """
    indices = indices_materializaveis(fatura)
    indecisos = [i for i in indices if fatura.transacoes[i].categoria is None]
    explicitos = [i for i in indices if fatura.transacoes[i].categoria is not None]

    sugestoes = _sugerir(session, usuario_id, fatura, indecisos)
    nomes = (
        nomes_categorias_do_usuario(session, usuario_id, TIPO_CATEGORIA_FATURA)
        if explicitos
        else []
    )

    resolvidas: dict[int, str] = {}
    for i in indices:
        crua = fatura.transacoes[i].categoria
        if crua is None:
            resolvidas[i] = sugestoes[i][0] or CATEGORIA_NEUTRA
        else:
            resolvidas[i] = casar_categoria(crua, nomes)
    return resolvidas
