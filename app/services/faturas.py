import calendar
import datetime as dt
from decimal import Decimal
from typing import Optional

from sqlalchemy import and_, case, func, or_
from sqlmodel import Session, select

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.pagamento_fatura import PagamentoFatura
from app.models.transaction import Transacao


def clamp_dia_no_mes(dia: int, ano: int, mes: int) -> int:
    """Clampa um dia ao último dia do mês (dia 31 em fevereiro → 28/29).

    Único ponto do clamp de dia do produto — reusado pelas faturas (vencimento)
    e pela recorrência (data da ocorrência, PLANO_PROJECAO §3.4).
    """
    return min(dia, calendar.monthrange(ano, mes)[1])


def _add_months(d: dt.date, months: int) -> dt.date:
    month = d.month + months
    year = d.year
    while month > 12:
        month -= 12
        year += 1
    return dt.date(year, month, clamp_dia_no_mes(d.day, year, month))


def _data_vencimento_parcela(
    transaction_date: dt.date,
    parcela_num: int,
    card: Optional[Cartao],
) -> dt.date:
    if card and card.dia_vencimento:
        # Determina o mês de fatura da primeira parcela
        if card.dia_fechamento and transaction_date.day > card.dia_fechamento:
            # Compra após fechamento: entra no ciclo do mês seguinte
            base_fatura = _add_months(transaction_date.replace(day=1), 1)
        else:
            base_fatura = transaction_date.replace(day=1)

        # Mês de fatura da parcela i = base + (i-1) meses
        fatura_date = _add_months(base_fatura, parcela_num - 1)

        # Vencimento = mês de fatura + mes_offset_vencimento, no dia_vencimento do cartão
        due_base = _add_months(fatura_date, card.mes_offset_vencimento)
        due_day = clamp_dia_no_mes(card.dia_vencimento, due_base.year, due_base.month)
        return dt.date(due_base.year, due_base.month, due_day)
    else:
        # Sem cartão: i meses a partir da data da compra
        return _add_months(transaction_date, parcela_num)


def _fatura_cartao_avulso(data: dt.date, card: Cartao) -> tuple[int, int]:
    """Retorna (fatura_mes, fatura_ano) para crédito avulso pelo vencimento do cartão."""
    if card.dia_fechamento and data.day > card.dia_fechamento:
        base = _add_months(data.replace(day=1), 1)
    else:
        base = data.replace(day=1)
    due_base = _add_months(base, card.mes_offset_vencimento)
    due_day = clamp_dia_no_mes(card.dia_vencimento, due_base.year, due_base.month)
    due = dt.date(due_base.year, due_base.month, due_day)
    return due.month, due.year


def _competencia_menos(ano: int, mes: int, meses: int) -> tuple[int, int]:
    """(ano, mes) recuado `meses` competências — o inverso de _add_months."""
    total = ano * 12 + (mes - 1) - meses
    return total // 12, total % 12 + 1


def data_fechamento_fatura(card: Cartao, fatura_mes: int, fatura_ano: int) -> dt.date:
    """Último dia em que uma compra NOVA ainda entra na competência (mes, ano).

    Inverte a materialização (_fatura_cartao_avulso/_data_vencimento_parcela):
    competência = mês-base da compra + mes_offset_vencimento, e compra com
    dia > dia_fechamento empurra o mês-base em +1. Logo o fechamento da
    competência é o dia_fechamento (clampado) do mês-base = competência −
    offset. Sem dia_fechamento, toda compra do mês-base entra na competência
    → fecha no último dia do mês-base.

    A fatura está FECHADA quando hoje > data_fechamento (no próprio dia do
    fechamento a compra ainda entra — o `>` da materialização é estrito).
    """
    base_ano, base_mes = _competencia_menos(
        fatura_ano, fatura_mes, card.mes_offset_vencimento
    )
    if card.dia_fechamento:
        dia = clamp_dia_no_mes(card.dia_fechamento, base_ano, base_mes)
    else:
        dia = calendar.monthrange(base_ano, base_mes)[1]
    return dt.date(base_ano, base_mes, dia)


