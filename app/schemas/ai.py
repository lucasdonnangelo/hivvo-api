from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    mensagem: str = Field(..., min_length=1, max_length=2000)
    mes: int = Field(..., ge=1, le=12)
    ano: int = Field(..., ge=2000)


class ChatResponse(BaseModel):
    resposta: str
