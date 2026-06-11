"""T-38 — variação percentual com saldo anterior negativo.

_variacao vive hoje em app/routers/statistics.py (a unificação com a versão
correta de ai.py, via services/estatisticas.py, é o Batch 3). Importar o módulo
cria o engine do SQLAlchemy a partir do .env, mas NÃO abre conexão — sem efeito
colateral real no teste.
"""

from decimal import Decimal

import pytest

from app.routers.statistics import _variacao


@pytest.mark.xfail(
    strict=True,
    reason="T-38: denominador deve usar abs(anterior); sinal invertido com saldo anterior negativo — corrigir no Batch 3",
)
def test_t38_variacao_com_anterior_negativo_usa_abs_no_denominador():
    # Saldo foi de −100 para −50: melhora de R$ 50 → variação CORRETA = +50%.
    # Código atual divide por −100 (sem abs) e reporta −50%.
    assert _variacao(Decimal("-50.00"), Decimal("-100.00")) == Decimal("50.00")
