"""API Batch 11a / F-07 — exclusão de conta (LGPD).

DELETE /auth/me (sob /api/v1) apaga TODOS os dados do próprio usuário numa
única transação, com reautenticação por senha. Os testes provam que ZERO
linhas do usuário sobram em CADA tabela ligada a ele — a garantia é do
endpoint (deletes explícitos na ordem correta de FK), provável no SQLite
que não força FK.
"""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.core.auth import get_current_user, hash_password
from app.core.database import get_session
from app.models.card import Cartao
from app.models.category import CategoriaCustomizada
from app.models.chat import ChatMessage
from app.models.installment import Parcela
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.transaction import Transacao
from app.models.user import Usuario
from main import app

SENHA = "senha-correta-1"

# Tabelas filhas ligadas ao usuário — a varredura do teste percorre todas.
_CHILD_MODELS = [
    Parcela,
    Transacao,
    Cartao,
    CategoriaCustomizada,
    RefreshToken,
    PasswordResetToken,
    ChatMessage,
]


def _popular_usuario(session) -> Usuario:
    """Cria um usuário com senha real e 1 linha em CADA tabela ligada a ele."""
    user = Usuario(
        email="delete-me@hivvo.test",
        username="delete_me",
        senha_hash=hash_password(SENHA),
        nome_completo="Para Excluir",
    )
    session.add(user)
    session.flush()  # popula user.id

    cartao = Cartao(usuario_id=user.id, nome="Nubank", tipo="Crédito")
    session.add(cartao)
    session.flush()

    transacao = Transacao(
        usuario_id=user.id,
        tipo="despesa",
        data=dt.date(2026, 6, 1),
        descricao="Compra parcelada",
        valor=Decimal("300.00"),
        categoria="Outros",
        cartao_id=cartao.id,
    )
    session.add(transacao)
    session.flush()

    session.add(
        Parcela(
            usuario_id=user.id,
            transacao_id=transacao.id,
            numero_parcela=1,
            total_parcelas=3,
            valor_parcela=Decimal("100.00"),
            data_vencimento=dt.date(2026, 7, 10),
            descricao="Compra parcelada (1/3)",
            categoria="Outros",
            cartao_id=cartao.id,
            fatura_mes=7,
            fatura_ano=2026,
        )
    )
    session.add(CategoriaCustomizada(usuario_id=user.id, nome="Pets"))
    session.add(
        RefreshToken(
            usuario_id=user.id,
            token="refresh-hash-abc",
            expires_at=dt.datetime.utcnow() + dt.timedelta(days=7),
        )
    )
    session.add(
        PasswordResetToken(
            usuario_id=user.id,
            token="reset-hash-xyz",
            expires_at=dt.datetime.utcnow() + dt.timedelta(minutes=15),
        )
    )
    session.add(
        ChatMessage(
            usuario_id=user.id,
            sessao_id=uuid.uuid4(),
            role="user",
            text="oi",
        )
    )
    session.commit()
    session.refresh(user)
    return user


def _rows_do_usuario(session, uid: int) -> dict:
    """Contagem de linhas remanescentes do usuário em cada tabela filha + usuário."""
    counts = {
        m.__tablename__: len(session.exec(select(m).where(m.usuario_id == uid)).all())
        for m in _CHILD_MODELS
    }
    counts["usuarios"] = 1 if session.get(Usuario, uid) is not None else 0
    return counts


@pytest.fixture()
def authed_client(session):
    """TestClient autenticado como o usuário populado (get_current_user trocado)."""
    user = _popular_usuario(session)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app, base_url="http://testserver/api/v1")
    yield client, user
    app.dependency_overrides.clear()


def test_delete_me_apaga_tudo_com_senha_correta(authed_client, session):
    client, user = authed_client
    uid = user.id

    # pré-condição: há dados em todas as tabelas
    antes = _rows_do_usuario(session, uid)
    assert all(v >= 1 for v in antes.values()), antes

    resp = client.request("DELETE", "/auth/me", json={"password": SENHA})
    assert resp.status_code == 204, resp.text

    session.expire_all()
    depois = _rows_do_usuario(session, uid)
    assert depois == {k: 0 for k in depois}, depois


def test_delete_me_senha_errada_nao_apaga(authed_client, session):
    client, user = authed_client
    uid = user.id

    resp = client.request("DELETE", "/auth/me", json={"password": "senha-errada"})
    assert resp.status_code == 401

    session.expire_all()
    depois = _rows_do_usuario(session, uid)
    assert all(v >= 1 for v in depois.values()), depois


def test_delete_me_sem_autenticacao_401(session):
    # Sem override de get_current_user e sem cookie: o guard de auth barra.
    app.dependency_overrides[get_session] = lambda: session
    try:
        client = TestClient(app, base_url="http://testserver/api/v1")
        resp = client.request("DELETE", "/auth/me", json={"password": SENHA})
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()