def status_fatura(
    card: Cartao,
    fatura_mes: int,
    fatura_ano: int,
    pagamento: Optional[PagamentoFatura],
    today: dt.date,
    total: Decimal,
    vazia: bool = False,
) -> str:
    """Status derivado da fatura (PLANO_3D — NUNCA materializado):

    - `vazia`: a competência NÃO tem lançamento algum (nenhuma parcela/avulsa) —
      não há o que pagar, logo não é "atrasada" nem "a_vencer". Status neutro:
      o frontend não deve pintar badge de alerta. Checa AUSÊNCIA de lançamento,
      não pagamento — distinto de `paga` (tem lançamento + pago=True). Só o
      detalhe por cartão (`get_invoice`) chega aqui vazio; as demais lentes só
      chamam para faturas que existem.
    - `paga`: pago=True e o pagamento COBRE o total atual (valor_pago >=
      total). Derivado por cobertura (#9): remover compra de fatura parcial
      baixa o total → volta a "paga" sozinha, sem write.
    - `paga_parcial`: pago=True mas a composição cresceu depois (compra
      retroativa) — valor_pago < total atual; falta (total − valor_pago),
      que o "A pagar" das estatísticas reflete (descoberta). valor_pago NULL
      com pago=True não deve existir (CHECK + backfill); se aparecer, degrada
      seguro para "paga" (comportamento pré-cobertura, nunca parcial falsa).
    - `aberta`: a competência ainda aceita compras (hoje <= fechamento).
    - `a_vencer`: fechada, não confirmada (sem registro ou pago=False),
      vencimento >= hoje.
    - `atrasada`: fechada, não confirmada, vencimento < hoje — o usuário
      nunca marca "atrasada"; é consequência de não confirmar + tempo.

    `total` = total ATUAL da fatura, sempre da fonte única da composição
    (_cond_parcelas_fatura/_cond_avulsas_fatura — total_fatura_cartao,
    totais_fatura_por_cartao ou a soma do detalhe).
    Vencimento via `vencimento_avulsa` (nunca None — fallback fim do mês).
    """
    if vazia:
        return "vazia"
    if pagamento is not None and pagamento.pago:
        if pagamento.valor_pago is not None and pagamento.valor_pago < total:
            return "paga_parcial"
        return "paga"
    if today <= data_fechamento_fatura(card, fatura_mes, fatura_ano):
        return "aberta"
    if vencimento_avulsa(card, fatura_mes, fatura_ano) >= today:
        return "a_vencer"
    return "atrasada"


def _fatura_vencimento(card: Cartao, fatura_mes: int, fatura_ano: int) -> Optional[dt.date]:
    if not card.dia_vencimento:
        return None
    day = clamp_dia_no_mes(card.dia_vencimento, fatura_ano, fatura_mes)
    return dt.date(fatura_ano, fatura_mes, day)


def vencimento_avulsa(
    card: Optional[Cartao], fatura_mes: int, fatura_ano: int
) -> dt.date:
    """Vencimento REAL de uma avulsa de cartão faturada em (fatura_mes, fatura_ano).

    fatura_mes/fatura_ano JÁ são o mês de vencimento (materializados por
    _fatura_cartao_avulso na criação) — só falta o DIA, que vem do
    dia_vencimento do cartão (PLANO_PROJECAO §"A pagar e Saldo", furo 1).

    Fallback (cartão apagado/sem dia_vencimento hoje): último dia do mês —
    conservador: crédito com dia desconhecido permanece "a pagar" até virar o
    mês (esconder dívida a vencer seria pior que superestimá-la).
    """
    if card is not None:
        venc = _fatura_vencimento(card, fatura_mes, fatura_ano)
        if venc is not None:
            return venc
    return dt.date(
        fatura_ano, fatura_mes, calendar.monthrange(fatura_ano, fatura_mes)[1]
    )


