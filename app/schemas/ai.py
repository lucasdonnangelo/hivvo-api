from typing import Literal

from pydantic import BaseModel, Field


class HistoricoItem(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(..., min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    mensagem: str = Field(..., min_length=1, max_length=2000)
    mes: int = Field(..., ge=1, le=12)
    ano: int = Field(..., ge=2000)
    historico: list[HistoricoItem] = Field(default_factory=list)


class ChatResponse(BaseModel):
    resposta: str
