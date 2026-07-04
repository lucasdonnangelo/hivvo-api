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