def _cond_parcelas_fatura(
    usuario_id: int,
    mes: Optional[int],
    ano: Optional[int],
    cartao_id: Optional[int] = None,
) -> list:
    """Condições de "parcela que compõe uma fatura de cartão" na competência.

    HELPER ÚNICO da composição (PLANO_3D §6): get_invoice,
    totais_fatura_por_cartao(_ano), fatura_existe e total_fatura_cartao usam
    as MESMAS condições — a consistência entre as lentes deixa de ser por
    duplicação afirmada em teste e passa a ser por construção. cartao_id=None
    = qualquer cartão (cartao_id != None); parcela SEM cartão nunca pertence
    a fatura. mes=None = ano inteiro (fatura_mes != None) — a variante anual
    da descoberta (#9) agrupa por mês fora daqui. ano=None = TODAS as
    competências (fatura_ano != None) — a lente do limite comprometido
    (limite_usado_por_cartao) agrupa por competência fora daqui.

    Em qualquer combinação, "sem competência" NÃO compõe fatura: parcela com
    fatura_mes/fatura_ano nulo fica de fora mesmo com mes=None/ano=None. É a
    mesma regra do cartao_id (parcela sem cartão não pertence a fatura), e é o
    que faz `tem_lancamentos` precisar de consulta própria
    (cartoes_com_lancamentos) em vez de sair das chaves da composição.
    """
    return [
        Parcela.usuario_id == usuario_id,
        Parcela.fatura_mes == mes if mes is not None
        else Parcela.fatura_mes != None,  # noqa: E711
        Parcela.fatura_ano == ano if ano is not None
        else Parcela.fatura_ano != None,  # noqa: E711
        Parcela.cancelado == False,  # noqa: E712
        Parcela.cartao_id == cartao_id if cartao_id is not None
        else Parcela.cartao_id != None,  # noqa: E711
    ]


# Tipos de Transacao que compõem uma fatura de cartão: a despesa SOMA, o
# estorno SUBTRAI (valor positivo no banco, sinal aplicado na leitura).
_TIPOS_AVULSA_FATURA = ("despesa", "estorno")

# Valor LÍQUIDO de uma avulsa na composição — o par inseparável de
# _cond_avulsas_fatura: quem soma avulsas soma ESTA expressão, nunca
# Transacao.valor cru (senão o estorno somaria em vez de abater).
valor_avulsa_liquido = case(
    (Transacao.tipo == "estorno", -Transacao.valor), else_=Transacao.valor
)


def _cond_avulsas_fatura(
    usuario_id: int,
    mes: Optional[int],
    ano: Optional[int],
    cartao_id: Optional[int] = None,
) -> list:
    """Condições de "avulsa de cartão que compõe uma fatura" na competência
    (parcelado=False, tipo despesa OU estorno) — par do _cond_parcelas_fatura
    (mesmas semânticas de mes=None, ano=None e cartao_id=None). Somas usam
    valor_avulsa_liquido (estorno abate)."""
    return [
        Transacao.usuario_id == usuario_id,
        Transacao.fatura_mes == mes if mes is not None
        else Transacao.fatura_mes != None,  # noqa: E711
        Transacao.fatura_ano == ano if ano is not None
        else Transacao.fatura_ano != None,  # noqa: E711
        Transacao.parcelado == False,  # noqa: E712
        Transacao.tipo.in_(_TIPOS_AVULSA_FATURA),  # type: ignore[attr-defined]
        Transacao.cartao_id == cartao_id if cartao_id is not None
        else Transacao.cartao_id != None,  # noqa: E711
    ]


def total_fatura_cartao(
    session: Session, usuario_id: int, cartao_id: int, mes: int, ano: int
) -> Decimal:
    """Total ATUAL da fatura (cartao_id, mes, ano) — fonte única da composição.

    2 SUMs sobre _cond_parcelas_fatura/_cond_avulsas_fatura — a MESMA
    composição de get_invoice/totais_fatura_por_cartao, por construção.
    Usado onde o total de UMA fatura é preciso fora das lentes de leitura:
    o PUT de pagamento e o import gravam PagamentoFatura.valor_pago com este
    valor (#9 — snapshot da cobertura no instante da confirmação).
    """
    parcelas = session.exec(
        select(func.sum(Parcela.valor_parcela)).where(
            *_cond_parcelas_fatura(usuario_id, mes, ano, cartao_id)
        )
    ).one()
    avulsas = session.exec(
        select(func.sum(valor_avulsa_liquido)).where(
            *_cond_avulsas_fatura(usuario_id, mes, ano, cartao_id)
        )
    ).one()
    return (parcelas or Decimal("0.00")) + (avulsas or Decimal("0.00"))


