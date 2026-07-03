"""CRUD de recorrência (Fase 2c — PLANO_PROJECAO §3.1.1/§3.4).

A recorrência é cabeçalho (identidade) + linha do tempo de vigências (valores).
Toda escrita preserva as invariantes que o algoritmo da 2a assume: vigências
SEM sobreposição e SEM gap. `ativa` é flag de estado/listagem — quem governa a
projeção são as vigências (encerrar = FECHAR a vigência, preservando o passado).
"""

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from app.core.auth import get_current_user
from app.core.database import get_session
from app.core.dates import hoje
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.models.user import Usuario
from app.schemas.recorrencia import (
    RecorrenciaCreate,
    RecorrenciaDetailResponse,
    RecorrenciaResponse,
    RecorrenciaUpdate,
)
from app.services.estatisticas import _recorrencias_com_vigencias
from app.services.recorrencias import valor_no_mes

router = APIRouter(prefix="/recorrencias", tags=["recorrencias"])


def _mes_anterior(mes: int, ano: int) -> tuple[int, int]:
    return (12, ano - 1) if mes == 1 else (mes - 1, ano)


def _default_mes_inicio(dia_do_mes: int, h: dt.date) -> tuple[int, int]:
    """Mês de início DEFAULT pela regra do dia (Fase 3a-backend) — lógica de
    negócio, não do frontend.

    O default depende do dia da ocorrência vs. hoje:
    - dia_do_mes >= dia de hoje → MÊS CORRENTE (a ocorrência ainda acontece este
      mês; inclui a borda dia == hoje).
    - dia_do_mes  < dia de hoje → MÊS SEGUINTE (o dia já passou; a primeira
      ocorrência é no próximo mês). Virada de ano natural (dez → jan/ano+1).

    Só se aplica quando o cliente NÃO envia mes_inicio/ano_inicio — o override
    explícito preserva a escolha do usuário (ex.: "esse salário só começa em
    setembro"). Sem relação com ciclo de fatura (recorrência não passa por cartão).
    """
    if dia_do_mes >= h.day:
        return (h.month, h.year)
    if h.month == 12:
        return (1, h.year + 1)
    return (h.month + 1, h.year)


def _get_propria(
    session: Session, current_user: Usuario, id: uuid.UUID, exigir_ativa: bool
) -> Recorrencia:
    """Isolamento (T-36): 404 para inexistente OU de outro usuário — mesma cara.

    Escrita (PATCH/DELETE) exige ativa=True: recorrência encerrada é imutável
    (o histórico dela está fechado) e responde 404 como se não existisse.
    """
    rec = session.get(Recorrencia, id)
    if not rec or rec.usuario_id != current_user.id or (exigir_ativa and not rec.ativa):
        raise HTTPException(status_code=404, detail="Recorrência não encontrada")
    return rec


def _vigencias_ordenadas(session: Session, recorrencia_id: uuid.UUID) -> list[RecorrenciaVigencia]:
    return session.exec(
        select(RecorrenciaVigencia)
        .where(RecorrenciaVigencia.recorrencia_id == recorrencia_id)
        .order_by(RecorrenciaVigencia.ano_inicio, RecorrenciaVigencia.mes_inicio)  # type: ignore[arg-type]
    ).all()


def _vigencia_aberta(session: Session, recorrencia_id: uuid.UUID) -> RecorrenciaVigencia | None:
    return session.exec(
        select(RecorrenciaVigencia).where(
            RecorrenciaVigencia.recorrencia_id == recorrencia_id,
            RecorrenciaVigencia.ano_fim == None,  # noqa: E711
        )
    ).first()


def _detail(
    rec: Recorrencia, vigencias: list[RecorrenciaVigencia]
) -> RecorrenciaDetailResponse:
    h = hoje()
    return RecorrenciaDetailResponse.model_validate(
        {
            **rec.model_dump(),
            "valor_vigente": valor_no_mes(rec, vigencias, h.month, h.year),
            "vigencias": vigencias,
        }
    )


