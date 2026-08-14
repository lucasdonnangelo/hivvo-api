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

    # #6 — aviso de vencimento por e-mail. LIGADO por padrão (opt-out, não
    # opt-in): ninguém procura uma configuração que não sabe que existe, e
    # opt-in aqui significaria que na prática ninguém recebe. O e-mail diz
    # como desligar. Coluna em tabela EXISTENTE — sem questão de RLS.
    notificar_vencimento: bool = True