def fatura_existe(
    session: Session, usuario_id: int, cartao_id: int, mes: int, ano: int
) -> bool:
    """A fatura (cartao_id, mes, ano) tem ao menos um lançamento?

    Validação (a) do PUT de pagamento: só se confirma fatura que EXISTE —
    parcela não cancelada OU avulsa na competência, mesma composição dos
    endpoints de fatura (2 EXISTS com curto-circuito).
    """
    parcela = (
        select(Parcela.id)
        .where(*_cond_parcelas_fatura(usuario_id, mes, ano, cartao_id))
        .limit(1)
    )
    avulsa = (
        select(Transacao.id)
        .where(*_cond_avulsas_fatura(usuario_id, mes, ano, cartao_id))
        .limit(1)
    )
    return (
        session.exec(parcela).first() is not None
        or session.exec(avulsa).first() is not None
    )


def competencias_da_compra(
    session: Session, transacao: Transacao
) -> set[tuple[int, int, int]]:
    """Competências (cartao_id, fatura_mes, fatura_ano) que a compra toca (#9).

    Lê o MATERIALIZADO, nunca recalcula: à vista = a competência gravada na
    própria transação por _fatura_cartao_avulso (1 no máximo); parcelada = as
    competências das parcelas JÁ criadas na sessão (N, uma por parcela).
    Compra sem cartão / sem fatura derivada não toca fatura alguma (vazio) —
    mesma regra da composição (parcela/avulsa sem cartão não pertence a fatura).
    """
    if transacao.cartao_id is None:
        return set()
    if transacao.parcelado:
        rows = session.exec(
            select(Parcela.cartao_id, Parcela.fatura_mes, Parcela.fatura_ano)
            .where(
                Parcela.transacao_id == transacao.id,
                Parcela.cartao_id != None,  # noqa: E711
                Parcela.fatura_mes != None,  # noqa: E711
                Parcela.cancelado == False,  # noqa: E712
            )
            .distinct()
        ).all()
        return {(cartao_id, mes, ano) for cartao_id, mes, ano in rows}
    if transacao.fatura_mes is None or transacao.fatura_ano is None:
        return set()
    return {(transacao.cartao_id, transacao.fatura_mes, transacao.fatura_ano)}


def faturas_pagas_atingidas(
    session: Session, usuario_id: int, competencias: set[tuple[int, int, int]]
) -> list[tuple[int, int, int]]:
    """Subconjunto de `competencias` com PagamentoFatura.pago=True (#9).

    Detecção READ-ONLY do aviso "compra caiu em fatura já paga": 1 query na
    chave natural (cartao_id, fatura_mes, fatura_ano), SEMPRE filtrada por
    usuario_id (isolamento no código). Não materializa nada nem toca
    status_fatura — só informa. Ordenado por (ano, mes, cartao_id) para
    resposta determinística.
    """
    if not competencias:
        return []
    chaves = [
        and_(
            PagamentoFatura.cartao_id == cartao_id,
            PagamentoFatura.fatura_mes == mes,
            PagamentoFatura.fatura_ano == ano,
        )
        for cartao_id, mes, ano in competencias
    ]
    rows = session.exec(
        select(
            PagamentoFatura.cartao_id,
            PagamentoFatura.fatura_mes,
            PagamentoFatura.fatura_ano,
        ).where(
            PagamentoFatura.usuario_id == usuario_id,
            PagamentoFatura.pago == True,  # noqa: E712
            or_(*chaves),
        )
    ).all()
    return sorted(
        ((cartao_id, mes, ano) for cartao_id, mes, ano in rows),
        key=lambda c: (c[2], c[1], c[0]),
    )


