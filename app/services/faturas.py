import calendar
import datetime as dt
from decimal import Decimal
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.card import Cartao
from app.models.installment import Parcela
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


def totais_fatura_por_cartao(
    session: Session, usuario_id: int, mes: int, ano: int
) -> dict[int, Decimal]:
    """{cartao_id: total} das faturas de TODOS os cartões na competência (mes, ano).

    Fonte única da composição da fatura (a MESMA do GET
    /cards/{id}/invoices/{ano}/{mes} — ver invoices.get_invoice): parcelas não
    canceladas (SUM valor_parcela) + avulsas de cartão (parcelado=False,
    tipo='despesa'; SUM valor) cuja fatura_mes/ano == (mes, ano). Agrega no
    banco (SUM GROUP BY cartao_id), em vez de varrer objeto a objeto.

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
        .where(
            Parcela.usuario_id == usuario_id,
            Parcela.cartao_id != None,  # noqa: E711
            Parcela.fatura_mes == mes,
            Parcela.fatura_ano == ano,
            Parcela.cancelado == False,  # noqa: E712
        )
        .group_by(Parcela.cartao_id)
    ).all()

    avulsas_rows = session.exec(
        select(
            Transacao.cartao_id,
            func.sum(Transacao.valor),
        )
        .where(
            Transacao.usuario_id == usuario_id,
            Transacao.cartao_id != None,  # noqa: E711
            Transacao.fatura_mes == mes,
            Transacao.fatura_ano == ano,
            Transacao.parcelado == False,  # noqa: E712
            Transacao.tipo == "despesa",
        )
        .group_by(Transacao.cartao_id)
    ).all()

    for cartao_id, total in parcelas_rows:
        totais[cartao_id] = totais.get(cartao_id, Decimal("0.00")) + (total or Decimal("0.00"))
    for cartao_id, total in avulsas_rows:
        totais[cartao_id] = totais.get(cartao_id, Decimal("0.00")) + (total or Decimal("0.00"))

    return totais


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
            Transacao.tipo == "despesa",
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
