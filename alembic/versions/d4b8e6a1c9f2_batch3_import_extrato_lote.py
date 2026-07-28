"""batch3 import_extrato_lote (guard de idempotência da importação de extrato)

Revision ID: d4b8e6a1c9f2
Revises: b7e4a2c9f1d6
Create Date: 2026-07-28 10:00:00.000000

Batch 3 do import de EXTRATO — a primeira escrita do fluxo de extrato. O commit
materializa os três baldes (receita, débito, pagamento de fatura) + o rendimento
do resumo; este lote é o guard de idempotência: um registro por extrato
importado na chave natural (usuario_id, banco, periodo_de, periodo_ate). O
commit insere o lote PRIMEIRO na mesma transação — violação do UNIQUE = 409
(fecha a corrida de duplo-clique de forma atômica).

Sem cartao_id (ao contrário do lote de fatura): o extrato é da CONTA. `banco`
entra normalizado pelo código (ver app/models/import_extrato_lote.py).

Escrita à mão (não autogenerate). CRIA TABELA → ativa RLS no upgrade() (como as
demais tabelas do produto; sem policies aqui). FK ON DELETE CASCADE (usuarios) +
índice por usuario_id.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4b8e6a1c9f2"
down_revision: Union[str, None] = "b7e4a2c9f1d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "import_extrato_lote",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("banco", sa.String(), nullable=False),
        sa.Column("periodo_de", sa.Date(), nullable=False),
        sa.Column("periodo_ate", sa.Date(), nullable=False),
        sa.Column("criada_em", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "periodo_de <= periodo_ate", name="ck_import_extrato_lote_periodo_ordenado"
        ),
        sa.UniqueConstraint(
            "usuario_id", "banco", "periodo_de", "periodo_ate",
            name="uq_import_extrato_lote_periodo",
        ),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_import_extrato_lote_usuario_id", "import_extrato_lote", ["usuario_id"]
    )
    # Tabela nova → RLS ligado (padrão do produto; isolamento é reforçado no
    # código por usuario_id, esta é a rede de segurança no banco).
    op.execute("ALTER TABLE import_extrato_lote ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_import_extrato_lote_usuario_id", table_name="import_extrato_lote")
    op.drop_table("import_extrato_lote")