def cartao_tem_lancamentos(session: Session, usuario_id: int, cartao_id: int) -> bool:
    """O cartão tem ao menos uma compra lançada (em QUALQUER competência)?

    "Compra" = a MESMA composição da fatura, sem o filtro de competência:
    parcela não cancelada OU avulsa de cartão (parcelado=False, tipo
    despesa/estorno) vinculada ao cartão. Espelho de :func:`fatura_existe`
    sem mes/ano (2 EXISTS com curto-circuito).

    Usado para BLOQUEAR a edição de dia_fechamento/dia_vencimento de um cartão
    com compras (mudar as datas congelaria o `fatura_mes` já materializado das
    compras enquanto as leituras que invertem a materialização passariam a usar
    o dia novo → incoerência silenciosa). Cartão SEM compras edita livremente.
    """
    parcela = (
        select(Parcela.id)
        .where(
            Parcela.usuario_id == usuario_id,
            Parcela.cartao_id == cartao_id,
            Parcela.cancelado == False,  # noqa: E712
        )
        .limit(1)
    )
    avulsa = (
        select(Transacao.id)
        .where(
            Transacao.usuario_id == usuario_id,
            Transacao.cartao_id == cartao_id,
            Transacao.parcelado == False,  # noqa: E712
            Transacao.tipo.in_(_TIPOS_AVULSA_FATURA),  # type: ignore[attr-defined]
        )
        .limit(1)
    )
    return (
        session.exec(parcela).first() is not None
        or session.exec(avulsa).first() is not None
    )


def cartoes_com_lancamentos(
    session: Session, usuario_id: int, cartao_ids: list[int]
) -> set[int]:
    """Subconjunto de `cartao_ids` que tem ao menos uma compra lançada.

    Variante multi-cartão de :func:`cartao_tem_lancamentos` — MESMA composição
    (parcela não cancelada OU avulsa de cartão despesa/estorno, em QUALQUER
    competência), 2 DISTINCT no banco em vez de 2 EXISTS por cartão (N+1).

    NÃO sai das chaves de :func:`totais_fatura_por_cartao_competencia`, e a
    diferença é o motivo de existir: a composição da FATURA exige competência
    (fatura_mes/ano != None), e uma avulsa de cartão SEM dia_vencimento é
    gravada com fatura_mes nulo (routers/transactions: a competência só é
    derivada quando o cartão tem dia_vencimento). Derivar `tem_lancamentos` da
    composição diria "sem compras" para esse cartão enquanto o PUT continuaria
    barrando a edição de datas com 422 — o front habilitaria um campo que o
    servidor recusa. A pergunta aqui é "tem compra?", não "compõe fatura?".
    """
    if not cartao_ids:
        return set()

    parcelas = session.exec(
        select(Parcela.cartao_id)
        .where(
            Parcela.usuario_id == usuario_id,
            Parcela.cartao_id.in_(cartao_ids),  # type: ignore[attr-defined]
            Parcela.cancelado == False,  # noqa: E712
        )
        .distinct()
    ).all()
    avulsas = session.exec(
        select(Transacao.cartao_id)
        .where(
            Transacao.usuario_id == usuario_id,
            Transacao.cartao_id.in_(cartao_ids),  # type: ignore[attr-defined]
            Transacao.parcelado == False,  # noqa: E712
            Transacao.tipo.in_(_TIPOS_AVULSA_FATURA),  # type: ignore[attr-defined]
        )
        .distinct()
    ).all()
    return set(parcelas) | set(avulsas)


