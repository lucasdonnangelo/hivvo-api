"""Batch 9 / F-04 — rate limiting com slowapi.

A suíte roda com RATE_LIMIT_ENABLED=false (tests/conftest.py), então o limiter
fica desligado por padrão e nenhum outro teste toma 429. Este teste o RELIGA
localmente para provar o 429 ao exceder, e o desliga de novo no fim.
"""

from fastapi.testclient import TestClient

from app.core.database import get_session
from app.core.rate_limit import limiter
from main import app


def test_forgot_password_retorna_429_ao_exceder(session):
    # forgot-password é por IP, 5/min, e não envia e-mail para e-mail inexistente
    app.dependency_overrides[get_session] = lambda: session
    limiter.enabled = True
    limiter.reset()
    try:
        client = TestClient(app)
        payload = {"email": "naoexiste@hivvo.test"}
        for _ in range(5):
            assert client.post("/auth/forgot-password", json=payload).status_code == 200
        # 6ª dentro do mesmo minuto estoura o limite
        assert client.post("/auth/forgot-password", json=payload).status_code == 429
    finally:
        limiter.enabled = False
        limiter.reset()
        app.dependency_overrides.clear()


def test_rate_limit_desligado_por_padrao_na_suite():
    # Garante o pré-requisito dos demais testes: limiter off no ambiente de teste.
    assert limiter.enabled is False
