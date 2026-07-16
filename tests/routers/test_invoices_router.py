"""Batch 8 / T-17 — GET /cards/{id}/invoices agregado no banco (GROUP BY).

A reescrita (SUM/COUNT GROUP BY fatura) deve dar valores IDÊNTICOS aos da
varredura anterior: total por fatura e total_itens (parcelas + avulsas).
Parcela cancelada e avulsa não-despesa ficam de fora; parcelas+avulsas na
MESMA fatura somam juntas.
"""

import datetime as dt
from decimal import Decimal

from sqlmodel import select

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.pagamento_fatura import PagamentoFatura
from app.models.transaction import Transacao


def _card(session, usuario_id):
    card = Cartao(
        usuario_id=usuario_id,
        nome="Nubank",
        tipo="Crédito",
        dia_fechamento=3,
        dia_vencimento=10,
        mes_offset_vencimento=1,
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def _parcela(session, usuario_id, cartao_id, transacao_id, mes, ano, valor, pago=False, cancelado=False):
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
            pago=pago,
            cancelado=cancelado,
        )
    )


def _avulsa(session, usuario_id, cartao_id, mes, ano, valor, tipo="despesa"):
    session.add(
        Transacao(
            usuario_id=usuario_id,
            tipo=tipo,
            data=dt.date(ano, mes, 5),
            descricao="a",
            valor=Decimal(valor),
            categoria="C",
            cartao_id=cartao_id,
            parcelado=False,
            fatura_mes=mes,
            fatura_ano=ano,
        )
    )


class TestT17InvoicesAgregacao:
    def test_totais_por_fatura_identicos(self, session, users, as_user):
        user_a, _ = users
        card = _card(session, user_a.id)

        # Fatura (3, 2026): parcela paga 100 + parcela não-paga 50 + avulsa 30
        _parcela(session, user_a.id, card.id, 1, 3, 2026, "100.00", pago=True)
        _parcela(session, user_a.id, card.id, 2, 3, 2026, "50.00", pago=False)
        _avulsa(session, user_a.id, card.id, 3, 2026, "30.00")
        # Fatura (4, 2026): uma parcela 200
        _parcela(session, user_a.id, card.id, 3, 4, 2026, "200.00", pago=False)
        # Excluídos: parcela cancelada e avulsa que é receita
        _parcela(session, user_a.id, card.id, 4, 3, 2026, "999.00", cancelado=True)
        _avulsa(session, user_a.id, card.id, 3, 2026, "999.00", tipo="receita")
        session.commit()

        faturas = as_user(user_a).get(f"/cards/{card.id}/invoices").json()
        por_chave = {(f["mes"], f["ano"]): f for f in faturas}

        # Ordenação (ano, mes) desc
        assert [(f["mes"], f["ano"]) for f in faturas] == [(4, 2026), (3, 2026)]

        f3 = por_chave[(3, 2026)]
        assert Decimal(str(f3["total"])) == Decimal("180.00")  # 100 + 50 + 30
        assert f3["total_itens"] == 3

        f4 = por_chave[(4, 2026)]
        assert Decimal(str(f4["total"])) == Decimal("200.00")
        assert f4["total_itens"] == 1

    def test_cartao_sem_movimento_retorna_lista_vazia(self, session, users, as_user):
        user_a, _ = users
        card = _card(session, user_a.id)
        assert as_user(user_a).get(f"/cards/{card.id}/invoices").json() == []


