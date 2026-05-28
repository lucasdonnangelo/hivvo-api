from typing import Optional
from sqlmodel import Field, SQLModel
import datetime as dt


class CategoriaCustomizada(SQLModel, table=True):
    __tablename__ = "categorias"

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)

    nome: str
    icone: str = "📦"
    tipo: str = "despesa"  # "despesa" | "receita"
    ativa: bool = True
    criado_em: dt.date = Field(default_factory=dt.date.today)
