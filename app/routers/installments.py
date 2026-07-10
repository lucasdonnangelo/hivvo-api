from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.installment import Parcela
from app.models.user import Usuario
from app.schemas.installment import ParcelaResponse, ParcelaUpdate

router = APIRouter(prefix="/installments", tags=["installments"])


@router.get("", response_model=list[ParcelaResponse])
def list_installments(
    cartao_id: Optional[int] = Query(None),
    pago: Optional[bool] = Query(None),
    cancelado: Optional[bool] = Query(None),
    mes: Optional[int] = Query(None, ge=1, le=12),
    ano: Optional[int] = Query(None, ge=2000),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    stmt = select(Parcela).where(Parcela.usuario_id == current_user.id)

    if cartao_id is not None:
        stmt = stmt.where(Parcela.cartao_id == cartao_id)
    if pago is not None:
        stmt = stmt.where(Parcela.pago == pago)
    if cancelado is not None:
        stmt = stmt.where(Parcela.cancelado == cancelado)
    if mes is not None:
        stmt = stmt.where(Parcela.fatura_mes == mes)
    if ano is not None:
        stmt = stmt.where(Parcela.fatura_ano == ano)

    stmt = stmt.order_by(Parcela.data_vencimento)
    return session.exec(stmt).all()


@router.put("/{id}", response_model=ParcelaResponse)
def update_installment(
    id: int,
    body: ParcelaUpdate,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    parcela = session.get(Parcela, id)
    if not parcela or parcela.usuario_id != current_user.id:
        raise HTTPException(status_code=404, detail="Parcela não encontrada")

    if parcela.cancelado:
        raise HTTPException(status_code=400, detail="Parcela cancelada não pode ser editada")

    # Leva 2: `pago`/`data_pagamento` não são mais graváveis aqui (o schema
    # rejeita com 422) — pagamento é por fatura, via PagamentoFatura.
    data = body.model_dump(exclude_unset=True)

    for field, value in data.items():
        setattr(parcela, field, value)

    session.add(parcela)
    session.commit()
    session.refresh(parcela)
    return parcela


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_installment(
    id: int,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    parcela = session.get(Parcela, id)
    if not parcela or parcela.usuario_id != current_user.id:
        raise HTTPException(status_code=404, detail="Parcela não encontrada")

    session.delete(parcela)
    session.commit()
