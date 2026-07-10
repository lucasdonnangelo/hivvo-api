import datetime as dt
from typing import Optional

from sqlmodel import Field, SQLModel
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.core.dates import hoje


class PagamentoFatura(SQLModel, table=True):
    """Confirmação de pagamento de UMA fatura (cartão + competência) — Leva 2.

    Fonte única de "essa fatura foi paga" (PLANO_3D_PAGAMENTO_FATURA):
    substitui Parcela.pago na marcação `a_pagar` e mata a presunção
    "avulsa vencida = paga" da Fonte 2. Semântica dos estados:
    - AUSÊNCIA de registro = pagamento não confirmado;
    - registro com pago=False = o usuário disse "não paguei" (equivale à
      ausência para o status derivado; existe pela reversibilidade do PUT);
    - registro com pago=True = fatura paga (sai do a_pagar, status `paga`).

    Chave natural (cartao_id, fatura_ano, fatura_mes) — um registro por
    fatura. O status (paga/aberta/a_vencer/atrasada) NUNCA é materializado
    aqui: é derivado on-the-fly (services/faturas.status_fatura).
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
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    usuario_id: int = Field(foreign_key="usuarios.id", index=True)
    cartao_id: int = Field(foreign_key="cartoes.id")

    fatura_mes: int
    fatura_ano: int

    pago: bool = False
    data_pagamento: Optional[dt.date] = None
    criado_em: dt.date = Field(default_factory=hoje)
