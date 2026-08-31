"""Dedup de parcela ENTRE importações (MULTI-FATURA).

Importar meses consecutivos relista a parcelada em andamento (julho 4/7,
agosto 5/7). O guard do lote é por (cartão, competência) e NÃO pega isso —
o dedup de parcela pega, pela IDENTIDADE ESTÁVEL
(cartão, descrição normalizada, total, origem implícita, valor da parcela),
onde origem = âncora − (indice − 1) = competência da parcela nº 1.

O skip decide contra um SNAPSHOT das identidades JÁ importadas (imports
ANTERIORES), tirado antes de qualquer insert — nunca contra o que ESTE request
cria. Consequência exigida: duas linhas idênticas na MESMA fatura são duas
compras e ambas materializam.

SQLite in-memory isolado do conftest — NUNCA o banco do .env. Money via
Decimal(str(x)) (SQLite coage Numeric por float).
"""

import copy
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.pagamento_fatura import PagamentoFatura
from app.models.transaction import Transacao
from tests.fixtures.faturas_validadas import NUBANK

# transacoes[0] da NUBANK é a Vexora parcelada (4/7, 120.00). As demais são
# avulsas/pagamento/ajuste.


def _fatura(mes, ano, vencimento, indice):
    """Uma NUBANK reancorada noutra competência, com a Vexora no `indice`
    daquele mês (mesmo total 7 e mesmo valor → mesma origem em abril)."""
    f = copy.deepcopy(NUBANK)
    f["competencia"] = {"mes": mes, "ano": ano}
    f["vencimento"] = vencimento
    f["transacoes"][0]["parcela"] = {"indice": indice, "total": 7}
    return f


# Julho 4/7 e agosto 5/7 — a MESMA Vexora, origem abril nas duas.
JULHO = _fatura(7, 2026, "2026-07-13", 4)
AGOSTO = _fatura(8, 2026, "2026-08-13", 5)


