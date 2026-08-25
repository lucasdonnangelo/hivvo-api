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
    MSG_VENCIMENTO_ANTES_DO_FECHAMENTO,
    CartaoComFaturaResponse,
    CartaoCreate,
    CartaoResponse,
    CartaoUpdate,
    fechamento_vencimento_coerentes,
)
from app.services.faturas import (
    _TIPOS_AVULSA_FATURA,
    _current_open_fatura,
    cartao_tem_lancamentos,
    valor_avulsa_liquido,
)

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
                # Par INSEPARÁVEL de _cond_avulsas_fatura: quem soma avulsas soma
                # o valor LÍQUIDO, nunca Transacao.valor cru. Antes daqui a soma
                # era `tipo == "despesa"` com o valor cru, então o MESMO estorno
                # abatia em GET /cards/{id}/invoices e no "A pagar" e NÃO abatia
                # aqui — dois números para a mesma fatura, em duas telas.
                func.sum(valor_avulsa_liquido),
            )
            .where(
                Transacao.usuario_id == current_user.id,
                Transacao.cartao_id.in_(card_ids),
                Transacao.parcelado == False,
                Transacao.tipo.in_(_TIPOS_AVULSA_FATURA),
            )
            .group_by(Transacao.cartao_id, Transacao.fatura_mes, Transacao.fatura_ano)
        ).all()
    }

    # `tem_lancamentos` sai de graça dos mesmos maps (parcela não cancelada +
    # avulsa despesa/estorno) — MESMA composição de cartao_tem_lancamentos, sem
    # query extra. Presença do cartao_id em qualquer competência.
    #
    # A afirmação "por construção" que estava aqui era FALSA enquanto a soma
    # filtrava `tipo == "despesa"`: cartão com APENAS estorno reportava False
    # contra o True do canônico. Passar a soma pela composição fecha isso.
    cartoes_com_lancamento = {cid for (cid, _, _) in parcelas_map} | {
        cid for (cid, _, _) in avulsas_map
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
                tem_lancamentos=card.id in cartoes_com_lancamento,
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

    data = body.model_dump(exclude_unset=True)

    # Bloqueio: alterar dia_fechamento/dia_vencimento/mes_offset_vencimento de um
    # cartão COM compras congelaria o fatura_mes já materializado enquanto as
    # leituras que invertem a materialização passariam a usar o valor novo →
    # incoerência silenciosa (reprocessar mudaria faturas pagas indetectavelmente;
    # decisão: bloquear e o usuário cria um novo cartão). mes_offset_vencimento
    # entra na mesma inversão (data_fechamento_fatura via _competencia_menos), logo
    # corrompe igual. Só barra quando o valor MUDA de fato — valores iguais aos
    # atuais (edição de outros campos) passam; cartão SEM compras edita livremente.
    muda_datas = (
        ("dia_fechamento" in data and data["dia_fechamento"] != card.dia_fechamento)
        or ("dia_vencimento" in data and data["dia_vencimento"] != card.dia_vencimento)
        or (
            "mes_offset_vencimento" in data
            and data["mes_offset_vencimento"] != card.mes_offset_vencimento
        )
    )
    if muda_datas and cartao_tem_lancamentos(session, current_user.id, card.id):
        raise HTTPException(
            status_code=422,
            detail=(
                "Não é possível alterar o fechamento ou vencimento de um cartão "
                "com compras lançadas. Crie um novo cartão."
            ),
        )

    # Fechamento×vencimento: update é PARCIAL — mescla o que veio com o que está
    # no cartão e valida o RESULTADO, mas SÓ quando o update toca algum campo da
    # regra. Assim edição de nome/limite num cartão pré-existente inválido
    # (nascido antes da validação do create) não trava. Borda documentada em
    # PENDENCIAS #34: cartão inválido COM lançamentos fica preso — o 422 acima
    # bloqueia mudar as datas.
    campos_regra = {"dia_fechamento", "dia_vencimento", "mes_offset_vencimento"}
    if campos_regra & data.keys():
        resultado = {c: data.get(c, getattr(card, c)) for c in campos_regra}
        if not fechamento_vencimento_coerentes(**resultado):
            raise HTTPException(
                status_code=422, detail=MSG_VENCIMENTO_ANTES_DO_FECHAMENTO
            )

    for field, value in data.items():
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
