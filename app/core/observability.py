"""Observabilidade (T-25) e fail-fast de boot (T-43).

Concentra logging, Sentry (opcional), o middleware de request-log e a validação
de configuração no startup. Regra dura de privacidade/LGPD: NUNCA logar nem
enviar ao Sentry corpo de request/response, tokens, senhas, cookies ou conteúdo
de mensagem de chat — só metadados.
"""

import logging
import time
import uuid
from logging.config import dictConfig

from starlette.requests import Request

from app.core.config import settings

_request_logger = logging.getLogger("hivvo.request")
_startup_logger = logging.getLogger("hivvo.startup")

# Headers que jamais podem ir ao Sentry (token/sessão).
_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-csrf-token"}


def configure_logging() -> None:
    """Configura o logging via dictConfig. Nível por ENVIRONMENT."""
    level = "DEBUG" if settings.ENVIRONMENT == "development" else "INFO"
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                },
            },
            "root": {"handlers": ["console"], "level": level},
        }
    )


def _scrub_frame_vars(stacktrace) -> None:
    """Remove as variáveis locais de todos os frames de um stacktrace.

    Os locals do traceback são o vetor mais perigoso de vazamento: um erro
    dentro de /ai/chat carrega a mensagem do usuário (e possivelmente token/
    senha) numa variável local. Não há como saber qual local é sensível, então
    descartamos `vars` de todo frame.
    """
    if isinstance(stacktrace, dict):
        for frame in stacktrace.get("frames") or []:
            if isinstance(frame, dict):
                frame.pop("vars", None)


def _before_send(event, hint):
    """Remove dados sensíveis dos eventos do Sentry (LGPD).

    Belt-and-suspenders sobre `send_default_pii=False` e `include_local_variables=
    False`: (1) filtra Authorization/Cookie dos headers; (2) descarta `cookies` e
    o corpo (`data`); (3) varre os locals de TODOS os frames de stacktrace
    (`exception` e `threads`). Garante que token, senha e conteúdo de mensagem de
    chat nunca saiam, mesmo que a captura de locals/corpo seja reativada.
    """
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers):
                if key.lower() in _SENSITIVE_HEADERS:
                    headers[key] = "[Filtered]"
        request.pop("cookies", None)
        request.pop("data", None)

    # Locals do stacktrace: o conteúdo da mensagem de chat viaja AQUI, não só no
    # corpo. Varrer exception.values[].stacktrace e threads.values[].stacktrace.
    for container_key in ("exception", "threads"):
        container = event.get(container_key)
        if isinstance(container, dict):
            for value in container.get("values") or []:
                if isinstance(value, dict):
                    _scrub_frame_vars(value.get("stacktrace"))
    return event


def init_sentry() -> None:
    """Inicializa o Sentry SOMENTE se SENTRY_DSN estiver setado.

    Sem DSN é no-op (não crasha em dev). O SDK é importado de forma lazy para
    não exigir o pacote quando o Sentry está inativo.
    """
    if not settings.SENTRY_DSN:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        # LGPD — cortar os vazamentos na ORIGEM, antes do before_send:
        send_default_pii=False,          # não coletar PII automaticamente
        include_local_variables=False,   # não anexar locals do traceback (mensagem/token/senha)
        max_request_body_size="never",   # não capturar o corpo do request
        before_send=_before_send,        # defesa adicional (scrub explícito)
    )


async def request_log_middleware(request: Request, call_next):
    """Gera request-id, devolve em X-Request-ID e loga só metadados.

    Nunca loga corpo, headers, cookies, tokens nem conteúdo de mensagem. Usa
    `request.url.path` (sem query string) para não vazar segredos em URL. O
    /health é logado em DEBUG (silenciado em produção, que roda em INFO).
    """
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    level = logging.DEBUG if request.url.path == "/health" else logging.INFO
    _request_logger.log(
        level,
        "%s %s %s %.1fms request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )
    return response


def validate_startup_config() -> None:
    """Fail-fast de boot (T-43).

    Em produção, aborta o boot com mensagem clara se GEMINI_API_KEY ou
    RESEND_API_KEY estiverem ausentes. Em dev, apenas WARNING (são
    feature-specific; o app deve subir sem elas em dev).
    """
    features = {
        "GEMINI_API_KEY": settings.GEMINI_API_KEY,
        "GEMINI_IMPORT_API_KEY": settings.GEMINI_IMPORT_API_KEY,
        "RESEND_API_KEY": settings.RESEND_API_KEY,
    }
    missing = [name for name, value in features.items() if not value]
    if not missing:
        return
    if settings.ENVIRONMENT == "production":
        raise RuntimeError(
            "Boot abortado: variáveis obrigatórias ausentes em produção: "
            f"{', '.join(missing)}. Defina-as no painel de deploy antes de subir."
        )
    _startup_logger.warning(
        "Variáveis de feature ausentes (%s) — OK em dev; as funcionalidades "
        "dependentes ficam indisponíveis até configurá-las.",
        ", ".join(missing),
    )
