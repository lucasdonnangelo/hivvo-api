from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import Usuario
from app.schemas.statistics import (
    AnualResponse,
    CategoriasResponse,
    LeituraMes,
    MensalResponse,
    MesAno,
    MesDefaultResponse,
    MesEvolucao,
)
from app.services.estatisticas import (
    _agregar,
    _categorias,
    _lancamentos_ano,
    _lancamentos_consumo_mes,
    _lancamentos_mes,
    _variacao,
    mes_default,
)

router = APIRouter(prefix="/statistics", tags=["statistics"])

_ZERO = Decimal("0.00")


def _mes_anterior(mes: int, ano: int) -> tuple[int, int]:
    if mes == 1:
        return 12, ano - 1
    return mes - 1, ano


@router.get("/monthly", response_model=MensalResponse)
def monthly_stats(
    mes: int = Query(..., ge=1, le=12),
    ano: int = Query(..., ge=2000),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Visão FLUXO: lançamentos por competência de fatura (parcelas + avulsas
    # faturadas + à vista/receitas por data), sem dupla contagem — T-39.
    # Topo da resposta = PROJEÇÃO integral (todos os lançamentos, §1.3.1).
    lancamentos = _lancamentos_mes(session, current_user.id, mes, ano)
    receitas, despesas = _agregar(lancamentos)
    saldo = receitas - despesas

    # §1.3.1 — decomposição do mês pelo dia (marcada nas fontes): realizado
    # (dia <= hoje) e a-vir (dia > hoje). Invariante: topo == realizado + a_vir.
    rec_real, desp_real = _agregar([l for l in lancamentos if l.realizado])
    a_vir = LeituraMes(
        receitas=receitas - rec_real,
        despesas=despesas - desp_real,
        saldo=(receitas - rec_real) - (despesas - desp_real),
    )

    # Variação: PROJEÇÃO integral vs. PROJEÇÃO integral (§1.3.1) — nunca o
    # realizado parcial (a % ficaria enganosa no começo do mês).
    mes_ant, ano_ant = _mes_anterior(mes, ano)
    lancamentos_ant = _lancamentos_mes(session, current_user.id, mes_ant, ano_ant)
    rec_ant, desp_ant = _agregar(lancamentos_ant)
    saldo_ant = rec_ant - desp_ant

    # Visão CONSUMO (§"Fase 3b"): gasto por DATA da compra (pai parcelada pelo
    # valor cheio + avulsa por data + à vista + receitas + recorrência). Número
    # único e integral (sem realizado/a_vir — D2) + donut próprio (D3). Aditivo:
    # o bloco de FLUXO acima fica intocado.
    consumo_lanc = _lancamentos_consumo_mes(session, current_user.id, mes, ano)
    rec_c, desp_c = _agregar(consumo_lanc)

    return MensalResponse(
        mes=mes,
        ano=ano,
        receitas=receitas,
        despesas=despesas,
        saldo=saldo,
        categorias=_categorias(lancamentos),
        variacao_receitas=_variacao(receitas, rec_ant),
        variacao_despesas=_variacao(despesas, desp_ant),
        variacao_saldo=_variacao(saldo, saldo_ant),
        realizado=LeituraMes(
            receitas=rec_real, despesas=desp_real, saldo=rec_real - desp_real
        ),
        a_vir=a_vir,
        consumo=LeituraMes(receitas=rec_c, despesas=desp_c, saldo=rec_c - desp_c),
        categorias_consumo=_categorias(consumo_lanc),
    )


@router.get("/default-month", response_model=MesDefaultResponse)
def default_month(
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Mês em que o Dashboard ABRE (PLANO §"Mês default do Dashboard"): FLUXO
    # pela regra histórico → corrente / 1º mês com fluxo no horizonte /
    # fallback mês seguinte; CONSUMO sempre o corrente. Chamado 1x na abertura
    # do app, ANTES do primeiro /monthly (resolve qual mês buscar primeiro).
    (fluxo_mes, fluxo_ano), (cons_mes, cons_ano) = mes_default(session, current_user.id)
    return MesDefaultResponse(
        fluxo=MesAno(mes=fluxo_mes, ano=fluxo_ano),
        consumo=MesAno(mes=cons_mes, ano=cons_ano),
    )


@router.get("/yearly", response_model=AnualResponse)
def yearly_stats(
    ano: int = Query(..., ge=2000),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Visão FLUXO por competência (coerente com monthly_stats): o gráfico
    # "Evolução mensal" mostra o desembolso mês a mês, não o consumo por data.
    # _lancamentos_ano resolve o ano em 3 queries (uma por fonte) agrupadas por
    # mês — sem N+1, sem 12x _lancamentos_mes.
    por_mes = _lancamentos_ano(session, current_user.id, ano)

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
    lancamentos = _lancamentos_mes(session, current_user.id, mes, ano)
    cats = _categorias(lancamentos)
    total = sum((c.total for c in cats), _ZERO)

    return CategoriasResponse(
        mes=mes,
        ano=ano,
        total_despesas=total,
        categorias=cats,
    )
