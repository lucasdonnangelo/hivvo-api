from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import Numeric
from decimal import Decimal
import datetime as dt


class Parcela(SQLModel, table=True):
    __tablename__ = "parcelas"

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    transacao_id: int = Field(foreign_key="transacoes.id", index=True)

    numero_parcela: int
    total_parcelas: int
    valor_parcela: Decimal = Field(sa_column=Column(Numeric(15, 2)))

    data_vencimento: dt.date
    data_pagamento: Optional[dt.date] = None

    taxa_juros: Decimal = Field(default=Decimal("0.0"), sa_column=Column(Numeric(5, 2)))
    valor_juros: Decimal = Field(default=Decimal("0.0"), sa_column=Column(Numeric(15, 2)))

    descricao: str
    categoria: str
    cartao_id: Optional[int] = Field(default=None, foreign_key="cartoes.id")

    pago: bool = False
    cancelado: bool = False
    criado_em: dt.date = Field(default_factory=dt.date.today)

    fatura_mes: Optional[int] = None
    fatura_ano: Optional[int] = None
