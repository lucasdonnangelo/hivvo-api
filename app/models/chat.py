import datetime as dt
import uuid
from typing import Optional

from sqlmodel import Field, SQLModel


class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: Optional[uuid.UUID] = Field(default_factory=uuid.uuid4, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    role: str = Field(max_length=20)
    text: str
    created_at: dt.datetime = Field(default_factory=dt.datetime.utcnow, index=True)