def _card_venc(session, usuario_id, nome, dia_vencimento):
    """Cartão com dia_vencimento explícito (para exercitar ordenação/next-due)."""
    card = Cartao(
        usuario_id=usuario_id,
        nome=nome,
        tipo="Crédito",
        dia_fechamento=1,
        dia_vencimento=dia_vencimento,
        mes_offset_vencimento=0,  # competência == mês de vencimento direto
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


class TestInvoicesByCompetencia:
    """Lente 3d — GET /invoices/{ano}/{mes}: faturas de N cartões num mês."""

    def test_dois_cartoes_uma_linha_cada_e_total_geral(self, session, users, as_user):
        user_a, _ = users
        itau = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        nubank = _card_venc(session, user_a.id, "Nubank", dia_vencimento=5)
        # Dez/2026: Itaú 2000 (parcela) + Nubank 1400 (avulsa)
        _parcela(session, user_a.id, itau.id, 1, 12, 2026, "2000.00")
        _avulsa(session, user_a.id, nubank.id, 12, 2026, "1400.00")
        session.commit()

        body = as_user(user_a).get("/invoices/2026/12").json()

        assert body["ano"] == 2026 and body["mes"] == 12
        assert Decimal(str(body["total_geral"])) == Decimal("3400.00")
        # Ordenação por data_vencimento asc: Nubank (dia 5) antes de Itaú (dia 10)
        assert [f["cartao_nome"] for f in body["faturas"]] == ["Nubank", "Itaú"]
        nu, it = body["faturas"]
        assert Decimal(str(nu["total"])) == Decimal("1400.00")
        assert nu["data_vencimento"] == "2026-12-05"
        assert Decimal(str(it["total"])) == Decimal("2000.00")
        assert it["data_vencimento"] == "2026-12-10"

    def test_cartao_sem_fatura_no_mes_nao_aparece(self, session, users, as_user):
        user_a, _ = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        _parcela(session, user_a.id, card.id, 1, 3, 2026, "100.00")  # só em mar
        session.commit()

        body = as_user(user_a).get("/invoices/2026/4").json()
        assert body["faturas"] == []
        assert Decimal(str(body["total_geral"])) == Decimal("0.00")

    def test_competencia_vazia(self, session, users, as_user):
        user_a, _ = users
        _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)  # sem lançamentos
        body = as_user(user_a).get("/invoices/2026/6").json()
        assert body == {"ano": 2026, "mes": 6, "total_geral": "0.00", "faturas": []}

    def test_parcela_cancelada_nao_conta_avulsa_conta(self, session, users, as_user):
        user_a, _ = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        _parcela(session, user_a.id, card.id, 1, 8, 2026, "500.00", cancelado=True)
        _avulsa(session, user_a.id, card.id, 8, 2026, "70.00")
        session.commit()

        body = as_user(user_a).get("/invoices/2026/8").json()
        assert len(body["faturas"]) == 1
        assert Decimal(str(body["faturas"][0]["total"])) == Decimal("70.00")
        assert Decimal(str(body["total_geral"])) == Decimal("70.00")

    def test_consistencia_cruzada_com_endpoint_por_cartao(self, session, users, as_user):
        user_a, _ = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        _parcela(session, user_a.id, card.id, 1, 9, 2026, "300.00")
        _avulsa(session, user_a.id, card.id, 9, 2026, "45.00")
        session.commit()

        client = as_user(user_a)
        comp = client.get("/invoices/2026/9").json()
        detalhe = client.get(f"/cards/{card.id}/invoices/2026/9").json()

        item = next(f for f in comp["faturas"] if f["cartao_id"] == card.id)
        assert Decimal(str(item["total"])) == Decimal(str(detalhe["total"]))
        assert item["data_vencimento"] == detalhe["data_vencimento"]

    def test_mes_ano_invalidos_422(self, session, users, as_user):
        user_a, _ = users
        client = as_user(user_a)
        assert client.get("/invoices/2026/13").status_code == 422
        assert client.get("/invoices/2026/0").status_code == 422
        assert client.get("/invoices/1999/6").status_code == 422

    def test_isolamento_entre_usuarios(self, session, users, as_user):
        user_a, user_b = users
        card_a = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        _parcela(session, user_a.id, card_a.id, 1, 10, 2026, "800.00")
        session.commit()

        body_b = as_user(user_b).get("/invoices/2026/10").json()
        assert body_b["faturas"] == []
        assert Decimal(str(body_b["total_geral"])) == Decimal("0.00")


