"""batch2 import_fatura_lote (guard de idempotência da importação de fatura)

Revision ID: c1a2b3d4e5f6
Revises: c8d1e5f2a7b3
Create Date: 2026-07-17 12:00:00.000000

Batch 2 do import de fatura — a primeira escrita no banco. O commit
materializa transações/parcelas a partir da fatura revisada; este lote é o
guard de idempotência: um registro por fatura importada na chave natural
(usuario_id, cartao_id, fatura_mes, fatura_ano), com a competência = âncora
(mês de vencimento). O commit insere o lote PRIMEIRO na mesma transação —
violação do UNIQUE = 409 (fecha a corrida de duplo-clique de forma atômica).

Escrita à mão (não autogenerate). CRIA TABELA → ativa RLS no upgrade()
(como as demais tabelas do produto; sem policies aqui). FKs ON DELETE CASCADE
(usuarios e cartoes) + índice por usuario_id.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1a2b3d4e5f6"
down_revision: Union[str, None] = "c8d1e5f2a7b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_fatura_lote",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("cartao_id", sa.Integer(), nullable=False),
        sa.Column("fatura_mes", sa.Integer(), nullable=False),
        sa.Column("fatura_ano", sa.Integer(), nullable=False),
        sa.Column("criada_em", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "fatura_mes BETWEEN 1 AND 12", name="ck_import_fatura_lote_mes_valido"
        ),
        sa.UniqueConstraint(
            "usuario_id", "cartao_id", "fatura_mes", "fatura_ano",
            name="uq_import_fatura_lote_competencia",
        ),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cartao_id"], ["cartoes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_fatura_lote_usuario_id", "import_fatura_lote", ["usuario_id"]
    )
    # Tabela nova → RLS ligado (padrão do produto; isolamento é reforçado no
    # código por usuario_id, esta é a rede de segurança no banco).
    op.execute("ALTER TABLE import_fatura_lote ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_import_fatura_lote_usuario_id", table_name="import_fatura_lote")
    op.drop_table("import_fatura_lote")
