"""API Batch 5 — Tokens e sessão (F-24, F-10, F-18/T-31).

Fluxos de auth reais via TestClient (login/refresh/logout/forgot/reset usam
cookies, não get_current_user). O Resend é sempre mockado — nenhum e-mail real.

- F-24: o que o banco guarda é o HASH (sha256), nunca o valor cru entregue ao
  cliente; o lookup hasheia o recebido e casa.
- F-10: troca/reset de senha revoga TODAS as sessões na mesma transação.
- F-18/T-31: falha no envio do e-mail não derruba o request; o token já está
  commitado; a resposta ao cliente permanece genérica.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.core.auth import hash_token
from app.core.database import get_session
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import Usuario
from main import app


@pytest.fixture()
def client(session):
    """TestClient com get_session sobre o SQLite in-memory.

    Sem override de get_current_user: os fluxos de token usam cookies reais
    emitidos pelos próprios endpoints (register/login).
    """
    app.dependency_overrides[get_session] = lambda: session
    # T-28: auth vive sob /api/v1 — prefixo no base_url (ver conftest de routers).
    c = TestClient(app, base_url="http://testserver/api/v1")
    yield c
    app.dependency_overrides.clear()


def _register(client, email="alice@hivvo.test", senha="senha-forte-1"):
    resp = client.post(
        "/auth/register",
        json={"email": email, "nome_completo": "Alice", "password": senha},
    )
    assert resp.status_code == 201, resp.text
    return resp


# --------------------------------------------------------------------------- #
# F-24 — Refresh token hasheado                                               #
# --------------------------------------------------------------------------- #


class TestRefreshTokenHashing:
    def test_banco_guarda_hash_nao_o_valor_cru(self, client, session):
        _register(client)
        raw = client.cookies.get("refresh_token")
        assert raw is not None

        tokens = session.exec(select(RefreshToken)).all()
        assert len(tokens) == 1
        # O que está no banco é o hash, NÃO o cru entregue ao cliente.
        assert tokens[0].token != raw
        assert tokens[0].token == hash_token(raw)

    def test_refresh_com_valor_cru_valida(self, client, session):
        _register(client)
        raw = client.cookies.get("refresh_token")

        resp = client.post("/auth/refresh", cookies={"refresh_token": raw})
        assert resp.status_code == 200

    def test_refresh_com_token_errado_falha(self, client):
        _register(client)

        resp = client.post(
            "/auth/refresh", cookies={"refresh_token": "valor-que-nao-existe"}
        )
        assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# F-24 — Reset token hasheado                                                 #
# --------------------------------------------------------------------------- #


def _forgot(client, mocker, email="alice@hivvo.test"):
    """Dispara forgot-password com o Resend mockado e devolve o token CRU."""
    sent = {}

    def _capture(payload):
        sent["html"] = payload["html"]
        return {"id": "fake"}

    mocker.patch("app.routers.auth.resend.Emails.send", side_effect=_capture)
    resp = client.post("/auth/forgot-password", json={"email": email})
    assert resp.status_code == 200
    # extrai ?token=<uuid> do link do e-mail
    if "html" in sent:
        import re

        m = re.search(r"token=([0-9a-f-]+)", sent["html"])
        return resp, (m.group(1) if m else None)
    return resp, None


class TestResetTokenHashing:
    def test_banco_guarda_hash_do_reset_token(self, client, session, mocker):
        _register(client)
        _, raw = _forgot(client, mocker)
        assert raw is not None

        tokens = session.exec(select(PasswordResetToken)).all()
        assert len(tokens) == 1
        assert tokens[0].token != raw
        assert tokens[0].token == hash_token(raw)

    def test_reset_com_token_cru_valida(self, client, session, mocker):
        _register(client, senha="senha-antiga-1")
        _, raw = _forgot(client, mocker)

        resp = client.post(
            "/auth/reset-password",
            json={"token": raw, "nova_senha": "nova-senha-99"},
        )
        assert resp.status_code == 204

        # a nova senha funciona no login
        login = client.post(
            "/auth/login",
            json={"email": "alice@hivvo.test", "password": "nova-senha-99"},
        )
        assert login.status_code == 200

    def test_reset_com_token_errado_falha(self, client, mocker):
        _register(client)
        _forgot(client, mocker)

        resp = client.post(
            "/auth/reset-password",
            json={"token": "token-invalido", "nova_senha": "nova-senha-99"},
        )
        assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# F-10 — Troca/reset de senha revoga sessões                                  #
# --------------------------------------------------------------------------- #


class TestRevogacaoDeSessoes:
    def test_reset_password_revoga_refresh_tokens(self, client, session, mocker):
        _register(client, senha="senha-antiga-1")
        raw_refresh = client.cookies.get("refresh_token")
        _, raw_reset = _forgot(client, mocker)

        resp = client.post(
            "/auth/reset-password",
            json={"token": raw_reset, "nova_senha": "nova-senha-99"},
        )
        assert resp.status_code == 204

        # o refresh token emitido antes do reset deixa de valer
        refresh = client.post(
            "/auth/refresh", cookies={"refresh_token": raw_refresh}
        )
        assert refresh.status_code == 401

    def test_change_password_revoga_refresh_tokens(self, client, session):
        _register(client, senha="senha-antiga-1")
        raw_refresh = client.cookies.get("refresh_token")

        resp = client.put(
            "/auth/password",
            json={"senha_atual": "senha-antiga-1", "nova_senha": "nova-senha-99"},
        )
        assert resp.status_code == 204

        refresh = client.post(
            "/auth/refresh", cookies={"refresh_token": raw_refresh}
        )
        assert refresh.status_code == 401


# --------------------------------------------------------------------------- #
# F-18/T-31 — Envio robusto do e-mail de reset                                #
# --------------------------------------------------------------------------- #


class TestEnvioRobustoDeEmail:
    def test_falha_no_envio_nao_derruba_e_token_fica_commitado(
        self, client, session, mocker
    ):
        _register(client)
        mocker.patch(
            "app.routers.auth.resend.Emails.send",
            side_effect=RuntimeError("Resend fora do ar"),
        )

        resp = client.post(
            "/auth/forgot-password", json={"email": "alice@hivvo.test"}
        )
        # NÃO 500; resposta genérica
        assert resp.status_code == 200
        assert resp.json() == {
            "message": "Se o e-mail estiver cadastrado, você receberá um link em breve."
        }

        # o token JÁ foi commitado mesmo com o envio falhando
        tokens = session.exec(select(PasswordResetToken)).all()
        assert len(tokens) == 1

    def test_caminho_feliz_commita_e_responde_generico(
        self, client, session, mocker
    ):
        _register(client)
        send = mocker.patch(
            "app.routers.auth.resend.Emails.send", return_value={"id": "ok"}
        )

        resp = client.post(
            "/auth/forgot-password", json={"email": "alice@hivvo.test"}
        )
        assert resp.status_code == 200
        send.assert_called_once()
        assert len(session.exec(select(PasswordResetToken)).all()) == 1

    def test_email_inexistente_resposta_generica_sem_token(
        self, client, session, mocker
    ):
        # proteção contra enumeração: mesma resposta, e nenhum token criado
        send = mocker.patch("app.routers.auth.resend.Emails.send")
        resp = client.post(
            "/auth/forgot-password", json={"email": "ninguem@hivvo.test"}
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "message": "Se o e-mail estiver cadastrado, você receberá um link em breve."
        }
        send.assert_not_called()
        assert session.exec(select(PasswordResetToken)).all() == []
