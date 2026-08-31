"""#40 — o rabo " CATEGORIA.CIDADE" do emissor e a DUPLICAÇÃO DE PARCELA.

A Itaú imprime a categoria do lojista e a cidade coladas na descrição
("SUPERMERCADOSBERG ALIMENTAÇÃO.SAOPAULO") e a extração leva esse rabo de forma
NÃO-DETERMINÍSTICA — medido em 4 execuções do MESMO PDF, 2 de cada lado.

O dano não é cosmético: a identidade de dedup de parcelada usa a descrição.
Julho extrai limpo na parcela 1/2 e agosto extrai sujo na 2/2 → as identidades
não casam → agosto cria um cronograma NOVO → a parcela é contada em DOBRO na
projeção. Silencioso (cada fatura, isolada, reconcilia) e ~moeda a cada import.

Este arquivo prova o cenário nas DUAS ordens, prova a idempotência que sustenta
o fix, e prova que a limpeza não come descrição legítima.

SQLite in-memory isolado do conftest. Money via Decimal(str(x)).
"""

import copy
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.transaction import Transacao
from app.services.import_fatura.descricao import chave_descricao, limpar_rabo_do_emissor
from tests.fixtures.faturas_validadas import NUBANK

# O lojista como as DUAS extrações do mesmo PDF o devolvem.
LIMPA = "SUPERMERCADOSBERG"
COM_RABO = "SUPERMERCADOSBERG ALIMENTAÇÃO.SAOPAULO"


def _fatura(mes, ano, vencimento, indice, descricao):
    """NUBANK reancorada, com a parcelada 3x no `indice` do mês e a descrição
    do lojista como aquela extração a devolveu. Mesmo total e mesmo valor →
    MESMA origem, então é a MESMA compra."""
    f = copy.deepcopy(NUBANK)
    f["competencia"] = {"mes": mes, "ano": ano}
    f["vencimento"] = vencimento
    f["transacoes"][0]["descricao"] = descricao
    f["transacoes"][0]["parcela"] = {"indice": indice, "total": 3}
    return f


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


def _commit(client, cartao_id, fatura):
    return client.post(
        "/import/fatura/commit",
        json={"cartao_id": cartao_id, "fatura": fatura, "competencias_pagas": []},
    )


def _assert_um_cronograma_so(session):
    """UMA parcelada, 3 parcelas — não duas de 3 (a duplicação silenciosa)."""
    parceladas = session.exec(
        select(Transacao).where(Transacao.parcelado == True)  # noqa: E712
    ).all()
    assert len(parceladas) == 1, "a MESMA compra virou dois cronogramas"
    assert session.exec(select(Parcela)).all().__len__() == 3


# --- O cenário real: a extração muda de ideia entre um mês e outro -----------


def test_limpa_depois_com_rabo_nao_duplica(session, as_user, users, cartao):
    """MUTAÇÃO-ALVO: `chave_descricao` sem `limpar_rabo_do_emissor` → agosto não
    reconhece a compra de julho, cria outro cronograma e a projeção conta a
    parcela duas vezes."""
    client = as_user(users[0])

    r1 = _commit(client, cartao.id, _fatura(7, 2026, "2026-07-13", 1, LIMPA))
    assert r1.status_code == 200
    assert r1.json()["parcelas_criadas"] == 3

    r2 = _commit(client, cartao.id, _fatura(8, 2026, "2026-08-13", 2, COM_RABO))
    assert r2.status_code == 200
    assert r2.json()["parceladas_deduplicadas"] == 1
    assert r2.json()["parcelas_criadas"] == 0

    _assert_um_cronograma_so(session)


def test_com_rabo_depois_limpa_nao_duplica(session, as_user, users, cartao):
    """A ordem inversa tem que dar o MESMO resultado: qual das duas extrações
    veio primeiro é sorteio, não informação."""
    client = as_user(users[0])

    assert _commit(client, cartao.id, _fatura(7, 2026, "2026-07-13", 1, COM_RABO)).status_code == 200

    r2 = _commit(client, cartao.id, _fatura(8, 2026, "2026-08-13", 2, LIMPA))
    assert r2.status_code == 200
    assert r2.json()["parceladas_deduplicadas"] == 1

    _assert_um_cronograma_so(session)


def test_descricao_gravada_continua_a_extraida(session, as_user, users, cartao):
    """A limpeza vale só onde a descrição vira CHAVE. O que o usuário vê na
    lista de transações é o texto extraído, intacto — este fix não toca display
    (nem o prompt)."""
    _commit(as_user(users[0]), cartao.id, _fatura(7, 2026, "2026-07-13", 1, COM_RABO))

    parcelada = session.exec(
        select(Transacao).where(Transacao.parcelado == True)  # noqa: E712
    ).one()
    assert parcelada.descricao == COM_RABO


