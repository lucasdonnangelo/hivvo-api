import datetime as dt
from typing import Optional

from pydantic import BaseModel, Field


class CategoriaCreate(BaseModel):
    # F-22: max_length nos campos de texto de entrada
    nome: str = Field(..., max_length=200)
    icone: str = Field("📦", max_length=50)
    tipo: str = Field("despesa", max_length=20)


class CategoriaResponse(BaseModel):
    id: Optional[int] = None
    nome: str
    icone: str
    tipo: str
    ativa: bool = True
    is_padrao: bool = False
    criado_em: Optional[dt.date] = None

    model_config = {"from_attributes": True}
