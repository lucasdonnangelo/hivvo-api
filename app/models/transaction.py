from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import CheckConstraint, Numeric
from decimal import Decimal
import datetime as dt


class Transacao(SQLModel, table=True):
    __tablename__ = "transacoes"
    # T-11: integridade de domínio no banco (rede de segurança além do Pydantic).
    # fatura_mes é nullable (avulsa sem cartão) — o CHECK só vale quando preenchido.
    __table_args__ = (
        CheckConstraint("valor > 0", name="ck_transacoes_valor_positivo"),
        CheckConstraint("tipo IN ('receita', 'despesa')", name="ck_transacoes_tipo_valido"),
        CheckConstraint(
            "fatura_mes IS NULL OR (fatura_mes BETWEEN 1 AND 12)",
            name="ck_transacoes_fatura_mes_valido",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)

    tipo: str  # "receita" | "despesa"
    data: dt.date
    descricao: str
    valor: Decimal = Field(sa_column=Column(Numeric(15, 2), nullable=False))
    categoria: str
    forma_pagamento: str = "Débito"  # Débito, Crédito, Dinheiro, Pix
    tipo_gasto: str = "Variável"  # Fixo, Variável
    origem: str = "manual"  # manual, csv, ia

    cartao_id: Optional[int] = Field(default=None, foreign_key="cartoes.id")
    fatura_mes: Optional[int] = None
    fatura_ano: Optional[int] = None

    parcelado: bool = False
    total_parcelas: Optional[int] = None
