"""T-38 — variação percentual com saldo anterior negativo.

_variacao vive em app/services/estatisticas.py (versão única, com abs() no
denominador); statistics.py e ai.py importam de lá. Fechado no Batch 3a.
"""

from decimal import Decimal

from app.services.estatisticas import _variacao


def test_t38_variacao_com_anterior_negativo_usa_abs_no_denominador():
    # Saldo foi de −100 para −50: melhora de R$ 50 → variação CORRETA = +50%.
    assert _variacao(Decimal("-50.00"), Decimal("-100.00")) == Decimal("50.00")


def test_t38_virada_de_negativo_para_positivo():
    # −100 → +100: melhora de R$ 200 sobre base 100 → +200% (não −200%).
    assert _variacao(Decimal("100.00"), Decimal("-100.00")) == Decimal("200.00")


def test_variacao_com_anterior_positivo_inalterada():
    # Caso já correto antes do T-38: 100 → 150 = +50%; 100 → 50 = −50%.
    assert _variacao(Decimal("150.00"), Decimal("100.00")) == Decimal("50.00")
    assert _variacao(Decimal("50.00"), Decimal("100.00")) == Decimal("-50.00")


def test_variacao_sem_dados_anteriores_retorna_none():
    assert _variacao(Decimal("100.00"), Decimal("0.00")) is None
