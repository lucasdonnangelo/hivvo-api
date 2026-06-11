from decimal import Decimal
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
from app.services.faturas import _fatura_cartao_avulso
from app.services.parcelas import _criar_parcelas

router = APIRouter(prefix="/transactions", tags=["transactions"])


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
