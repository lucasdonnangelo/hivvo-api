"""Data suspeita (#46) ponta a ponta, nos DOIS módulos — SQLite isolado, Gemini mockado.

O que este arquivo prova, e que o teste puro (tests/services/test_import_data_suspeita.py)
não alcança:

1. o sinal CHEGA no preview, no item do `indice` certo — com a linha pulada na
   PRIMEIRA posição, para que índice e posição no array NÃO coincidam (no batch
   da auto-categoria a fixture tinha as não-materializáveis no FIM e a mutação do
   join por índice ficou invisível; ver o log do scripts/mutacao.py);
2. o commit NÃO BLOQUEIA uma linha flagada. É o mesmo princípio da reconciliação:
   não bater não é erro HTTP — o cliente decide. Sinalizar e mesmo assim gravar é
   a regra, não um efeito colateral;
3. âncora ausente devolve 200 com o campo em None — degradação silenciosa e
   segura, não 422.
"""

import copy
import json
from pathlib import Path

import pytest
from sqlmodel import select

from app.core.config import settings
from app.models.card import Cartao
from app.models.transaction import Transacao
from app.services.import_extrato import gemini as gemini_extrato
from app.services.import_fatura import gemini as gemini_fatura
from tests.fixtures.extratos_validados import EXTRATO_COM_RENDIMENTO
from tests.fixtures.faturas_validadas import NUBANK

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
_PDF_FATURA = (_FIXTURES / "fatura_texto_minimo.pdf").read_bytes()
_PDF_EXTRATO = (_FIXTURES / "extrato_texto_minimo.pdf").read_bytes()

# A fatura validada é emitida em 2026-07-06 — a âncora dos casos abaixo.
_EMISSAO_NUBANK = "2026-07-06"


# --- Fatura -------------------------------------------------------------------


