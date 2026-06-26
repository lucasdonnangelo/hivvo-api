from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.transaction import Transacao
from app.models.user import Usuario
from app.schemas.invoice import (
    FaturaDetalhe,
    FaturaListItem,
    ParcelaFaturaResponse,
    TransacaoFaturaResponse,
)
from app.services.faturas import _fatura_vencimento

router = APIRouter(prefix="/cards", tags=["invoices"])


def _get_card_for_user(session: Session, card_id: int, usuario_id: int) -> Cartao:
    card = session.get(Cartao, card_id)
    if not card or card.usuario_id != usuario_id:
        raise HTTPException(status_code=404, detail="Cartão não encontrado")
    return card


@router.get("/{card_id}/invoices", response_model=list[FaturaListItem])
def list_invoices(
    card_id: int,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    card = _get_card_for_user(session, card_id, current_user.id)

    parcelas = session.exec(
        select(Parcela).where(
            Parcela.cartao_id == card_id,
            Parcela.usuario_id == current_user.id,
            Parcela.cancelado == False,
        )
    ).all()

    avulsas = session.exec(
        select(Transacao).where(
            Transacao.cartao_id == card_id,
            Transacao.usuario_id == current_user.id,
            Transacao.parcelado == False,
            Transacao.tipo == "despesa",
            Transacao.fatura_mes != None,
        )
    ).all()

    faturas: dict[tuple[int, int], dict] = {}

    for p in parcelas:
        if p.fatura_mes and p.fatura_ano:
            key = (p.fatura_mes, p.fatura_ano)
            if key not in faturas:
                faturas[key] = {"total": Decimal("0.00"), "pagas": 0, "itens": 0}
            faturas[key]["total"] += p.valor_parcela
            faturas[key]["itens"] += 1
            if p.pago:
                faturas[key]["pagas"] += 1

    for t in avulsas:
        if t.fatura_mes and t.fatura_ano:
            key = (t.fatura_mes, t.fatura_ano)
            if key not in faturas:
                faturas[key] = {"total": Decimal("0.00"), "pagas": 0, "itens": 0}
            faturas[key]["total"] += t.valor
            faturas[key]["itens"] += 1

    return [
        FaturaListItem(
            mes=mes,
            ano=ano,
            total=data["total"],
            data_vencimento=_fatura_vencimento(card, mes, ano),
            total_parcelas_pagas=data["pagas"],
            total_itens=data["itens"],
        )
        for (mes, ano), data in sorted(faturas.items(), key=lambda x: (x[0][1], x[0][0]), reverse=True)
    ]


@router.get("/{card_id}/invoices/{ano}/{mes}", response_model=FaturaDetalhe)
def get_invoice(
    card_id: int,
    ano: int,
    mes: int,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    card = _get_card_for_user(session, card_id, current_user.id)

    parcelas = session.exec(
        select(Parcela)
        .where(
            Parcela.cartao_id == card_id,
            Parcela.usuario_id == current_user.id,
            Parcela.fatura_mes == mes,
            Parcela.fatura_ano == ano,
            Parcela.cancelado == False,
        )
        .order_by(Parcela.data_vencimento)
    ).all()

    avulsas = session.exec(
        select(Transacao)
        .where(
            Transacao.cartao_id == card_id,
            Transacao.usuario_id == current_user.id,
            Transacao.fatura_mes == mes,
            Transacao.fatura_ano == ano,
            Transacao.parcelado == False,
            Transacao.tipo == "despesa",
        )
        # Mesmo desempate determinístico do GET /transactions (T-29): data DESC,
        # id DESC — mesmo dia ordena pela ordem de criação (id maior no topo).
        .order_by(Transacao.data.desc(), Transacao.id.desc())
    ).all()

    total = sum((p.valor_parcela for p in parcelas), Decimal("0.00")) + sum(
        (t.valor for t in avulsas), Decimal("0.00")
    )

    return FaturaDetalhe(
        mes=mes,
        ano=ano,
        total=total,
        data_vencimento=_fatura_vencimento(card, mes, ano),
        parcelas=[ParcelaFaturaResponse.model_validate(p) for p in parcelas],
        avulsas=[TransacaoFaturaResponse.model_validate(t) for t in avulsas],
    )
