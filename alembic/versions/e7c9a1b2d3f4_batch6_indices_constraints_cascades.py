"""batch6 indices, constraints, cascades (T-09, T-11, T-14)

Revision ID: e7c9a1b2d3f4
Revises: 1046109fa1a2
Create Date: 2026-06-29 12:00:00.000000

Batch 6 — banco:
- T-09: índices compostos nos padrões de acesso dominantes.
- T-11: colunas monetárias NOT NULL; CHECKs de domínio; UNIQUE de parcelas;
        índice parcial UNIQUE de categorias (só entre ATIVAS, dado o soft delete).
- T-14: FKs de usuario_id (todas as tabelas) e parcelas.transacao_id recriadas
        com ON DELETE CASCADE.

Pré-checagem (PASSO 0) rodada antes desta migration: nenhum dado violante das
constraints novas (0 NULL monetário, 0 valor<=0, 0 tipo inválido, 0 fatura_mes
fora de 1..12, 0 numero_parcela>total_parcelas, 0 parcela duplicada; categorias
sem duas ATIVAS de mesmo nome normalizado).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7c9a1b2d3f4"
down_revision: Union[str, None] = "1046109fa1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# T-14: (constraint, tabela, coluna_local, tabela_ref, coluna_ref).
# Nomes confirmados em pg_constraint. Apenas FKs de usuario_id + parcelas.transacao_id
# (as FKs de cartao_id ficam fora — soft delete de cartão, não cascade).
_CASCADE_FKS = [
    ("cartoes_usuario_id_fkey", "cartoes", "usuario_id", "usuarios", "id"),
    ("categorias_usuario_id_fkey", "categorias", "usuario_id", "usuarios", "id"),
    ("transacoes_usuario_id_fkey", "transacoes", "usuario_id", "usuarios", "id"),
    ("parcelas_usuario_id_fkey", "parcelas", "usuario_id", "usuarios", "id"),
    ("chat_messages_usuario_id_fkey", "chat_messages", "usuario_id", "usuarios", "id"),
    ("refresh_tokens_usuario_id_fkey", "refresh_tokens", "usuario_id", "usuarios", "id"),
    (
        "password_reset_tokens_usuario_id_fkey",
        "password_reset_tokens",
        "usuario_id",
        "usuarios",
        "id",
    ),
    ("parcelas_transacao_id_fkey", "parcelas", "transacao_id", "transacoes", "id"),
]


def upgrade() -> None:
    # ---- T-09: índices compostos ----
    op.create_index("ix_transacoes_usuario_data", "transacoes", ["usuario_id", "data"])
    op.create_index(
        "ix_transacoes_cartao_fatura", "transacoes", ["cartao_id", "fatura_ano", "fatura_mes"]
    )
    op.create_index(
        "ix_parcelas_cartao_fatura", "parcelas", ["cartao_id", "fatura_ano", "fatura_mes"]
    )
    op.create_index(
        "ix_parcelas_usuario_fatura", "parcelas", ["usuario_id", "fatura_ano", "fatura_mes"]
    )
    op.create_index("ix_chat_messages_sessao_id", "chat_messages", ["sessao_id"])

    # ---- T-11: colunas monetárias NOT NULL ----
    op.alter_column("transacoes", "valor", existing_type=sa.Numeric(15, 2), nullable=False)
    op.alter_column("parcelas", "valor_parcela", existing_type=sa.Numeric(15, 2), nullable=False)
    op.alter_column("parcelas", "taxa_juros", existing_type=sa.Numeric(5, 2), nullable=False)
    op.alter_column("parcelas", "valor_juros", existing_type=sa.Numeric(15, 2), nullable=False)

    # ---- T-11: CHECKs de integridade de domínio ----
    op.create_check_constraint("ck_transacoes_valor_positivo", "transacoes", "valor > 0")
    op.create_check_constraint(
        "ck_transacoes_tipo_valido", "transacoes", "tipo IN ('receita', 'despesa')"
    )
    op.create_check_constraint(
        "ck_transacoes_fatura_mes_valido",
        "transacoes",
        "fatura_mes IS NULL OR (fatura_mes BETWEEN 1 AND 12)",
    )
    op.create_check_constraint("ck_parcelas_valor_positivo", "parcelas", "valor_parcela > 0")
    op.create_check_constraint(
        "ck_parcelas_fatura_mes_valido",
        "parcelas",
        "fatura_mes IS NULL OR (fatura_mes BETWEEN 1 AND 12)",
    )
    op.create_check_constraint(
        "ck_parcelas_numero_parcela_valido", "parcelas", "numero_parcela <= total_parcelas"
    )

    # ---- T-11: UNIQUE puro de parcelas + índice parcial UNIQUE de categorias ----
    op.create_unique_constraint(
        "uq_parcelas_transacao_numero", "parcelas", ["transacao_id", "numero_parcela"]
    )
    op.create_index(
        "uq_categorias_usuario_nome_ativa",
        "categorias",
        ["usuario_id", sa.text("lower(trim(nome))")],
        unique=True,
        postgresql_where=sa.text("ativa = true"),
    )

    # ---- T-14: recriar FKs com ON DELETE CASCADE ----
    for fk_name, table, col, ref_table, ref_col in _CASCADE_FKS:
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.create_foreign_key(fk_name, table, ref_table, [col], [ref_col], ondelete="CASCADE")


def downgrade() -> None:
    # ---- T-14: restaurar FKs sem ON DELETE (NO ACTION, estado original) ----
    for fk_name, table, col, ref_table, ref_col in _CASCADE_FKS:
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.create_foreign_key(fk_name, table, ref_table, [col], [ref_col])

    # ---- T-11: índice parcial + UNIQUE puro ----
    op.drop_index("uq_categorias_usuario_nome_ativa", table_name="categorias")
    op.drop_constraint("uq_parcelas_transacao_numero", "parcelas", type_="unique")

    # ---- T-11: CHECKs ----
    op.drop_constraint("ck_parcelas_numero_parcela_valido", "parcelas", type_="check")
    op.drop_constraint("ck_parcelas_fatura_mes_valido", "parcelas", type_="check")
    op.drop_constraint("ck_parcelas_valor_positivo", "parcelas", type_="check")
    op.drop_constraint("ck_transacoes_fatura_mes_valido", "transacoes", type_="check")
    op.drop_constraint("ck_transacoes_tipo_valido", "transacoes", type_="check")
    op.drop_constraint("ck_transacoes_valor_positivo", "transacoes", type_="check")

    # ---- T-11: colunas monetárias voltam a nullable ----
    op.alter_column("parcelas", "valor_juros", existing_type=sa.Numeric(15, 2), nullable=True)
    op.alter_column("parcelas", "taxa_juros", existing_type=sa.Numeric(5, 2), nullable=True)
    op.alter_column("parcelas", "valor_parcela", existing_type=sa.Numeric(15, 2), nullable=True)
    op.alter_column("transacoes", "valor", existing_type=sa.Numeric(15, 2), nullable=True)

    # ---- T-09: índices ----
    op.drop_index("ix_chat_messages_sessao_id", table_name="chat_messages")
    op.drop_index("ix_parcelas_usuario_fatura", table_name="parcelas")
    op.drop_index("ix_parcelas_cartao_fatura", table_name="parcelas")
    op.drop_index("ix_transacoes_cartao_fatura", table_name="transacoes")
    op.drop_index("ix_transacoes_usuario_data", table_name="transacoes")
