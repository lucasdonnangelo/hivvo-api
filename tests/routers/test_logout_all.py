"""POST /auth/logout-all — sair de todos os dispositivos (PLANO_PERFIL_CONFIG).

Revoga TODAS as sessões do usuário (refresh_tokens) e limpa os cookies desta
também: revoke_all_refresh_tokens mata o refresh deste dispositivo junto, então
manter o cookie deixaria o cliente com um token morto na mão.

Fluxo com cookies REAIS (register/login emitem), não get_current_user — é o
cookie que o endpoint precisa limpar.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.core.database import get_session
from app.models.refresh_token import RefreshToken
from app.models.user import Usuario
from main import app

SENHA = "senha-forte-1"


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    c = TestClient(app, base_url="http://testserver/api/v1")
    yield c
    app.dependency_overrides.clear()


def _register(client, email="alice@hivvo.test"):
    resp = client.post(
        "/auth/register",
        json={"email": email, "nome_completo": "Alice", "password": SENHA},
    )
    assert resp.status_code == 201, resp.text
    return resp


def _tokens_ativos(session, uid: int) -> int:
    return len(
        session.exec(
            select(RefreshToken).where(
                RefreshToken.usuario_id == uid,
                RefreshToken.revogado == False,  # noqa: E712
            )
        ).all()
    )


def _uid(session, email: str) -> int:
    return session.exec(select(Usuario).where(Usuario.email == email)).first().id


class TestLogoutAll:
    def test_revoga_todas_as_sessoes_do_usuario(self, client, session):
        _register(client)
        uid = _uid(session, "alice@hivvo.test")
        # 3 sessões: o register + dois logins (dispositivos diferentes).
        client.post("/auth/login", json={"email": "alice@hivvo.test", "password": SENHA})
        client.post("/auth/login", json={"email": "alice@hivvo.test", "password": SENHA})
        assert _tokens_ativos(session, uid) == 3

        resp = client.post("/auth/logout-all")
        assert resp.status_code == 204

        session.expire_all()
        assert _tokens_ativos(session, uid) == 0

    def test_limpa_os_cookies_desta_sessao(self, client):
        _register(client)
        assert client.cookies.get("refresh_token") is not None

        resp = client.post("/auth/logout-all")
        assert resp.status_code == 204

        # Decisão (opção A): sai daqui junto — o refresh desta sessão também foi
        # revogado, e segurar um cookie morto só adiaria o 401 para o próximo
        # refresh. O rótulo na UI é literal ("Sair de todos os dispositivos",
        # este incluído); a ressalva é sobre o PRAZO dos outros, onde o access
        # token (JWT stateless) ainda vive até expirar.
        assert client.cookies.get("access_token") is None
        assert client.cookies.get("refresh_token") is None

    def test_nao_toca_nas_sessoes_de_outro_usuario(self, client, session):
        _register(client, email="alice@hivvo.test")
        alice = _uid(session, "alice@hivvo.test")

        _register(client, email="bob@hivvo.test")  # o cliente fica logado como Bob
        bob = _uid(session, "bob@hivvo.test")

        resp = client.post("/auth/logout-all")
        assert resp.status_code == 204

        session.expire_all()
        assert _tokens_ativos(session, bob) == 0
        # Isolamento: a sessão da Alice segue viva.
        assert _tokens_ativos(session, alice) == 1

    def test_sem_autenticacao_401(self, client):
        assert client.post("/auth/logout-all").status_code == 401

    def test_sessao_revogada_nao_consegue_mais_refresh(self, client, session):
        """O efeito que importa: o dispositivo não renova mais o access token."""
        _register(client)
        refresh = client.cookies.get("refresh_token")

        client.post("/auth/logout-all")

        # Reapresenta o refresh antigo à mão (o logout-all limpou o cookie).
        resp = client.post("/auth/refresh", cookies={"refresh_token": refresh})
        assert resp.status_code == 401
