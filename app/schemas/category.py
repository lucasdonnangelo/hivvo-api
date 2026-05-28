import datetime as dt
from typing import Optional

from pydantic import BaseModel


class CategoriaCreate(BaseModel):
    nome: str
    icone: str = "📦"
    tipo: str = "despesa"


class CategoriaResponse(BaseModel):
    id: Optional[int] = None
    nome: str
    icone: str
    tipo: str
    ativa: bool = True
    is_padrao: bool = False
    criado_em: Optional[dt.date] = None

    model_config = {"from_attributes": True}
