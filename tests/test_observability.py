"""Batch 10 / T-25 + T-43 — scrub do Sentry e fail-fast de boot."""

import json
import logging
import sys
import types

import pytest

from app.core.config import settings
from app.core.observability import (
    _before_breadcrumb,
    _before_send,
    init_sentry,
    validate_startup_config,
)


def _evento_realista():
    """Evento Sentry com TODOS os vetores de vazamento preenchidos:

    request.headers (Authorization/Cookie), request.cookies (token), request.data
    (senha + mensagem de chat) E locals do stacktrace (mensagem de chat + token).
    """
    return {
        "request": {
            "headers": {
                "Authorization": "Bearer abc123",
                "Cookie": "access_token=cookie-token-xyz",
                "User-Agent": "pytest",
            },
            "cookies": {"access_token": "cookie-token-xyz"},
            "data": {"senha": "SuperSecreta", "mensagem": "quanto gastei no cartao?"},
        },
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {"function": "outra", "vars": {"x": "ok"}},
                            {
                                "function": "chat",
                                "vars": {
                                    "mensagem": "conteudo secreto de chat do usuario",
                                    "token": "local-token-987",
                                },
                            },
                        ]
                    }
                }
            ]
        },
    }


def test_before_send_remove_request_sensivel():
    out = _before_send(_evento_realista(), {})
    headers = out["request"]["headers"]
    assert headers["Authorization"] == "[Filtered]"
    assert headers["Cookie"] == "[Filtered]"
    assert headers["User-Agent"] == "pytest"  # header inócuo preservado
    assert "cookies" not in out["request"]
    assert "data" not in out["request"]


def test_before_send_remove_locals_do_stacktrace():
    out = _before_send(_evento_realista(), {})
    frames = out["exception"]["values"][0]["stacktrace"]["frames"]
    # vars de TODO frame removidos — a mensagem de chat viaja nos locals
    assert all("vars" not in f for f in frames)


def test_before_send_nada_sensivel_sobra_no_evento_inteiro():
    """Varredura de texto: nenhum segredo pode restar em lugar nenhum do evento."""
    out = _before_send(_evento_realista(), {})
    blob = json.dumps(out)
    for segredo in (
        "conteudo secreto de chat do usuario",  # mensagem nos locals
        "quanto gastei no cartao?",             # mensagem no corpo
        "SuperSecreta",                         # senha no corpo
        "local-token-987",                      # token nos locals
        "cookie-token-xyz",                     # token no cookie/header
        "abc123",                               # token no header Authorization
    ):
        assert segredo not in blob


# --- #39: scrub de logentry e breadcrumb --------------------------------------
#
# A LoggingIntegration é DEFAULT e manda toda string de log para fora: INFO vira
# breadcrumb, ERROR vira evento. O controle continua sendo não pôr conteúdo em
# log (auditoria site a site do #39); isto aqui é a REDE abaixo dele.


# (rótulo, texto que seria logado, o pedaço que NÃO pode sair)
SHAPES_SENSIVEIS = [
    ("cpf_formatado", "titular 123.456.789-01 no extrato", "123.456.789-01"),
    ("cpf_corrido", "pix para o documento 98765432109", "98765432109"),
    ("email", "falha ao enviar para fulano.silva@example.com", "fulano.silva@example.com"),
    ("agencia", "transferencia recebida Ag: 0234-5", "0234-5"),
    ("conta", "credito em Conta corrente 000123456-7", "000123456-7"),
]

IDS_SHAPES = [s[0] for s in SHAPES_SENSIVEIS]


@pytest.mark.parametrize("_rotulo,texto,segredo", SHAPES_SENSIVEIS, ids=IDS_SHAPES)
def test_breadcrumb_redige_todos_os_shapes(_rotulo, texto, segredo):
    """No breadcrumb a `message` já vem INTERPOLADA (a integração usa
    `record.message`), então é ali que a PII aparece."""
    crumb = _before_breadcrumb(
        {"type": "log", "level": "info", "category": "app.x", "message": texto}, {}
    )
    assert segredo not in json.dumps(crumb)


@pytest.mark.parametrize("_rotulo,texto,segredo", SHAPES_SENSIVEIS, ids=IDS_SHAPES)
def test_logentry_redige_todos_os_shapes_nos_tres_campos(_rotulo, texto, segredo):
    """`logentry` tem TRÊS campos e a PII pode estar em qualquer um:

    `formatted` (interpolado, o caso normal), `params` (os args crus) e
    `message` — que é o format string, normalmente inócuo, MAS carrega tudo
    quando alguém loga uma f-string já montada.
    """
    evento = _before_send(
        {
            "logentry": {
                "message": texto,            # caso f-string
                "formatted": f"contexto: {texto}",
                "params": [texto, 42, None],  # args crus, com metadado junto
            }
        },
        {},
    )
    assert segredo not in json.dumps(evento)


def test_logentry_scrub_nao_para_no_primeiro_campo():
    """Guarda do erro NATURAL de implementação: varrer só `logentry["message"]`.

    Quem lê "o scrub tem que varrer logentry" e para no primeiro campo redige o
    FORMAT STRING — que é nosso e constante — e não pega nada. Este evento tem
    `message` limpo de propósito: só passa quem varre `formatted` e `params`.
    """
    evento = _before_send(
        {
            "logentry": {
                "message": "falha ao enviar e-mail para %s (cpf %s)",  # sem PII
                "formatted": "falha ao enviar e-mail para vitima@example.com (cpf 123.456.789-01)",
                "params": ["vitima@example.com", "123.456.789-01"],
            }
        },
        {},
    )
    blob = json.dumps(evento)
    assert "vitima@example.com" not in blob
    assert "123.456.789-01" not in blob


