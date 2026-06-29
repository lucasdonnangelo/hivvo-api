from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select, func

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.dates import hoje
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
from app.services.faturas import _current_open_fatura

router = APIRouter(prefix="/cards", tags=["cards"])


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
    if not cards:
        return []

    today = hoje()
    abertas = {card.id: _current_open_fatura(card, today) for card in cards}
    card_ids = [card.id for card in cards]

    # T-17: 2 queries GROUP BY cartao_id cobrindo TODOS os cartões de uma vez (em
    # vez de 2 por cartão — N+1). Cada total por cartão é depois lido da tupla da
    # fatura aberta daquele cartão — mesmo filtro do código anterior, valor idêntico.
    parcelas_map = {
        (cid, mes, ano): total
        for cid, mes, ano, total in session.exec(
            select(
                Parcela.cartao_id,
                Parcela.fatura_mes,
                Parcela.fatura_ano,
                func.sum(Parcela.valor_parcela),
            )
            .where(
                Parcela.usuario_id == current_user.id,
                Parcela.cartao_id.in_(card_ids),
                Parcela.cancelado == False,
            )
            .group_by(Parcela.cartao_id, Parcela.fatura_mes, Parcela.fatura_ano)
        ).all()
    }

    avulsas_map = {
        (cid, mes, ano): total
        for cid, mes, ano, total in session.exec(
            select(
                Transacao.cartao_id,
                Transacao.fatura_mes,
                Transacao.fatura_ano,
                func.sum(Transacao.valor),
            )
            .where(
                Transacao.usuario_id == current_user.id,
                Transacao.cartao_id.in_(card_ids),
                Transacao.parcelado == False,
                Transacao.tipo == "despesa",
            )
            .group_by(Transacao.cartao_id, Transacao.fatura_mes, Transacao.fatura_ano)
        ).all()
    }

    result = []
    for card in cards:
        fatura_mes, fatura_ano, venc = abertas[card.id]

        total = Decimal("0.00")
        parcelas_total = parcelas_map.get((card.id, fatura_mes, fatura_ano))
        avulsas_total = avulsas_map.get((card.id, fatura_mes, fatura_ano))
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
