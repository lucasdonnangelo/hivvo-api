import datetime as dt
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class TransacaoCreate(BaseModel):
    # F-22: max_length generoso por campo nos campos de texto de ENTRADA
    tipo: str = Field(..., max_length=20)
    data: dt.date
    descricao: str = Field(..., max_length=200)
    valor: Decimal
    categoria: str = Field(..., max_length=200)
    forma_pagamento: str = Field("Débito", max_length=50)
    tipo_gasto: str = Field("Variável", max_length=50)
    origem: str = Field("manual", max_length=50)
    cartao_id: Optional[int] = None
    parcelado: bool = False
    total_parcelas: Optional[int] = None

    @field_validator("valor", mode="before")
    @classmethod
    def normaliza_decimal(cls, v: object) -> object:
        if isinstance(v, str):
            return v.replace(",", ".")
        return v

    @field_validator("tipo")
    @classmethod
    def tipo_valido(cls, v: str) -> str:
        if v not in ("receita", "despesa"):
            raise ValueError("tipo deve ser 'receita' ou 'despesa'")
        return v

    @field_validator("valor")
    @classmethod
    def valor_positivo(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("valor deve ser positivo")
        return v

    @model_validator(mode="after")
    def valida_parcelamento(self) -> "TransacaoCreate":
        if self.parcelado and (self.total_parcelas is None or self.total_parcelas < 2):
            raise ValueError("total_parcelas deve ser >= 2 quando parcelado=True")
        if self.parcelado and self.valor < self.total_parcelas * Decimal("0.01"):
            raise ValueError(
                "valor muito baixo para o número de parcelas: "
                "cada parcela deve ser de pelo menos R$ 0,01"
            )
        return self


class TransacaoUpdate(BaseModel):
    # fatura_mes/fatura_ano são derivados da data de vencimento — o cliente
    # não os define (T-35/F-15); a rederivação no endpoint é o Batch 3b.
    tipo: Optional[str] = Field(None, max_length=20)
    data: Optional[dt.date] = None
    descricao: Optional[str] = Field(None, max_length=200)
    valor: Optional[Decimal] = None
    categoria: Optional[str] = Field(None, max_length=200)
    forma_pagamento: Optional[str] = Field(None, max_length=50)
    tipo_gasto: Optional[str] = Field(None, max_length=50)
    cartao_id: Optional[int] = None

    @field_validator("valor", mode="before")
    @classmethod
    def normaliza_decimal(cls, v: object) -> object:
        if isinstance(v, str):
            return v.replace(",", ".")
        return v

    @field_validator("tipo")
    @classmethod
    def tipo_valido(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("receita", "despesa"):
            raise ValueError("tipo deve ser 'receita' ou 'despesa'")
        return v

    @field_validator("valor")
    @classmethod
    def valor_positivo(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= 0:
            raise ValueError("valor deve ser positivo")
        return v


class TransacaoResponse(BaseModel):
    id: int
    usuario_id: int
    tipo: str
    data: dt.date
    descricao: str
    valor: Decimal
    categoria: str
    forma_pagamento: str
    tipo_gasto: str
    origem: str
    cartao_id: Optional[int] = None
    fatura_mes: Optional[int] = None
    fatura_ano: Optional[int] = None
    parcelado: bool
    total_parcelas: Optional[int] = None

    model_config = {"from_attributes": True}


class TransacaoCreateResponse(TransacaoResponse):
    parcelas_criadas: int = 0