def totais_fatura_por_cartao(
    session: Session, usuario_id: int, mes: int, ano: int
) -> dict[int, Decimal]:
    """{cartao_id: total} das faturas de TODOS os cartões na competência (mes, ano).

    Fonte única da composição da fatura (a MESMA do GET
    /cards/{id}/invoices/{ano}/{mes} — ver invoices.get_invoice): parcelas não
    canceladas (SUM valor_parcela) + avulsas de cartão (parcelado=False, tipo
    despesa/estorno; SUM valor_avulsa_liquido — estorno abate) cuja
    fatura_mes/ano == (mes, ano) — condições compartilhadas em
    _cond_parcelas_fatura/_cond_avulsas_fatura. Agrega no banco (SUM GROUP BY
    cartao_id), em vez de varrer objeto a objeto.

    Só entram CARTÕES (cartao_id != None): a lente 3d é "1 mês × N cartões".
    Parcela sem cartão (cartao_id None) não pertence à fatura de cartão algum.
    Só cartões COM lançamento na competência aparecem no dict (sem zeros).
    """
    totais: dict[int, Decimal] = {}

    parcelas_rows = session.exec(
        select(
            Parcela.cartao_id,
            func.sum(Parcela.valor_parcela),
        )
        .where(*_cond_parcelas_fatura(usuario_id, mes, ano))
        .group_by(Parcela.cartao_id)
    ).all()

    avulsas_rows = session.exec(
        select(
            Transacao.cartao_id,
            func.sum(valor_avulsa_liquido),
        )
        .where(*_cond_avulsas_fatura(usuario_id, mes, ano))
        .group_by(Transacao.cartao_id)
    ).all()

    for cartao_id, total in parcelas_rows:
        totais[cartao_id] = totais.get(cartao_id, Decimal("0.00")) + (total or Decimal("0.00"))
    for cartao_id, total in avulsas_rows:
        totais[cartao_id] = totais.get(cartao_id, Decimal("0.00")) + (total or Decimal("0.00"))

    return totais


def totais_fatura_por_cartao_ano(
    session: Session, usuario_id: int, ano: int
) -> dict[tuple[int, int], Decimal]:
    """{(fatura_mes, cartao_id): total} das faturas do ANO inteiro.

    Variante anual de :func:`totais_fatura_por_cartao` — mesmas condições
    (_cond_* com mes=None), GROUP BY (fatura_mes, cartao_id), 2 queries fixas
    para o ano. Consumidor: a descoberta anual do "A pagar" (#9,
    estatisticas.descoberta_faturas_ano) — a projeção precisa dos totais mês a
    mês sem 12× as queries mensais.
    """
    totais: dict[tuple[int, int], Decimal] = {}

    parcelas_rows = session.exec(
        select(
            Parcela.fatura_mes,
            Parcela.cartao_id,
            func.sum(Parcela.valor_parcela),
        )
        .where(*_cond_parcelas_fatura(usuario_id, None, ano))
        .group_by(Parcela.fatura_mes, Parcela.cartao_id)
    ).all()

    avulsas_rows = session.exec(
        select(
            Transacao.fatura_mes,
            Transacao.cartao_id,
            func.sum(valor_avulsa_liquido),
        )
        .where(*_cond_avulsas_fatura(usuario_id, None, ano))
        .group_by(Transacao.fatura_mes, Transacao.cartao_id)
    ).all()

    for rows in (parcelas_rows, avulsas_rows):
        for mes, cartao_id, total in rows:
            chave = (mes, cartao_id)
            totais[chave] = totais.get(chave, Decimal("0.00")) + (
                total or Decimal("0.00")
            )

    return totais


def totais_fatura_por_cartao_competencia(
    session: Session, usuario_id: int, cartao_ids: list[int]
) -> dict[tuple[int, int, int], Decimal]:
    """{(cartao_id, fatura_mes, fatura_ano): total} de TODAS as competências.

    Variante sem recorte de tempo de :func:`totais_fatura_por_cartao_ano` —
    mesmas condições (_cond_* com mes=None E ano=None), GROUP BY (cartao_id,
    fatura_mes, fatura_ano), 2 queries fixas para o histórico INTEIRO de N
    cartões. Inclui competência FUTURA: as parcelas de uma compra em 24x são
    materializadas todas na criação (services/parcelas, import_fatura), então
    "todas as competências" é leitura do banco, nunca projeção.

    Só cartões COM lançamento aparecem (sem zeros), como nas outras lentes.
    """
    if not cartao_ids:
        return {}

    totais: dict[tuple[int, int, int], Decimal] = {}

    parcelas_rows = session.exec(
        select(
            Parcela.cartao_id,
            Parcela.fatura_mes,
            Parcela.fatura_ano,
            func.sum(Parcela.valor_parcela),
        )
        .where(
            *_cond_parcelas_fatura(usuario_id, None, None),
            Parcela.cartao_id.in_(cartao_ids),  # type: ignore[attr-defined]
        )
        .group_by(Parcela.cartao_id, Parcela.fatura_mes, Parcela.fatura_ano)
    ).all()

    avulsas_rows = session.exec(
        select(
            Transacao.cartao_id,
            Transacao.fatura_mes,
            Transacao.fatura_ano,
            func.sum(valor_avulsa_liquido),  # estorno ABATE (par inseparável)
        )
        .where(
            *_cond_avulsas_fatura(usuario_id, None, None),
            Transacao.cartao_id.in_(cartao_ids),  # type: ignore[attr-defined]
        )
        .group_by(Transacao.cartao_id, Transacao.fatura_mes, Transacao.fatura_ano)
    ).all()

    for rows in (parcelas_rows, avulsas_rows):
        for cartao_id, mes, ano, total in rows:
            chave = (cartao_id, mes, ano)
            totais[chave] = totais.get(chave, Decimal("0.00")) + (
                total or Decimal("0.00")
            )

    return totais


