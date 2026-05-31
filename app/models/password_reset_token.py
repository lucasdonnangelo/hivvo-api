import datetime as dt
from typing import Optional

from sqlmodel import Field, SQLModel


class PasswordResetToken(SQLModel, table=True):
    __tablename__ = "password_reset_tokens"

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    token: str = Field(unique=True, index=True)
    expires_at: dt.datetime
    usado: bool = False
