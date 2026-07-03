"""fase2a recorrencias (modelo cabeçalho + vigências)

Revision ID: f2a7c9d1e8b3
Revises: e7c9a1b2d3f4
Create Date: 2026-07-03 12:00:00.000000

Fase 2a do PLANO_PROJECAO (§3.4) — fundação da recorrência:
- recorrencias: cabeçalho estável (identidade "meu salário"), UUID PK, soft
  delete via `ativa`, frequencia só 'mensal' (CHECK; campo extensível).
- recorrencia_vigencias: versões de valor ao longo do tempo; mes_fim/ano_fim
  NULL = vigência aberta (CHECK: os dois nulos juntos ou ambos preenchidos).
- FKs com ON DELETE CASCADE; índices em usuario_id/recorrencia_id + composto
  (recorrencia_id, ano_inicio, mes_inicio) para busca de vigência por período.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = "f2a7c9d1e8b3"
down_revision: Union[str, None] = "e7c9a1b2d3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recorrencias",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("categoria", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("forma_pagamento", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("frequencia", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("dia_do_mes", sa.Integer(), nullable=False),
        sa.Column("descricao", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("ativa", sa.Boolean(), nullable=False),
        sa.Column("data_criacao", sa.DateTime(), nullable=False),
        sa.CheckConstraint("tipo IN ('receita', 'despesa')", name="ck_recorrencias_tipo_valido"),
        sa.CheckConstraint(
            "dia_do_mes BETWEEN 1 AND 31", name="ck_recorrencias_dia_do_mes_valido"
        ),
        sa.CheckConstraint("frequencia = 'mensal'", name="ck_recorrencias_frequencia_valida"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recorrencias_usuario_id", "recorrencias", ["usuario_id"])

    op.create_table(
        "recorrencia_vigencias",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recorrencia_id", sa.Uuid(), nullable=False),
        sa.Column("valor", sa.Numeric(15, 2), nullable=False),
        sa.Column("mes_inicio", sa.Integer(), nullable=False),
        sa.Column("ano_inicio", sa.Integer(), nullable=False),
        sa.Column("mes_fim", sa.Integer(), nullable=True),
        sa.Column("ano_fim", sa.Integer(), nullable=True),
        sa.CheckConstraint("valor > 0", name="ck_rec_vigencias_valor_positivo"),
        sa.CheckConstraint(
            "mes_inicio BETWEEN 1 AND 12", name="ck_rec_vigencias_mes_inicio_valido"
        ),
        sa.CheckConstraint(
            "mes_fim IS NULL OR (mes_fim BETWEEN 1 AND 12)",
            name="ck_rec_vigencias_mes_fim_valido",
        ),
        sa.CheckConstraint(
            "(mes_fim IS NULL) = (ano_fim IS NULL)", name="ck_rec_vigencias_fim_consistente"
        ),
        sa.ForeignKeyConstraint(["recorrencia_id"], ["recorrencias.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recorrencia_vigencias_recorrencia_id", "recorrencia_vigencias", ["recorrencia_id"]
    )
    op.create_index(
        "ix_rec_vigencias_rec_periodo",
        "recorrencia_vigencias",
        ["recorrencia_id", "ano_inicio", "mes_inicio"],
    )


def downgrade() -> None:
    op.drop_index("ix_rec_vigencias_rec_periodo", table_name="recorrencia_vigencias")
    op.drop_index(
        "ix_recorrencia_vigencias_recorrencia_id", table_name="recorrencia_vigencias"
    )
    op.drop_table("recorrencia_vigencias")
    op.drop_index("ix_recorrencias_usuario_id", table_name="recorrencias")
    op.drop_table("recorrencias")
