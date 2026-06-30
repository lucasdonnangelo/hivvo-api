import os

# F-04: desliga o rate limiting na suíte ANTES de qualquer import de app/main —
# settings lê esta env na criação do limiter. Sem isso, os testes que repetem
# chamadas (login/chat) tomariam 429 e ficariam flaky. O teste específico de
# rate limiting religa o limiter localmente.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

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
