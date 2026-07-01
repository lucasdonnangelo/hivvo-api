from sqlmodel import create_engine, Session, SQLModel
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    # Batch 7 (código): resiliência de conexão. pool_pre_ping reconecta no
    # checkout se a conexão morreu; pool_recycle descarta conexões velhas.
    # Pool MODESTO — o Session pooler do Supabase tem limite próprio de conexões.
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=5,
    max_overflow=10,
)


def get_session():
    with Session(engine) as session:
        yield session
