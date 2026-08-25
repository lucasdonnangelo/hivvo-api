from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.dates import hoje
from app.models.card import Cartao
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
    _current_open_fatura,
    cartao_tem_lancamentos,
    cartoes_com_lancamentos,
    limite_usado_por_cartao,
    totais_fatura_por_cartao_competencia,
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

    # T-17: agregação de TODOS os cartões de uma vez (em vez de 2 queries por
    # cartão — N+1). O map cobre TODAS as competências, e agora as duas leituras
    # que ele alimenta usam recortes DIFERENTES dele:
    #   - fatura_aberta_total → só a competência aberta daquele cartão;
    #   - limite_usado        → o histórico inteiro, abatido pelos pagamentos.
    # Passa pela fonte única da composição (_cond_parcelas/avulsas_fatura), o que
    # traz o estorno junto: `valor_avulsa_liquido` ABATE. Antes daqui a soma era
    # `tipo == "despesa"` com `Transacao.valor` cru, então o mesmo estorno abatia
    # em GET /cards/{id}/invoices e no "A pagar" e NÃO abatia na barra de limite —
    # dois números para a mesma fatura, em duas telas.
    totais = totais_fatura_por_cartao_competencia(session, current_user.id, card_ids)

    # 1 query: os pagamentos confirmados, para a cobertura por fatura.
    usados = limite_usado_por_cartao(session, current_user.id, card_ids, totais)

    # `tem_lancamentos` NÃO sai das chaves de `totais`: a composição da fatura
    # exige competência, e avulsa de cartão sem dia_vencimento é gravada com
    # fatura_mes nulo — sairia "sem compras" aqui e 422 no PUT. Pergunta
    # diferente, consulta própria (ver cartoes_com_lancamentos).
    cartoes_com_lancamento = cartoes_com_lancamentos(session, current_user.id, card_ids)

    result = []
    for card in cards:
        fatura_mes, fatura_ano, venc = abertas[card.id]

        result.append(
            CartaoComFaturaResponse(
                **card.model_dump(),
                fatura_aberta_total=totais.get(
                    (card.id, fatura_mes, fatura_ano), Decimal("0.00")
                ),
                fatura_aberta_mes=fatura_mes,
                fatura_aberta_ano=fatura_ano,
                fatura_aberta_vencimento=venc,
                limite_usado=usados[card.id],
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
