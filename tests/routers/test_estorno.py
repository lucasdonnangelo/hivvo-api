"""Estorno — netting no consumo, no fluxo e na composição de fatura.

tipo="estorno" com valor POSITIVO (CHECK valor>0 vale): as agregações de
consumo SUBTRAEM (Σ despesa − Σ estorno). Regras de clamp:
- totais (_agregar) são LÍQUIDOS sem clamp (o saldo precisa do real);
- breakdowns de gráfico (donut, por-categoria, por-cartão) clampam célula
  net-negativa em 0;
- a_pagar clampa POR FATURA (cartao_id) — estorno abate só na fatura dele,
  fatura net-negativa nunca "cria crédito" contra outra (régua do #9).

Cada agregação tem asserção com o valor LÍQUIDO esperado — remover a
subtração do estorno de qualquer uma (kernel ou SUM(CASE)) quebra o teste
correspondente (mutação de over-count).

SQLite in-memory isolado do conftest — NUNCA o banco do .env. hoje congelado
em 15/07/2026 (marcações de estatísticas e status de fatura).
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.models.card import Cartao
from app.models.pagamento_fatura import PagamentoFatura
from app.models.transaction import Transacao
from app.services.faturas import totais_fatura_por_cartao_ano

HOJE = dt.date(2026, 7, 15)


def _q(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


@pytest.fixture(autouse=True)
def clock(mocker):
    mocker.patch("app.services.estatisticas.hoje", return_value=HOJE)
    mocker.patch("app.routers.invoices.hoje", return_value=HOJE)


def _add_cartao(session, uid, nome="Nubank"):
    cartao = Cartao(
        usuario_id=uid, nome=nome, tipo="Crédito",
        dia_vencimento=13, dia_fechamento=6, mes_offset_vencimento=1,
    )
    session.add(cartao)
    session.commit()
    session.refresh(cartao)
    return cartao


def _add_fatura_tx(session, uid, cartao_id, tipo="despesa", valor="100.00",
                   mes=7, ano=2026, data=None, categoria="Alimentação",
                   descricao=None):
    """Avulsa de cartão (despesa OU estorno) já faturada em (mes, ano)."""
    session.add(
        Transacao(
            usuario_id=uid, tipo=tipo, data=data or dt.date(2026, 7, 5),
            descricao=descricao or tipo, valor=Decimal(valor),
            categoria=categoria, forma_pagamento="Crédito",
            cartao_id=cartao_id, fatura_mes=mes, fatura_ano=ano,
        )
    )
    session.commit()


def _monthly(as_user, user, mes=7, ano=2026):
    return as_user(user).get(
        "/statistics/monthly", params={"mes": mes, "ano": ano}
    ).json()


# --- Consumo mensal + donut (mutação: _agregar / _categorias) ----------------

class TestConsumoNetting:
    def test_estorno_abate_consumo_e_fluxo_do_mes(self, session, users, as_user):
        # 100 despesa + 30 estorno (mesma fatura, mesmo mês da data) → 70 em
        # AMBAS as visões. MUTAÇÃO: sem a subtração em _agregar, viria 100.
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00")
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00", data=dt.date(2026, 7, 10))

        body = _monthly(as_user, users[0])
        assert _q(body["consumo"]["despesas"]) == Decimal("70.00")
        assert _q(body["despesas"]) == Decimal("70.00")  # fluxo (Fonte 2) neta
        # Donuts (fluxo e consumo) netam POR categoria — Σ categorias == total
        for chave in ("categorias", "categorias_consumo"):
            assert [(c["categoria"], _q(c["total"])) for c in body[chave]] == [
                ("Alimentação", Decimal("70.00"))
            ]

    def test_categoria_negativa_clampa_em_zero_no_donut(self, session, users, as_user):
        # Roupas: 20 despesa − 50 estorno = −30 → clampa em 0; o total segue
        # LÍQUIDO (70), aceitando Σ categorias != total nessa borda.
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00")
        _add_fatura_tx(session, users[0].id, cartao.id, valor="20.00",
                       categoria="Roupas")
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="50.00", categoria="Roupas")

        body = _monthly(as_user, users[0])
        assert _q(body["consumo"]["despesas"]) == Decimal("70.00")
        cats = {c["categoria"]: _q(c["total"]) for c in body["categorias_consumo"]}
        assert cats == {"Alimentação": Decimal("100.00"), "Roupas": Decimal("0.00")}

    def test_so_estorno_total_liquido_negativo_e_donut_vazio(
        self, session, users, as_user
    ):
        # Total é líquido SEM clamp (−30 honesto no saldo); donut com total
        # não-positivo fica vazio.
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00")

        body = _monthly(as_user, users[0])
        assert _q(body["consumo"]["despesas"]) == Decimal("-30.00")
        assert _q(body["despesas"]) == Decimal("-30.00")
        assert body["categorias_consumo"] == []
        assert body["categorias"] == []


# --- Fluxo por competência + anual + projeção --------------------------------

class TestFluxoCompetencia:
    def test_estorno_neta_na_competencia_da_fatura_nao_da_data(
        self, session, users, as_user
    ):
        # Compra e estorno em JULHO (data), faturados em AGOSTO: o fluxo neta
        # em agosto; o consumo neta em julho (pela data). Zero drift entre as
        # visões — cada uma neta no eixo dela.
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00",
                       mes=8, data=dt.date(2026, 7, 20))
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00", mes=8, data=dt.date(2026, 7, 25))

        agosto = _monthly(as_user, users[0], mes=8)
        assert _q(agosto["despesas"]) == Decimal("70.00")
        assert _q(agosto["consumo"]["despesas"]) == Decimal("0.00")

        julho = _monthly(as_user, users[0], mes=7)
        assert _q(julho["consumo"]["despesas"]) == Decimal("70.00")
        assert _q(julho["despesas"]) == Decimal("0.00")

    def test_yearly_neta(self, session, users, as_user):
        # MUTAÇÃO: sem o estorno na Fonte 2 anual (ou sem a subtração no
        # kernel), agosto viria 100 e o total anual idem.
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00", mes=8)
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00", mes=8)

        body = as_user(users[0]).get("/statistics/yearly", params={"ano": 2026}).json()
        assert _q(body["despesas_total"]) == Decimal("70.00")
        agosto = next(m for m in body["meses"] if m["mes"] == 8)
        assert _q(agosto["despesas"]) == Decimal("70.00")

    def test_projection_neta_despesas_e_a_pagar(self, session, users, as_user):
        # Fatura FUTURA (8/2026, primeiro mês com fluxo após o corrente):
        # a série da projeção mostra o líquido nas despesas E no a_pagar.
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00", mes=8)
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00", mes=8)

        body = as_user(users[0]).get(
            "/statistics/projection", params={"meses": 1}
        ).json()
        serie = body["series"][0]
        assert (serie["mes"], serie["ano"]) == (8, 2026)
        assert _q(serie["despesas"]) == Decimal("70.00")
        assert _q(serie["a_pagar"]) == Decimal("70.00")

    def test_totais_fatura_por_cartao_ano_neta(self, session, users):
        # Fonte única anual da descoberta (#9): SUM líquido por (mes, cartão).
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00", mes=8)
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00", mes=8)

        totais = totais_fatura_por_cartao_ano(session, users[0].id, 2026)
        assert _q(totais[(8, cartao.id)]) == Decimal("70.00")


# --- A pagar: líquido POR FATURA, clamp em 0 ---------------------------------

class TestAPagarPorFatura:
    def test_multi_cartao_fatura_negativa_nao_abate_a_outra(
        self, session, users, as_user
    ):
        # Cartão A: 30 − 50 = −20 → clampa 0. Cartão B: 50. A pagar = 50.
        # MUTAÇÃO-alvo: clamp no AGREGADO mensal daria max(30+50−50, 0) = 30 —
        # subcontaria o A pagar (a mentira que o #9 matou).
        cartao_a = _add_cartao(session, users[0].id, nome="A")
        cartao_b = _add_cartao(session, users[0].id, nome="B")
        _add_fatura_tx(session, users[0].id, cartao_a.id, valor="30.00")
        _add_fatura_tx(session, users[0].id, cartao_a.id, tipo="estorno",
                       valor="50.00")
        _add_fatura_tx(session, users[0].id, cartao_b.id, valor="50.00")

        body = _monthly(as_user, users[0])
        assert _q(body["a_pagar"]) == Decimal("50.00")

    def test_fatura_unica_net_negativa_clampa_zero(self, session, users, as_user):
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="30.00")
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="50.00")

        body = _monthly(as_user, users[0])
        assert _q(body["a_pagar"]) == Decimal("0.00")
        assert _q(body["despesas"]) == Decimal("-20.00")  # total segue líquido


# --- Endpoints de fatura: composição líquida + cobertura (#9) ----------------

class TestFaturaEndpoints:
    def test_detalhe_lista_estorno_e_total_liquido(self, session, users, as_user):
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00")
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00", descricao="Estorno de compra")

        body = as_user(users[0]).get(f"/cards/{cartao.id}/invoices/2026/7").json()
        assert _q(body["total"]) == Decimal("70.00")
        tipos = {a["descricao"]: a["tipo"] for a in body["avulsas"]}
        assert tipos == {"despesa": "despesa", "Estorno de compra": "estorno"}
        estorno = next(a for a in body["avulsas"] if a["tipo"] == "estorno")
        assert _q(estorno["valor"]) == Decimal("30.00")  # positivo no payload

    def test_lista_de_faturas_total_liquido(self, session, users, as_user):
        # MUTAÇÃO: o SUM inline do list_invoices sem o CASE viria 130.
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00")
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00")

        body = as_user(users[0]).get(f"/cards/{cartao.id}/invoices").json()
        assert len(body) == 1
        assert _q(body[0]["total"]) == Decimal("70.00")
        assert body[0]["total_itens"] == 2

    def test_lente_3d_total_liquido(self, session, users, as_user):
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00")
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00")

        body = as_user(users[0]).get("/invoices/2026/7").json()
        assert _q(body["total_geral"]) == Decimal("70.00")
        assert _q(body["faturas"][0]["total"]) == Decimal("70.00")

    def test_estorno_apos_paga_mantem_paga_por_cobertura(
        self, session, users, as_user
    ):
        # Paga com valor_pago=100; estorno posterior baixa o total pra 70 →
        # cobertura (#9): valor_pago >= total, segue "paga", descoberta 0.
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00")
        session.add(
            PagamentoFatura(
                usuario_id=users[0].id, cartao_id=cartao.id, fatura_mes=7,
                fatura_ano=2026, pago=True, valor_pago=Decimal("100.00"),
                data_pagamento=HOJE,
            )
        )
        session.commit()
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00")

        body = as_user(users[0]).get(f"/cards/{cartao.id}/invoices/2026/7").json()
        assert body["status"] == "paga"
        assert _q(body["total"]) == Decimal("70.00")
        assert _q(_monthly(as_user, users[0])["a_pagar"]) == Decimal("0.00")

    def test_descoberta_usa_total_liquido(self, session, users, as_user):
        # Paga o líquido (70 = 100 − 30); compra retroativa de 40 → total 110,
        # descoberta = 110 − 70 = 40 (paga_parcial). MUTAÇÃO: sem o netting na
        # composição, o total viria 140 e a descoberta 70.
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00")
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00")
        session.add(
            PagamentoFatura(
                usuario_id=users[0].id, cartao_id=cartao.id, fatura_mes=7,
                fatura_ano=2026, pago=True, valor_pago=Decimal("70.00"),
                data_pagamento=HOJE,
            )
        )
        session.commit()
        _add_fatura_tx(session, users[0].id, cartao.id, valor="40.00",
                       descricao="retroativa")

        body = as_user(users[0]).get(f"/cards/{cartao.id}/invoices/2026/7").json()
        assert body["status"] == "paga_parcial"
        assert _q(_monthly(as_user, users[0])["a_pagar"]) == Decimal("40.00")


# --- Spending-by-card / evolução por categoria / highlights ------------------

class TestBreakdownsConsumo:
    def test_spending_by_card_neta_no_cartao_do_estorno(
        self, session, users, as_user
    ):
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00")
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00")
        session.add(  # à vista sem cartão — bucket sem_cartao intocado
            Transacao(
                usuario_id=users[0].id, tipo="despesa", data=dt.date(2026, 7, 8),
                descricao="pix", valor=Decimal("50.00"), categoria="Outros",
                forma_pagamento="Pix",
            )
        )
        session.commit()

        body = as_user(users[0]).get(
            "/statistics/spending-by-card", params={"mes": 7, "ano": 2026}
        ).json()
        assert _q(body["cartoes"][0]["total"]) == Decimal("70.00")
        assert _q(body["sem_cartao"]) == Decimal("50.00")
        assert _q(body["total"]) == Decimal("120.00")

    def test_spending_by_card_cartao_so_estorno_clampa_zero(
        self, session, users, as_user
    ):
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00")

        body = as_user(users[0]).get(
            "/statistics/spending-by-card", params={"mes": 7, "ano": 2026}
        ).json()
        assert [(c["cartao_id"], _q(c["total"])) for c in body["cartoes"]] == [
            (cartao.id, Decimal("0.00"))
        ]

    def test_evolution_categories_celula_neta(self, session, users, as_user):
        # MUTAÇÃO: sem o netting em _despesas_por_categoria, a série viria 100.
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00")
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="30.00")

        body = as_user(users[0]).get(
            "/statistics/evolution/categories", params={"meses": 1}
        ).json()
        assert [(c["categoria"], _q(c["total"]), [_q(v) for v in c["serie"]])
                for c in body["categorias"]] == [
            ("Alimentação", Decimal("70.00"), [Decimal("70.00")])
        ]

    def test_highlights_maior_despesa_bruta_dia_neta(self, session, users, as_user):
        # Dia 5: 100. Dia 10: 180 − 100 (estorno) = 80 líquido. Maior despesa
        # é BRUTA (180, dia 10); dia de maior gasto NETA (dia 5, 100).
        # MUTAÇÃO: sem o netting no por_dia, o dia 10 (180) venceria.
        cartao = _add_cartao(session, users[0].id)
        _add_fatura_tx(session, users[0].id, cartao.id, valor="100.00",
                       data=dt.date(2026, 7, 5), descricao="compra dia 5")
        _add_fatura_tx(session, users[0].id, cartao.id, valor="180.00",
                       data=dt.date(2026, 7, 10), descricao="compra dia 10")
        _add_fatura_tx(session, users[0].id, cartao.id, tipo="estorno",
                       valor="100.00", data=dt.date(2026, 7, 10))

        body = as_user(users[0]).get(
            "/statistics/highlights", params={"mes": 7, "ano": 2026}
        ).json()
        assert _q(body["maior_despesa"]["valor"]) == Decimal("180.00")
        assert body["dia_maior_gasto"]["data"] == "2026-07-05"
        assert _q(body["dia_maior_gasto"]["total"]) == Decimal("100.00")


# --- POST/PUT /transactions: validação e derivação de fatura -----------------

class TestTransacoesEstorno:
    def test_post_estorno_com_cartao_deriva_fatura(self, session, users, as_user):
        cartao = _add_cartao(session, users[0].id)
        resp = as_user(users[0]).post("/transactions", json={
            "tipo": "estorno", "data": "2026-07-05", "descricao": "estorno",
            "valor": "30.00", "categoria": "Outros",
            "forma_pagamento": "Crédito", "cartao_id": cartao.id,
        })
        assert resp.status_code == 201
        body = resp.json()
        # dia 5 <= fechamento 6 → base julho; offset 1 → vence agosto (mesma
        # derivação de uma despesa de crédito avulsa)
        assert (body["fatura_mes"], body["fatura_ano"]) == (8, 2026)
        assert body["tipo"] == "estorno"

    def test_post_estorno_SEM_cartao_ponta_a_ponta(self, session, users, as_user):
        """#48 (B) — o caso que a tela de criação manual passou a permitir.

        Reembolso por Pix é estorno SEM cartão: `cartao_id` é nulável no modelo
        e o CHECK `valor > 0` mantém o valor positivo. Sem cartão ele não deriva
        competência (fica na Fonte 3, à vista) e ABATE o consumo do mês pela
        data — que é o ponto: renda inflada era o bug.
        """
        _add_fatura_tx(session, users[0].id, None, valor="500.00")  # despesa do mês

        resp = as_user(users[0]).post("/transactions", json={
            "tipo": "estorno", "data": "2026-07-08", "descricao": "Reembolso do rachar",
            "valor": "120.00", "categoria": "Alimentação",
            "forma_pagamento": "PIX", "cartao_id": None,
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["tipo"] == "estorno"
        assert body["cartao_id"] is None
        assert (body["fatura_mes"], body["fatura_ano"]) == (None, None)

        mensal = _monthly(as_user, users[0])
        # 500 − 120: abate a despesa E não entra na receita (as duas metades)
        assert _q(mensal["despesas"]) == Decimal("380.00")
        assert _q(mensal["receitas"]) == Decimal("0.00")

    def test_post_estorno_parcelado_422(self, users, as_user):
        resp = as_user(users[0]).post("/transactions", json={
            "tipo": "estorno", "data": "2026-07-05", "descricao": "estorno",
            "valor": "30.00", "categoria": "Outros",
            "parcelado": True, "total_parcelas": 3,
        })
        assert resp.status_code == 422

    def test_put_parcelada_nao_vira_estorno_422(self, session, users, as_user):
        cartao = _add_cartao(session, users[0].id)
        criada = as_user(users[0]).post("/transactions", json={
            "tipo": "despesa", "data": "2026-07-05", "descricao": "parcelada",
            "valor": "300.00", "categoria": "Outros",
            "forma_pagamento": "Crédito", "cartao_id": cartao.id,
            "parcelado": True, "total_parcelas": 3,
        }).json()

        resp = as_user(users[0]).put(
            f"/transactions/{criada['id']}", json={"tipo": "estorno"}
        )
        assert resp.status_code == 422
        assert "parcelada" in resp.json()["detail"]
