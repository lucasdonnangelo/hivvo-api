import datetime as dt
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class ParcelaFaturaResponse(BaseModel):
    id: int
    transacao_id: int
    numero_parcela: int
    total_parcelas: int
    valor_parcela: Decimal
    descricao: str
    categoria: str
    pago: bool
    cancelado: bool
    data_vencimento: dt.date
    data_pagamento: Optional[dt.date] = None

    model_config = {"from_attributes": True}


class TransacaoFaturaResponse(BaseModel):
    id: int
    descricao: str
    valor: Decimal
    categoria: str
    data: dt.date
    tipo_gasto: str

    model_config = {"from_attributes": True}


class FaturaListItem(BaseModel):
    mes: int
    ano: int
    total: Decimal
    data_vencimento: Optional[dt.date] = None
    total_parcelas_pagas: int = 0
    total_itens: int = 0


class FaturaDetalhe(BaseModel):
    mes: int
    ano: int
    total: Decimal
    data_vencimento: Optional[dt.date] = None
    parcelas: list[ParcelaFaturaResponse]
    avulsas: list[TransacaoFaturaResponse]


class FaturaCartaoItem(BaseModel):
    """Fatura de UM cartão numa competência (lente 3d: 1 mês × N cartões)."""

    cartao_id: int
    cartao_nome: str
    total: Decimal
    data_vencimento: Optional[dt.date] = None


class CompetenciaFaturas(BaseModel):
    """Faturas de todos os cartões numa competência (ano, mes).

    Uma linha por cartão COM fatura no mês (total > 0) — cartões sem lançamento
    naquela competência não aparecem. `total_geral` = soma das faturas exibidas.
    Ordenado por data_vencimento (o que vence primeiro em cima).
    """

    ano: int
    mes: int
    total_geral: Decimal
    faturas: list[FaturaCartaoItem]


class ProximaFaturaResponse(BaseModel):
    """Competência em que a tela 3d abre = a próxima fatura a vencer."""

    ano: int
    mes: int