def limite_usado_por_cartao(
    session: Session,
    usuario_id: int,
    cartao_ids: list[int],
    totais: dict[tuple[int, int, int], Decimal],
) -> dict[int, Decimal]:
    """{cartao_id: comprometido} — quanto do limite do cartão está preso.

    NÃO é a fatura aberta. É a soma do que resta em aberto em TODAS as
    competências (passadas, corrente e futuras), abatida pelo que o usuário
    confirmou ter pago:

        comprometido = Σ_competência ( total_c − cobertura_c )
        cobertura_c  = min(valor_pago_c, total_c)  se pago=True
                     = 0                           caso contrário

    O clamp é POR FATURA, e é o ponto todo. `valor_pago` é SNAPSHOT do total no
    instante da confirmação (models/pagamento_fatura), não derivado: cancelar
    uma parcela ou lançar um estorno DEPOIS de marcar paga deixa valor_pago
    ACIMA do total atual. Somar Σ(valor_pago) global deixaria essa sobra
    escapar da competência e liberar limite em OUTRA — crédito fantasma. Com
    `min`, a fatura devolve no máximo o que ela mesma pesa.

    É o mesmo kernel de cobertura que já decide o status (`status_fatura`:
    valor_pago >= total → paga, menor → paga_parcial) e a descoberta
    (estatisticas._soma_descobertas, cujo `if valor_pago < total` É este
    clamp). Reescrito por metades: fatura não confirmada contribui `total_c`
    inteiro; fatura pago=True contribui exatamente a sua descoberta.

    Sinal: competência com estorno maior que a despesa tem total_c NEGATIVO e
    DEVE devolver limite — por isso a cobertura de fatura não confirmada é 0
    fixo, e não min(0, total_c), que anularia a devolução. O resultado por
    cartão não é clampado em zero pela mesma razão.

    `totais` vem de :func:`totais_fatura_por_cartao_competencia` (o chamador já
    o tem para a fatura aberta) — aqui é 1 query, a dos pagamentos.
    """
    usado = {cartao_id: Decimal("0.00") for cartao_id in cartao_ids}
    if not cartao_ids:
        return usado

    # Só pago=True: ausência de registro E pago=False são ambos "não
    # confirmado" (models/pagamento_fatura). O filtro não depende do PUT
    # limpar valor_pago no reverso — o CHECK só exige valor_pago QUANDO pago,
    # não proíbe sobra em pago=False.
    pagos = {
        (cartao_id, mes, ano): valor_pago
        for cartao_id, mes, ano, valor_pago in session.exec(
            select(
                PagamentoFatura.cartao_id,
                PagamentoFatura.fatura_mes,
                PagamentoFatura.fatura_ano,
                PagamentoFatura.valor_pago,
            ).where(
                PagamentoFatura.usuario_id == usuario_id,
                PagamentoFatura.cartao_id.in_(cartao_ids),  # type: ignore[attr-defined]
                PagamentoFatura.pago == True,  # noqa: E712
            )
        ).all()
    }

    for (cartao_id, mes, ano), total in totais.items():
        if cartao_id not in usado:
            continue
        valor_pago = pagos.get((cartao_id, mes, ano))
        # valor_pago NULL com pago=True não deve existir (CHECK + backfill);
        # se aparecer, degrada seguro para "não cobre nada" — nunca libera
        # limite que ninguém confirmou ter pago.
        cobertura = (
            min(valor_pago, total) if valor_pago is not None else Decimal("0.00")
        )
        usado[cartao_id] += total - cobertura

    return usado


