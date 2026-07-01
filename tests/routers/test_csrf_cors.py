"""API Batch 11b — integração: reforço CSRF (Origin) + CORS com credenciais.

Prova, via TestClient, que verify_origin está ligado nos routers de negócio e
que o CORS usa origem explícita + credenciais (nunca "*"). O login serve de
endpoint mutável de teste: com Origin inválido é barrado antes da lógica; com
Origin correto (ou ausente) segue e cai em 401 de credencial inválida.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_session
from main import app


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app, base_url="http://testserver/api/v1")
    app.dependency_overrides.clear()


def _login(client, origin):
    headers = {"Origin": origin} if origin is not None else {}
    return client.post(
        "/auth/login",
        json={"email": "quem@hivvo.test", "password": "seja-la-o-que-for"},
        headers=headers,
    )


def test_post_origin_invalido_bloqueado_403(client):
    resp = _login(client, "https://evil.example")
    assert resp.status_code == 403


def test_post_origin_correto_passa_a_checagem(client):
    # Origem do frontend (settings.FRONTEND_URL): passa o CSRF e chega ao login,
    # que responde 401 (usuário inexistente) — o importante é NÃO ser 403.
    resp = _login(client, settings.FRONTEND_URL)
    assert resp.status_code != 403
    assert resp.status_code == 401


def test_post_sem_origin_passa(client):
    # Cliente não-browser (sem Origin) não é barrado.
    resp = _login(client, None)
    assert resp.status_code != 403
    assert resp.status_code == 401


def test_cors_preflight_credenciais_e_origem_explicita(client):
    resp = client.options(
        "/auth/login",
        headers={
            "Origin": settings.FRONTEND_URL,
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    # Origem explícita ecoada (nunca "*") + credenciais habilitadas.
    assert resp.headers.get("access-control-allow-origin") == settings.FRONTEND_URL
    assert resp.headers.get("access-control-allow-origin") != "*"
    assert resp.headers.get("access-control-allow-credentials") == "true"
