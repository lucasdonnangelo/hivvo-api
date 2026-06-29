from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import CheckConstraint, Numeric, UniqueConstraint
from decimal import Decimal
import datetime as dt

from app.core.dates import hoje


class Parcela(SQLModel, table=True):
    __tablename__ = "parcelas"
    # T-11: integridade de domínio + unicidade da parcela dentro da transação.
    __table_args__ = (
        CheckConstraint("valor_parcela > 0", name="ck_parcelas_valor_positivo"),
        CheckConstraint(
            "fatura_mes IS NULL OR (fatura_mes BETWEEN 1 AND 12)",
            name="ck_parcelas_fatura_mes_valido",
        ),
        CheckConstraint(
            "numero_parcela <= total_parcelas", name="ck_parcelas_numero_parcela_valido"
        ),
        UniqueConstraint("transacao_id", "numero_parcela", name="uq_parcelas_transacao_numero"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    transacao_id: int = Field(foreign_key="transacoes.id", index=True)

    numero_parcela: int
    total_parcelas: int
    valor_parcela: Decimal = Field(sa_column=Column(Numeric(15, 2), nullable=False))

    data_vencimento: dt.date
    data_pagamento: Optional[dt.date] = None

    taxa_juros: Decimal = Field(default=Decimal("0.0"), sa_column=Column(Numeric(5, 2), nullable=False))
    valor_juros: Decimal = Field(default=Decimal("0.0"), sa_column=Column(Numeric(15, 2), nullable=False))

    descricao: str
    categoria: str
    cartao_id: Optional[int] = Field(default=None, foreign_key="cartoes.id")

    pago: bool = False
    cancelado: bool = False
    criado_em: dt.date = Field(default_factory=hoje)

    fatura_mes: Optional[int] = None
    fatura_ano: Optional[int] = None
