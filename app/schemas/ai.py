import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field


class HistoricoResponseItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    created_at: dt.datetime


class ChatRequest(BaseModel):
    mensagem: str = Field(..., min_length=1, max_length=2000)
    mes: int = Field(..., ge=1, le=12)
    ano: int = Field(..., ge=2000)
    sessao_id: str = Field(..., min_length=36, max_length=36)


class ChatResponse(BaseModel):
    resposta: str
