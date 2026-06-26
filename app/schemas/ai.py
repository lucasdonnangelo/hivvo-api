import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class HistoricoResponseItem(BaseModel):
    # Schema de RELEITURA (montado de rows do banco) — sem max_length em `text`
    # de propósito (T-37): não rejeitar dado já persistido.
    role: Literal["user", "assistant"]
    text: str
    created_at: dt.datetime


class ChatRequest(BaseModel):
    mensagem: str = Field(..., min_length=1, max_length=2000)
    mes: int = Field(..., ge=1, le=12)
    ano: int = Field(..., ge=2000)
    sessao_id: uuid.UUID  # F-16: entrada malformada vira 422 automático


class ChatResponse(BaseModel):
    resposta: str


class SuggestCategoryRequest(BaseModel):
    descricao: str = Field(..., min_length=1, max_length=500)  # F-22
    valor: Optional[Decimal] = None
    tipo: Optional[Literal["receita", "despesa"]] = None


class SuggestCategoryResponse(BaseModel):
    categoria: str
