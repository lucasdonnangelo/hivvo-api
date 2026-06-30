"""Batch 10 / T-25 + T-43 — scrub do Sentry e fail-fast de boot."""

import json
import logging
import sys
import types

import pytest

from app.core.config import settings
from app.core.observability import _before_send, init_sentry, validate_startup_config


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
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    with pytest.raises(RuntimeError) as exc:
        validate_startup_config()
    msg = str(exc.value)
    assert "GEMINI_API_KEY" in msg
    assert "RESEND_API_KEY" in msg


def test_producao_com_chaves_ok(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "resend-key")
    validate_startup_config()  # não deve levantar


def test_dev_sem_chaves_apenas_warning(monkeypatch, caplog):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    with caplog.at_level(logging.WARNING):
        validate_startup_config()  # não levanta em dev
    assert any("GEMINI_API_KEY" in r.getMessage() for r in caplog.records)
