"""Enriquecimento do preview de extrato (Batch 2) ponta a ponta — SQLite isolado,
Gemini SEMPRE mockado, nenhuma chamada de rede.

Cobre os três blocos (categoria sugerida, fatura proposta, flag de recorrência),
a EFICIÊNCIA (uma única chamada ao Gemini para todas as linhas — asserção, não
comentário), o isolamento entre usuários e a STATELESSNESS (nenhuma escrita no
caminho do preview).
"""

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func
from sqlalchemy import select as sa_select
from sqlmodel import SQLModel

from app.core.config import settings
from app.models.card import Cartao
from app.models.pagamento_fatura import PagamentoFatura
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.models.transaction import Transacao
from app.services.import_extrato import gemini
from tests.fixtures.extratos_validados import EXTRATO_ENRIQUECIMENTO

_PDF = (
    Path(__file__).resolve().parent.parent / "fixtures" / "extrato_texto_minimo.pdf"
).read_bytes()


@pytest.fixture(autouse=True)
def extracao_mockada(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_IMPORT_API_KEY", "chave-de-teste")
    monkeypatch.setattr(
        gemini, "extrair_extrato", lambda texto: json.dumps(EXTRATO_ENRIQUECIMENTO)
    )


@pytest.fixture()
def categorizador(monkeypatch):
    """Instala o stub da categorização em lote e devolve o registro das chamadas.

    `chamadas` é a garantia de eficiência: com 5 linhas categorizáveis ele tem de
    ficar em 1 — N chamadas (uma por linha) explodiriam a latência do preview.
    """
    chamadas: list[dict] = []
    resposta: dict = {}

    def _fake(pedidos, nomes_despesa, nomes_receita):
        chamadas.append(
            {
                "pedidos": list(pedidos),
                "nomes_despesa": nomes_despesa,
                "nomes_receita": nomes_receita,
            }
        )
        return dict(resposta)

    monkeypatch.setattr(gemini, "categorizar_linhas", _fake)
    return {"chamadas": chamadas, "resposta": resposta}


def _post(client):
    return client.post(
        "/import/extrato/preview",
        files={"arquivo": ("extrato.pdf", _PDF, "application/pdf")},
    )


def _enriquecimento(resp) -> list[dict]:
    assert resp.status_code == 200, resp.text
    return resp.json()["enriquecimento"]


# --- helpers de cenário -------------------------------------------------------


def _cartao(session, usuario, nome, *, dia_vencimento=13, ativo=True) -> Cartao:
    cartao = Cartao(
        usuario_id=usuario.id,
        nome=nome,
        tipo="Crédito",
        dia_vencimento=dia_vencimento,
        dia_fechamento=5,
        mes_offset_vencimento=1,
        ativo=ativo,
    )
    session.add(cartao)
    session.commit()
    session.refresh(cartao)
    return cartao


def _fatura(session, usuario, cartao, valor, *, mes=6, ano=2026) -> None:
    """Materializa uma fatura mínima: uma avulsa de crédito na competência."""
    session.add(
        Transacao(
            usuario_id=usuario.id,
            tipo="despesa",
            data=dt.date(ano, mes, 1),
            descricao="Compra",
            valor=Decimal(valor),
            categoria="Outros",
            forma_pagamento="Crédito",
            cartao_id=cartao.id,
            fatura_mes=mes,
            fatura_ano=ano,
        )
    )
    session.commit()


def _recorrencia_salario(session, usuario, *, valor="5000.00", dia=5) -> Recorrencia:
    rec = Recorrencia(
        usuario_id=usuario.id,
        tipo="receita",
        categoria="Salário",
        forma_pagamento="Pix",
        dia_do_mes=dia,
        descricao="Salário ACME",
    )
    session.add(rec)
    session.commit()
    session.add(
        RecorrenciaVigencia(
            recorrencia_id=rec.id, valor=Decimal(valor), mes_inicio=1, ano_inicio=2026
        )
    )
    session.commit()
    session.refresh(rec)
    return rec


# --- 1. Categorização ---------------------------------------------------------


def test_uma_unica_chamada_categoriza_todas_as_linhas_com_dedup(
    as_user, users, categorizador
):
    categorizador["resposta"].update(
        {0: "Salário", 1: "Alimentação", 2: "Transporte", 3: "Outros"}
    )

    enriquecido = _enriquecimento(_post(as_user(users[0])))

    # EFICIÊNCIA: uma chamada só, nunca uma por linha.
    assert len(categorizador["chamadas"]) == 1

    # DEDUP: 5 linhas categorizáveis (2 receitas + 3 débitos), mas os dois
    # débitos de descrição idêntica viram UM pedido -> 4 pedidos.
    pedidos = categorizador["chamadas"][0]["pedidos"]
    assert len(pedidos) == 4
    assert [p.tipo for p in pedidos] == ["receita", "despesa", "despesa", "receita"]

    por_indice = {e["indice"]: e["categoria_sugerida"] for e in enriquecido}
    assert por_indice[0] == "Salário"
    assert por_indice[1] == "Alimentação"
    assert por_indice[2] == "Alimentação"  # a linha deduplicada recebe a mesma
    assert por_indice[3] is None  # pagamento_fatura não tem categoria
    assert por_indice[4] == "Transporte"
    assert por_indice[5] == "Outros"


def test_categoria_inventada_pelo_modelo_cai_em_outros(as_user, users, categorizador):
    categorizador["resposta"].update({1: "Criptomoedas Exóticas"})

    enriquecido = _enriquecimento(_post(as_user(users[0])))

    assert enriquecido[1]["categoria_sugerida"] == "Outros"


def test_categoria_de_despesa_sugerida_para_receita_cai_em_outros(
    as_user, users, categorizador
):
    """O guarda-corpo usa a lista do TIPO da linha: receita nunca vira 'Alimentação'."""
    categorizador["resposta"].update({0: "Alimentação"})

    enriquecido = _enriquecimento(_post(as_user(users[0])))

    assert enriquecido[0]["categoria_sugerida"] == "Outros"


def test_falha_da_categorizacao_nao_derruba_o_preview(as_user, users, monkeypatch):
    """Degradação graciosa: a extração (cara) já foi paga — o preview sobrevive."""

    def _falha(pedidos, nomes_despesa, nomes_receita):
        raise HTTPException(status_code=503, detail="indisponível")

    monkeypatch.setattr(gemini, "categorizar_linhas", _falha)

    resp = _post(as_user(users[0]))

    assert resp.status_code == 200
    body = resp.json()
    assert body["reconciliacao"]["bate"] is True  # o resto do preview intacto
    assert all(e["categoria_sugerida"] is None for e in body["enriquecimento"])


def test_categoria_customizada_do_usuario_entra_na_lista_enviada(
    as_user, users, session, categorizador
):
    from app.models.category import CategoriaCustomizada

    session.add(
        CategoriaCustomizada(usuario_id=users[0].id, nome="Padaria", tipo="despesa")
    )
    session.commit()
    categorizador["resposta"].update({1: "Padaria"})

    enriquecido = _enriquecimento(_post(as_user(users[0])))

    assert "Padaria" in categorizador["chamadas"][0]["nomes_despesa"]
    assert enriquecido[1]["categoria_sugerida"] == "Padaria"


# --- 2. Casamento pagamento -> fatura -----------------------------------------


def test_match_unico_quando_ha_um_cartao_do_banco_com_fatura(
    as_user, users, session, categorizador
):
    cartao = _cartao(session, users[0], "Nubank")
    _fatura(session, users[0], cartao, "200.00")

    proposta = _enriquecimento(_post(as_user(users[0])))[3]["fatura_proposta"]

    assert proposta["status"] == "match_unico"
    (candidata,) = proposta["candidatas"]
    assert candidata["cartao_id"] == cartao.id
    assert (candidata["fatura_mes"], candidata["fatura_ano"]) == (6, 2026)
    assert candidata["total_fatura"] == "200.00"
    assert candidata["diferenca"] == "0.00"
    assert candidata["valor_bate"] is True
    assert candidata["ja_paga"] is False


def test_ambiguo_com_dois_cartoes_do_mesmo_banco(as_user, users, session, categorizador):
    """Valor exato ORDENA, mas não colapsa a ambiguidade — o usuário decide."""
    exato = _cartao(session, users[0], "Nubank")
    outro = _cartao(session, users[0], "Nubank Ultravioleta")
    _fatura(session, users[0], exato, "200.00")
    _fatura(session, users[0], outro, "150.00")

    proposta = _enriquecimento(_post(as_user(users[0])))[3]["fatura_proposta"]

    assert proposta["status"] == "ambiguo"
    assert [c["cartao_id"] for c in proposta["candidatas"]] == [exato.id, outro.id]
    assert [c["valor_bate"] for c in proposta["candidatas"]] == [True, False]
    assert proposta["candidatas"][1]["diferenca"] == "50.00"


def test_sem_match_quando_a_fatura_nao_foi_importada(
    as_user, users, session, categorizador
):
    _cartao(session, users[0], "Nubank")  # cartão existe, fatura não

    proposta = _enriquecimento(_post(as_user(users[0])))[3]["fatura_proposta"]

    assert proposta["status"] == "sem_match"
    assert proposta["candidatas"] == []
    assert "importe a fatura" in proposta["motivo"].lower()


def test_sem_match_quando_nenhum_cartao_e_do_emissor_citado(
    as_user, users, session, categorizador
):
    cartao = _cartao(session, users[0], "Itaú Click")
    _fatura(session, users[0], cartao, "200.00")

    proposta = _enriquecimento(_post(as_user(users[0])))[3]["fatura_proposta"]

    assert proposta["status"] == "sem_match"
    assert "Nubank" in proposta["motivo"]


def test_fatura_ja_paga_e_sinalizada(as_user, users, session, categorizador):
    cartao = _cartao(session, users[0], "Nubank")
    _fatura(session, users[0], cartao, "200.00")
    session.add(
        PagamentoFatura(
            usuario_id=users[0].id,
            cartao_id=cartao.id,
            fatura_mes=6,
            fatura_ano=2026,
            pago=True,
            valor_pago=Decimal("200.00"),
        )
    )
    session.commit()

    proposta = _enriquecimento(_post(as_user(users[0])))[3]["fatura_proposta"]

    assert proposta["candidatas"][0]["ja_paga"] is True


def test_pagamento_fora_da_janela_de_vencimento_nao_casa(
    as_user, users, session, categorizador
):
    """Cartão que vence dia 28: pagamento em 10/06 está a 18 dias -> sem_match."""
    cartao = _cartao(session, users[0], "Nubank", dia_vencimento=28)
    _fatura(session, users[0], cartao, "200.00")

    proposta = _enriquecimento(_post(as_user(users[0])))[3]["fatura_proposta"]

    assert proposta["status"] == "sem_match"


# --- 3. Receita x recorrência -------------------------------------------------


def test_receita_que_casa_recorrencia_recebe_flag(as_user, users, session, categorizador):
    rec = _recorrencia_salario(session, users[0])

    enriquecido = _enriquecimento(_post(as_user(users[0])))

    salario = enriquecido[0]
    assert salario["provavel_recorrencia"] is True
    assert salario["recorrencia_casada"]["id"] == str(rec.id)
    assert salario["recorrencia_casada"]["valor_vigente"] == "5000.00"
    assert (
        salario["recorrencia_casada"]["competencia_mes"],
        salario["recorrencia_casada"]["competencia_ano"],
    ) == (6, 2026)


def test_receita_que_nao_casa_fica_sem_flag(as_user, users, session, categorizador):
    _recorrencia_salario(session, users[0])

    enriquecido = _enriquecimento(_post(as_user(users[0])))

    # Pix de R$ 777,00 em 18/06 — nem valor nem dia batem com o salário
    assert enriquecido[5]["provavel_recorrencia"] is False
    assert enriquecido[5]["recorrencia_casada"] is None


def test_sem_recorrencias_nenhuma_receita_e_flagada(as_user, users, categorizador):
    enriquecido = _enriquecimento(_post(as_user(users[0])))

    assert all(e["provavel_recorrencia"] is False for e in enriquecido)


# --- Isolamento e statelessness ----------------------------------------------


def test_isolamento_cartoes_e_recorrencias_de_outro_usuario_nao_vazam(
    as_user, users, session, categorizador
):
    cartao_b = _cartao(session, users[1], "Nubank")
    _fatura(session, users[1], cartao_b, "200.00")
    _recorrencia_salario(session, users[1])

    enriquecido = _enriquecimento(_post(as_user(users[0])))

    assert enriquecido[3]["fatura_proposta"]["status"] == "sem_match"
    assert enriquecido[0]["provavel_recorrencia"] is False


def _contagens(session) -> dict[str, int]:
    return {
        tabela.name: session.execute(
            sa_select(func.count()).select_from(tabela)
        ).scalar()
        for tabela in SQLModel.metadata.sorted_tables
    }


def test_preview_nao_escreve_nada_no_banco(as_user, users, session, categorizador):
    """STATELESS: nem add, nem flush, nem commit no caminho do preview.

    Cinto e suspensórios: um listener de `before_flush` (que só dispara com
    estado pendente de verdade) E a contagem de linhas de TODAS as tabelas.
    """
    cartao = _cartao(session, users[0], "Nubank")
    _fatura(session, users[0], cartao, "200.00")
    _recorrencia_salario(session, users[0])

    escritas: list[tuple] = []

    def _guarda(sessao, flush_context, instances):
        escritas.append(
            (list(sessao.new), list(sessao.dirty), list(sessao.deleted))
        )

    antes = _contagens(session)
    event.listen(session, "before_flush", _guarda)
    try:
        resp = _post(as_user(users[0]))
    finally:
        event.remove(session, "before_flush", _guarda)

    assert resp.status_code == 200
    assert escritas == [], f"o preview tentou escrever: {escritas}"
    assert _contagens(session) == antes
