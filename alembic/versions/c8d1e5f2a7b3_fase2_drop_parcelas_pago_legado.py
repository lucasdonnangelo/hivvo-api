"""fase2 (#8): drop físico de parcelas.pago e parcelas.data_pagamento

Revision ID: c8d1e5f2a7b3
Revises: a3d9f4c2b7e1
Create Date: 2026-07-16 12:00:00.000000

Parcela.pago/data_pagamento morreram na Leva 2 (PagamentoFatura é a fonte
única de "fatura paga") e a Fase 1 do #8 removeu as últimas referências de
contrato (ParcelaResponse, ParcelaFaturaResponse, total_parcelas_pagas e o
filtro ?pago=). Este é o drop físico — zero leitores/escritores no código.

Escrita à mão (não autogenerate). NÃO cria tabela — só ALTER TABLE em
`parcelas` (a regra de RLS para tabelas novas não se aplica).

downgrade(): reversível em SCHEMA — re-adiciona `pago` Boolean NOT NULL
(server_default=false, necessário para repovoar linhas existentes; em
produção todo valor era False mesmo — Leva 2 nasceu sem backfill) e
`data_pagamento` Date nullable. Os DADOS dropados não voltam.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8d1e5f2a7b3"
down_revision: Union[str, None] = "a3d9f4c2b7e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("parcelas", "pago")
    op.drop_column("parcelas", "data_pagamento")


def downgrade() -> None:
    op.add_column(
        "parcelas",
        sa.Column("pago", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "parcelas",
        sa.Column("data_pagamento", sa.Date(), nullable=True),
    )
