import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse as _JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlmodel import Session, text

from app.core.config import settings
from app.core.database import engine
from app.core.observability import (
    configure_logging,
    init_sentry,
    request_log_middleware,
    validate_startup_config,
)
from app.core.csrf import verify_origin
from app.core.rate_limit import limiter
from app.routers import auth, transactions, categories, cards, invoices, installments, statistics, ai, recorrencias, import_fatura

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


def db_unavailable_handler(request: Request, exc: Exception) -> _JSONResponse:
    # Fase 5: banco fora (conexão) → 503 limpo, nunca 500 cru. Tratado pelo
    # ExceptionMiddleware, que fica DENTRO do CORSMiddleware no stack do
    # Starlette — então a resposta volta COM os headers de CORS, e o browser
    # não a lê como falso erro de CORS (o que mascarou o diagnóstico 2x).
    # Erro real só no log, sem str(exc) (pode conter host/string de conexão).
    logger.error("Falha de conexão com o banco: %s", exc.__class__.__name__)
    return UTF8JSONResponse(
        status_code=503,
        content={"detail": "Serviço temporariamente indisponível"},
    )


# OperationalError/InterfaceError são as classes de falha de conexão do
# SQLAlchemy. pool_pre_ping (database.py) cobre a conexão reciclada/transitória;
# este handler cobre o banco totalmente fora (pausado, IPv6 inalcançável).
app.add_exception_handler(OperationalError, db_unavailable_handler)
app.add_exception_handler(InterfaceError, db_unavailable_handler)

app.add_middleware(
    CORSMiddleware,
    # F-03: origem EXPLÍCITA (nunca "*" — incompatível com credentials); métodos
    # e headers restritos ao que a API usa (JWT vai no cookie, não em header).
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    # PATCH: usado pelo PATCH /recorrencias (Fase 2c); verify_origin já o cobre.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# T-28: todos os routers de NEGÓCIO sob /api/v1 (hard switch — sem dual-mount).
# /health permanece na RAIZ (health check do load balancer) — ver abaixo.
# F-03: verify_origin (reforço CSRF) em todos os routers de negócio — só age em
# métodos mutáveis com Origin presente e não permitido.
_csrf = [Depends(verify_origin)]
app.include_router(auth.router, prefix="/api/v1", dependencies=_csrf)
app.include_router(transactions.router, prefix="/api/v1", dependencies=_csrf)
app.include_router(categories.router, prefix="/api/v1", dependencies=_csrf)
app.include_router(cards.router, prefix="/api/v1", dependencies=_csrf)
app.include_router(invoices.router, prefix="/api/v1", dependencies=_csrf)
app.include_router(invoices.router_competencia, prefix="/api/v1", dependencies=_csrf)
app.include_router(installments.router, prefix="/api/v1", dependencies=_csrf)
app.include_router(statistics.router, prefix="/api/v1", dependencies=_csrf)
app.include_router(ai.router, prefix="/api/v1", dependencies=_csrf)
app.include_router(recorrencias.router, prefix="/api/v1", dependencies=_csrf)
app.include_router(import_fatura.router, prefix="/api/v1", dependencies=_csrf)


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
