"""Data de negócio do produto.

O servidor de produção roda em UTC; para um usuário no Brasil (UTC-3),
date.today() do servidor já é "amanhã" entre 21h e meia-noite. Toda data
de negócio "hoje" (data de pagamento, fatura aberta, criado_em de domínio)
usa o fuso do produto (T-27). Timestamps técnicos continuam em UTC.

Em testes, fixar a data com patch neste helper (ou no nome importado pelo
módulo sob teste, ex. app.routers.cards.hoje).
"""

import datetime as dt
from zoneinfo import ZoneInfo

TZ_PRODUTO = ZoneInfo("America/Sao_Paulo")


def hoje() -> dt.date:
    """Data 'hoje' no fuso do produto (America/Sao_Paulo)."""
    return dt.datetime.now(TZ_PRODUTO).date()


def agora() -> dt.datetime:
    """Datetime 'agora' no fuso do produto (America/Sao_Paulo)."""
    return dt.datetime.now(TZ_PRODUTO)
