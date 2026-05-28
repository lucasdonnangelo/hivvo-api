from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import extract
from sqlmodel import Session, select

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.transaction import Transacao
from app.models.user import Usuario
from app.schemas.statistics import (
    AnualResponse,
    CategoriaStats,
    CategoriasResponse,
    MensalResponse,
    MesEvolucao,
)

router = APIRouter(prefix="/statistics", tags=["statistics"])

_ZERO = Decimal("0.00")


def _mes_anterior(mes: int, ano: int) -> tuple[int, int]:
    if mes == 1:
        return 12, ano - 1
    return mes - 1, ano


def _variacao(atual: Decimal, anterior: Decimal) -> Optional[Decimal]:
    """Retorna variação percentual; None se não há dados anteriores."""
    if anterior == _ZERO:
        return None
    return ((atual - anterior) / anterior * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _agregar(transacoes: list[Transacao]) -> tuple[Decimal, Decimal]:
    """Retorna (receitas, despesas) para uma lista de transações."""
    receitas = sum((t.valor for t in transacoes if t.tipo == "receita"), _ZERO)
    despesas = sum((t.valor for t in transacoes if t.tipo == "despesa"), _ZERO)
    return receitas, despesas


def _categorias(transacoes: list[Transacao]) -> list[CategoriaStats]:
    """Agrupa despesas por categoria com percentual do total."""
    despesas = [t for t in transacoes if t.tipo == "despesa"]
    total = sum((t.valor for t in despesas), _ZERO)
    if not total:
        return []

    grupos: dict[str, Decimal] = {}
    for t in despesas:
        grupos[t.categoria] = grupos.get(t.categoria, _ZERO) + t.valor

    return sorted(
        [
            CategoriaStats(
                categoria=cat,
                total=val,
                percentual=(val / total * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            )
            for cat, val in grupos.items()
        ],
        key=lambda x: x.total,
        reverse=True,
    )


def _buscar_mes(session: Session, usuario_id: int, mes: int, ano: int) -> list[Transacao]:
    return session.exec(
        select(Transacao).where(
            Transacao.usuario_id == usuario_id,
            extract("month", Transacao.data) == mes,
            extract("year", Transacao.data) == ano,
        )
    ).all()


@router.get("/monthly", response_model=MensalResponse)
def monthly_stats(
    mes: int = Query(..., ge=1, le=12),
    ano: int = Query(..., ge=2000),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    transacoes = _buscar_mes(session, current_user.id, mes, ano)
    receitas, despesas = _agregar(transacoes)
    saldo = receitas - despesas

    mes_ant, ano_ant = _mes_anterior(mes, ano)
    transacoes_ant = _buscar_mes(session, current_user.id, mes_ant, ano_ant)
    rec_ant, desp_ant = _agregar(transacoes_ant)
    saldo_ant = rec_ant - desp_ant

    return MensalResponse(
        mes=mes,
        ano=ano,
        receitas=receitas,
        despesas=despesas,
        saldo=saldo,
        categorias=_categorias(transacoes),
        variacao_receitas=_variacao(receitas, rec_ant),
        variacao_despesas=_variacao(despesas, desp_ant),
        variacao_saldo=_variacao(saldo, saldo_ant),
    )


@router.get("/yearly", response_model=AnualResponse)
def yearly_stats(
    ano: int = Query(..., ge=2000),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Busca todas as transações do ano de uma vez
    transacoes_ano = session.exec(
        select(Transacao).where(
            Transacao.usuario_id == current_user.id,
            extract("year", Transacao.data) == ano,
        )
    ).all()

    # Agrupa por mês em Python
    por_mes: dict[int, list[Transacao]] = {m: [] for m in range(1, 13)}
    for t in transacoes_ano:
        por_mes[t.data.month].append(t)

    meses = []
    for m in range(1, 13):
        rec, desp = _agregar(por_mes[m])
        meses.append(MesEvolucao(mes=m, receitas=rec, despesas=desp, saldo=rec - desp))

    receitas_total = sum((m.receitas for m in meses), _ZERO)
    despesas_total = sum((m.despesas for m in meses), _ZERO)

    return AnualResponse(
        ano=ano,
        receitas_total=receitas_total,
        despesas_total=despesas_total,
        saldo_total=receitas_total - despesas_total,
        meses=meses,
    )


@router.get("/categories", response_model=CategoriasResponse)
def categories_stats(
    mes: int = Query(..., ge=1, le=12),
    ano: int = Query(..., ge=2000),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    transacoes = _buscar_mes(session, current_user.id, mes, ano)
    cats = _categorias(transacoes)
    total = sum((c.total for c in cats), _ZERO)

    return CategoriasResponse(
        mes=mes,
        ano=ano,
        total_despesas=total,
        categorias=cats,
    )
