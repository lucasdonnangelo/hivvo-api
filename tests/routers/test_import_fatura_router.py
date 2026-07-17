"""POST /import/fatura/preview — auth, ownership, validação de arquivo,
mapeamento de erros e NÃO-vazamento do conteúdo da fatura em logs/respostas.

Gemini SEMPRE mockado (patch em gemini.extrair_fatura); nenhum teste bate na
API real nem em banco real. O caminho feliz usa um PDF fixture sintético
mínimo (tests/fixtures/fatura_texto_minimo.pdf) e a fatura Nubank do run
validado do spike (números reais).
"""

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.models.card import Cartao
from app.services.import_fatura import extracao_pdf, gemini
from main import app
from tests.fixtures.faturas_validadas import NUBANK

_PDF = (
    Path(__file__).resolve().parent.parent / "fixtures" / "fatura_texto_minimo.pdf"
).read_bytes()


@pytest.fixture(autouse=True)
def chave_import(monkeypatch):
    """Chave presente por padrão — o teste do 503 a remove localmente."""
    monkeypatch.setattr(settings, "GEMINI_IMPORT_API_KEY", "chave-de-teste")


@pytest.fixture()
def cartoes(session, users):
    user_a, user_b = users
    cartao_a = Cartao(usuario_id=user_a.id, nome="Nubank", tipo="Crédito")
    cartao_b = Cartao(usuario_id=user_b.id, nome="Itaú", tipo="Crédito")
    session.add(cartao_a)
    session.add(cartao_b)
    session.commit()
    session.refresh(cartao_a)
    session.refresh(cartao_b)
    return cartao_a, cartao_b


def _post(client, cartao_id, conteudo=_PDF):
    return client.post(
        "/import/fatura/preview",
        files={"arquivo": ("fatura.pdf", conteudo, "application/pdf")},
        data={"cartao_id": str(cartao_id)},
    )


def test_preview_feliz_devolve_fatura_e_reconciliacao(
    as_user, users, cartoes, monkeypatch, caplog
):
    monkeypatch.setattr(gemini, "extrair_fatura", lambda texto: json.dumps(NUBANK))

    with caplog.at_level(logging.DEBUG):
        resp = _post(as_user(users[0]), cartoes[0].id)

    assert resp.status_code == 200
    body = resp.json()
    assert body["cartao_id"] == cartoes[0].id

    fatura = body["fatura"]
    assert fatura["banco"] == "Nubank"
    assert fatura["total_a_pagar"] == "206.06"
    assert len(fatura["transacoes"]) == 8

    # números REAIS do run validado — inclusive o secundário que NÃO bate
    rec = body["reconciliacao"]
    assert rec["ancora"] == "206.06"
    assert rec["soma_gastos"] == "206.06"
    assert rec["diferenca"] == "0.00"
    assert rec["bate"] is True
    assert rec["excluidos"] == "-58.95"
    assert rec["diferenca_secundaria"] == "-58.95"
    assert rec["bate_secundario"] is False

    # nem o texto extraído do PDF nem o conteúdo da fatura vão para log
    assert "BANCO SINTETICO" not in caplog.text  # linha do PDF fixture
    assert "Blacktag" not in caplog.text  # descrição vinda do Gemini


def test_cartao_inexistente_404(as_user, users, cartoes):
    resp = _post(as_user(users[0]), 99999)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Cartão não encontrado"


def test_cartao_de_outro_usuario_404(as_user, users, cartoes):
    resp = _post(as_user(users[0]), cartoes[1].id)
    assert resp.status_code == 404
    # mesmo detail do inexistente — anti-enumeração (nunca 403)
    assert resp.json()["detail"] == "Cartão não encontrado"


def test_sem_autenticacao_401(session):
    client = TestClient(app)
    resp = client.post(
        "/api/v1/import/fatura/preview",
        files={"arquivo": ("fatura.pdf", _PDF, "application/pdf")},
        data={"cartao_id": "1"},
    )
    assert resp.status_code == 401


def test_arquivo_sem_magic_bytes_de_pdf_400(as_user, users, cartoes):
    resp = _post(as_user(users[0]), cartoes[0].id, conteudo=b"definitivamente nao e um pdf")
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_pdf_corrompido_400(as_user, users, cartoes):
    resp = _post(as_user(users[0]), cartoes[0].id, conteudo=b"%PDF-1.4\nlixo sem estrutura")
    assert resp.status_code == 400


def test_arquivo_acima_do_limite_413(as_user, users, cartoes, monkeypatch):
    monkeypatch.setattr(settings, "IMPORT_MAX_PDF_BYTES", 100)
    resp = _post(as_user(users[0]), cartoes[0].id)  # fixture tem ~1 KB
    assert resp.status_code == 413
    assert "limite" in resp.json()["detail"]


def test_paginas_acima_do_limite_422(as_user, users, cartoes, monkeypatch):
    monkeypatch.setattr(settings, "IMPORT_MAX_PDF_PAGINAS", 0)
    resp = _post(as_user(users[0]), cartoes[0].id)
    assert resp.status_code == 422
    assert "limite é 0" in resp.json()["detail"]


def test_fatura_escaneada_sem_camada_de_texto_422(as_user, users, cartoes, monkeypatch):
    monkeypatch.setattr(
        extracao_pdf, "extrair_texto", lambda dados, max_paginas: ("", 1)
    )
    resp = _post(as_user(users[0]), cartoes[0].id)
    assert resp.status_code == 422
    assert "escaneada" in resp.json()["detail"]


def test_resposta_invalida_do_gemini_502_sem_vazar_conteudo(
    as_user, users, cartoes, monkeypatch, caplog
):
    # inválida no schema, com um marcador que NÃO pode aparecer em log/response
    raw = json.dumps({"banco": "X", "transacoes": [{"descricao": "VALOR-SENSIVEL-XYZ"}]})
    monkeypatch.setattr(gemini, "extrair_fatura", lambda texto: raw)

    with caplog.at_level(logging.DEBUG):
        resp = _post(as_user(users[0]), cartoes[0].id)

    assert resp.status_code == 502
    assert "VALOR-SENSIVEL-XYZ" not in resp.text
    assert "VALOR-SENSIVEL-XYZ" not in caplog.text


def test_sem_chave_de_importacao_503(as_user, users, cartoes, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_IMPORT_API_KEY", "")
    resp = _post(as_user(users[0]), cartoes[0].id)
    assert resp.status_code == 503
    assert "GEMINI_IMPORT_API_KEY" in resp.json()["detail"]
