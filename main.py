import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse as _JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlmodel import Session, text

from app.core.config import settings
from app.core.database import engine
from app.core.observability import (
    configure_logging,
    init_sentry,
    request_log_middleware,
    validate_startup_config,
)
from app.core.rate_limit import limiter
from app.routers import auth, transactions, categories, cards, invoices, installments, statistics, ai

logger = logging.getLogger(__name__)

_IS_PRODUCTION = settings.ENVIRONMENT == "production"


class UTF8JSONResponse(_JSONResponse):
    media_type = "application/json; charset=utf-8"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # T-25/T-43: observabilidade + fail-fast de boot no startup.
    configure_logging()
    init_sentry()
    validate_startup_config()  # aborta o boot em produção sem GEMINI/RESEND
    yield
    # T-43: libera o pool de conexões no shutdown.
    engine.dispose()


app = FastAPI(
    title="Hivvo API",
    version="0.1.0",
    # F-13: superfície da API não fica exposta em produção
    docs_url=None if _IS_PRODUCTION else "/docs",
    redoc_url=None if _IS_PRODUCTION else "/redoc",
    openapi_url=None if _IS_PRODUCTION else "/openapi.json",
    default_response_class=UTF8JSONResponse,
    lifespan=lifespan,
)

# T-25: request-id (X-Request-ID) + log de metadados por request. Registrado
# como middleware HTTP; nunca loga corpo, tokens, cookies nem mensagem.
app.middleware("http")(request_log_middleware)

# F-04: limiter compartilhado + handler 429. Os limites por rota ficam nos
# decorators @limiter.limit(...) nos routers.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],  # T-07: dirigido por config (default Vite dev server)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(cards.router)
app.include_router(invoices.router)
app.include_router(installments.router)
app.include_router(statistics.router)
app.include_router(ai.router)


@app.get("/health", tags=["health"])
def health_check():
    # F-14: /health é público — o corpo não nomeia subsistemas nem o ambiente.
    # Status saudável genérico; falha vira 503 genérico, com o detalhe real só no log.
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        logger.error("Health check falhou: %s", e)
        return UTF8JSONResponse(status_code=503, content={"status": "unhealthy"})
