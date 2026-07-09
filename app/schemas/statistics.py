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


class MesDefaultResponse(BaseModel):
    """Mês default de abertura do Dashboard (PLANO §"Mês default do Dashboard").

    fluxo: com histórico → mês corrente; senão o 1º mês com fluxo no horizonte
    de 60 meses; senão o mês seguinte. consumo: sempre o mês corrente. Define
    só onde a tela ABRE — a navegação segue livre.
    """

    fluxo: MesAno
    consumo: MesAno
