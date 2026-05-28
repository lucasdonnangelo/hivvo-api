import calendar
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import extract
from sqlmodel import Session, select

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.transaction import Transacao
from app.models.user import Usuario
from app.schemas.transaction import (
    TransacaoCreate,
    TransacaoCreateResponse,
    TransacaoResponse,
    TransacaoUpdate,
)

router = APIRouter(prefix="/transactions", tags=["transactions"])


def _add_months(d: dt.date, months: int) -> dt.date:
    month = d.month + months
    year = d.year
    while month > 12:
        month -= 12
        year += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


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
        due_day = min(card.dia_vencimento, calendar.monthrange(due_base.year, due_base.month)[1])
        return dt.date(due_base.year, due_base.month, due_day)
    else:
        # Sem cartão: i meses a partir da data da compra
        return _add_months(transaction_date, parcela_num)


def _criar_parcelas(session: Session, transacao: Transacao, card: Optional[Cartao]) -> int:
    total = transacao.total_parcelas
    valor_base = (transacao.valor / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    valor_ultima = (transacao.valor - valor_base * (total - 1)).quantize(Decimal("0.01"))

    for i in range(1, total + 1):
        valor_parcela = valor_ultima if i == total else valor_base
        data_venc = _data_vencimento_parcela(transacao.data, i, card)

        parcela = Parcela(
            usuario_id=transacao.usuario_id,
            transacao_id=transacao.id,
            numero_parcela=i,
            total_parcelas=total,
            valor_parcela=valor_parcela,
            data_vencimento=data_venc,
            fatura_mes=data_venc.month,  # derivado da data_vencimento da parcela
            fatura_ano=data_venc.year,
            descricao=f"{transacao.descricao} ({i}/{total})",
            categoria=transacao.categoria,
            cartao_id=transacao.cartao_id,
        )
        session.add(parcela)

    session.commit()
    return total


def _fatura_cartao_avulso(data: dt.date, card: Cartao) -> tuple[int, int]:
    """Retorna (fatura_mes, fatura_ano) para crédito avulso pelo vencimento do cartão."""
    if card.dia_fechamento and data.day > card.dia_fechamento:
        base = _add_months(data.replace(day=1), 1)
    else:
        base = data.replace(day=1)
    due_base = _add_months(base, card.mes_offset_vencimento)
    due_day = min(card.dia_vencimento, calendar.monthrange(due_base.year, due_base.month)[1])
    due = dt.date(due_base.year, due_base.month, due_day)
    return due.month, due.year


@router.get("", response_model=list[TransacaoResponse])
def list_transactions(
    mes: Optional[int] = Query(None, ge=1, le=12),
    ano: Optional[int] = Query(None, ge=2000),
    tipo: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    forma_pagamento: Optional[str] = Query(None),
    valor_min: Optional[Decimal] = Query(None),
    valor_max: Optional[Decimal] = Query(None),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    stmt = select(Transacao).where(Transacao.usuario_id == current_user.id)

    if mes is not None:
        stmt = stmt.where(extract("month", Transacao.data) == mes)
    if ano is not None:
        stmt = stmt.where(extract("year", Transacao.data) == ano)
    if tipo:
        stmt = stmt.where(Transacao.tipo == tipo)
    if categoria:
        stmt = stmt.where(Transacao.categoria == categoria)
    if forma_pagamento:
        stmt = stmt.where(Transacao.forma_pagamento == forma_pagamento)
    if valor_min is not None:
        stmt = stmt.where(Transacao.valor >= valor_min)
    if valor_max is not None:
        stmt = stmt.where(Transacao.valor <= valor_max)

    stmt = stmt.order_by(Transacao.data.desc())
    return session.exec(stmt).all()


@router.post("", response_model=TransacaoCreateResponse, status_code=status.HTTP_201_CREATED)
def create_transaction(
    body: TransacaoCreate,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    card = None
    if body.cartao_id:
        card = session.get(Cartao, body.cartao_id)
        if not card or card.usuario_id != current_user.id:
            raise HTTPException(status_code=404, detail="Cartão não encontrado")

    transacao = Transacao(
        usuario_id=current_user.id,
        tipo=body.tipo,
        data=body.data,
        descricao=body.descricao,
        valor=body.valor,
        categoria=body.categoria,
        forma_pagamento=body.forma_pagamento,
        tipo_gasto=body.tipo_gasto,
        origem=body.origem,
        cartao_id=body.cartao_id,
        parcelado=body.parcelado,
        total_parcelas=body.total_parcelas,
    )

    # Crédito avulso: calcula fatura_mes/fatura_ano pelo dia de vencimento do cartão
    if not body.parcelado and card and card.dia_vencimento:
        transacao.fatura_mes, transacao.fatura_ano = _fatura_cartao_avulso(body.data, card)

    session.add(transacao)
    session.commit()
    session.refresh(transacao)

    parcelas_criadas = 0
    if body.parcelado:
        parcelas_criadas = _criar_parcelas(session, transacao, card)
        session.refresh(transacao)  # re-carrega após commit dentro de _criar_parcelas

    return TransacaoCreateResponse.model_validate(
        {**transacao.model_dump(), "parcelas_criadas": parcelas_criadas}
    )


@router.put("/{id}", response_model=TransacaoResponse)
def update_transaction(
    id: int,
    body: TransacaoUpdate,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    transacao = session.get(Transacao, id)
    if not transacao or transacao.usuario_id != current_user.id:
        raise HTTPException(status_code=404, detail="Transação não encontrada")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(transacao, field, value)

    session.add(transacao)
    session.commit()
    session.refresh(transacao)
    return transacao


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    id: int,
    deletar_parcelas: bool = Query(True),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    transacao = session.get(Transacao, id)
    if not transacao or transacao.usuario_id != current_user.id:
        raise HTTPException(status_code=404, detail="Transação não encontrada")

    if transacao.parcelado and deletar_parcelas:
        for p in session.exec(select(Parcela).where(Parcela.transacao_id == id)).all():
            session.delete(p)

    session.delete(transacao)
    session.commit()
