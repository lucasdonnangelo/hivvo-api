"""#9 — compra retroativa em fatura paga: cobertura (valor_pago) + paga_parcial.

O furo: compra caía num mês cuja fatura já estava paga e o status seguia
"paga" com "A pagar" 0 — a descoberta sumia. Agora PagamentoFatura guarda
`valor_pago` (total no instante da confirmação) e o status é derivado por
COBERTURA (services/faturas.status_fatura): valor_pago >= total atual →
"paga"; menor → "paga_parcial", e a DESCOBERTA (total − valor_pago) entra no
a_pagar (/statistics/monthly e /projection). Tudo derivado: mudar a
composição muda o status sem nenhum write de pagamento.

CONCORDÂNCIA status↔a_pagar (fonte única da composição): com uma única
fatura no mês, a contribuição dela pro a_pagar é função do status —
não confirmada → total; paga → 0; paga_parcial → total − valor_pago.
O teste de concordância percorre os três estados afirmando a aritmética
exata — remover a descoberta do a_pagar OU afrouxar a regra de cobertura
quebra uma das asserções (mutação morta por construção).

hoje congelado em 15/07/2026. Geometria: cartão offset 0, fecha dia 1,
vence dia 20 → competência jul/2026 fechada (1/jul) e a vencer (20/07).
SQLite in-memory isolado do conftest — NUNCA o banco do .env.
"""

import datetime as dt
import importlib.util
import sqlite3
from decimal import Decimal
from pathlib import Path

from sqlmodel import select

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.pagamento_fatura import PagamentoFatura
from app.models.transaction import Transacao
from app.services.faturas import status_fatura

HOJE = dt.date(2026, 7, 15)


