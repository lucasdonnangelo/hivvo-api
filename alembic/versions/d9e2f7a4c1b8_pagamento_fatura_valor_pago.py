"""pagamentos_fatura.valor_pago — cobertura do pagamento (#9)

Revision ID: d9e2f7a4c1b8
Revises: c1a2b3d4e5f6
Create Date: 2026-07-24 12:00:00.000000

Furo #9 (compra retroativa em fatura paga): PagamentoFatura ganha
`valor_pago` = total da fatura NO INSTANTE em que foi marcada paga; o status
passa a ser derivado por COBERTURA (valor_pago >= total atual → paga; menor →
paga_parcial, e a diferença volta ao "A pagar").

- ALTER TABLE add column (Numeric(15,2), nullable) — sem tabela nova, sem RLS.
- BACKFILL: valor_pago = total ATUAL da fatura para as linhas pago=TRUE
  (assume cobertura — não existe valor histórico; nenhuma fatura existente
  nasce falsamente parcial). Linhas pago=FALSE ficam NULL (sem pagamento,
  sem valor — mesmo contrato do data_pagamento).
  A composição da fatura é reescrita em SQL AQUI, uma única vez (one-shot):
  parcelas não canceladas + avulsas de cartão (parcelado=FALSE,
  tipo='despesa') da mesma (usuario, cartao, mes, ano) — espelho de
  services/faturas._cond_parcelas_fatura/_cond_avulsas_fatura, que seguem
  sendo a fonte única em runtime. O SQL vive na constante
  BACKFILL_VALOR_PAGO_SQL para o teste de backfill executar o MESMO texto.
- CHECK (NOT pago OR valor_pago IS NOT NULL): nenhum writer futuro marca
  pago=TRUE sem gravar a cobertura. batch_alter_table: ALTER normal no
  Postgres; recreate no SQLite (se algum dia rodar lá).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d9e2f7a4c1b8"
down_revision: Union[str, None] = "c1a2b3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BACKFILL_VALOR_PAGO_SQL = """
UPDATE pagamentos_fatura SET valor_pago =
    COALESCE((SELECT SUM(p.valor_parcela) FROM parcelas p
              WHERE p.usuario_id = pagamentos_fatura.usuario_id
                AND p.cartao_id = pagamentos_fatura.cartao_id
                AND p.fatura_mes = pagamentos_fatura.fatura_mes
                AND p.fatura_ano = pagamentos_fatura.fatura_ano
                AND p.cancelado = FALSE), 0)
  + COALESCE((SELECT SUM(t.valor) FROM transacoes t
              WHERE t.usuario_id = pagamentos_fatura.usuario_id
                AND t.cartao_id = pagamentos_fatura.cartao_id
                AND t.fatura_mes = pagamentos_fatura.fatura_mes
                AND t.fatura_ano = pagamentos_fatura.fatura_ano
                AND t.parcelado = FALSE
                AND t.tipo = 'despesa'), 0)
WHERE pago = TRUE
"""


def upgrade() -> None:
    op.add_column(
        "pagamentos_fatura",
        sa.Column("valor_pago", sa.Numeric(15, 2), nullable=True),
    )
    op.execute(BACKFILL_VALOR_PAGO_SQL)
    with op.batch_alter_table("pagamentos_fatura") as batch:
        batch.create_check_constraint(
            "ck_pagamentos_fatura_valor_pago_quando_pago",
            "NOT pago OR valor_pago IS NOT NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("pagamentos_fatura") as batch:
        batch.drop_constraint(
            "ck_pagamentos_fatura_valor_pago_quando_pago", type_="check"
        )
        batch.drop_column("valor_pago")
