import datetime as dt
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, model_validator


class ParcelaUpdate(BaseModel):
    pago: Optional[bool] = None
    data_pagamento: Optional[dt.date] = None
    cancelado: Optional[bool] = None
    data_vencimento: Optional[dt.date] = None

    @model_validator(mode="after")
    def pago_requer_data(self) -> "ParcelaUpdate":
        # Se marcar como paga sem informar data, data_pagamento será preenchida
        # pelo router com a data de hoje — sem necessidade de validação aqui.
        if self.data_pagamento and not self.pago:
            raise ValueError("data_pagamento só pode ser definida quando pago=True")
        return self


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