@pytest.fixture()
def cartao(session, users):
    card = Cartao(
        usuario_id=users[0].id, nome="Nubank", tipo="Crédito",
        dia_vencimento=13, dia_fechamento=6, mes_offset_vencimento=1,
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


@pytest.fixture()
def extracao_fatura(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_IMPORT_API_KEY", "chave-de-teste")
    estado = {"fatura": NUBANK}
    monkeypatch.setattr(
        gemini_fatura, "extrair_fatura", lambda texto: json.dumps(estado["fatura"])
    )
    return estado


def _fatura_pagamento_e_compra_impossivel() -> dict:
    """Fatura com a linha NÃO-materializável em PRIMEIRO — índice != posição.

    O item de enriquecimento da compra é o ÚNICO do array (posição 0), mas seu
    `indice` é 1. Um join por posição devolveria 0 e passaria despercebido se o
    pagamento estivesse no fim.
    """
    fatura = copy.deepcopy(NUBANK)
    fatura["transacoes"] = [
        {
            "data": "2026-06-20",
            "descricao": "Pagamento recebido",
            "valor_brl": "-100.00",
            "tipo": "pagamento",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        },
        {
            "data": "2026-07-10",  # QUATRO dias depois da emissão: impossível
            "descricao": "LOJISTA EXEMPLO",
            "valor_brl": "50.00",
            "tipo": "compra",
            "parcela": None,
            "portador_final": None,
            "internacional": None,
        },
    ]
    return fatura


def _preview_fatura(client, cartao_id):
    return client.post(
        "/import/fatura/preview",
        files={"arquivo": ("fatura.pdf", _PDF_FATURA, "application/pdf")},
        data={"cartao_id": str(cartao_id)},
    )


def test_fatura_preview_flaga_no_indice_certo(as_user, users, cartao, extracao_fatura):
    extracao_fatura["fatura"] = _fatura_pagamento_e_compra_impossivel()

    resp = _preview_fatura(as_user(users[0]), cartao.id)
    assert resp.status_code == 200, resp.text
    enriquecimento = resp.json()["enriquecimento"]

    # Um item só (o pagamento não materializa), e ele aponta para o ÍNDICE 1.
    assert [(e["indice"], e["data_suspeita"]) for e in enriquecimento] == [
        (1, "posterior_a_emissao")
    ]


def test_fatura_preview_nao_flaga_o_documento_validado(
    as_user, users, cartao, extracao_fatura
):
    """A fatura REAL do run validado do spike não tem nenhuma linha suspeita — a
    regra fica calada no caso normal."""
    resp = _preview_fatura(as_user(users[0]), cartao.id)
    assert resp.status_code == 200, resp.text
    assert all(e["data_suspeita"] is None for e in resp.json()["enriquecimento"])


def test_fatura_preview_sem_emissao_degrada_silencioso(
    as_user, users, cartao, extracao_fatura
):
    """`emissao` null: 200, campo None, nenhum 422 — e nem para a linha que seria
    flagada se houvesse âncora."""
    fatura = _fatura_pagamento_e_compra_impossivel()
    fatura["emissao"] = None
    extracao_fatura["fatura"] = fatura

    resp = _preview_fatura(as_user(users[0]), cartao.id)
    assert resp.status_code == 200, resp.text
    assert all(e["data_suspeita"] is None for e in resp.json()["enriquecimento"])


def test_fatura_commit_NAO_bloqueia_linha_flagada(
    session, as_user, users, cartao, extracao_fatura
):
    """SINALIZAR não é BARRAR: a linha impossível é gravada com a data que veio.

    O servidor não corrige a data (não sabe qual é a certa — inventá-la seria
    pior que o erro) e não recusa o import. Quem decide é o usuário na revisão.
    """
    fatura = _fatura_pagamento_e_compra_impossivel()

    resp = as_user(users[0]).post(
        "/import/fatura/commit",
        json={"cartao_id": cartao.id, "fatura": fatura, "competencias_pagas": []},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["transacoes_criadas"] == 1

    gravada = session.exec(
        select(Transacao).where(Transacao.usuario_id == users[0].id)
    ).one()
    assert gravada.data.isoformat() == "2026-07-10"  # intacta, não "consertada"


# --- Extrato ------------------------------------------------------------------


@pytest.fixture()
def extracao_extrato(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_IMPORT_API_KEY", "chave-de-teste")
    monkeypatch.setattr(
        gemini_extrato, "categorizar_linhas", lambda *a, **k: {}
    )
    estado = {"extrato": EXTRATO_COM_RENDIMENTO}
    monkeypatch.setattr(
        gemini_extrato, "extrair_extrato", lambda texto: json.dumps(estado["extrato"])
    )
    return estado


def _extrato_fora_dos_dois_lados() -> dict:
    """Período 01/06 -> 30/06 com uma linha ANTES e uma DEPOIS."""
    extrato = copy.deepcopy(EXTRATO_COM_RENDIMENTO)
    extrato["linhas"] = [
        {
            "data": "2026-05-20",
            "descricao": "Compra no debito LOJA A",
            "valor": "10.00",
            "balde": "debito",
            "cartao_citado": None,
        },
        {
            "data": "2026-06-15",
            "descricao": "Compra no debito LOJA B",
            "valor": "10.00",
            "balde": "debito",
            "cartao_citado": None,
        },
        {
            "data": "2026-07-05",
            "descricao": "Compra no debito LOJA C",
            "valor": "10.00",
            "balde": "debito",
            "cartao_citado": None,
        },
    ]
    return extrato


def _preview_extrato(client):
    return client.post(
        "/import/extrato/preview",
        files={"arquivo": ("extrato.pdf", _PDF_EXTRATO, "application/pdf")},
    )


def test_extrato_preview_flaga_os_dois_lados(as_user, users, extracao_extrato):
    extracao_extrato["extrato"] = _extrato_fora_dos_dois_lados()

    resp = _preview_extrato(as_user(users[0]))
    assert resp.status_code == 200, resp.text
    assert [
        (e["indice"], e["data_suspeita"]) for e in resp.json()["enriquecimento"]
    ] == [(0, "antes_do_periodo"), (1, None), (2, "depois_do_periodo")]


def test_extrato_preview_sem_periodo_degrada_silencioso(
    as_user, users, extracao_extrato
):
    """Sem período o preview segue (só o commit exige o período) e ninguém é
    flagado — inclusive as linhas que seriam, com âncora."""
    extrato = _extrato_fora_dos_dois_lados()
    extrato["periodo"] = None
    extracao_extrato["extrato"] = extrato

    resp = _preview_extrato(as_user(users[0]))
    assert resp.status_code == 200, resp.text
    assert all(e["data_suspeita"] is None for e in resp.json()["enriquecimento"])


def test_extrato_commit_NAO_bloqueia_linha_flagada(
    session, as_user, users, extracao_extrato
):
    """Mesmo contrato da fatura: o sinal não vira gate no commit."""
    extrato = _extrato_fora_dos_dois_lados()
    for linha in extrato["linhas"]:
        linha["importar"] = True

    resp = as_user(users[0]).post(
        "/import/extrato/commit",
        json={"extrato": extrato, "importar_rendimento": False},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["debitos_criados"] == 3

    datas = sorted(
        t.data.isoformat()
        for t in session.exec(
            select(Transacao).where(Transacao.usuario_id == users[0].id)
        ).all()
    )
    assert datas == ["2026-05-20", "2026-06-15", "2026-07-05"]  # intactas
