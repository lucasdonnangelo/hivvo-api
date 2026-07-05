import datetime as dt
import uuid
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class RecorrenciaCreate(BaseModel):
    # F-22: max_length generoso nos campos de texto de ENTRADA. Categoria é
    # string livre (desnormalizada — padrão do projeto, igual a transações).
    # frequencia não é aceita: só 'mensal' existe hoje (default do model).
    tipo: str = Field(..., max_length=20)
    valor: Decimal
    categoria: str = Field(..., max_length=200)
    forma_pagamento: str = Field("Pix", max_length=50)
    dia_do_mes: int = Field(..., ge=1, le=31)
    descricao: str = Field(..., max_length=200)
    # Início opcional (os dois juntos): ausente = mês corrente (hoje()).
    mes_inicio: Optional[int] = Field(None, ge=1, le=12)
    ano_inicio: Optional[int] = Field(None, ge=2000)

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
    def inicio_completo(self) -> "RecorrenciaCreate":
        # Espelha o CHECK de pareamento das vigências: os dois juntos ou nenhum.
        if (self.mes_inicio is None) != (self.ano_inicio is None):
            raise ValueError("mes_inicio e ano_inicio devem vir juntos (ou nenhum)")
        return self


class RecorrenciaUpdate(BaseModel):
    """PATCH — dois caminhos (PLANO §3.4): `valor` é VERSIONADO (fecha vigência
    + abre nova); os demais são metadados retroativos (cabeçalho direto)."""

    valor: Optional[Decimal] = None
    descricao: Optional[str] = Field(None, max_length=200)
    categoria: Optional[str] = Field(None, max_length=200)
    dia_do_mes: Optional[int] = Field(None, ge=1, le=31)
    forma_pagamento: Optional[str] = Field(None, max_length=50)

    @field_validator("valor", mode="before")
    @classmethod
    def normaliza_decimal(cls, v: object) -> object:
        if isinstance(v, str):
            return v.replace(",", ".")
        return v

    @field_validator("valor")
    @classmethod
    def valor_positivo(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= 0:
            raise ValueError("valor deve ser positivo")
        return v


class RecorrenciaCorrigirValor(BaseModel):
    """PATCH /{id}/corrigir-valor — operação de ERRO (§3.1.2): reescreve o valor
    em TODOS os meses (só permitido com vigência única). Distinta do PATCH
    normal, que VERSIONA ("a realidade mudou")."""

    valor: Decimal

    @field_validator("valor", mode="before")
    @classmethod
    def normaliza_decimal(cls, v: object) -> object:
        if isinstance(v, str):
            return v.replace(",", ".")
        return v

    @field_validator("valor")
    @classmethod
    def valor_positivo(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("valor deve ser positivo")
        return v


class VigenciaResponse(BaseModel):
    valor: Decimal
    mes_inicio: int
    ano_inicio: int
    mes_fim: Optional[int] = None
    ano_fim: Optional[int] = None

    model_config = {"from_attributes": True}


class RecorrenciaResponse(BaseModel):
    id: uuid.UUID
    tipo: str
    categoria: str
    forma_pagamento: str
    frequencia: str
    dia_do_mes: int
    descricao: str
    ativa: bool
    data_criacao: dt.datetime
    # Valor da vigência do mês corrente (None se nada vige — ex.: encerrada,
    # ou início futuro) — para a UI mostrar "salário: R$X" sem abrir o detalhe.
    valor_vigente: Optional[Decimal] = None
    # Valor a EXIBIR/preencher na gestão (Bug 1): = valor_vigente, ou o da
    # vigência futura mais próxima quando nada vige hoje (início futuro).
    # None só quando encerrada (só passado). Aditivo — não substitui valor_vigente.
    valor_exibicao: Optional[Decimal] = None
    # Início (mês/ano) da vigência de exibição, para a UI mostrar "a partir de
    # ago/2026". Vêm da MESMA vigência que valor_exibicao. None quando já vige
    # hoje (sem "a partir de") ou encerrada — coerentes com valor_exibicao.
    mes_exibicao: Optional[int] = None
    ano_exibicao: Optional[int] = None

    model_config = {"from_attributes": True}


class RecorrenciaDetailResponse(RecorrenciaResponse):
    vigencias: list[VigenciaResponse] = []
