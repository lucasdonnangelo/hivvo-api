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
    # Remetente do e-mail (Resend). Default = sandbox (dev/testes funcionam sem env).
    # PRODUÇÃO: setar EMAIL_FROM="Hivvo <noreply@hivvo.app>" (domínio verificado).
    EMAIL_FROM: str = "Hivvo <onboarding@resend.dev>"

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

    # Importação de fatura (Batch 1, 17/07): chave DEDICADA, tier PAGO, custo
    # e controle isolados do assistente. NUNCA cai na GEMINI_API_KEY (zero
    # fallback, por design). Produção não sobe sem ela (validate_startup_config).
    GEMINI_IMPORT_API_KEY: str = ""
    GEMINI_IMPORT_MODEL: str = "gemini-2.5-flash"
    # 150s DERIVADO, não chutado. Com o thinking limitado (THINKING_BUDGET de
    # core/gemini_generation), o pior caso MEDIDO numa Itaú de 6 páginas / 95
    # transações foi 35,6s; extrapolando a 255 tok/s, uma fatura de ~200
    # transações dá ~65-70s. 150s = ~2x de folga sobre esse pior caso projetado.
    # Os 60000 anteriores cortavam a Itaú SEMPRE (o thinking sem teto levava
    # 63,9-88,6s, variando ±39% entre execuções idênticas).
    # NÃO é só timeout de cliente: o SDK deriva o X-Server-Timeout daqui, então
    # o prazo vale dos dois lados. Consumido pelos dois módulos de importação
    # por core/gemini_generation.http_options() — nunca na mão.
    GEMINI_IMPORT_TIMEOUT_MS: int = 150000  # fatura é bem maior que chat
    IMPORT_MAX_PDF_BYTES: int = 10 * 1024 * 1024
    IMPORT_MAX_PDF_PAGINAS: int = 20

    # F-04: rate limiting (slowapi). Ligado por padrão (produção); desligado no
    # ambiente de teste para a suíte não tomar 429.
    RATE_LIMIT_ENABLED: bool = True

    # T-25: Sentry OPCIONAL — setado só no deploy (ops). Sem DSN, o Sentry fica
    # inativo (no-op), inclusive em dev.
    SENTRY_DSN: str | None = None

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