def _q(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"))


def _card(session, usuario_id, dia_fechamento=1, dia_vencimento=20, offset=0):
    card = Cartao(
        usuario_id=usuario_id,
        nome="Itaú",
        tipo="Crédito",
        dia_fechamento=dia_fechamento,
        dia_vencimento=dia_vencimento,
        mes_offset_vencimento=offset,
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def _parcela(session, usuario_id, cartao_id, transacao_id, mes, ano, valor):
    session.add(
        Parcela(
            usuario_id=usuario_id,
            transacao_id=transacao_id,
            numero_parcela=1,
            total_parcelas=1,
            valor_parcela=Decimal(valor),
            data_vencimento=dt.date(ano, mes, 10),
            descricao="p",
            categoria="C",
            cartao_id=cartao_id,
            fatura_mes=mes,
            fatura_ano=ano,
        )
    )


def _avulsa(session, usuario_id, cartao_id, mes, ano, valor, descricao="a"):
    session.add(
        Transacao(
            usuario_id=usuario_id,
            tipo="despesa",
            data=dt.date(ano, mes, 5),
            descricao=descricao,
            valor=Decimal(valor),
            categoria="C",
            cartao_id=cartao_id,
            parcelado=False,
            fatura_mes=mes,
            fatura_ano=ano,
        )
    )


class TestPagaParcial:
    """Router-level, ponta a ponta: PUT de pagamento + lentes de fatura +
    a_pagar das estatísticas reagindo à cobertura."""

    def _clock(self, mocker, data=HOJE):
        # O PUT/lentes leem app.routers.invoices.hoje; o a_pagar do /monthly
        # e a projeção leem app.services.estatisticas.hoje — MESMO instante.
        return (
            mocker.patch("app.routers.invoices.hoje", return_value=data),
            mocker.patch("app.services.estatisticas.hoje", return_value=data),
        )

    def _a_pagar(self, client, mes=7, ano=2026):
        body = client.get("/statistics/monthly", params={"mes": mes, "ano": ano}).json()
        return _q(body["a_pagar"])

    def _fatura_jul_paga(self, session, users, as_user, mocker):
        """Fatura jul/2026 (parcela 100 + avulsa 30) confirmada paga."""
        self._clock(mocker)
        user_a, _ = users
        card = _card(session, user_a.id)
        _parcela(session, user_a.id, card.id, 1, 7, 2026, "100.00")
        _avulsa(session, user_a.id, card.id, 7, 2026, "30.00")
        session.commit()
        client = as_user(user_a)
        resp = client.put(f"/invoices/{card.id}/2026/7/pagamento", json={"pago": True})
        assert resp.status_code == 200
        return user_a, card, client, resp

    def _retroativa(self, session, usuario_id, cartao_id, valor="50.00"):
        """Compra nova caindo na fatura jul/2026 JÁ paga (o furo #9)."""
        _avulsa(session, usuario_id, cartao_id, 7, 2026, valor, descricao="retro")
        session.commit()

    # ---- Estado coberto: paga de verdade -----------------------------------

    def test_paga_coberta_valor_pago_e_a_pagar_zero(self, session, users, as_user, mocker):
        _, card, client, resp = self._fatura_jul_paga(session, users, as_user, mocker)

        assert resp.json()["status"] == "paga"
        assert _q(resp.json()["valor_pago"]) == Decimal("130.00")  # snapshot do total
        assert client.get(f"/cards/{card.id}/invoices/2026/7").json()["status"] == "paga"
        assert self._a_pagar(client) == Decimal("0.00")

    # ---- O furo: compra retroativa em fatura paga ---------------------------

    def test_compra_retroativa_vira_paga_parcial_nas_tres_lentes(
        self, session, users, as_user, mocker
    ):
        user_a, card, client, _ = self._fatura_jul_paga(session, users, as_user, mocker)
        self._retroativa(session, user_a.id, card.id)

        # Detalhe, lista por cartão e lente por competência — todas derivam.
        assert client.get(f"/cards/{card.id}/invoices/2026/7").json()["status"] == "paga_parcial"
        lista = client.get(f"/cards/{card.id}/invoices").json()
        assert {(f["mes"], f["ano"]): f["status"] for f in lista}[(7, 2026)] == "paga_parcial"
        comp = client.get("/invoices/2026/7").json()
        assert comp["faturas"][0]["status"] == "paga_parcial"

        # A descoberta EXATA (total 180 − valor_pago 130), não o total cheio
        # nem zero — é esta asserção que mata as mutações (tirar a descoberta
        # do a_pagar → 0.00; afrouxar a cobertura → status volta "paga").
        assert self._a_pagar(client) == Decimal("50.00")

    def test_re_marcar_paga_atualiza_cobertura_e_zera_a_pagar(
        self, session, users, as_user, mocker
    ):
        user_a, card, client, _ = self._fatura_jul_paga(session, users, as_user, mocker)
        self._retroativa(session, user_a.id, card.id)

        # Re-PUT pago=True (registro JÁ pago — não é transição): valor_pago
        # tem que atualizar pro novo total, senão a fatura nunca volta a "paga".
        resp = client.put(f"/invoices/{card.id}/2026/7/pagamento", json={"pago": True})
        assert resp.json()["status"] == "paga"
        assert _q(resp.json()["valor_pago"]) == Decimal("180.00")
        assert self._a_pagar(client) == Decimal("0.00")
        # E continua UM registro (upsert pela chave natural).
        assert len(session.exec(select(PagamentoFatura)).all()) == 1

    # ---- Tudo derivado: a composição manda, nenhum write --------------------

    def test_remover_compra_retroativa_volta_paga_sozinha(
        self, session, users, as_user, mocker
    ):
        user_a, card, client, _ = self._fatura_jul_paga(session, users, as_user, mocker)
        self._retroativa(session, user_a.id, card.id)
        assert client.get(f"/cards/{card.id}/invoices/2026/7").json()["status"] == "paga_parcial"

        retro = session.exec(select(Transacao).where(Transacao.descricao == "retro")).one()
        session.delete(retro)
        session.commit()

        # valor_pago (130) volta a cobrir o total (130) → "paga", sem PUT.
        assert client.get(f"/cards/{card.id}/invoices/2026/7").json()["status"] == "paga"
        assert self._a_pagar(client) == Decimal("0.00")

    def test_remover_alem_do_pago_nao_gera_descoberta_negativa(
        self, session, users, as_user, mocker
    ):
        user_a, card, client, _ = self._fatura_jul_paga(session, users, as_user, mocker)
        original = session.exec(select(Transacao).where(Transacao.descricao == "a")).one()
        session.delete(original)
        session.commit()

        # total (100) < valor_pago (130): coberta com sobra — "paga", e a
        # descoberta nunca fica negativa (não abate outras faturas do mês).
        assert client.get(f"/cards/{card.id}/invoices/2026/7").json()["status"] == "paga"
        assert self._a_pagar(client) == Decimal("0.00")

    def test_desmarcar_limpa_valor_pago(self, session, users, as_user, mocker):
        _, card, client, _ = self._fatura_jul_paga(session, users, as_user, mocker)
        resp = client.put(f"/invoices/{card.id}/2026/7/pagamento", json={"pago": False})
        assert resp.json()["valor_pago"] is None
        assert session.exec(select(PagamentoFatura)).one().valor_pago is None

    # ---- Concordância status ↔ a_pagar (fonte única da composição) ----------

    def test_concordancia_status_a_pagar_nos_tres_estados(
        self, session, users, as_user, mocker
    ):
        """Com UMA fatura no mês, a contribuição dela pro a_pagar é função do
        status — as duas lentes derivam da MESMA composição, e a aritmética
        (total do detalhe × valor_pago do PUT × a_pagar do monthly) fecha
        exata nos três estados."""
        self._clock(mocker)
        user_a, _ = users
        card = _card(session, user_a.id)
        _parcela(session, user_a.id, card.id, 1, 7, 2026, "100.00")
        _avulsa(session, user_a.id, card.id, 7, 2026, "30.00")
        session.commit()
        client = as_user(user_a)

        def _detalhe():
            body = client.get(f"/cards/{card.id}/invoices/2026/7").json()
            return body["status"], _q(body["total"])

        # Estado 1 — não confirmada: contribui o TOTAL.
        status, total = _detalhe()
        assert status == "a_vencer"
        assert self._a_pagar(client) == total == Decimal("130.00")

        # Estado 2 — paga (coberta): contribui 0.
        put = client.put(f"/invoices/{card.id}/2026/7/pagamento", json={"pago": True})
        valor_pago = _q(put.json()["valor_pago"])
        status, total = _detalhe()
        assert status == "paga"
        assert valor_pago == total
        assert self._a_pagar(client) == Decimal("0.00")

        # Estado 3 — paga_parcial: contribui EXATAMENTE (total − valor_pago).
        self._retroativa(session, user_a.id, card.id)
        status, total = _detalhe()
        assert status == "paga_parcial"
        assert total > valor_pago
        assert self._a_pagar(client) == total - valor_pago == Decimal("50.00")

    # ---- Projeção (série anual) reflete a descoberta no mês certo -----------

    def test_projection_reflete_descoberta_no_mes_da_fatura(
        self, session, users, as_user, mocker
    ):
        self._clock(mocker)
        user_a, _ = users
        # fech. 3 / offset 1: competência ago/2026 fechou em 3/jul (< hoje
        # 15/jul) → confirmável; ago é mês FUTURO → entra na série.
        card = _card(session, user_a.id, dia_fechamento=3, dia_vencimento=10, offset=1)
        _parcela(session, user_a.id, card.id, 1, 8, 2026, "100.00")
        session.commit()
        client = as_user(user_a)
        client.put(f"/invoices/{card.id}/2026/8/pagamento", json={"pago": True})
        _avulsa(session, user_a.id, card.id, 8, 2026, "40.00", descricao="retro")
        session.commit()

        series = client.get("/statistics/projection").json()["series"]
        ago = next(m for m in series if (m["mes"], m["ano"]) == (8, 2026))
        assert _q(ago["a_pagar"]) == Decimal("40.00")  # só a descoberta


# ---- Backfill da migration (SQL real, bordas de composição) ------------------

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic" / "versions" / "d9e2f7a4c1b8_pagamento_fatura_valor_pago.py"
)


def _backfill_sql() -> str:
    spec = importlib.util.spec_from_file_location("mig_valor_pago", _MIGRATION_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.BACKFILL_VALOR_PAGO_SQL


class TestBackfillValorPago:
    """Executa o MESMO texto SQL da migration (BACKFILL_VALOR_PAGO_SQL) num
    SQLite descartável com o schema pós-add_column/pré-backfill — as linhas
    pago=True nascem com valor_pago NULL, estado que o CHECK proíbe no schema
    final (por isso não dá para semear via modelo)."""

    _DDL = """
        CREATE TABLE parcelas (
            usuario_id INTEGER, cartao_id INTEGER, fatura_mes INTEGER,
            fatura_ano INTEGER, valor_parcela NUMERIC, cancelado BOOLEAN
        );
        CREATE TABLE transacoes (
            usuario_id INTEGER, cartao_id INTEGER, fatura_mes INTEGER,
            fatura_ano INTEGER, valor NUMERIC, parcelado BOOLEAN, tipo TEXT
        );
        CREATE TABLE pagamentos_fatura (
            usuario_id INTEGER, cartao_id INTEGER, fatura_mes INTEGER,
            fatura_ano INTEGER, pago BOOLEAN, valor_pago NUMERIC
        );
    """

    def test_backfill_composicao_e_bordas(self):
        con = sqlite3.connect(":memory:")
        con.executescript(self._DDL)

        con.executemany(
            "INSERT INTO parcelas VALUES (?,?,?,?,?,?)",
            [
                (1, 1, 7, 2026, 100.0, 0),   # fatura A: conta
                (1, 1, 7, 2026, 50.0, 0),    # fatura A: conta
                (1, 1, 7, 2026, 999.0, 1),   # cancelada → FORA
                (1, 1, 6, 2026, 777.0, 0),   # outra competência (fatura B)
                (2, 1, 7, 2026, 444.0, 0),   # outro usuário → FORA da A
                (1, 4, 4, 2026, 25.0, 0),    # fatura E (só parcelas)
                (1, 4, 4, 2026, 25.0, 0),    # fatura E
            ],
        )
        con.executemany(
            "INSERT INTO transacoes VALUES (?,?,?,?,?,?,?)",
            [
                (1, 1, 7, 2026, 30.0, 0, "despesa"),   # fatura A: conta
                (1, 1, 7, 2026, 20.0, 0, "despesa"),   # fatura A: conta
                (1, 1, 7, 2026, 999.0, 0, "receita"),  # receita → FORA
                (1, 1, 7, 2026, 999.0, 1, "despesa"),  # pai parcelada → FORA
                (1, 2, 7, 2026, 555.0, 0, "despesa"),  # outro cartão → FORA da A
                (1, 3, 5, 2026, 40.0, 0, "despesa"),   # fatura D (só avulsas)
                (1, 3, 5, 2026, 10.0, 0, "despesa"),   # fatura D
            ],
        )
        con.executemany(
            "INSERT INTO pagamentos_fatura VALUES (?,?,?,?,?,NULL)",
            [
                (1, 1, 7, 2026, 1),  # A: parcelas 150 + avulsas 50 → 200
                (1, 1, 6, 2026, 0),  # B: pago=False → fica NULL
                (2, 9, 7, 2026, 1),  # C: paga sem lançamento → 0 (COALESCE)
                (1, 3, 5, 2026, 1),  # D: só a perna avulsa → 50
                (1, 4, 4, 2026, 1),  # E: só a perna parcela → 50
            ],
        )

        con.execute(_backfill_sql())

        resultado = {
            (u, c, m, a): vp
            for u, c, m, a, vp in con.execute(
                "SELECT usuario_id, cartao_id, fatura_mes, fatura_ano, valor_pago"
                " FROM pagamentos_fatura"
            )
        }
        assert resultado[(1, 1, 7, 2026)] == 200.0  # parcelas+avulsas, bordas fora
        assert resultado[(1, 1, 6, 2026)] is None   # pago=False intocada
        assert resultado[(2, 9, 7, 2026)] == 0.0    # sem lançamento → 0
        assert resultado[(1, 3, 5, 2026)] == 50.0   # só avulsas
        assert resultado[(1, 4, 4, 2026)] == 50.0   # só parcelas
        con.close()

    def test_backfill_resulta_em_status_paga(self):
        # valor_pago = total atual (o que o backfill grava) ⇒ cobertura exata
        # ⇒ nenhuma fatura existente nasce parcial; a régua é estrita — um
        # centavo de compra retroativa já vira paga_parcial.
        card = Cartao(
            usuario_id=1, nome="Itaú", tipo="Crédito",
            dia_fechamento=1, dia_vencimento=20, mes_offset_vencimento=0,
        )
        pag = PagamentoFatura(
            usuario_id=1, cartao_id=1, fatura_mes=7, fatura_ano=2026,
            pago=True, valor_pago=Decimal("200.00"),
        )
        assert status_fatura(card, 7, 2026, pag, HOJE, Decimal("200.00")) == "paga"
        assert status_fatura(card, 7, 2026, pag, HOJE, Decimal("200.01")) == "paga_parcial"
