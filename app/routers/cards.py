import calendar
import datetime as dt
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select, func

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.transaction import Transacao
from app.models.user import Usuario
from app.schemas.card import (
    CartaoComFaturaResponse,
    CartaoCreate,
    CartaoResponse,
    CartaoUpdate,
)

router = APIRouter(prefix="/cards", tags=["cards"])


def _add_months(d: dt.date, months: int) -> dt.date:
    month = d.month + months
    year = d.year
    while month > 12:
        month -= 12
        year += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def _fatura_vencimento(card: Cartao, fatura_mes: int, fatura_ano: int) -> Optional[dt.date]:
    if not card.dia_vencimento:
        return None
    day = min(card.dia_vencimento, calendar.monthrange(fatura_ano, fatura_mes)[1])
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


@router.get("", response_model=list[CartaoComFaturaResponse])
def list_cards(
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    cards = session.exec(
        select(Cartao)
        .where(Cartao.usuario_id == current_user.id, Cartao.ativo == True)
        .order_by(Cartao.criado_em)
    ).all()

    today = dt.date.today()
    result = []
    for card in cards:
        fatura_mes, fatura_ano, venc = _current_open_fatura(card, today)

        parcelas_total = session.exec(
            select(func.sum(Parcela.valor_parcela)).where(
                Parcela.cartao_id == card.id,
                Parcela.fatura_mes == fatura_mes,
                Parcela.fatura_ano == fatura_ano,
                Parcela.cancelado == False,
            )
        ).one()

        avulsas_total = session.exec(
            select(func.sum(Transacao.valor)).where(
                Transacao.cartao_id == card.id,
                Transacao.fatura_mes == fatura_mes,
                Transacao.fatura_ano == fatura_ano,
                Transacao.parcelado == False,
                Transacao.tipo == "despesa",
            )
        ).one()

        total = Decimal("0.00")
        if parcelas_total:
            total += parcelas_total
        if avulsas_total:
            total += avulsas_total

        result.append(
            CartaoComFaturaResponse(
                **card.model_dump(),
                fatura_aberta_total=total,
                fatura_aberta_mes=fatura_mes,
                fatura_aberta_ano=fatura_ano,
                fatura_aberta_vencimento=venc,
            )
        )

    return result


@router.post("", response_model=CartaoResponse, status_code=status.HTTP_201_CREATED)
def create_card(
    body: CartaoCreate,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    card = Cartao(
        usuario_id=current_user.id,
        nome=body.nome,
        tipo=body.tipo,
        limite=body.limite,
        dia_vencimento=body.dia_vencimento,
        dia_fechamento=body.dia_fechamento,
        mes_offset_vencimento=body.mes_offset_vencimento,
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


@router.put("/{id}", response_model=CartaoResponse)
def update_card(
    id: int,
    body: CartaoUpdate,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    card = session.get(Cartao, id)
    if not card or card.usuario_id != current_user.id:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(card, field, value)

    session.add(card)
    session.commit()
    session.refresh(card)
    return card


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_card(
    id: int,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    card = session.get(Cartao, id)
    if not card or card.usuario_id != current_user.id:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")

    card.ativo = False
    session.add(card)
    session.commit()
