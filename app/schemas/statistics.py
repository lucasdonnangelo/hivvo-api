from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class CategoriaStats(BaseModel):
    categoria: str
    total: Decimal
    percentual: Decimal  # 0.00–100.00


class LeituraMes(BaseModel):
    """Uma leitura do mês (§1.3.1): realizado (dia <= hoje) ou a-vir (dia > hoje)."""

    receitas: Decimal
    despesas: Decimal
    saldo: Decimal


class MensalResponse(BaseModel):
    # Topo = PROJEÇÃO integral do mês (realizado + a_vir) — número principal do
    # Dashboard, estável ao longo do mês. Shape pré-§1.3.1 preservado.
    mes: int
    ano: int
    receitas: Decimal
    despesas: Decimal
    saldo: Decimal
    categorias: list[CategoriaStats]
    variacao_receitas: Optional[Decimal] = None   # % vs mês anterior, None se sem dados anteriores
    variacao_despesas: Optional[Decimal] = None
    variacao_saldo: Optional[Decimal] = None
    # §1.3.1 — decomposição do mês corrente pelo dia de hoje. Em mês
    # não-corrente: realizado == projeção (topo) e a_vir zerado.
    realizado: LeituraMes
    a_vir: LeituraMes
    # §"Fase 3b" — visão CONSUMO (gasto por DATA da compra: pai parcelada pelo
    # valor cheio + avulsa por data + à vista + receitas + recorrência). Número
    # único, INTEGRAL (sem realizado/a_vir — D2) + donut próprio (D3). Aditivo:
    # o topo/fluxo acima não muda.
    consumo: LeituraMes
    categorias_consumo: list[CategoriaStats]
    # §"A pagar e Saldo" — card "A pagar": só CRÉDITO cuja saída ainda não
    # ocorreu (parcela não paga + avulsa de fatura a vencer). À vista/
    # recorrência saem no ato e ficam FORA. NÃO confundir com a_vir (eixo
    # tempo-no-mês-corrente): a_pagar é o eixo dívida-de-crédito, válido para
    # qualquer mês. O saldo do topo segue receitas − despesas (caixa projetado
    # de fim de mês) — a_pagar não entra nessa conta.
    a_pagar: Decimal


class MesEvolucao(BaseModel):
    mes: int
    receitas: Decimal
    despesas: Decimal
    saldo: Decimal


class AnualResponse(BaseModel):
    ano: int
    receitas_total: Decimal
    despesas_total: Decimal
    saldo_total: Decimal
    meses: list[MesEvolucao]  # sempre 12 itens, zeros para meses sem dados


class CategoriasResponse(BaseModel):
    mes: int
    ano: int
    total_despesas: Decimal
    categorias: list[CategoriaStats]


class MesAno(BaseModel):
    mes: int
    ano: int


class MesProjecao(BaseModel):
    """Um mês da série de projeção do Bloco 2 (PLANO_DASHBOARD_DOIS_BLOCOS).

    Sempre visão FLUXO, com os MESMOS significados do /monthly (fonte única,
    lentes que não divergem): despesas = saídas integrais do mês por
    competência, saldo = receitas − despesas (caixa projetado de fim de mês)
    e a_pagar = só o crédito cuja saída ainda não ocorreu (§"A pagar e
    Saldo") — a_pagar NÃO é o subtraendo do saldo.
    """

    mes: int
    ano: int
    receitas: Decimal
    despesas: Decimal
    a_pagar: Decimal
    saldo: Decimal


class ProjecaoResponse(BaseModel):
    """Série de N meses de FLUXO do Bloco 2 "Sua projeção".

    series[0] é o início da projeção (§"PROJEÇÃO (Bloco 2)"): o primeiro mês
    FUTURO com fluxo — NUNCA o corrente (esse é o Bloco 1), fallback mês
    seguinte. series[1..N-1] são os meses seguintes, contínuos — mês sem
    fluxo aparece com zeros, não é omitido.
    """

    series: list[MesProjecao]