def test_scrub_preserva_o_metadado_ao_redor():
    """O scrub não pode virar deny-all disfarçado: o valor do log são os
    contadores e ids, e um scrub que apaga tudo passaria nos testes de ausência
    acima sem servir para nada."""
    evento = _before_send(
        {
            "logentry": {
                "message": "[import] commit extrato: banco=%s receitas=%d bate=%s",
                "formatted": "[import] commit extrato: banco=nubank receitas=12 bate=True",
                "params": ["nubank", 12, True],
            }
        },
        {},
    )
    logentry = evento["logentry"]
    assert logentry["params"] == ["nubank", 12, True]  # tipos preservados, não stringificados
    assert "receitas=12" in logentry["formatted"]
    assert "[import] commit extrato" in logentry["formatted"]


def test_valor_da_excecao_e_redigido():
    """`exception.values[].value` é `str(exceção)`, e truncar na ORIGEM não
    alcança: todo `logger.exception` manda a mensagem inteira por aqui. Foi o
    que test_import_extrato_gemini_erros::..._respeita_o_teto mediu."""
    evento = _before_send(
        {
            "exception": {
                "values": [
                    {
                        "type": "RuntimeError",
                        "value": "falhou para fulano@example.com cpf 123.456.789-01",
                        "stacktrace": {"frames": [{"function": "f", "vars": {"a": 1}}]},
                    }
                ]
            }
        },
        {},
    )
    blob = json.dumps(evento)
    assert "fulano@example.com" not in blob
    assert "123.456.789-01" not in blob
    assert evento["exception"]["values"][0]["type"] == "RuntimeError"  # grouping intacto


def test_breadcrumbs_do_evento_tambem_sao_varridos():
    """Os dois hooks são religados em separado; o #39 nomeia `breadcrumbs` E
    `logentry`, e sair com um só seria meia correção difícil de perceber."""
    evento = _before_send(
        {"breadcrumbs": {"values": [{"type": "log", "message": "cpf 123.456.789-01"}]}},
        {},
    )
    assert "123.456.789-01" not in json.dumps(evento)


def test_descricao_de_lojista_e_residuo_declarado_nao_e_redigida():
    """CRISTALIZA O LIMITE, no idioma do test_import_extrato_redacao.

    Texto livre não tem FORMA para casar: descrição de lojista e nome de
    contraparte de Pix/TED atravessam o scrub inteiros. Este teste falha no dia
    em que alguém achar que o scrubber "cobre PII de log" e relaxar a regra de
    não logar conteúdo — que é o controle de verdade.
    """
    evento = _before_send(
        {
            "logentry": {
                "message": "compra %s",
                "formatted": "compra PAODEACUCA-CT91 45,90",
                "params": ["PAODEACUCA-CT91 45,90"],
            }
        },
        {},
    )
    blob = json.dumps(evento)
    assert "PAODEACUCA-CT91" in blob

    crumb = _before_breadcrumb({"message": "Pix enviado - BELTRANO DE SOUZA"}, {})
    assert "BELTRANO DE SOUZA" in crumb["message"]


def test_init_sentry_usa_config_segura(monkeypatch):
    """init passa as flags que cortam o vazamento na origem."""
    captured = {}
    fake_sdk = types.ModuleType("sentry_sdk")
    fake_sdk.init = lambda **kwargs: captured.update(kwargs)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://fake@sentry.example/1")

    init_sentry()

    assert captured["send_default_pii"] is False
    assert captured["include_local_variables"] is False
    assert captured["max_request_body_size"] == "never"
    assert captured["before_send"] is _before_send
    # #39: o caminho do breadcrumb é o OUTRO metade do vazamento de log. Sem
    # este hook, todo logger.info sai do servidor sem passar por redação.
    assert captured["before_send_breadcrumb"] is _before_breadcrumb
    # A LoggingIntegration segue ativa DE PROPÓSITO (postura do #39: os logs do
    # backend são nossos e enumeráveis, e são o que dá sequência a um erro em
    # produção). Se um dia for desligada, é decisão — não pode acontecer sem
    # que este teste seja reescrito.
    assert "integrations" not in captured


def test_init_sentry_noop_sem_dsn(monkeypatch):
    chamou = {"init": False}
    fake_sdk = types.ModuleType("sentry_sdk")
    fake_sdk.init = lambda **kwargs: chamou.__setitem__("init", True)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake_sdk)
    monkeypatch.setattr(settings, "SENTRY_DSN", None)

    init_sentry()

    assert chamou["init"] is False  # sem DSN, nem importa/inicializa


def test_fail_fast_producao_sem_chaves(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_IMPORT_API_KEY", "")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    with pytest.raises(RuntimeError) as exc:
        validate_startup_config()
    msg = str(exc.value)
    assert "GEMINI_API_KEY" in msg
    assert "GEMINI_IMPORT_API_KEY" in msg
    assert "RESEND_API_KEY" in msg


def test_producao_com_chaves_ok(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(settings, "GEMINI_IMPORT_API_KEY", "gemini-import-key")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "resend-key")
    validate_startup_config()  # não deve levantar


def test_dev_sem_chaves_apenas_warning(monkeypatch, caplog):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_IMPORT_API_KEY", "")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    with caplog.at_level(logging.WARNING):
        validate_startup_config()  # não levanta em dev
    assert any("GEMINI_API_KEY" in r.getMessage() for r in caplog.records)
