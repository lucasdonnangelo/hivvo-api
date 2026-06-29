from typing import Optional
from sqlmodel import Field, SQLModel
from sqlalchemy import Index, text
import datetime as dt

from app.core.dates import hoje


class CategoriaCustomizada(SQLModel, table=True):
    __tablename__ = "categorias"
    # T-11: índice parcial UNIQUE — a regra real, dado o soft delete, é "não duas
    # categorias ATIVAS com o mesmo nome" (normalizado por lower(trim)). Linhas
    # inativas duplicadas são esperadas (histórico preservado). WHERE por dialeto:
    # 'ativa = true' no Postgres, 'ativa = 1' no SQLite (boolean é INTEGER lá).
    __table_args__ = (
        Index(
            "uq_categorias_usuario_nome_ativa",
            text("usuario_id"),
            text("lower(trim(nome))"),
            unique=True,
            postgresql_where=text("ativa = true"),
            sqlite_where=text("ativa = 1"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)

    nome: str
    icone: str = "📦"
    tipo: str = "despesa"  # "despesa" | "receita"
    ativa: bool = True
    criado_em: dt.date = Field(default_factory=hoje)
