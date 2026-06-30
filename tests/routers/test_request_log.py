"""Batch 10 / T-25 — middleware de request log.

Garante o header X-Request-ID e o teste NEGATIVO de vazamento: senha/token no
corpo do request NÃO podem aparecer nos logs (só metadados).
"""

import logging
import uuid

from fastapi.testclient import TestClient

from main import app


def test_resposta_inclui_x_request_id():
    client = TestClient(app)
    # rota inexistente: 404 ainda passa pelo middleware, sem depender de DB/auth
    resp = client.get("/rota-inexistente-batch10")
    assert resp.status_code == 404
    rid = resp.headers.get("X-Request-ID")
    assert rid
    # é um UUID válido
    uuid.UUID(rid)


def test_log_nao_vaza_senha_nem_token(caplog):
    client = TestClient(app)
    with caplog.at_level(logging.INFO):
        client.post(
            "/rota-inexistente-batch10",
            json={"senha": "SuperSecreta123", "token": "tok-abc-xyz-999"},
        )
    texto = caplog.text
    # corpo do request não pode vazar nos logs
    assert "SuperSecreta123" not in texto
    assert "tok-abc-xyz-999" not in texto
    # mas a linha de metadados (método + path) saiu
    assert "POST" in texto
    assert "/rota-inexistente-batch10" in texto
