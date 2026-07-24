import datetime as dt
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel

# Status derivado da fatura (Leva 2 — PLANO_3D_PAGAMENTO_FATURA), nunca
# materializado: `vazia` = competência SEM lançamento (nada a pagar, status
# neutro — não é atrasada); `paga` = pago=True e o pagamento COBRE o total
# atual (valor_pago >= total); `paga_parcial` (#9) = pago=True mas o total
# cresceu depois (compra retroativa) — falta (total − valor_pago), refletida
# no a_pagar das estatísticas; `aberta` = ainda aceita compras (fechamento não
# passou); `a_vencer`/`atrasada` = fechada e não confirmada, antes/depois do
# vencimento. Só `FaturaDetalhe` chega a emitir `vazia` (detalhe de uma
# competência que pode não ter lançamento).
StatusFatura = Literal[
    "vazia", "paga", "paga_parcial", "aberta", "a_vencer", "atrasada"
]


class ParcelaFaturaResponse(BaseModel):
    id: int
    transacao_id: int
    numero_parcela: int
    total_parcelas: int
    valor_parcela: Decimal
    descricao: str
    categoria: str
    cancelado: bool
    data_vencimento: dt.date

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
    total_itens: int = 0
    status: StatusFatura


class FaturaDetalhe(BaseModel):
    mes: int
    ano: int
    total: Decimal
    data_vencimento: Optional[dt.date] = None
    status: StatusFatura
    parcelas: list[ParcelaFaturaResponse]
    avulsas: list[TransacaoFaturaResponse]


class FaturaCartaoItem(BaseModel):
    """Fatura de UM cartão numa competência (lente 3d: 1 mês × N cartões)."""

    cartao_id: int
    cartao_nome: str
    total: Decimal
    data_vencimento: Optional[dt.date] = None
    status: StatusFatura


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


class PagamentoFaturaUpdate(BaseModel):
    """Body do PUT de pagamento — só a intenção; data_pagamento é do servidor."""

    pago: bool

    model_config = {"extra": "forbid"}


class PagamentoFaturaResponse(BaseModel):
    """Estado da confirmação + o status derivado resultante.

    `valor_pago` (#9): snapshot do total no instante da confirmação — None
    quando pago=False. Aditivo: o front pode exibir a cobertura sem recalcular.
    """

    cartao_id: int
    ano: int
    mes: int
    pago: bool
    valor_pago: Optional[Decimal] = None
    data_pagamento: Optional[dt.date] = None
    status: StatusFatura
