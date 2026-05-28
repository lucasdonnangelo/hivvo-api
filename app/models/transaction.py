from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import Numeric
from decimal import Decimal
import datetime as dt


class Transacao(SQLModel, table=True):
    __tablename__ = "transacoes"

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)

    tipo: str  # "receita" | "despesa"
    data: dt.date
    descricao: str
    valor: Decimal = Field(sa_column=Column(Numeric(15, 2)))
    categoria: str
    forma_pagamento: str = "Débito"  # Débito, Crédito, Dinheiro, Pix
    tipo_gasto: str = "Variável"  # Fixo, Variável
    origem: str = "manual"  # manual, csv, ia

    cartao_id: Optional[int] = Field(default=None, foreign_key="cartoes.id")
    fatura_mes: Optional[int] = None
    fatura_ano: Optional[int] = None

    parcelado: bool = False
    total_parcelas: Optional[int] = None
