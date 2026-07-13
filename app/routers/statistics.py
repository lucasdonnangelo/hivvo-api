from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import Usuario
from app.schemas.statistics import (
    AnualResponse,
    CategoriaComparacao,
    CategoriasResponse,
    ComparacaoResponse,
    DiaMaiorGasto,
    EvolucaoCategoriasResponse,
    EvolucaoResponse,
    HighlightsResponse,
    LeituraMes,
    MaiorDespesa,
    MensalResponse,
    MesAno,
    MesDefaultResponse,
    MesEvolucao,
    MesEvolucaoConsumo,
    MesProjecao,
    ProjecaoResponse,
    SerieCategoria,
    TotaisComparacao,
    VariacaoTripla,
)
from app.services.estatisticas import (
    _agregar,
    _categorias,
    _lancamentos_ano,
    _lancamentos_consumo_horizonte,
    _lancamentos_consumo_mes,
    _lancamentos_mes,
    _mes_seguinte,
    _soma_a_pagar,
    _variacao,
    inicio_projecao,
    mes_default,
)

router = APIRouter(prefix="/statistics", tags=["statistics"])

_ZERO = Decimal("0.00")


def _mes_anterior(mes: int, ano: int) -> tuple[int, int]:
    if mes == 1:
        return 12, ano - 1
    return mes - 1, ano


def _despesas_por_categoria(lancamentos) -> dict[str, Decimal]:
    """Total de despesas por categoria de uma lista de lançamentos — a célula
    básica do /evolution/categories e do /comparison (só despesa: categoria é
    dimensão de gasto, como no donut)."""
    grupos: dict[str, Decimal] = {}
    for lanc in lancamentos:
        if lanc.tipo == "despesa":
            grupos[lanc.categoria] = grupos.get(lanc.categoria, _ZERO) + lanc.valor
    return grupos


