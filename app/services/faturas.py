import calendar
import datetime as dt
from typing import Optional

from app.models.card import Cartao


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
