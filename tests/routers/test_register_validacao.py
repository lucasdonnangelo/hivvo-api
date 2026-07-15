"""POST /auth/register — validação do nome_completo.

O RegisterRequest exigia nome_completo (NOT NULL na coluna) mas sem min_length:
o NOT NULL do Postgres aceita "" numa boa, então uma chamada direta à API — sem
passar pelo zod da UI — gravava conta com nome em branco. Pior, era INCONSISTENTE
com o PUT /auth/me, que já exigia 2+ caracteres: dava para registrar com nome
vazio mas não para editá-lo depois.

Aqui o contrato do register é o mesmo do UpdateMeRequest (ver test_update_me.py):
strip antes das constraints, min_length=2.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.core.database import get_session
from app.models.user import Usuario
from main import app


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    # T-28: auth vive sob /api/v1 — prefixo no base_url (ver conftest de routers).
    c = TestClient(app, base_url="http://testserver/api/v1")
    yield c
    app.dependency_overrides.clear()


def _post(client, nome, email="novo@hivvo.test"):
    return client.post(
        "/auth/register",
        json={"email": email, "nome_completo": nome, "password": "senha-forte-1"},
    )


class TestRegisterNomeCompleto:
    def test_nome_vazio_422(self, client):
        assert _post(client, "").status_code == 422

    def test_nome_so_espacos_422(self, client):
        # strip antes das constraints: "   " vira "" e não passa por min_length=2.
        assert _post(client, "   ").status_code == 422

    def test_nome_um_caractere_422(self, client):
        assert _post(client, "L").status_code == 422

    def test_nome_dois_caracteres_ok(self, client):
        # min_length=2 é o piso, não o alvo: "Ab" é nome válido.
        resp = _post(client, "Ab")
        assert resp.status_code == 201, resp.text
        assert resp.json()["nome_completo"] == "Ab"

    def test_nome_e_aparado_antes_de_gravar(self, client, session):
        resp = _post(client, "  Lucas Donnangelo  ")
        assert resp.status_code == 201, resp.text
        assert resp.json()["nome_completo"] == "Lucas Donnangelo"

        # O que a resposta mostra é o que o banco guardou.
        gravado = session.exec(
            select(Usuario).where(Usuario.email == "novo@hivvo.test")
        ).first()
        assert gravado.nome_completo == "Lucas Donnangelo"

    def test_nome_invalido_nao_cria_conta(self, client, session):
        # 422 é barreira, não aviso: nada é persistido.
        _post(client, " ")
        assert (
            session.exec(
                select(Usuario).where(Usuario.email == "novo@hivvo.test")
            ).first()
            is None
        )