class TestNextDueInvoice:
    """GET /invoices/next-due — mês em que a tela 3d abre (próxima a vencer)."""

    def test_futuro_puro(self, session, users, as_user, mocker):
        mocker.patch("app.routers.invoices.hoje", return_value=dt.date(2026, 7, 15))
        user_a, _ = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        _parcela(session, user_a.id, card.id, 1, 12, 2026, "100.00")
        session.commit()

        body = as_user(user_a).get("/invoices/next-due").json()
        assert (body["ano"], body["mes"]) == (2026, 12)

    def test_corrente_ainda_a_vencer(self, session, users, as_user, mocker):
        mocker.patch("app.routers.invoices.hoje", return_value=dt.date(2026, 12, 5))
        user_a, _ = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)  # vence 10/12
        _parcela(session, user_a.id, card.id, 1, 12, 2026, "100.00")
        session.commit()

        body = as_user(user_a).get("/invoices/next-due").json()
        assert (body["ano"], body["mes"]) == (2026, 12)

    def test_corrente_todo_vencido_pula_para_futuro(self, session, users, as_user, mocker):
        mocker.patch("app.routers.invoices.hoje", return_value=dt.date(2026, 12, 15))
        user_a, _ = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)  # 10/12 já passou
        _parcela(session, user_a.id, card.id, 1, 12, 2026, "100.00")
        _parcela(session, user_a.id, card.id, 2, 1, 2027, "100.00")
        session.commit()

        body = as_user(user_a).get("/invoices/next-due").json()
        assert (body["ano"], body["mes"]) == (2027, 1)

    def test_sem_faturas_fallback_corrente(self, session, users, as_user, mocker):
        mocker.patch("app.routers.invoices.hoje", return_value=dt.date(2026, 7, 15))
        user_a, _ = users
        _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)  # sem lançamentos
        session.commit()

        body = as_user(user_a).get("/invoices/next-due").json()
        assert (body["ano"], body["mes"]) == (2026, 7)


HOJE_L2 = dt.date(2026, 7, 15)


