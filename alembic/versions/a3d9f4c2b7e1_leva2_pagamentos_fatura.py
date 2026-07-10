"""leva2 pagamentos_fatura (confirmação de pagamento por fatura)

Revision ID: a3d9f4c2b7e1
Revises: f2a7c9d1e8b3
Create Date: 2026-07-10 12:00:00.000000

Leva 2 do PLANO_3D_PAGAMENTO_FATURA — fonte única de "essa fatura foi paga":
- pagamentos_fatura: um registro por (cartao_id, fatura_ano, fatura_mes)
  (UNIQUE — chave natural), escopado por usuario_id. Ausência = não
  confirmado; pago=False = "não paguei"; pago=True = paga.
- Tabela criada VAZIA, SEM backfill (não há base instalada — decisão da leva).
- FKs com ON DELETE CASCADE (usuarios e cartoes; defesa em profundidade — o
  delete de cartão via API é soft) + índice composto
  (usuario_id, fatura_ano, fatura_mes) para a query das estatísticas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3d9f4c2b7e1"
down_revision: Union[str, None] = "f2a7c9d1e8b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pagamentos_fatura",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("cartao_id", sa.Integer(), nullable=False),
        sa.Column("fatura_mes", sa.Integer(), nullable=False),
        sa.Column("fatura_ano", sa.Integer(), nullable=False),
        sa.Column("pago", sa.Boolean(), nullable=False),
        sa.Column("data_pagamento", sa.Date(), nullable=True),
        sa.Column("criado_em", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "fatura_mes BETWEEN 1 AND 12", name="ck_pagamentos_fatura_mes_valido"
        ),
        sa.UniqueConstraint(
            "cartao_id", "fatura_ano", "fatura_mes",
            name="uq_pagamentos_fatura_competencia",
        ),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cartao_id"], ["cartoes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pagamentos_fatura_usuario_id", "pagamentos_fatura", ["usuario_id"]
    )
    op.create_index(
        "ix_pagamentos_fatura_usuario_competencia",
        "pagamentos_fatura",
        ["usuario_id", "fatura_ano", "fatura_mes"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pagamentos_fatura_usuario_competencia", table_name="pagamentos_fatura"
    )
    op.drop_index("ix_pagamentos_fatura_usuario_id", table_name="pagamentos_fatura")
    op.drop_table("pagamentos_fatura")