def test_lojistas_diferentes_continuam_diferentes(session, as_user, users, cartao):
    """A limpeza não pode COLAPSAR compras distintas: identidade que casa demais
    faz o import PULAR uma compra de verdade — pior que duplicar (a duplicada o
    usuário apaga; a que não entrou ele não sabe que faltou).

    O cenário isola a DESCRIÇÃO: índices 1 e 2 em meses consecutivos dão a MESMA
    competência de origem, e total e valor já são iguais — então a descrição é a
    única coisa que separa as duas identidades. Sem isso o teste passa por
    acidente (origens diferentes bastariam) e não prova nada.
    """
    client = as_user(users[0])

    assert _commit(
        client, cartao.id, _fatura(7, 2026, "2026-07-13", 1, "MERCADO ALFA ALIMENTAÇÃO.SAOPAULO")
    ).status_code == 200

    r2 = _commit(
        client, cartao.id, _fatura(8, 2026, "2026-08-13", 2, "MERCADO BETA ALIMENTAÇÃO.SAOPAULO")
    )
    assert r2.status_code == 200
    assert r2.json()["parceladas_deduplicadas"] == 0
    assert r2.json()["parcelas_criadas"] == 3

    parceladas = session.exec(
        select(Transacao).where(Transacao.parcelado == True)  # noqa: E712
    ).all()
    assert len(parceladas) == 2


# --- A propriedade que sustenta o fix ----------------------------------------


@pytest.mark.parametrize(
    "bruta,esperada",
    [
        ("SUPERMERCADOSBERG", "SUPERMERCADOSBERG"),
        ("SUPERMERCADOSBERG ALIMENTAÇÃO.SAOPAULO", "SUPERMERCADOSBERG"),
        ("PostoDe VEÍCULOS.SAOPAULO", "PostoDe"),
        ("IFD *KAMIAFITLTDA ALIMENTAÇÃO.SAOPAULO", "IFD *KAMIAFITLTDA"),
        ("SONDAJACANA-CT ALIMENTAÇÃO.", "SONDAJACANA-CT"),  # cidade vazia
        ("Sirio-LibanesDigital TURISMOEENTRETENIM.SAOCAETANOD", "Sirio-LibanesDigital"),
        ("MP*MANOELPEREIRA VESTUÁRIO.SoPaulo", "MP*MANOELPEREIRA"),  # cidade CamelCase
        ("ZIG*FESTAJUNINASANTA EDUCAÇÃO.SAOPAULO", "ZIG*FESTAJUNINASANTA"),
    ],
)
def test_remove_o_rabo_do_emissor(bruta, esperada):
    assert limpar_rabo_do_emissor(bruta) == esperada


@pytest.mark.parametrize(
    "descricao",
    [
        "Pagamento efetuado",
        "Pagamento efetuado em 01/07/2026",
        "Saldo restante da fatura anterior",
        "LOJA S.A",  # sigla curta: o mínimo de 4 letras a protege
        "VICEMALOTERIASLTDA SaoPaulo",  # LIMITE CONHECIDO: sem ponto, não mexe
        "IFD*40827151VICTORMA",
        "Vexora",
    ],
)
def test_nao_come_descricao_legitima(descricao):
    """Cortar de menos deixa uma duplicata (visível, corrigível). Cortar de mais
    colapsa compras distintas (invisível). O erro tem que cair para o lado
    conservador."""
    assert limpar_rabo_do_emissor(descricao) == descricao


@pytest.mark.parametrize(
    "descricao",
    [
        "SUPERMERCADOSBERG",
        "SUPERMERCADOSBERG ALIMENTAÇÃO.SAOPAULO",
        "SONDAJACANA-CT ALIMENTAÇÃO.",
        "Pagamento efetuado",
        "VICEMALOTERIASLTDA SaoPaulo",
    ],
)
def test_limpeza_e_idempotente(descricao):
    """É a propriedade que faz "remover-se-houver" funcionar sob as DUAS
    extrações — e a razão de o fix morar no servidor em vez de num campo novo
    do schema, que pediria a separação sem GARANTIR a descrição limpa.
    """
    uma = limpar_rabo_do_emissor(descricao)
    assert limpar_rabo_do_emissor(uma) == uma
    assert chave_descricao(descricao) == chave_descricao(uma)


def test_chave_absorve_caixa_espaco_e_rabo_juntos():
    """A chave canônica é UMA: o drift de caixa/espaço que já era tratado, mais
    o rabo do emissor, resolvidos no mesmo lugar."""
    assert (
        chave_descricao("  supermercadosberg   ALIMENTAÇÃO.SAOPAULO ")
        == chave_descricao("SUPERMERCADOSBERG")
    )


# --- O mesmo drift na camada 1 da auto-categoria ------------------------------


def test_historico_casa_apesar_do_rabo(session, as_user, users, cartao):
    """Mesma causa, dano mais fraco: sem a limpeza, o que o usuário categorizou
    como "SONDAJACANA" não seria reconhecido em "SONDAJACANA ALIMENTAÇÃO.SAOPAULO"
    e a camada 1 perderia o aprendizado justamente onde ele foi ensinado."""
    import datetime as dt

    for _ in range(2):
        session.add(
            Transacao(
                usuario_id=users[0].id, tipo="despesa", data=dt.date(2026, 5, 1),
                descricao="SONDAJACANA", valor=Decimal("10.00"),
                categoria="Pets", forma_pagamento="Crédito",
            )
        )
    session.commit()

    fatura = _fatura(7, 2026, "2026-07-13", 1, "SONDAJACANA ALIMENTAÇÃO.SAOPAULO")
    del fatura["transacoes"][0]["parcela"]
    assert _commit(as_user(users[0]), cartao.id, fatura).status_code == 200

    importada = session.exec(
        select(Transacao).where(Transacao.origem == "importacao")
    ).first()
    assert importada.categoria == "Pets"
