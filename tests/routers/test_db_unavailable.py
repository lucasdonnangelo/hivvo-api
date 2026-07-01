"""Fase 5 — banco fora → 503 limpo COM headers de CORS (não falso-CORS).

Quando o banco está inalcançável, o SQLAlchemy levanta OperationalError. Sem
handler, isso vira 500 pelo ServerErrorMiddleware (FORA do CORSMiddleware) e o
browser lê a ausência de CORS como erro de CORS — mascarou o diagnóstico duas
vezes. Com o handler (dentro do ExceptionMiddleware, DENTRO do CORS), a resposta
503 sai decorada com Access-Control-Allow-Origin. Este teste prova isso.
"""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_session
from app.models.user import Usuario
from main import app


def _raise_db_down():
    # Simula o banco inalcançável no checkout da conexão.
    raise OperationalError("SELECT 1", {}, Exception("could not connect to server"))


@pytest.fixture()
def client_db_down():
    # get_session cai como se o banco estivesse fora; get_current_user não toca
    # o banco (usuário dummy) para o request chegar até o uso da sessão.
    app.dependency_overrides[get_session] = _raise_db_down
    app.dependency_overrides[get_current_user] = lambda: Usuario(
        id=1, email="x@hivvo.test", username="x", senha_hash="x", nome_completo="X"
    )
    client = TestClient(app, base_url="http://testserver/api/v1")
    yield client
    app.dependency_overrides.clear()


def test_banco_fora_retorna_503_com_cors(client_db_down):
    resp = client_db_down.get("/transactions", headers={"Origin": settings.FRONTEND_URL})

    # 503, não 500 (o próprio retorno prova que foi tratado dentro do stack).
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Serviço temporariamente indisponível"}
    # O header de CORS PRECISA estar presente — senão o browser lê como falso-CORS.
    assert resp.headers.get("access-control-allow-origin") == settings.FRONTEND_URL


def test_banco_fora_nao_vaza_detalhe_no_corpo(client_db_down, caplog):
    with caplog.at_level(logging.ERROR):
        resp = client_db_down.get("/transactions", headers={"Origin": settings.FRONTEND_URL})

    assert resp.status_code == 503
    # Corpo genérico — o detalhe do erro (e a string de conexão) não vaza ao cliente.
    assert "could not connect" not in resp.text