@pytest.fixture()
def cartao(session, users):
    c = Cartao(
        usuario_id=users[0].id, nome="Nubank", tipo="Crédito",
        dia_vencimento=13, dia_fechamento=6, mes_offset_vencimento=1,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def _commit(client, cartao_id, fatura, competencias_pagas=None):
    return client.post(
        "/import/fatura/commit",
        json={
            "cartao_id": cartao_id,
            "fatura": fatura,
            "competencias_pagas": competencias_pagas or [],
        },
    )


def _parceladas(session):
    return session.exec(
        select(Transacao).where(Transacao.parcelado == True)  # noqa: E712
    ).all()


def _avulsas(session):
    return session.exec(
        select(Transacao).where(Transacao.parcelado == False)  # noqa: E712
    ).all()


def _assert_uma_vexora_completa(session):
    """Uma transação parcelada, 7 parcelas no total (não 14), avulsas dos dois
    meses presentes — o estado-alvo do onboarding multi-mês."""
    parceladas = _parceladas(session)
    assert len(parceladas) == 1
    assert parceladas[0].total_parcelas == 7
    parcelas = session.exec(select(Parcela)).all()
    assert len(parcelas) == 7
    competencias = sorted((p.fatura_mes, p.fatura_ano) for p in parcelas)
    assert competencias == [
        (4, 2026), (5, 2026), (6, 2026), (7, 2026),
        (8, 2026), (9, 2026), (10, 2026),
    ]
    meses_avulsa = {(a.fatura_mes, a.fatura_ano) for a in _avulsas(session)}
    assert (7, 2026) in meses_avulsa and (8, 2026) in meses_avulsa
    assert len(_avulsas(session)) == 8  # 4 de julho + 4 de agosto


# --- Não duplica a parcelada em andamento (as duas ordens) -------------------

def test_julho_depois_agosto_nao_duplica(session, as_user, users, cartao):
    client = as_user(users[0])
    r1 = _commit(client, cartao.id, JULHO)
    assert r1.status_code == 200
    assert r1.json()["parcelas_criadas"] == 7

    r2 = _commit(client, cartao.id, AGOSTO)
    assert r2.status_code == 200
    # MUTAÇÃO-alvo: sem o guard de dedup (ou afrouxando a identidade), agosto
    # criaria OUTRA Vexora com 7 parcelas → _assert_uma_vexora_completa
    # falharia (2 parceladas, 14 parcelas).
    assert r2.json()["parceladas_deduplicadas"] == 1
    assert r2.json()["parcelas_criadas"] == 0  # a parcelada pulou; só avulsas

    _assert_uma_vexora_completa(session)


def test_agosto_depois_julho_mesmo_resultado(session, as_user, users, cartao):
    client = as_user(users[0])
    assert _commit(client, cartao.id, AGOSTO).status_code == 200

    r2 = _commit(client, cartao.id, JULHO)
    assert r2.status_code == 200
    assert r2.json()["parceladas_deduplicadas"] == 1

    _assert_uma_vexora_completa(session)


# --- Desempate por valor (colisão desc/total/origem, valores distintos) ------

def _fatura_duas_vexora(mes, ano, vencimento, indice):
    """Duas parceladas colidindo em desc/total/origem, mas valores distintos
    (120.00 e 200.00) — compras genuinamente diferentes."""
    f = _fatura(mes, ano, vencimento, indice)
    segunda = copy.deepcopy(f["transacoes"][0])
    segunda["valor_brl"] = "200.00"
    f["transacoes"].append(segunda)
    return f


def test_desempate_por_valor_mantem_duas(session, as_user, users, cartao):
    client = as_user(users[0])
    r1 = _commit(client, cartao.id, _fatura_duas_vexora(7, 2026, "2026-07-13", 4))
    assert r1.status_code == 200
    parceladas = _parceladas(session)
    assert len(parceladas) == 2  # valores distintos → duas transações
    valores = sorted(Decimal(str(p.valor)) for p in parceladas)
    assert valores == [Decimal("840.00"), Decimal("1400.00")]  # 120.00×7, 200×7

    # Cross-fatura: agosto relista as DUAS (5/7) → o valor desempata cada uma
    # contra a sua no snapshot → ambas dedupam, nenhuma nova.
    r2 = _commit(client, cartao.id, _fatura_duas_vexora(8, 2026, "2026-08-13", 5))
    assert r2.status_code == 200
    assert r2.json()["parceladas_deduplicadas"] == 2
    assert len(_parceladas(session)) == 2


# --- Snapshot: duas idênticas na MESMA fatura materializam as DUAS -----------

def test_duas_identicas_mesma_fatura_materializam_ambas(
    session, as_user, users, cartao
):
    client = as_user(users[0])
    fatura = copy.deepcopy(JULHO)
    # Vexora IDÊNTICA (mesma desc/total/origem/VALOR) repetida na MESMA fatura.
    fatura["transacoes"].append(copy.deepcopy(fatura["transacoes"][0]))

    r = _commit(client, cartao.id, fatura)
    assert r.status_code == 200
    # MUTAÇÃO-alvo: decidir o skip contra a QUERY VIVA (em vez do snapshot
    # congelado antes dos inserts) faria a 2ª linha enxergar a 1ª já flushada e
    # PULAR → 1 só transação. São duas compras: contar a mais é corrigível na
    # revisão; contar a menos é invisível.
    assert r.json()["parceladas_deduplicadas"] == 0
    assert len(_parceladas(session)) == 2
    assert len(session.exec(select(Parcela)).all()) == 14


# --- Confirmação de pagamento de passada cuja parcelada foi PULADA -----------

def test_pagamento_passada_com_parcelada_pulada_aceita(
    session, as_user, users, cartao
):
    client = as_user(users[0])
    # Julho materializa a Vexora: parcelas em 04..10/2026 (05/2026 SÓ existe
    # por ela — não há avulsa em maio).
    assert _commit(client, cartao.id, JULHO).status_code == 200

    # Agosto DEDUPA a Vexora (não recria 05/2026 neste request). Ainda assim,
    # marcar 05/2026 paga é aceito: a competência tem lançamento EXISTENTE
    # (< âncora 08) de julho. A regra antiga ("só o que ESTE import criou")
    # rejeitaria — é a MUTAÇÃO-alvo do gate de pagamento.
    r = _commit(
        client, cartao.id, AGOSTO, competencias_pagas=[{"mes": 5, "ano": 2026}]
    )
    assert r.status_code == 200
    assert r.json()["parceladas_deduplicadas"] == 1
    assert r.json()["faturas_marcadas_pagas"] == 1

    pag = session.exec(
        select(PagamentoFatura).where(PagamentoFatura.fatura_mes == 5)
    ).one()
    assert pag.pago is True
    assert pag.data_pagamento is None  # histórico: nunca data falsa


def test_pagamento_competencia_sem_lancamento_rejeita(session, as_user, users, cartao):
    client = as_user(users[0])
    # 01/2020 não tem lançamento nenhum deste cartão → não é marcável (nem com
    # dedup afrouxando nada): fatura arbitrária continua barrada.
    r = _commit(
        client, cartao.id, JULHO, competencias_pagas=[{"mes": 1, "ano": 2020}]
    )
    assert r.status_code == 422
    assert "não faz parte" in r.json()["detail"]
    assert session.exec(select(Transacao)).all() == []  # atômico: desfaz tudo