class TestPagamentoFatura:
    """Leva 2 — PUT /invoices/{cartao_id}/{ano}/{mes}/pagamento: confirmar/negar
    o pagamento de uma fatura FECHADA e EXISTENTE; upsert idempotente e
    reversível; o a_pagar do /monthly reage (e só ele). hoje = 15/07/2026."""

    def _clock(self, mocker, data=HOJE_L2):
        # O endpoint lê app.routers.invoices.hoje; o a_pagar do /monthly lê
        # app.services.estatisticas.hoje — o MESMO instante nos dois.
        return (
            mocker.patch("app.routers.invoices.hoje", return_value=data),
            mocker.patch("app.services.estatisticas.hoje", return_value=data),
        )

    def _a_pagar(self, client, mes, ano):
        body = client.get("/statistics/monthly", params={"mes": mes, "ano": ano}).json()
        return Decimal(str(body["a_pagar"]))

    def test_confirmar_fatura_fechada_some_do_a_pagar(self, session, users, as_user, mocker):
        self._clock(mocker)
        user_a, _ = users
        # offset 0 + fechamento dia 1: competência jul fechou em 1/jul < hoje.
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        _parcela(session, user_a.id, card.id, 1, 7, 2026, "100.00")
        _avulsa(session, user_a.id, card.id, 7, 2026, "30.00")  # avulsa segue a fatura
        session.commit()

        client = as_user(user_a)
        assert self._a_pagar(client, 7, 2026) == Decimal("130.00")

        resp = client.put(f"/invoices/{card.id}/2026/7/pagamento", json={"pago": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["pago"] is True
        assert body["data_pagamento"] == "2026-07-15"
        assert body["status"] == "paga"

        # Parcela E avulsa saem juntas — o pagamento é da FATURA.
        assert self._a_pagar(client, 7, 2026) == Decimal("0.00")

    def test_desmarcar_volta_ao_a_pagar(self, session, users, as_user, mocker):
        self._clock(mocker)
        user_a, _ = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        _parcela(session, user_a.id, card.id, 1, 7, 2026, "100.00")
        session.commit()

        client = as_user(user_a)
        client.put(f"/invoices/{card.id}/2026/7/pagamento", json={"pago": True})
        assert self._a_pagar(client, 7, 2026) == Decimal("0.00")

        resp = client.put(f"/invoices/{card.id}/2026/7/pagamento", json={"pago": False})
        assert resp.status_code == 200
        assert resp.json()["pago"] is False
        assert resp.json()["data_pagamento"] is None
        assert self._a_pagar(client, 7, 2026) == Decimal("100.00")

        # O registro FICA (pago=False = "não paguei" — reversível), não é apagado.
        pagamento = session.exec(select(PagamentoFatura)).one()
        assert pagamento.pago is False

    def test_fatura_aberta_422(self, session, users, as_user, mocker):
        self._clock(mocker)
        user_a, _ = users
        # Competência ago/2026 fecha em 1/ago — hoje (15/07) ainda não passou.
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        _parcela(session, user_a.id, card.id, 1, 8, 2026, "100.00")
        session.commit()

        resp = as_user(user_a).put(
            f"/invoices/{card.id}/2026/8/pagamento", json={"pago": True}
        )
        assert resp.status_code == 422
        assert "aberta" in resp.json()["detail"]

    def test_competencia_sem_lancamentos_422(self, session, users, as_user, mocker):
        self._clock(mocker)
        user_a, _ = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        # Fatura de mar/2026 (fechada) não existe — nada foi lançado nela.
        _parcela(session, user_a.id, card.id, 1, 7, 2026, "100.00")
        session.commit()

        resp = as_user(user_a).put(
            f"/invoices/{card.id}/2026/3/pagamento", json={"pago": True}
        )
        assert resp.status_code == 422
        assert "Não há fatura" in resp.json()["detail"]

    def test_pagamento_antecipado_permitido(self, session, users, as_user, mocker):
        self._clock(mocker)
        user_a, _ = users
        # Fechada (1/jul < hoje) mas vencimento 20/07 ainda no futuro.
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=20)
        _parcela(session, user_a.id, card.id, 1, 7, 2026, "100.00")
        session.commit()

        resp = as_user(user_a).put(
            f"/invoices/{card.id}/2026/7/pagamento", json={"pago": True}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "paga"

    def test_idempotente_preserva_data_pagamento(self, session, users, as_user, mocker):
        clock_router, _ = self._clock(mocker)
        user_a, _ = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        _parcela(session, user_a.id, card.id, 1, 7, 2026, "100.00")
        session.commit()

        client = as_user(user_a)
        primeiro = client.put(f"/invoices/{card.id}/2026/7/pagamento", json={"pago": True})
        assert primeiro.json()["data_pagamento"] == "2026-07-15"

        clock_router.return_value = dt.date(2026, 7, 20)  # re-PUT dias depois
        segundo = client.put(f"/invoices/{card.id}/2026/7/pagamento", json={"pago": True})
        assert segundo.status_code == 200
        assert segundo.json()["data_pagamento"] == "2026-07-15"  # transição manda

        # E continua UM registro só (upsert pela chave natural).
        assert len(session.exec(select(PagamentoFatura)).all()) == 1

    def test_borda_do_fechamento(self, session, users, as_user, mocker):
        # _card: dia_fechamento=3, offset=1 → competência ago fecha em 3/jul.
        # No PRÓPRIO dia do fechamento a compra ainda entra → aberta (422);
        # no dia seguinte, fechada → confirmável.
        clock_router, _ = self._clock(mocker, dt.date(2026, 7, 3))
        user_a, _ = users
        card = _card(session, user_a.id)
        _parcela(session, user_a.id, card.id, 1, 8, 2026, "100.00")
        session.commit()

        client = as_user(user_a)
        url = f"/invoices/{card.id}/2026/8/pagamento"
        assert client.put(url, json={"pago": True}).status_code == 422

        clock_router.return_value = dt.date(2026, 7, 4)
        assert client.put(url, json={"pago": True}).status_code == 200

    def test_cartao_sem_dia_fechamento_fecha_no_fim_do_mes_base(
        self, session, users, as_user, mocker
    ):
        clock_router, _ = self._clock(mocker, dt.date(2026, 7, 31))
        user_a, _ = users
        card = Cartao(
            usuario_id=user_a.id, nome="Inter", tipo="Crédito",
            dia_fechamento=None, dia_vencimento=10, mes_offset_vencimento=1,
        )
        session.add(card)
        session.commit()
        session.refresh(card)
        # Competência ago (base = jul, sem dia de fechamento) → fecha em 31/07.
        _parcela(session, user_a.id, card.id, 1, 8, 2026, "100.00")
        session.commit()

        client = as_user(user_a)
        url = f"/invoices/{card.id}/2026/8/pagamento"
        assert client.put(url, json={"pago": True}).status_code == 422  # 31/07: aberta

        clock_router.return_value = dt.date(2026, 8, 1)
        assert client.put(url, json={"pago": True}).status_code == 200

    def test_cartao_de_outro_usuario_404(self, session, users, as_user, mocker):
        self._clock(mocker)
        user_a, user_b = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        _parcela(session, user_a.id, card.id, 1, 7, 2026, "100.00")
        session.commit()

        resp = as_user(user_b).put(
            f"/invoices/{card.id}/2026/7/pagamento", json={"pago": True}
        )
        assert resp.status_code == 404

    def test_mes_ano_invalidos_422(self, session, users, as_user, mocker):
        self._clock(mocker)
        user_a, _ = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=10)
        client = as_user(user_a)
        assert client.put(f"/invoices/{card.id}/2026/13/pagamento", json={"pago": True}).status_code == 422
        assert client.put(f"/invoices/{card.id}/1999/6/pagamento", json={"pago": True}).status_code == 422


class TestStatusFatura:
    """Leva 2 — o `status` derivado (paga/aberta/a_vencer/atrasada) exposto nos
    3 endpoints de fatura. hoje = 15/07/2026; cartão offset 0, fecha dia 1,
    vence dia 20: jun = atrasada (venceu 20/06), jul = a_vencer (vence 20/07),
    ago = aberta (fecha 1/ago)."""

    def _setup(self, session, users, mocker):
        mocker.patch("app.routers.invoices.hoje", return_value=HOJE_L2)
        user_a, _ = users
        card = _card_venc(session, user_a.id, "Itaú", dia_vencimento=20)
        for mes in (6, 7, 8):
            _parcela(session, user_a.id, card.id, mes, mes, 2026, "100.00")
        session.commit()
        return user_a, card

    def test_status_na_lista_por_cartao(self, session, users, as_user, mocker):
        user_a, card = self._setup(session, users, mocker)
        faturas = as_user(user_a).get(f"/cards/{card.id}/invoices").json()
        status = {(f["mes"], f["ano"]): f["status"] for f in faturas}
        assert status == {
            (6, 2026): "atrasada",
            (7, 2026): "a_vencer",
            (8, 2026): "aberta",
        }

    def test_status_no_detalhe_e_vira_paga_ao_confirmar(self, session, users, as_user, mocker):
        user_a, card = self._setup(session, users, mocker)
        client = as_user(user_a)

        assert client.get(f"/cards/{card.id}/invoices/2026/6").json()["status"] == "atrasada"
        client.put(f"/invoices/{card.id}/2026/6/pagamento", json={"pago": True})
        assert client.get(f"/cards/{card.id}/invoices/2026/6").json()["status"] == "paga"

    def test_status_na_lente_por_competencia(self, session, users, as_user, mocker):
        user_a, card = self._setup(session, users, mocker)
        client = as_user(user_a)

        body = client.get("/invoices/2026/6").json()
        assert body["faturas"][0]["status"] == "atrasada"

        client.put(f"/invoices/{card.id}/2026/6/pagamento", json={"pago": True})
        body = client.get("/invoices/2026/6").json()
        assert body["faturas"][0]["status"] == "paga"

    def test_registro_pago_false_equivale_a_ausencia(self, session, users, as_user, mocker):
        # "não paguei" explícito não muda o status derivado (atrasada segue).
        user_a, card = self._setup(session, users, mocker)
        client = as_user(user_a)
        client.put(f"/invoices/{card.id}/2026/6/pagamento", json={"pago": False})
        assert client.get(f"/cards/{card.id}/invoices/2026/6").json()["status"] == "atrasada"

    def test_competencia_sem_lancamento_e_vazia_nao_atrasada(self, session, users, as_user, mocker):
        # Competência SEM nenhum lançamento (mai/2026 — o cartão só tem jun/jul/ago):
        # detalhe da fatura vem "vazia" (neutro), NUNCA "atrasada", mesmo já vencida.
        user_a, card = self._setup(session, users, mocker)
        body = as_user(user_a).get(f"/cards/{card.id}/invoices/2026/5").json()
        assert body["status"] == "vazia"
        assert Decimal(str(body["total"])) == Decimal("0.00")

    def test_competencia_com_lancamento_vencida_continua_atrasada(self, session, users, as_user, mocker):
        # Guarda de regressão: fatura COM lançamento, vencida e não paga, segue
        # "atrasada" (o fix de fatura vazia não regrediu o caso legítimo).
        user_a, card = self._setup(session, users, mocker)
        assert as_user(user_a).get(f"/cards/{card.id}/invoices/2026/6").json()["status"] == "atrasada"
