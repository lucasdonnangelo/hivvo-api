"""Batch 9 / T-21 — singleton + timeout + orçamento de retry do Gemini.

Sem rede: o client é mockado. Cobre que _get_client é singleton, que a chave
ausente falha com mensagem clara, e que o retry usa o orçamento reduzido
(len(GEMINI_RETRY_WAITS) + 1 tentativas).
"""

import pytest
from fastapi import HTTPException
from google.genai import errors as genai_errors

import app.routers.ai as ai


class _FakeServerError(genai_errors.ServerError):
    # Evita o __init__ real (exige code/response) — só precisamos do tipo para
    # o except genai_errors.ServerError do retry.
    def __init__(self):
        pass


class TestT21Singleton:
    def test_get_client_reusa_a_mesma_instancia(self, monkeypatch):
        monkeypatch.setattr(ai, "_client", None)
        monkeypatch.setattr(ai.settings, "GEMINI_API_KEY", "fake-key")
        assert ai._get_client() is ai._get_client()

    def test_get_client_sem_chave_falha_com_mensagem_clara(self, monkeypatch):
        monkeypatch.setattr(ai, "_client", None)
        monkeypatch.setattr(ai.settings, "GEMINI_API_KEY", "")
        with pytest.raises(HTTPException) as exc:
            ai._get_client()
        assert exc.value.status_code == 503
        assert "GEMINI_API_KEY" in exc.value.detail


class TestT21RetryBudget:
    def test_retry_usa_orcamento_reduzido(self, monkeypatch):
        calls = {"n": 0}

        class _Models:
            def generate_content(self, **kwargs):
                calls["n"] += 1
                raise _FakeServerError()

        class _Client:
            models = _Models()

        # Singleton já resolvido para o fake — não constrói client real nem dorme
        monkeypatch.setattr(ai, "_client", _Client())
        monkeypatch.setattr(ai.time, "sleep", lambda *_: None)

        with pytest.raises(HTTPException) as exc:
            ai._gemini_generate([], "sys")
        assert exc.value.status_code == 503
        # 2 tentativas por padrão (GEMINI_RETRY_WAITS = [2])
        assert calls["n"] == len(ai.settings.GEMINI_RETRY_WAITS) + 1
