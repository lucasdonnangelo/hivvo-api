import os

# F-04: desliga o rate limiting na suíte ANTES de qualquer import de app/main —
# settings lê esta env na criação do limiter. Sem isso, os testes que repetem
# chamadas (login/chat) tomariam 429 e ficariam flaky. O teste específico de
# rate limiting religa o limiter localmente.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

# A guarda de chave em app/routers/ai.py devolve 503 na PRIMEIRA linha dos
# endpoints /ai/* — antes do _gemini_generate que estes testes mockam, o que
# torna o mock inerte. Sem um valor aqui, os testes de IA dependeriam do .env
# da máquina: verdes em quem tem chave, vermelhos em qualquer checkout limpo.
# Valor FALSO de propósito e sem risco de rede: nesses testes o _gemini_generate
# está sempre mockado, e o teste da chave AUSENTE (test_ai_resiliencia) zera o
# atributo de settings por monkeypatch, não pelo ambiente — ele não é afetado.
os.environ.setdefault("GEMINI_API_KEY", "test-key-nao-usada-em-rede")

import pytest  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import app.models  # noqa: F401,E402 — registra todas as tabelas no metadata


@pytest.fixture()
def session():
    """Sessão SQLite em memória, isolada por teste.

    StaticPool garante que todas as operações usem a mesma conexão
    (um banco :memory: por engine). SQLite coage Numeric via float —
    nos testes, comparar dinheiro sempre via Decimal(str(x)).
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()
