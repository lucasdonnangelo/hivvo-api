"""F-06 — a extração de extrato passa safety_settings EXPLÍCITO ao Gemini: as 4
categorias em BLOCK_ONLY_HIGH (a mesma config do assistente, fonte única em
app/core/gemini_safety).

Sem rede: _get_client é trocado por um fake que captura os kwargs de
generate_content. Verificação por mutação: remover o safety_settings do extrato
(ou trocar por BLOCK_NONE) faz este teste FALHAR.
"""

import app.services.import_extrato.gemini as gemini_extrato


class _FakeResponse:
    text = "{}"


def _fake_client(captura: dict):
    class _Models:
        def generate_content(self, **kwargs):
            captura.update(kwargs)
            return _FakeResponse()

    class _Client:
        models = _Models()

    return _Client()


def _valor(x):
    """Normaliza enum str do google-genai ou string crua para o valor textual."""
    return getattr(x, "value", x)


def test_extrato_passa_as_4_categorias_em_block_only_high(monkeypatch):
    captura: dict = {}
    monkeypatch.setattr(gemini_extrato, "_get_client", lambda: _fake_client(captura))

    gemini_extrato.extrair_extrato("texto qualquer redigido do extrato")

    safety = captura["config"].safety_settings
    assert safety is not None, "extrato não passou safety_settings (roda no default do provedor)"

    por_categoria = {_valor(s.category): _valor(s.threshold) for s in safety}
    assert por_categoria == {
        "HARM_CATEGORY_HARASSMENT": "BLOCK_ONLY_HIGH",
        "HARM_CATEGORY_HATE_SPEECH": "BLOCK_ONLY_HIGH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_ONLY_HIGH",
        "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_ONLY_HIGH",
    }


def test_extrato_usa_a_mesma_constante_do_assistente(monkeypatch):
    """Fonte única: a config do extrato é exatamente o SAFETY_SETTINGS compartilhado."""
    from app.core.gemini_safety import SAFETY_SETTINGS

    captura: dict = {}
    monkeypatch.setattr(gemini_extrato, "_get_client", lambda: _fake_client(captura))

    gemini_extrato.extrair_extrato("texto qualquer redigido do extrato")

    assert captura["config"].safety_settings == SAFETY_SETTINGS
