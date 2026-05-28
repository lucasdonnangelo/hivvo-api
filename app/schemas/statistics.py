from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class CategoriaStats(BaseModel):
    categoria: str
    total: Decimal
    percentual: Decimal  # 0.00–100.00


class MensalResponse(BaseModel):
    mes: int
    ano: int
    receitas: Decimal
    despesas: Decimal
    saldo: Decimal
    categorias: list[CategoriaStats]
    variacao_receitas: Optional[Decimal] = None   # % vs mês anterior, None se sem dados anteriores
    variacao_despesas: Optional[Decimal] = None
    variacao_saldo: Optional[Decimal] = None


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