def _competencias_com_fatura(session: Session, usuario_id: int) -> set[tuple[int, int]]:
    """Conjunto de competências (ano, mes) que têm ao menos uma fatura de cartão.

    Mesma composição de :func:`totais_fatura_por_cartao` (parcelas não
    canceladas + avulsas de cartão), mas só as chaves distintas de competência
    — barato (DISTINCT no banco), sem materializar totais.
    """
    parcelas = session.exec(
        select(Parcela.fatura_ano, Parcela.fatura_mes)
        .where(
            Parcela.usuario_id == usuario_id,
            Parcela.cartao_id != None,  # noqa: E711
            Parcela.fatura_mes != None,  # noqa: E711
            Parcela.cancelado == False,  # noqa: E712
        )
        .distinct()
    ).all()
    avulsas = session.exec(
        select(Transacao.fatura_ano, Transacao.fatura_mes)
        .where(
            Transacao.usuario_id == usuario_id,
            Transacao.cartao_id != None,  # noqa: E711
            Transacao.fatura_mes != None,  # noqa: E711
            Transacao.parcelado == False,  # noqa: E712
            Transacao.tipo.in_(_TIPOS_AVULSA_FATURA),  # type: ignore[attr-defined]
        )
        .distinct()
    ).all()
    return {(ano, mes) for ano, mes in parcelas} | {(ano, mes) for ano, mes in avulsas}


def proxima_fatura_a_vencer(
    session: Session, usuario_id: int, today: dt.date
) -> tuple[int, int]:
    """(ano, mes) da PRÓXIMA fatura a vencer — mês em que o Dashboard 3d ABRE.

    Regra: a primeira competência (varrendo do mês corrente para frente) que
    tem ao menos UMA fatura com vencimento >= hoje.
    - Competência FUTURA (> corrente): qualifica de imediato (todo vencimento
      cai num mês à frente, logo >= hoje).
    - Competência CORRENTE: qualifica só se algum cartão com fatura no mês tem
      vencimento (derivado do dia_vencimento, via `vencimento_avulsa` — que
      trata dia ausente como fim do mês) >= hoje. Se todas já venceram, segue
      para a próxima competência.
    Competências passadas (< corrente) nunca contam (já venceram — são
    "vencidas", não "a vencer").

    Fallback: o mês corrente (neutro) quando não há nenhuma fatura a vencer —
    a tela sempre recebe um mês para abrir.
    """
    corrente = (today.year, today.month)
    competencias = sorted(
        c for c in _competencias_com_fatura(session, usuario_id) if c >= corrente
    )
    for ano, mes in competencias:
        if (ano, mes) > corrente:
            return ano, mes
        # Competência corrente: precisa de ao menos um cartão a vencer.
        totais = totais_fatura_por_cartao(session, usuario_id, mes, ano)
        cartoes = {
            c.id: c
            for c in session.exec(
                select(Cartao).where(
                    Cartao.usuario_id == usuario_id,
                    Cartao.id.in_(list(totais)),  # type: ignore[attr-defined]
                )
            )
        }
        if any(
            vencimento_avulsa(cartoes.get(cid), mes, ano) >= today for cid in totais
        ):
            return ano, mes
    return corrente


def _current_open_fatura(card: Cartao, today: dt.date) -> tuple[int, int, Optional[dt.date]]:
    """Retorna (fatura_mes, fatura_ano, data_vencimento) da fatura aberta atual."""
    if card.dia_fechamento and today.day > card.dia_fechamento:
        base = _add_months(today.replace(day=1), 1)
    else:
        base = today.replace(day=1)
    due_base = _add_months(base, card.mes_offset_vencimento)
    fatura_mes = due_base.month
    fatura_ano = due_base.year
    venc = _fatura_vencimento(card, fatura_mes, fatura_ano)
    return fatura_mes, fatura_ano, venc
