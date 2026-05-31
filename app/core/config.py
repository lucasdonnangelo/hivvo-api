from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h
    ENVIRONMENT: str = "development"
    GEMINI_API_KEY: str = ""
    RESEND_API_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:5173"

    model_config = {"env_file": ".env"}


settings = Settings()
