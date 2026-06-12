import datetime as dt
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator


class CartaoCreate(BaseModel):
    nome: str
    tipo: str
    limite: Optional[Decimal] = None
    dia_vencimento: Optional[int] = None
    dia_fechamento: Optional[int] = None
    mes_offset_vencimento: int = 1

    @field_validator("tipo")
    @classmethod
    def tipo_valido(cls, v: str) -> str:
        if v not in ("Crédito", "Débito", "Ambos"):
            raise ValueError("tipo deve ser 'Crédito', 'Débito' ou 'Ambos'")
        return v

    @field_validator("dia_vencimento", "dia_fechamento", mode="before")
    @classmethod
    def dia_valido(cls, v):
        if v is not None and not (1 <= int(v) <= 31):
            raise ValueError("dia deve estar entre 1 e 31")
        return v

    @field_validator("mes_offset_vencimento")
    @classmethod
    def offset_nao_negativo(cls, v: int) -> int:
        if v < 0:
            raise ValueError("mes_offset_vencimento deve ser >= 0")
        return v


class CartaoUpdate(BaseModel):
    nome: Optional[str] = None
    tipo: Optional[str] = None
    limite: Optional[Decimal] = None
    dia_vencimento: Optional[int] = None
    dia_fechamento: Optional[int] = None
    mes_offset_vencimento: Optional[int] = None
    ativo: Optional[bool] = None

    @field_validator("tipo")
    @classmethod
    def tipo_valido(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("Crédito", "Débito", "Ambos"):
            raise ValueError("tipo deve ser 'Crédito', 'Débito' ou 'Ambos'")
        return v

    @field_validator("dia_vencimento", "dia_fechamento", mode="before")
    @classmethod
    def dia_valido(cls, v):
        if v is not None and not (1 <= int(v) <= 31):
            raise ValueError("dia deve estar entre 1 e 31")
        return v

    @field_validator("mes_offset_vencimento")
    @classmethod
    def offset_nao_negativo(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("mes_offset_vencimento deve ser >= 0")
        return v


class CartaoResponse(BaseModel):
    id: int
    usuario_id: int
    nome: str
    tipo: str
    limite: Optional[Decimal] = None
    dia_vencimento: Optional[int] = None
    dia_fechamento: Optional[int] = None
    mes_offset_vencimento: int
    ativo: bool
    criado_em: dt.date

    model_config = {"from_attributes": True}


class CartaoComFaturaResponse(CartaoResponse):
    fatura_aberta_total: Optional[Decimal] = None
    fatura_aberta_mes: Optional[int] = None
    fatura_aberta_ano: Optional[int] = None
    fatura_aberta_vencimento: Optional[dt.date] = None