def _media(valores: list[Decimal], n: int) -> Decimal:
    """Média com denominador FIXO n (mês ausente = zero), quantize 0.01."""
    return (sum(valores, _ZERO) / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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
        # §"A pagar e Saldo" — só crédito não-saído (marcado nas fontes);
        # aditivo: topo/saldo intocados (saldo já é o caixa fim de mês).
        a_pagar=_soma_a_pagar(lancamentos),
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


@router.get("/projection", response_model=ProjecaoResponse)
def projection_stats(
    meses: int = Query(12, ge=1, le=60),  # alinhado a HORIZONTE_MESES
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Série do Bloco 2 (PLANO_DASHBOARD_DOIS_BLOCOS): N meses de FLUXO a partir
    # do início da projeção — primeiro mês FUTURO com fluxo, nunca o corrente
    # (§"PROJEÇÃO (Bloco 2)"; o corrente é o Bloco 1). _lancamentos_ano é
    # carregado quando o ano muda (queries fixas/ano) e o mês fatiado em
    # memória — a virada dez→jan sai de graça (_mes_seguinte troca o ano e o
    # ano seguinte é carregado). Mês sem fluxo entra com zeros (série
    # contínua). Semântica idêntica ao /monthly (mesmas 4 fontes, projeção
    # integral; a_pagar = só crédito não-saído, NÃO é o subtraendo do saldo).
    mes, ano = inicio_projecao(session, current_user.id)

    series = []
    por_mes: dict = {}
    ano_carregado = None
    for _ in range(meses):
        if ano != ano_carregado:
            por_mes = _lancamentos_ano(session, current_user.id, ano)
            ano_carregado = ano
        rec, desp = _agregar(por_mes[mes])
        series.append(
            MesProjecao(
                mes=mes,
                ano=ano,
                receitas=rec,
                despesas=desp,
                a_pagar=_soma_a_pagar(por_mes[mes]),
                saldo=rec - desp,
            )
        )
        mes, ano = _mes_seguinte(mes, ano)

    return ProjecaoResponse(series=series)


@router.get("/evolution", response_model=EvolucaoResponse)
def evolution_stats(
    meses: int = Query(3, ge=1, le=60),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Série do Resumo (Seção 3, PLANO_RESUMO) — o espelho PRA TRÁS do
    # /projection, em base CONSUMO (o "gasto" do Resumo é consumo, coerente
    # com o donut do Dashboard). Âncora = mês corrente, incluído; cronológica;
    # mês sem dado entra com zeros. Fonte única: _lancamentos_consumo_horizonte
    # (cache por ano, sem N+1).
    series = []
    for mes, ano, lancamentos in _lancamentos_consumo_horizonte(
        session, current_user.id, meses
    ):
        rec, desp = _agregar(lancamentos)
        series.append(
            MesEvolucaoConsumo(
                mes=mes, ano=ano, receitas=rec, despesas=desp, saldo=rec - desp
            )
        )
    return EvolucaoResponse(series=series)


@router.get("/evolution/categories", response_model=EvolucaoCategoriasResponse)
def evolution_categories_stats(
    meses: int = Query(3, ge=1, le=60),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Série por categoria (Seção 3 "evolução de uma categoria" + base da
    # comparação) — CONSUMO, só despesas (categoria é dimensão de gasto, como
    # no donut). Mesma fonte única do /evolution: as duas séries nunca
    # divergem. Categoria ausente num mês = 0.00 (série alinhada ao eixo).
    serie = _lancamentos_consumo_horizonte(session, current_user.id, meses)
    grupos_mes = [_despesas_por_categoria(lanc) for _, _, lanc in serie]

    categorias = sorted(
        (
            SerieCategoria(
                categoria=nome,
                total=sum((g.get(nome, _ZERO) for g in grupos_mes), _ZERO),
                serie=[g.get(nome, _ZERO) for g in grupos_mes],
            )
            for nome in {nome for g in grupos_mes for nome in g}
        ),
        key=lambda c: (-c.total, c.categoria),
    )
    return EvolucaoCategoriasResponse(
        meses=[MesAno(mes=m, ano=a) for m, a, _ in serie],
        categorias=categorias,
    )


@router.get("/comparison", response_model=ComparacaoResponse)
def comparison_stats(
    meses: int = Query(3, ge=1, le=60),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Seção 2 do Resumo (PLANO_RESUMO) — mês ATUAL vs ANTERIOR vs MÉDIA,
    # totais e por categoria, base CONSUMO. `meses=N` conta meses FECHADOS:
    # a média é o BASELINE dos N meses anteriores ao corrente (o corrente,
    # parcial, não a contamina — a comparação não é circular); o horizonte
    # buscado é N+1 (os N fechados + o corrente). anterior = o último fechado.
    # Mesma fonte única do /evolution → as telas nunca divergem.
    serie = _lancamentos_consumo_horizonte(session, current_user.id, meses + 1)
    mes, ano = serie[-1][0], serie[-1][1]

    agregados = [_agregar(lancamentos) for _, _, lancamentos in serie]
    fechados = agregados[:-1]
    rec_atual, desp_atual = agregados[-1]
    rec_ant, desp_ant = agregados[-2]
    media_rec = _media([r for r, _ in fechados], meses)
    media_desp = _media([d for _, d in fechados], meses)

    def _leitura(rec: Decimal, desp: Decimal) -> LeituraMes:
        return LeituraMes(receitas=rec, despesas=desp, saldo=rec - desp)

    def _tripla(base: LeituraMes) -> VariacaoTripla:
        return VariacaoTripla(
            receitas=_variacao(rec_atual, base.receitas),
            despesas=_variacao(desp_atual, base.despesas),
            saldo=_variacao(rec_atual - desp_atual, base.saldo),
        )

    anterior = _leitura(rec_ant, desp_ant)
    media = _leitura(media_rec, media_desp)
    totais = TotaisComparacao(
        atual=_leitura(rec_atual, desp_atual),
        anterior=anterior,
        media=media,
        variacao_vs_anterior=_tripla(anterior),
        variacao_vs_media=_tripla(media),
    )

    # Por categoria (despesas): alinhamento pela UNIÃO dos nomes com gasto em
    # qualquer mês do horizonte — ausente num mês = base zero (_variacao trata:
    # surgiu → None, sumiu → −100%); a média divide pelo N fixo de fechados.
    grupos_mes = [_despesas_por_categoria(lanc) for _, _, lanc in serie]
    categorias = []
    for nome in {nome for g in grupos_mes for nome in g}:
        atual = grupos_mes[-1].get(nome, _ZERO)
        ant = grupos_mes[-2].get(nome, _ZERO)
        med = _media([g.get(nome, _ZERO) for g in grupos_mes[:-1]], meses)
        categorias.append(
            CategoriaComparacao(
                categoria=nome,
                atual=atual,
                anterior=ant,
                media=med,
                variacao_vs_anterior=_variacao(atual, ant),
                variacao_vs_media=_variacao(atual, med),
            )
        )
    categorias.sort(key=lambda c: (-c.atual, c.categoria))

    return ComparacaoResponse(mes=mes, ano=ano, totais=totais, categorias=categorias)


@router.get("/highlights", response_model=HighlightsResponse)
def highlights_stats(
    mes: int = Query(..., ge=1, le=12),
    ano: int = Query(..., ge=2000),
    current_user: Usuario = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Destaques do mês (Resumo, Seção 1 — PLANO_RESUMO), base CONSUMO: a
    # MESMA lista do donut do /monthly (fonte única — a recorrência concorre,
    # com data/descricao carregados pela trilha detalhada). Empates
    # determinísticos: maior despesa por (valor, data mais recente,
    # descrição); dia por (total, dia mais recente). Mês vazio → None/0.
    lancamentos = _lancamentos_consumo_mes(session, current_user.id, mes, ano)
    despesas = [l for l in lancamentos if l.tipo == "despesa"]

    maior_despesa = None
    dia_maior_gasto = None
    if despesas:
        top = max(despesas, key=lambda l: (l.valor, l.data, l.descricao))
        maior_despesa = MaiorDespesa(
            valor=top.valor, descricao=top.descricao,
            categoria=top.categoria, data=top.data,
        )
        por_dia: dict = {}
        for l in despesas:
            por_dia[l.data] = por_dia.get(l.data, _ZERO) + l.valor
        data, total = max(por_dia.items(), key=lambda item: (item[1], item[0]))
        dia_maior_gasto = DiaMaiorGasto(data=data, total=total)

    num_recorrentes = sum(1 for l in lancamentos if l.recorrente)
    return HighlightsResponse(
        mes=mes,
        ano=ano,
        maior_despesa=maior_despesa,
        dia_maior_gasto=dia_maior_gasto,
        num_transacoes_total=len(lancamentos),
        num_lancadas=len(lancamentos) - num_recorrentes,
        num_recorrentes=num_recorrentes,
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
