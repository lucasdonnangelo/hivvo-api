from sqlmodel import create_engine, Session, SQLModel
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
)


def get_session():
    with Session(engine) as session:
        yield session
