"""PUT /auth/me — edição de perfil (PLANO_PERFIL_CONFIG).

Antes o schema era {username: str} OBRIGATÓRIO: a tela de Perfil, que edita o
NOME, não conseguia nem chamar a rota. Agora ambos são opcionais e só o que veio
é aplicado; username segue aceito para um cliente futuro.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.auth import get_current_user, hash_password
from app.core.database import get_session
from app.models.user import Usuario
from main import app


def _criar(session, email="perfil@hivvo.test", username="perfil_me") -> Usuario:
    user = Usuario(
        email=email,
        username=username,
        senha_hash=hash_password("senha-forte-1"),
        nome_completo="Nome Antigo",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture()
def authed_client(session):
    user = _criar(session)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app, base_url="http://testserver/api/v1")
    yield client, user
    app.dependency_overrides.clear()


class TestUpdateMe:
    def test_so_nome_atualiza_nome_e_preserva_username(self, authed_client, session):
        client, user = authed_client
        resp = client.put("/auth/me", json={"nome_completo": "Lucas Donnangelo"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["nome_completo"] == "Lucas Donnangelo"
        # exclude_unset: o que não veio não é tocado.
        assert resp.json()["username"] == "perfil_me"

        session.expire_all()
        assert session.get(Usuario, user.id).nome_completo == "Lucas Donnangelo"

    def test_so_username_atualiza_username_e_preserva_nome(self, authed_client):
        client, _ = authed_client
        resp = client.put("/auth/me", json={"username": "novo_username"})
        assert resp.status_code == 200
        assert resp.json()["username"] == "novo_username"
        assert resp.json()["nome_completo"] == "Nome Antigo"

    def test_ambos_atualiza_os_dois(self, authed_client):
        client, _ = authed_client
        resp = client.put(
            "/auth/me", json={"nome_completo": "Lucas D", "username": "lucas_d"}
        )
        assert resp.status_code == 200
        assert resp.json()["nome_completo"] == "Lucas D"
        assert resp.json()["username"] == "lucas_d"

    def test_corpo_vazio_422(self, authed_client):
        # PUT no-op não é sucesso silencioso.
        assert client_put(authed_client, {}) == 422

    def test_null_explicito_422_nao_500(self, authed_client):
        # O campo VEM set com valor None: aplicá-lo violaria o NOT NULL da coluna
        # e viraria 500. O validador o barra antes.
        assert client_put(authed_client, {"nome_completo": None}) == 422
        assert client_put(authed_client, {"nome_completo": None, "username": None}) == 422

    def test_nome_em_branco_422(self, authed_client):
        # strip antes das constraints: "   " não pode passar por min_length=2.
        assert client_put(authed_client, {"nome_completo": "   "}) == 422
        assert client_put(authed_client, {"nome_completo": "L"}) == 422

    def test_nome_e_aparado(self, authed_client):
        client, _ = authed_client
        resp = client.put("/auth/me", json={"nome_completo": "  Lucas Donnangelo  "})
        assert resp.status_code == 200
        assert resp.json()["nome_completo"] == "Lucas Donnangelo"

    def test_username_ja_em_uso_400(self, authed_client, session):
        client, _ = authed_client
        _criar(session, email="outro@hivvo.test", username="ocupado")

        resp = client.put("/auth/me", json={"username": "ocupado"})
        assert resp.status_code == 400
        assert "já em uso" in resp.json()["detail"]

    def test_nome_nao_colide_com_username_de_outro(self, authed_client, session):
        """A checagem de unicidade só roda quando o username veio — editar o
        nome não pode tropeçar no username alheio."""
        client, _ = authed_client
        _criar(session, email="outro@hivvo.test", username="ocupado")

        resp = client.put("/auth/me", json={"nome_completo": "ocupado"})
        assert resp.status_code == 200
        assert resp.json()["nome_completo"] == "ocupado"

    def test_sem_autenticacao_401(self, session):
        app.dependency_overrides[get_session] = lambda: session
        try:
            client = TestClient(app, base_url="http://testserver/api/v1")
            resp = client.put("/auth/me", json={"nome_completo": "Qualquer"})
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()


def client_put(authed_client, body) -> int:
    client, _ = authed_client
    return client.put("/auth/me", json=body).status_code
