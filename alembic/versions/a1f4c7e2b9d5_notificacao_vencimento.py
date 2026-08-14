"""notificacao_envio (guard) + usuarios.notificar_vencimento (preferência)

Revision ID: a1f4c7e2b9d5
Revises: d4b8e6a1c9f2
Create Date: 2026-08-14 10:00:00.000000

Batch 1 do aviso de vencimento (#6). Duas mudanças, uma migration, porque uma
sem a outra não entrega nada: o guard sem a preferência manda e-mail para quem
não quer, e a preferência sem o guard manda o mesmo e-mail várias vezes.

1. `notificacao_envio` — TABELA NOVA. Um registro por (usuario_id,
   data_referencia, tipo); o UNIQUE é o mecanismo de idempotência (o envio
   insere ANTES de enviar e commita depois). CRIA TABELA → **ativa RLS no
   upgrade()**: o Alembic não sabe de RLS e tabela nova nasce EXPOSTA no
   Postgres. Regra não-negociável do produto, mesma das duas tabelas de lote
   de importação. FK ON DELETE CASCADE (usuarios) + índice por usuario_id.

2. `usuarios.notificar_vencimento` — coluna em tabela EXISTENTE (sem RLS a
   ativar; `usuarios` já tem). `server_default` de `true` para as linhas que
   já existem nascerem LIGADAS — é a decisão de produto (opt-out) escrita no
   schema, não só no modelo. O default fica na coluna depois do backfill: um
   INSERT que não cite a coluna (seed, script) também nasce ligado, em vez de
   violar o NOT NULL.

Escrita à mão (não autogenerate).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1f4c7e2b9d5"
down_revision: Union[str, None] = "d4b8e6a1c9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notificacao_envio",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("data_referencia", sa.Date(), nullable=False),
        sa.Column("tipo", sa.String(), nullable=False),
        sa.Column("criado_em", sa.Date(), nullable=False),
        sa.UniqueConstraint(
            "usuario_id", "data_referencia", "tipo",
            name="uq_notificacao_envio_usuario_dia_tipo",
        ),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notificacao_envio_usuario_id", "notificacao_envio", ["usuario_id"]
    )
    # Tabela nova → RLS ligado (padrão do produto; o isolamento é reforçado no
    # código por usuario_id, esta é a rede de segurança no banco).
    op.execute("ALTER TABLE notificacao_envio ENABLE ROW LEVEL SECURITY")

    op.add_column(
        "usuarios",
        sa.Column(
            "notificar_vencimento",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("usuarios", "notificar_vencimento")
    op.drop_index("ix_notificacao_envio_usuario_id", table_name="notificacao_envio")
    op.drop_table("notificacao_envio")
