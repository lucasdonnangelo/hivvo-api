import datetime as dt
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class ParcelaUpdate(BaseModel):
    # Leva 2 (PLANO_3D): `pago`/`data_pagamento` SAÍRAM do update — pagamento
    # agora é por FATURA (PUT /invoices/{cartao_id}/{ano}/{mes}/pagamento).
    # extra="forbid" faz mandar `pago` virar 422 explícito, não um no-op
    # silencioso sobre a coluna obsoleta.
    cancelado: Optional[bool] = None
    data_vencimento: Optional[dt.date] = None

    model_config = {"extra": "forbid"}


class ParcelaResponse(BaseModel):
    id: int
    usuario_id: int
    transacao_id: int
    cartao_id: Optional[int] = None
    numero_parcela: int
    total_parcelas: int
    valor_parcela: Decimal
    descricao: str
    categoria: str
    data_vencimento: dt.date
    data_pagamento: Optional[dt.date] = None
    fatura_mes: Optional[int] = None
    fatura_ano: Optional[int] = None
    pago: bool
    cancelado: bool
    criado_em: dt.date

    model_config = {"from_attributes": True}
