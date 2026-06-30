from pydantic import model_validator
from pydantic_settings import BaseSettings

# Valores de exemplo que NUNCA podem ser usados como SECRET_KEY em produção
_SECRET_KEY_EXEMPLOS = {"change-me-in-production", "your-secret-key-here"}


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str  # F-01: sem default — fail-fast no boot se ausente
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ENVIRONMENT: str = "development"
    GEMINI_API_KEY: str = ""
    RESEND_API_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:5173"

    # T-07: parâmetros operacionais da IA promovidos para config (apenas movidos —
    # valores e comportamento idênticos ao que estava hardcoded em routers/ai.py)
    GEMINI_MODEL: str = "gemini-2.5-flash"
    CHAT_SESSION_WINDOW_HOURS: int = 24
    CHAT_CONTEXT_MESSAGES: int = 50
    # T-21: nº de tentativas no caminho da request = len(GEMINI_RETRY_WAITS) + 1.
    # Orçamento reduzido (2 tentativas) — o usuário está esperando; retry longo é
    # para job assíncrono. GEMINI_TIMEOUT_MS: timeout do client (ms, ~30s).
    GEMINI_RETRY_WAITS: list[int] = [2]
    GEMINI_TIMEOUT_MS: int = 30000

    # F-04: rate limiting (slowapi). Ligado por padrão (produção); desligado no
    # ambiente de teste para a suíte não tomar 429.
    RATE_LIMIT_ENABLED: bool = True

    model_config = {"env_file": ".env"}

    @model_validator(mode="after")
    def _validar_secret_key(self) -> "Settings":
        # F-01: em produção, a SECRET_KEY precisa ser forte e não um valor de exemplo.
        if self.ENVIRONMENT == "production":
            if self.SECRET_KEY in _SECRET_KEY_EXEMPLOS:
                raise ValueError(
                    "SECRET_KEY inválida em produção: é um valor de exemplo. "
                    "Gere uma chave com `openssl rand -hex 32`."
                )
            if len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "SECRET_KEY inválida em produção: precisa ter pelo menos 32 caracteres. "
                    "Gere uma chave com `openssl rand -hex 32`."
                )
        return self


settings = Settings()
