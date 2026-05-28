from typing import Optional
from sqlmodel import Field, SQLModel
import datetime as dt


class Usuario(SQLModel, table=True):
    __tablename__ = "usuarios"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    username: str = Field(unique=True, index=True)
    senha_hash: str
    nome_completo: str
    criado_em: dt.datetime = Field(default_factory=dt.datetime.utcnow)
    ativo: bool = True

    tentativas_login: int = 0
    bloqueado_ate: Optional[dt.datetime] = None
