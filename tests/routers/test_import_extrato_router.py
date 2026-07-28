"""POST /import/extrato/preview — auth, validação de arquivo, mapeamento de erros
e NÃO-vazamento do conteúdo do extrato em logs/respostas. SEM cartao_id (o extrato
é da CONTA), stateless (nada persiste).

Gemini SEMPRE mockado (patch em gemini.extrair_extrato); nenhum teste bate na API
real nem em banco real. O caminho feliz usa o PDF fixture sintético mínimo
(tests/fixtures/extrato_texto_minimo.pdf) e o extrato sintético
(tests/fixtures/extratos_validados.py).
"""

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.import_extrato import gemini
from app.services.import_fatura import extracao_pdf
from main import app
from tests.fixtures.extratos_validados import EXTRATO_COM_RENDIMENTO

_PDF = (
    Path(__file__).resolve().parent.parent / "fixtures" / "extrato_texto_minimo.pdf"
).read_bytes()


@pytest.fixture(autouse=True)
def chave_import(monkeypatch):
    """Chave presente por padrão — o teste do 503 a remove localmente."""
    monkeypatch.setattr(settings, "GEMINI_IMPORT_API_KEY", "chave-de-teste")


@pytest.fixture(autouse=True)
def sem_categorizacao_real(monkeypatch):
    """Neutraliza a 2ª chamada ao Gemini (categorização em lote do Batch 2).

    Sem isto, o caminho feliz — que tem uma linha de débito — tentaria uma
    chamada de REDE de verdade (a chave de teste existe, o client é real) e a
    degradação graciosa esconderia o vazamento. Este arquivo cobre o contrato do
    Batch 1; o enriquecimento tem arquivo próprio.
    """
    monkeypatch.setattr(
        gemini, "categorizar_linhas", lambda pedidos, despesa, receita: {}
    )


def _post(client, conteudo=_PDF):
    return client.post(
        "/import/extrato/preview",
        files={"arquivo": ("extrato.pdf", conteudo, "application/pdf")},
    )


def test_preview_feliz_devolve_extrato_e_walk(as_user, users, monkeypatch, caplog):
    monkeypatch.setattr(
        gemini, "extrair_extrato", lambda texto: json.dumps(EXTRATO_COM_RENDIMENTO)
    )

    with caplog.at_level(logging.DEBUG):
        resp = _post(as_user(users[0]))

    assert resp.status_code == 200
    body = resp.json()
    assert "cartao_id" not in body  # extrato é da CONTA

    extrato = body["extrato"]
    assert extrato["banco"] == "Nubank"
    assert extrato["rendimento"] == "4.56"
    assert len(extrato["linhas"]) == 3

    # Batch 2: um item de enriquecimento por linha, alinhado por índice explícito
    assert [e["indice"] for e in body["enriquecimento"]] == [0, 1, 2]

    rec = body["reconciliacao"]
    assert rec["aplicavel"] is True
    assert rec["rendimento"] == "4.56"
    assert rec["saldo_final_calc"] == "1184.56"
    assert rec["diferenca"] == "0.00"
    assert rec["bate"] is True

    # nem o texto extraído do PDF nem o conteúdo do extrato vão para log
    assert "BANCO SINTETICO" not in caplog.text  # linha do PDF fixture
    assert "MERCADO EXEMPLO" not in caplog.text  # descrição vinda do Gemini


def test_sem_autenticacao_401(session):
    client = TestClient(app)
    resp = client.post(
        "/api/v1/import/extrato/preview",
        files={"arquivo": ("extrato.pdf", _PDF, "application/pdf")},
    )
    assert resp.status_code == 401


def test_arquivo_sem_magic_bytes_de_pdf_400(as_user, users):
    resp = _post(as_user(users[0]), conteudo=b"definitivamente nao e um pdf")
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_pdf_corrompido_400(as_user, users):
    resp = _post(as_user(users[0]), conteudo=b"%PDF-1.4\nlixo sem estrutura")
    assert resp.status_code == 400


def test_arquivo_acima_do_limite_413(as_user, users, monkeypatch):
    monkeypatch.setattr(settings, "IMPORT_MAX_PDF_BYTES", 100)
    resp = _post(as_user(users[0]))  # fixture tem ~1 KB
    assert resp.status_code == 413
    assert "limite" in resp.json()["detail"]


def test_paginas_acima_do_limite_422(as_user, users, monkeypatch):
    monkeypatch.setattr(settings, "IMPORT_MAX_PDF_PAGINAS", 0)
    resp = _post(as_user(users[0]))
    assert resp.status_code == 422
    assert "limite é 0" in resp.json()["detail"]


def test_extrato_escaneado_sem_camada_de_texto_422(as_user, users, monkeypatch):
    monkeypatch.setattr(
        extracao_pdf, "extrair_texto", lambda dados, max_paginas: ("", 1)
    )
    resp = _post(as_user(users[0]))
    assert resp.status_code == 422
    assert "escaneado" in resp.json()["detail"]


def test_resposta_invalida_do_gemini_502_sem_vazar_conteudo(
    as_user, users, monkeypatch, caplog
):
    # inválida no schema (linha sem data/valor/balde), com marcador sensível que
    # NÃO pode aparecer em log/response
    raw = json.dumps({"banco": "X", "linhas": [{"descricao": "VALOR-SENSIVEL-XYZ"}]})
    monkeypatch.setattr(gemini, "extrair_extrato", lambda texto: raw)

    with caplog.at_level(logging.DEBUG):
        resp = _post(as_user(users[0]))

    assert resp.status_code == 502
    assert "VALOR-SENSIVEL-XYZ" not in resp.text
    assert "VALOR-SENSIVEL-XYZ" not in caplog.text


def test_sem_chave_de_importacao_503(as_user, users, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_IMPORT_API_KEY", "")
    resp = _post(as_user(users[0]))
    assert resp.status_code == 503
    assert "GEMINI_IMPORT_API_KEY" in resp.json()["detail"]
