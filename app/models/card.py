from typing import Optional
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import Numeric
from decimal import Decimal
import datetime as dt

from app.core.dates import hoje


class Cartao(SQLModel, table=True):
    __tablename__ = "cartoes"

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)

    nome: str  # Ex: "Nubank", "Inter Mastercard"
    tipo: str  # "Crédito", "Débito", "Ambos"
    limite: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(15, 2)))

    dia_vencimento: Optional[int] = None
    dia_fechamento: Optional[int] = None
    mes_offset_vencimento: int = 1  # Meses entre fechamento e vencimento

    ativo: bool = True
    criado_em: dt.date = Field(default_factory=hoje)
