"""Batch 8 / T-17 — GET /cards/{id}/invoices agregado no banco (GROUP BY).

A reescrita (SUM/COUNT GROUP BY fatura) deve dar valores IDÊNTICOS aos da
varredura anterior: total por fatura, total_itens (parcelas + avulsas) e
total_parcelas_pagas (só parcelas). Parcela cancelada e avulsa não-despesa
ficam de fora; parcelas+avulsas na MESMA fatura somam juntas.
"""

import datetime as dt
from decimal import Decimal

from app.models.card import Cartao
from app.models.installment import Parcela
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
        assert f3["total_parcelas_pagas"] == 1

        f4 = por_chave[(4, 2026)]
        assert Decimal(str(f4["total"])) == Decimal("200.00")
        assert f4["total_itens"] == 1
        assert f4["total_parcelas_pagas"] == 0

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
