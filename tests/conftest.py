import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401 — registra todas as tabelas no metadata


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
