"""Fixtures para testes de endpoint (TestClient sobre o app real).

A sessão SQLite in-memory (tests/conftest.py) substitui get_session, e
get_current_user é trocável por usuário — permite exercitar isolamento
entre usuários sem JWT/cookies. Datas de negócio: sempre fixar via patch
no helper `hoje` (app.core.dates) importado pelo módulo sob teste —
nenhum teste pode depender do relógio real.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.auth import get_current_user
from app.core.database import get_session
from app.models.user import Usuario
from main import app


@pytest.fixture()
def users(session):
    """Dois usuários persistidos — base dos testes de isolamento."""
    user_a = Usuario(
        email="a@hivvo.test", username="user_a", senha_hash="x", nome_completo="Usuário A"
    )
    user_b = Usuario(
        email="b@hivvo.test", username="user_b", senha_hash="x", nome_completo="Usuário B"
    )
    session.add(user_a)
    session.add(user_b)
    session.commit()
    session.refresh(user_a)
    session.refresh(user_b)
    return user_a, user_b


@pytest.fixture()
def as_user(session, users):
    """Retorna um trocador de identidade: client = as_user(usuario)."""
    holder = {"user": users[0]}
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: holder["user"]
    # T-28: rotas de negócio vivem sob /api/v1 (hard switch). O prefixo no
    # base_url faz cada chamada relativa (ex. client.get("/transactions"))
    # resolver para /api/v1/transactions.
    client = TestClient(app, base_url="http://testserver/api/v1")

    def _as(user: Usuario) -> TestClient:
        holder["user"] = user
        return client

    yield _as
    app.dependency_overrides.clear()
