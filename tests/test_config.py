"""Testes de carregamento de Settings (F-01, T-07).

Usa _env_file=None para não ler o .env local — assim o teste controla
exatamente quais variáveis estão presentes. As variáveis de ambiente reais
relacionadas são limpas via monkeypatch para isolamento.
"""
import pytest
from pydantic import ValidationError

from app.core.config import Settings

_ENV_VARS = ["SECRET_KEY", "DATABASE_URL", "ENVIRONMENT", "FRONTEND_URL"]


@pytest.fixture(autouse=True)
def _limpa_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _make(**over):
    base = dict(
        _env_file=None,
        DATABASE_URL="postgresql://u:p@localhost:5432/db",
        SECRET_KEY="x" * 64,
        ENVIRONMENT="development",
    )
    base.update(over)
    return Settings(**base)


def test_secret_key_ausente_falha_no_startup():
    # F-01: sem default — Settings não pode ser construída sem SECRET_KEY
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL="postgresql://u:p@localhost:5432/db")


def test_secret_key_curta_rejeitada_em_producao():
    with pytest.raises(ValidationError):
        _make(SECRET_KEY="curta", ENVIRONMENT="production")


def test_secret_key_exemplo_rejeitada_em_producao():
    with pytest.raises(ValidationError):
        _make(SECRET_KEY="change-me-in-production", ENVIRONMENT="production")


def test_secret_key_forte_aceita_em_producao():
    s = _make(SECRET_KEY="a" * 32, ENVIRONMENT="production")
    assert s.ENVIRONMENT == "production"


def test_secret_key_curta_aceita_em_dev():
    # Em dev não há validação de força — só obrigatoriedade
    s = _make(SECRET_KEY="curta")
    assert s.SECRET_KEY == "curta"


def test_frontend_url_default():
    # T-07: CORS usa este valor; default cobre o Vite dev server
    assert _make().FRONTEND_URL == "http://localhost:5173"


def test_frontend_url_lido_de_settings():
    s = _make(FRONTEND_URL="https://app.hivvo.app")
    assert s.FRONTEND_URL == "https://app.hivvo.app"
