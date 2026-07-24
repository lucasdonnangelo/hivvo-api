import datetime as dt
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
    AvisoFaturaPaga,
    CompetenciaFatura,
    TransacaoCreate,
    TransacaoCreateResponse,
    TransacaoResponse,
    TransacaoUpdate,
)
from app.services.faturas import (
    _fatura_cartao_avulso,
    competencias_da_compra,
    faturas_pagas_atingidas,
)
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
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # T-12: teto inviolável de 500 por página (clampado, não 422) — "tudo" só pelo
    # /transactions/export. Mantém array nu; envelope {items,total} é passo futuro.
    limit = min(limit, 500)

    stmt = select(Transacao).where(Transacao.usuario_id == current_user.id)

    # T-10: quando dá pra formar um range de datas, usa range sargável (habilita o
    # índice (usuario_id, data)) em vez de extract(). Comportamento idêntico ao
    # anterior em todos os combos de mes/ano (mês isolado, sem range possível por
    # cruzar anos, mantém o extract). Dezembro avança para janeiro do ano seguinte.
    if mes is not None and ano is not None:
        inicio = dt.date(ano, mes, 1)
        fim = dt.date(ano + 1, 1, 1) if mes == 12 else dt.date(ano, mes + 1, 1)
        stmt = stmt.where(Transacao.data >= inicio, Transacao.data < fim)
    elif ano is not None:
        stmt = stmt.where(
            Transacao.data >= dt.date(ano, 1, 1), Transacao.data < dt.date(ano + 1, 1, 1)
        )
    elif mes is not None:
        stmt = stmt.where(extract("month", Transacao.data) == mes)
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

    # Desempate determinístico (T-29): mesmo dia tem 'data' idêntica e Transacao
    # não tem coluna de criação — sem tiebreak, a ordem entre as do mesmo dia é
    # heap do Postgres (não-determinística). id é PK autoincremento: id maior =
    # criada depois = topo dentro do mesmo dia.
    stmt = stmt.order_by(Transacao.data.desc(), Transacao.id.desc())
    stmt = stmt.offset(offset).limit(limit)
    return session.exec(stmt).all()


@router.get("/export", response_model=list[TransacaoResponse])
def export_transactions(
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # T-12: caminho dedicado de backup — TODAS as transações do usuário, sem teto,
    # mesma ordenação estável (data DESC, id DESC). Separa "exportar tudo" da
    # listagem paginada, que tem teto de 500 inviolável.
    stmt = (
        select(Transacao)
        .where(Transacao.usuario_id == current_user.id)
        .order_by(Transacao.data.desc(), Transacao.id.desc())
    )
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

    # Transação + parcelas num único commit (T-41): falha na geração de
    # parcelas não pode deixar transação parcelada sem parcelas no banco
    session.add(transacao)
    session.flush()  # obtém transacao.id sem commitar

    parcelas_criadas = 0
    if body.parcelado:
        parcelas_criadas = _criar_parcelas(session, transacao, card)

    session.commit()
    session.refresh(transacao)

    # #9: aviso NÃO-bloqueante quando a compra cai em fatura já confirmada paga
    # (PagamentoFatura.pago=True) — a compra sai do "A pagar" sem o usuário ver.
    # Detecção read-only pós-commit: o lançamento já persistiu; nada é
    # materializado, nenhum status muda (status_fatura intacto). Só informa.
    pagas = faturas_pagas_atingidas(
        session, current_user.id, competencias_da_compra(session, transacao)
    )
    avisos = (
        [
            AvisoFaturaPaga(
                competencias=[
                    CompetenciaFatura(cartao_id=c, fatura_mes=m, fatura_ano=a)
                    for c, m, a in pagas
                ]
            )
        ]
        if pagas
        else []
    )

    return TransacaoCreateResponse.model_validate(
        {**transacao.model_dump(), "parcelas_criadas": parcelas_criadas, "avisos": avisos}
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

    data = body.model_dump(exclude_unset=True)

    # Mesmo check de propriedade da criação (T-36): cartão alheio nunca é aceito
    new_card = None
    if data.get("cartao_id") is not None:
        new_card = session.get(Cartao, data["cartao_id"])
        if not new_card or new_card.usuario_id != current_user.id:
            raise HTTPException(status_code=404, detail="Cartão não encontrado")

    # Estorno nunca é parcelado (mesma regra do POST): parcelada não vira estorno
    if data.get("tipo") == "estorno" and transacao.parcelado:
        raise HTTPException(
            status_code=422, detail="Transação parcelada não pode virar estorno."
        )

    # Parcelada: valor/data definem as parcelas já criadas — editar dessincronizaria
    # a soma das parcelas e as faturas (T-35)
    if transacao.parcelado and ("valor" in data or "data" in data):
        raise HTTPException(
            status_code=400,
            detail=(
                "Transação parcelada não permite editar valor ou data. "
                "Exclua e recrie a transação, ou ajuste em Gerenciar Parcelas."
            ),
        )

    for field, value in data.items():
        setattr(transacao, field, value)

    # fatura_mes/ano são derivados de data + cartão — rederivar como na criação (T-35)
    if not transacao.parcelado and ("data" in data or "cartao_id" in data):
        card = new_card
        if card is None and transacao.cartao_id:
            card = session.get(Cartao, transacao.cartao_id)
        if card and card.dia_vencimento:
            transacao.fatura_mes, transacao.fatura_ano = _fatura_cartao_avulso(
                transacao.data, card
            )
        else:
            transacao.fatura_mes = None
            transacao.fatura_ano = None

    session.add(transacao)
    session.commit()
    session.refresh(transacao)
    return transacao


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    id: int,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    transacao = session.get(Transacao, id)
    if not transacao or transacao.usuario_id != current_user.id:
        raise HTTPException(status_code=404, detail="Transação não encontrada")

    # As parcelas referenciam a transação via FK NOT NULL — sempre saem junto,
    # na mesma transação de banco (T-34)
    for p in session.exec(select(Parcela).where(Parcela.transacao_id == id)).all():
        session.delete(p)

    session.delete(transacao)
    session.commit()
