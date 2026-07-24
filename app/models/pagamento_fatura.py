import datetime as dt
from decimal import Decimal
from typing import Optional

from sqlmodel import Field, SQLModel
from sqlalchemy import CheckConstraint, Column, Numeric, UniqueConstraint

from app.core.dates import hoje


class PagamentoFatura(SQLModel, table=True):
    """Confirmação de pagamento de UMA fatura (cartão + competência) — Leva 2.

    Fonte única de "essa fatura foi paga" (PLANO_3D_PAGAMENTO_FATURA):
    substitui Parcela.pago na marcação `a_pagar` e mata a presunção
    "avulsa vencida = paga" da Fonte 2. Semântica dos estados:
    - AUSÊNCIA de registro = pagamento não confirmado;
    - registro com pago=False = o usuário disse "não paguei" (equivale à
      ausência para o status derivado; existe pela reversibilidade do PUT);
    - registro com pago=True = fatura paga (sai do a_pagar, status `paga`
      ou `paga_parcial` — ver valor_pago).

    `valor_pago` (#9 — cobertura): total da fatura NO INSTANTE em que foi
    marcada paga. Compra retroativa sobe o total sem tocar aqui → o status
    derivado vira `paga_parcial` e a descoberta (total − valor_pago) volta
    ao "A pagar". NULL só quando pago=False (CHECK); pago=True sempre grava
    (PUT e import). Snapshot, não derivado — é o único fato histórico.

    Chave natural (cartao_id, fatura_ano, fatura_mes) — um registro por
    fatura. O status (paga/paga_parcial/aberta/a_vencer/atrasada) NUNCA é
    materializado aqui: é derivado on-the-fly (services/faturas.status_fatura,
    por COBERTURA: valor_pago >= total atual → paga; menor → paga_parcial).
    """

    __tablename__ = "pagamentos_fatura"
    __table_args__ = (
        UniqueConstraint(
            "cartao_id", "fatura_ano", "fatura_mes",
            name="uq_pagamentos_fatura_competencia",
        ),
        CheckConstraint(
            "fatura_mes BETWEEN 1 AND 12", name="ck_pagamentos_fatura_mes_valido"
        ),
        CheckConstraint(
            "NOT pago OR valor_pago IS NOT NULL",
            name="ck_pagamentos_fatura_valor_pago_quando_pago",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    cartao_id: int = Field(foreign_key="cartoes.id")

    fatura_mes: int
    fatura_ano: int

    pago: bool = False
    valor_pago: Optional[Decimal] = Field(
        default=None, sa_column=Column(Numeric(15, 2))
    )
    data_pagamento: Optional[dt.date] = None
    criado_em: dt.date = Field(default_factory=hoje)
