"""estorno: tipo IN ('receita','despesa','estorno')

Revision ID: b7e4a2c9f1d6
Revises: d9e2f7a4c1b8
Create Date: 2026-07-24 12:00:00.000000

Estorno vira lançamento de primeira classe: tipo="estorno" com valor POSITIVO
(o CHECK valor>0 fica intacto) — as agregações de consumo SUBTRAEM. Só o CHECK
de tipo muda (drop+add com o conjunto expandido); sem tabela nova, sem
alteração de coluna. Dado existente passa trivialmente: o conjunto novo é
superconjunto do antigo.

Downgrade recria o CHECK original — exige 0 linhas tipo='estorno' no banco
(senão o ADD CONSTRAINT falha na validação, corretamente).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b7e4a2c9f1d6"
down_revision: Union[str, None] = "d9e2f7a4c1b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_transacoes_tipo_valido", "transacoes", type_="check")
    op.create_check_constraint(
        "ck_transacoes_tipo_valido",
        "transacoes",
        "tipo IN ('receita', 'despesa', 'estorno')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transacoes_tipo_valido", "transacoes", type_="check")
    op.create_check_constraint(
        "ck_transacoes_tipo_valido", "transacoes", "tipo IN ('receita', 'despesa')"
    )
