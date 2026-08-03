"""Observabilidade (T-25) e fail-fast de boot (T-43).

Concentra logging, Sentry (opcional), o middleware de request-log e a validação
de configuração no startup. Regra dura de privacidade/LGPD: NUNCA logar nem
enviar ao Sentry corpo de request/response, tokens, senhas, cookies ou conteúdo
de mensagem de chat — só metadados.

--- A REGRA É O CONTROLE; O SCRUB É A REDE (#39) ---

A `LoggingIntegration` do sentry_sdk é DEFAULT e continua ativa: todo
`logger.info`/`warning` vira breadcrumb e todo `logger.error`/`exception` vira
evento. Ou seja, a regra do parágrafo acima é o que de fato impede conteúdo de
sair do servidor — não uma configuração.

Abaixo dela `_before_send` + `_before_breadcrumb` redigem PII de FORMA CONHECIDA
(CPF, e-mail, agência/conta — `core/scrub.py`). Isso é defesa em profundidade,
com um limite que não deve ser esquecido: **texto livre não tem forma para
casar**. Descrição de lojista e nome de contraparte de Pix/TED passam inteiros.
Um log novo que carregue conteúdo de documento não fica seguro por existir scrub.
"""

import logging
import time
import uuid
from logging.config import dictConfig

from starlette.requests import Request

from app.core.config import settings
from app.core.scrub import redigir_pii

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


def _redigir_valor(valor):
    """Redige se for string; deixa o resto intocado.

    Os args de log que NÃO são string são metadado por construção (contadores,
    ids, enums, durações) — ver a auditoria do #39. RESÍDUO: um objeto não-str
    cujo `repr` carregue PII passa, porque a formatação dele acontece depois
    daqui.
    """
    return redigir_pii(valor) if isinstance(valor, str) else valor


def _scrub_logentry(logentry) -> None:
    """Redige a mensagem de log que a LoggingIntegration anexa ao EVENTO.

    O shape tem TRÊS campos e cada um precisa de tratamento (sentry_sdk 2.x,
    `integrations/logging.py`):
      * `message`   — `record.msg`, o FORMAT STRING. Normalmente é nosso e
                      constante, MAS é onde mora tudo quando alguém loga uma
                      f-string já interpolada (`logger.error(f"...{x}")`), que é
                      o caso em que `params` fica vazio. Não é redundante.
      * `formatted` — `record.getMessage()`, já interpolado. É aqui que a PII
                      aparece no fluxo normal.
      * `params`    — `record.args` crus.

    Varrer só `message` — o erro natural de quem lê "logentry" e para no primeiro
    campo — redigiria o format string e NÃO pegaria nada. O teste de mutação em
    tests/test_observability.py existe por causa disso.
    """
    if not isinstance(logentry, dict):
        return
    for chave in ("message", "formatted"):
        if isinstance(logentry.get(chave), str):
            logentry[chave] = redigir_pii(logentry[chave])

    params = logentry.get("params")
    if isinstance(params, (list, tuple)):
        logentry["params"] = [_redigir_valor(p) for p in params]
    elif isinstance(params, dict):
        logentry["params"] = {k: _redigir_valor(v) for k, v in params.items()}


def _scrub_breadcrumb(crumb) -> None:
    """Redige um breadcrumb. `message` já vem INTERPOLADO (ao contrário do
    evento): a integração usa `record.message`, montado por `format(record)`."""
    if not isinstance(crumb, dict):
        return
    if isinstance(crumb.get("message"), str):
        crumb["message"] = redigir_pii(crumb["message"])
    data = crumb.get("data")
    if isinstance(data, dict):
        for chave, valor in data.items():
            data[chave] = _redigir_valor(valor)


def _before_breadcrumb(crumb, hint):
    """Hook de breadcrumb (#39).

    Por que redigir em vez de descartar, ao contrário do front: aqui os logs são
    NOSSOS e enumeráveis (auditados no #39: 20 de 31 sites são metadado puro), e
    são o que dá sequência temporal a um erro em produção. No front o deny-all é
    certo porque `console` captura saída de biblioteca de terceiro, de shape
    desconhecido.
    """
    _scrub_breadcrumb(crumb)
    return crumb


def _before_send(event, hint):
    """Remove dados sensíveis dos eventos do Sentry (LGPD).

    Belt-and-suspenders sobre `send_default_pii=False` e `include_local_variables=
    False`: (1) filtra Authorization/Cookie dos headers; (2) descarta `cookies` e
    o corpo (`data`); (3) varre os locals de TODOS os frames de stacktrace
    (`exception` e `threads`); (4) desde o #39, redige `logentry`, `extra`,
    `breadcrumbs` e o `value` das exceções.

    O (4) é DEFESA EM PROFUNDIDADE e não o controle — o controle é a regra de
    não pôr conteúdo em log, que a auditoria do #39 verificou site a site. Isto
    casa FORMATO conhecido (CPF, e-mail, agência/conta) e não tem como casar
    texto livre: descrição de lojista e nome de contraparte de Pix/TED passam.
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
                    # `value` é str(exceção). Truncar na ORIGEM não alcança isto:
                    # todo `logger.exception` manda a mensagem INTEIRA por aqui,
                    # e o traceback renderizado a repete. Medido em
                    # test_import_extrato_gemini_erros::..._respeita_o_teto.
                    if isinstance(value.get("value"), str):
                        value["value"] = redigir_pii(value["value"])

    _scrub_logentry(event.get("logentry"))

    extra = event.get("extra")
    if isinstance(extra, dict):
        for chave, valor in extra.items():
            extra[chave] = _redigir_valor(valor)

    # Breadcrumbs já passaram por `_before_breadcrumb` na captura. Varrer de novo
    # aqui é barato e cobre o caso de os dois hooks serem religados em separado —
    # o #39 nomeia `breadcrumbs` E `logentry`, e sair com um só seria meia
    # correção difícil de perceber.
    breadcrumbs = event.get("breadcrumbs")
    valores = (
        breadcrumbs.get("values") if isinstance(breadcrumbs, dict) else breadcrumbs
    )
    if isinstance(valores, list):
        for crumb in valores:
            _scrub_breadcrumb(crumb)

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
        before_send_breadcrumb=_before_breadcrumb,  # idem, no caminho do breadcrumb
        #
        # ⚠ NÃO LIGUE `enable_logs` SEM UM TERCEIRO HOOK.
        # A LoggingIntegration é DEFAULT e não é desabilitada aqui de propósito
        # (#39): breadcrumb em INFO e evento em ERROR são o que dá sequência
        # temporal a um erro em produção, e os dois hooks acima redigem os dois
        # caminhos. `enable_logs=True` abre um TERCEIRO caminho — o pipeline de
        # Sentry Logs, que emite os args do log como atributos
        # `sentry.message.parameter.N` e NÃO passa por `before_send` nem por
        # `before_send_breadcrumb`. Ele tem hook próprio, `before_send_log`.
        # Ligar a flag sem passar um scrub por lá manda os args de todo log do
        # backend para fora sem redação — inclusive os do caminho de EXTRATO,
        # que carrega PII de terceiros (contraparte de Pix/TED).
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