@router.post("", response_model=RecorrenciaDetailResponse, status_code=status.HTTP_201_CREATED)
def create_recorrencia(
    body: RecorrenciaCreate,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Cria o cabeçalho + a PRIMEIRA vigência (aberta) num único commit."""
    h = hoje()
    if body.mes_inicio is not None:
        # Override explícito (o "ajustar" da UI): mes_inicio/ano_inicio vêm
        # pareados do schema — usar o que o cliente escolheu.
        mes_inicio, ano_inicio = body.mes_inicio, body.ano_inicio
    else:
        # Default: regra do dia (dia da ocorrência vs. hoje).
        mes_inicio, ano_inicio = _default_mes_inicio(body.dia_do_mes, h)

    rec = Recorrencia(
        usuario_id=current_user.id,
        tipo=body.tipo,
        categoria=body.categoria,
        forma_pagamento=body.forma_pagamento,
        dia_do_mes=body.dia_do_mes,
        descricao=body.descricao,
    )
    session.add(rec)
    session.flush()  # obtém rec.id sem commitar (vigência sai no mesmo commit)

    session.add(
        RecorrenciaVigencia(
            recorrencia_id=rec.id,
            valor=body.valor,
            mes_inicio=mes_inicio,
            ano_inicio=ano_inicio,
        )
    )
    session.commit()
    session.refresh(rec)
    return _detail(rec, _vigencias_ordenadas(session, rec.id))


@router.get("", response_model=list[RecorrenciaResponse])
def list_recorrencias(
    incluir_encerradas: bool = Query(False),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Lista as recorrências do usuário (só ativas por padrão), com o valor
    VIGENTE no mês corrente ("salário: R$X"). 2 queries fixas — reusa a busca
    da Fonte 4 (sem N+1)."""
    h = hoje()
    resposta = []
    for rec, vigencias in _recorrencias_com_vigencias(session, current_user.id):
        if not incluir_encerradas and not rec.ativa:
            continue
        resposta.append(
            RecorrenciaResponse.model_validate(
                {**rec.model_dump(), "valor_vigente": valor_no_mes(rec, vigencias, h.month, h.year)}
            )
        )
    resposta.sort(key=lambda r: r.data_criacao)
    return resposta


@router.get("/{id}", response_model=RecorrenciaDetailResponse)
def get_recorrencia(
    id: uuid.UUID,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Detalhe com as vigências (histórico). Encerrada TAMBÉM aparece aqui."""
    rec = _get_propria(session, current_user, id, exigir_ativa=False)
    return _detail(rec, _vigencias_ordenadas(session, rec.id))


@router.patch("/{id}", response_model=RecorrenciaDetailResponse)
def update_recorrencia(
    id: uuid.UUID,
    body: RecorrenciaUpdate,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Edita — dois caminhos (§3.4): valor VERSIONADO; metadados retroativos."""
    rec = _get_propria(session, current_user, id, exigir_ativa=True)
    data = body.model_dump(exclude_unset=True)
    valor_novo = data.pop("valor", None)

    # Metadados (descricao/categoria/dia_do_mes/forma_pagamento): retroativos,
    # direto no cabeçalho — não versionam, não tocam vigências.
    for field, value in data.items():
        setattr(rec, field, value)
    session.add(rec)

    if valor_novo is not None:
        aberta = _vigencia_aberta(session, rec.id)
        if aberta is None:
            # Estado anômalo (ativa sem vigência aberta) — não deve ocorrer via API.
            raise HTTPException(status_code=409, detail="Recorrência sem vigência aberta")
        h = hoje()
        if (aberta.ano_inicio, aberta.mes_inicio) >= (h.year, h.month):
            # Vigência aberta começou NESTE mês (2ª edição no mês) ou no futuro:
            # substituir o valor in place — fechar+abrir criaria vigência
            # degenerada/sobreposta, e nenhum mês passado usou o valor antigo.
            aberta.valor = valor_novo
            session.add(aberta)
        else:
            # Versiona: fecha a atual no mês ANTERIOR e abre a nova no corrente
            # — sem gap nem sobreposição por construção (§3.1.1).
            aberta.mes_fim, aberta.ano_fim = _mes_anterior(h.month, h.year)
            session.add(aberta)
            session.add(
                RecorrenciaVigencia(
                    recorrencia_id=rec.id,
                    valor=valor_novo,
                    mes_inicio=h.month,
                    ano_inicio=h.year,
                )
            )

    session.commit()
    session.refresh(rec)
    return _detail(rec, _vigencias_ordenadas(session, rec.id))


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recorrencia(
    id: uuid.UUID,
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Encerra PRESERVANDO o passado (§3.4): fecha a vigência aberta no mês
    corrente + ativa=False (flag de listagem). Nenhuma linha é apagada — meses
    passados continuam na projeção; o futuro para (nenhuma vigência cobre).

    Se a vigência aberta começa no FUTURO, o fechamento gera intervalo
    fim < início, que o algoritmo trata como vazio → nunca gera (correto para
    "excluí antes de começar")."""
    rec = _get_propria(session, current_user, id, exigir_ativa=True)

    aberta = _vigencia_aberta(session, rec.id)
    if aberta is not None:
        h = hoje()
        aberta.mes_fim, aberta.ano_fim = h.month, h.year
        session.add(aberta)

    rec.ativa = False
    session.add(rec)
    session.commit()