class MesEvolucaoConsumo(BaseModel):
    """Um mês da série do /evolution (Resumo, Seção 3 — PLANO_RESUMO).

    Base CONSUMO (gasto pela DATA da compra, o mesmo do donut do Dashboard),
    integral (sem realizado/a_vir). Tem `ano` porque o horizonte relativo
    cruza a virada de ano (diferente do MesEvolucao do /yearly, ano fixo).
    """

    mes: int
    ano: int
    receitas: Decimal
    despesas: Decimal
    saldo: Decimal


class EvolucaoResponse(BaseModel):
    """Série CONSUMO dos últimos N meses — o espelho PRA TRÁS do /projection.

    Cronológica: series[0] é o mês mais antigo, series[-1] é o corrente
    (âncora, incluída). Contínua — mês sem dado entra com zeros, não é
    omitido.
    """

    series: list[MesEvolucaoConsumo]


class SerieCategoria(BaseModel):
    """Série de uma categoria no horizonte do /evolution/categories.

    `serie` é alinhada por ÍNDICE ao eixo `meses` da resposta (0.00 nos meses
    em que a categoria não teve gasto); `total` = soma no horizonte (critério
    de ordenação).
    """

    categoria: str
    total: Decimal
    serie: list[Decimal]


class EvolucaoCategoriasResponse(BaseModel):
    """Gasto por categoria mês a mês nos últimos N meses (Resumo, Seção 3).

    CONSUMO, só despesas (categoria é dimensão de gasto, como no donut) —
    formato categoria-major: o front plota uma categoria contra o eixo
    `meses` sem pivotar. Categorias ordenadas por total desc (desempate
    alfabético). Eixo cronológico, o mesmo do /evolution.
    """

    meses: list[MesAno]
    categorias: list[SerieCategoria]


class VariacaoTripla(BaseModel):
    """Variação % (via _variacao) de receitas/despesas/saldo entre duas
    leituras — None quando a base é zero (sem dado anterior)."""

    receitas: Optional[Decimal] = None
    despesas: Optional[Decimal] = None
    saldo: Optional[Decimal] = None


class TotaisComparacao(BaseModel):
    """Totais do /comparison: mês atual vs anterior vs média dos fechados.

    `media` = média dos N meses FECHADOS anteriores ao corrente (o corrente,
    parcial, NÃO entra — é o baseline contra o qual `atual` é comparado;
    incluí-lo tornaria a comparação circular). Denominador N fixo, quantize
    0.01 HALF_UP; saldo da média = receitas − despesas (invariante preservada).
    """

    atual: LeituraMes
    anterior: LeituraMes
    media: LeituraMes
    variacao_vs_anterior: VariacaoTripla
    variacao_vs_media: VariacaoTripla


class CategoriaComparacao(BaseModel):
    """Uma categoria (despesa, CONSUMO) alinhada entre atual/anterior/média.

    Valores ABSOLUTOS + variações. Categoria ausente num mês = base zero:
    surgiu → variação None (nunca "+∞"); sumiu → atual 0, variação −100%.
    `media` divide pelo N fixo de meses fechados, mesmo ausente em alguns.
    """

    categoria: str
    atual: Decimal
    anterior: Decimal
    media: Decimal
    variacao_vs_anterior: Optional[Decimal] = None
    variacao_vs_media: Optional[Decimal] = None


class ComparacaoResponse(BaseModel):
    """Seção 2 do Resumo (PLANO_RESUMO): as duas leituras de comparação —
    vs mês anterior (intuitiva) e vs média (robusta a meses atípicos) — num
    só lugar, base CONSUMO. (mes, ano) = âncora (mês corrente)."""

    mes: int
    ano: int
    totais: TotaisComparacao
    categorias: list[CategoriaComparacao]  # despesas, ordenadas por atual desc


class MesDefaultResponse(BaseModel):
    """Mês default de abertura do Dashboard (PLANO §"Mês default do Dashboard").

    fluxo: com histórico → mês corrente; senão o 1º mês com fluxo no horizonte
    de 60 meses; senão o mês seguinte. consumo: sempre o mês corrente. Define
    só onde a tela ABRE — a navegação segue livre.
    """

    fluxo: MesAno
    consumo: MesAno
