"""§1.3.1 no endpoint — GET /statistics/monthly com realizado/a_vir.

Topo da resposta = PROJEÇÃO integral (shape antigo preservado); realizado e
a_vir são a decomposição do mês corrente pelo dia. hoje congelado em
15/07/2026 via patch em app.services.estatisticas.hoje (onde a marcação vive).
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.pagamento_fatura import PagamentoFatura
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.models.transaction import Transacao

HOJE = dt.date(2026, 7, 15)


def _q(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


@pytest.fixture(autouse=True)
def clock(mocker):
    mocker.patch("app.services.estatisticas.hoje", return_value=HOJE)


def _add_recorrencia(session, uid, dia, valor="10000.00", mes_inicio=1, ano_inicio=2026,
                     mes_fim=None, ano_fim=None, tipo="receita", categoria="Salário"):
    rec = Recorrencia(
        usuario_id=uid, tipo=tipo, categoria=categoria,
        forma_pagamento="Pix", dia_do_mes=dia, descricao=categoria,
    )
    session.add(rec)
    session.flush()
    session.add(
        RecorrenciaVigencia(
            recorrencia_id=rec.id, valor=Decimal(valor),
            mes_inicio=mes_inicio, ano_inicio=ano_inicio,
            mes_fim=mes_fim, ano_fim=ano_fim,
        )
    )
    session.commit()


class TestMonthlyLeituras:
    def test_mes_corrente_topo_projecao_e_decomposicao(self, session, users, as_user):
        # salário dia 20 (a vir) desde jan/2026
        _add_recorrencia(session, users[0].id, dia=20)

        body = as_user(users[0]).get(
            "/statistics/monthly", params={"mes": 7, "ano": 2026}
        ).json()

        # topo = projeção integral (conta o dia 20 que ainda não chegou)
        assert _q(body["receitas"]) == Decimal("10000.00")
        # decomposição: nada realizado, tudo a vir
        assert _q(body["realizado"]["receitas"]) == Decimal("0.00")
        assert _q(body["a_vir"]["receitas"]) == Decimal("10000.00")
        assert _q(body["a_vir"]["saldo"]) == Decimal("10000.00")
        # invariante no shape
        assert _q(body["realizado"]["receitas"]) + _q(body["a_vir"]["receitas"]) == _q(
            body["receitas"]
        )

    def test_mes_nao_corrente_realizado_igual_topo_a_vir_zero(
        self, session, users, as_user
    ):
        _add_recorrencia(session, users[0].id, dia=20)

        for mes in (6, 8):  # passado e futuro
            body = as_user(users[0]).get(
                "/statistics/monthly", params={"mes": mes, "ano": 2026}
            ).json()
            assert _q(body["realizado"]["receitas"]) == _q(body["receitas"])
            assert _q(body["a_vir"]["receitas"]) == Decimal("0.00")
            assert _q(body["a_vir"]["despesas"]) == Decimal("0.00")

    def test_variacao_usa_projecao_nao_o_realizado(self, session, users, as_user):
        # mesma recorrência em jun e jul; em jul o dia 20 ainda não chegou.
        # Projeção×projeção → 0%. (Se usasse o realizado, seria -100%.)
        _add_recorrencia(session, users[0].id, dia=20)

        body = as_user(users[0]).get(
            "/statistics/monthly", params={"mes": 7, "ano": 2026}
        ).json()
        assert _q(body["variacao_receitas"]) == Decimal("0.00")


def _add_parcelada(session, uid, valor_total="1200.00", n=12, mes0=1, ano0=2026,
                   categoria="Eletrônicos", cartao_id=1, cancelado=False):
    """Pai parcelada (data no dia 15 de mes0/ano0) + n parcelas por competência."""
    total = Decimal(valor_total)
    pai = Transacao(
        usuario_id=uid, tipo="despesa", data=dt.date(ano0, mes0, 15),
        descricao="compra parcelada", valor=total, categoria=categoria,
        forma_pagamento="Crédito", cartao_id=cartao_id, parcelado=True, total_parcelas=n,
    )
    session.add(pai)
    session.flush()
    base = (total / n).quantize(Decimal("0.01"))
    m, a = mes0, ano0
    for i in range(1, n + 1):
        val = base if i < n else total - base * (n - 1)
        session.add(
            Parcela(
                usuario_id=uid, transacao_id=pai.id, numero_parcela=i, total_parcelas=n,
                valor_parcela=val, data_vencimento=dt.date(a, m, 10),
                descricao="compra parcelada", categoria=categoria, cartao_id=cartao_id,
                fatura_mes=m, fatura_ano=a, cancelado=cancelado,
            )
        )
        m += 1
        if m == 13:
            m, a = 1, a + 1
    session.commit()


class TestMonthlyConsumo:
    """§"Fase 3b" — a resposta ganha `consumo` (LeituraMes) + `categorias_consumo`
    (donut), aditivos ao topo de FLUXO (que não muda)."""

    def test_consumo_parcelada_valor_cheio_no_mes_da_compra(self, session, users, as_user):
        _add_parcelada(session, users[0].id)  # R$1200/12x, compra em jan/2026

        body = as_user(users[0]).get(
            "/statistics/monthly", params={"mes": 1, "ano": 2026}
        ).json()

        # FLUXO (topo) = a parcela de jan; inalterado
        assert _q(body["despesas"]) == Decimal("100.00")
        # CONSUMO = valor cheio no mês da compra (número único, sem realizado/a_vir)
        assert _q(body["consumo"]["despesas"]) == Decimal("1200.00")
        assert _q(body["consumo"]["receitas"]) == Decimal("0.00")
        assert _q(body["consumo"]["saldo"]) == Decimal("-1200.00")
        assert "realizado" not in body["consumo"] and "a_vir" not in body["consumo"]
        # donut de consumo
        assert [(c["categoria"], _q(c["total"])) for c in body["categorias_consumo"]] == [
            ("Eletrônicos", Decimal("1200.00"))
        ]

    def test_consumo_zero_no_mes_sem_compra_mas_fluxo_tem_a_parcela(
        self, session, users, as_user
    ):
        _add_parcelada(session, users[0].id)  # compra em jan; fev só tem a parcela

        body = as_user(users[0]).get(
            "/statistics/monthly", params={"mes": 2, "ano": 2026}
        ).json()
        assert _q(body["despesas"]) == Decimal("100.00")            # fluxo: parcela de fev
        assert _q(body["consumo"]["despesas"]) == Decimal("0.00")  # consumo: nada comprado em fev
        assert body["categorias_consumo"] == []


def _add_avista(session, uid, data, tipo="despesa", valor="50.00", categoria="Outros"):
    """Transação à vista/receita (não parcelada, não faturada) — Fonte 3."""
    session.add(
        Transacao(
            usuario_id=uid, tipo=tipo, data=data, descricao="à vista",
            valor=Decimal(valor), categoria=categoria, forma_pagamento="Pix",
        )
    )
    session.commit()


class TestMonthlyAPagar:
    """§"A pagar e Saldo" — MensalResponse ganha `a_pagar` (só crédito não
    saído); o `saldo` do topo segue receitas − despesas (caixa projetado de
    fim de mês). hoje congelado em 15/07/2026 (fixture clock)."""

    def test_a_vista_pago_fora_e_saldo_caixa_fim_de_mes(self, session, users, as_user):
        # O caso que motivou a decisão: receita 8k + aluguel 2k via PIX (já
        # saiu) → NADA a pagar; saldo = como termino o mês = 6k.
        _add_avista(session, users[0].id, dt.date(2026, 7, 5), tipo="receita",
                    valor="8000.00")
        _add_avista(session, users[0].id, dt.date(2026, 7, 10), valor="2000.00")

        body = as_user(users[0]).get(
            "/statistics/monthly", params={"mes": 7, "ano": 2026}
        ).json()
        assert _q(body["a_pagar"]) == Decimal("0.00")
        assert _q(body["saldo"]) == Decimal("6000.00")
        assert _q(body["despesas"]) == Decimal("2000.00")
        assert _q(body["receitas"]) == Decimal("8000.00")

    def test_credito_do_mes_dentro_de_a_pagar(self, session, users, as_user):
        # Parcela de jul vence dia 10 (< hoje 15) e não está paga → atrasada,
        # continua a pagar (furo 2); e a_pagar nunca excede as despesas.
        _add_parcelada(session, users[0].id)  # 1200/12x — parcela jul = 100

        body = as_user(users[0]).get(
            "/statistics/monthly", params={"mes": 7, "ano": 2026}
        ).json()
        assert _q(body["a_pagar"]) == Decimal("100.00")
        assert _q(body["a_pagar"]) <= _q(body["despesas"])

    def test_confirmar_fatura_so_mexe_no_a_pagar(self, session, users, as_user):
        # Fronteira do pagamento de ponta a ponta (Leva 2): confirmar a FATURA
        # (PagamentoFatura) não move NENHUM outro campo da resposta (projeção,
        # realizado/a_vir, variações, consumo, donuts) — só o a_pagar.
        _add_parcelada(session, users[0].id)
        _add_recorrencia(session, users[0].id, dia=20)

        def _monthly():
            return as_user(users[0]).get(
                "/statistics/monthly", params={"mes": 7, "ano": 2026}
            ).json()

        antes = _monthly()
        session.add(
            PagamentoFatura(
                usuario_id=users[0].id, cartao_id=1, fatura_mes=7,
                fatura_ano=2026, pago=True, data_pagamento=HOJE,
            )
        )
        session.commit()
        depois = _monthly()

        assert _q(antes.pop("a_pagar")) == Decimal("100.00")
        assert _q(depois.pop("a_pagar")) == Decimal("0.00")
        assert antes == depois  # resto da resposta byte a byte igual


class TestDefaultMonth:
    """GET /statistics/default-month — mês em que o Dashboard ABRE (PLANO §"Mês
    default do Dashboard"). hoje congelado em 15/07/2026 (fixture clock)."""

    def _get(self, as_user, user):
        resp = as_user(user).get("/statistics/default-month")
        assert resp.status_code == 200
        return resp.json()

    def test_com_historico_abre_no_mes_corrente(self, session, users, as_user):
        # histórico (à vista em junho) + fluxo futuro (parcela em setembro):
        # a regra 1 ganha — abre no corrente, não pula para o fluxo futuro.
        _add_avista(session, users[0].id, dt.date(2026, 6, 10))
        _add_parcelada(session, users[0].id, n=1, mes0=9)

        body = self._get(as_user, users[0])
        assert body["fluxo"] == {"mes": 7, "ano": 2026}

    def test_sem_passado_parcela_vencendo_no_corrente(self, session, users, as_user):
        # pai parcelada não é histórico (§2.1); a parcela fatura jul → corrente
        _add_parcelada(session, users[0].id, n=1, mes0=7)

        body = self._get(as_user, users[0])
        assert body["fluxo"] == {"mes": 7, "ano": 2026}

    def test_sem_passado_corrente_vazio_pula_para_primeiro_mes_com_fluxo(
        self, session, users, as_user
    ):
        _add_parcelada(session, users[0].id, n=1, mes0=9)  # daqui a 2 meses

        body = self._get(as_user, users[0])
        assert body["fluxo"] == {"mes": 9, "ano": 2026}  # pula jul/ago vazios

    def test_sem_nada_fallback_mes_seguinte(self, users, as_user):
        body = self._get(as_user, users[0])
        assert body["fluxo"] == {"mes": 8, "ano": 2026}
        assert body["consumo"] == {"mes": 7, "ano": 2026}

    def test_multi_cartao_abre_no_mes_mais_proximo_com_fluxo(
        self, session, users, as_user
    ):
        # dois cartões com fatura em meses diferentes: fatura_mes já respeita o
        # ciclo de cada cartão — o default é o mês mais próximo com fluxo.
        _add_parcelada(session, users[0].id, n=1, mes0=10, cartao_id=1)
        _add_parcelada(session, users[0].id, n=1, mes0=9, cartao_id=2)

        body = self._get(as_user, users[0])
        assert body["fluxo"] == {"mes": 9, "ano": 2026}

    def test_consumo_sempre_corrente_mesmo_com_fluxo_futuro(
        self, session, users, as_user
    ):
        _add_parcelada(session, users[0].id, n=1, mes0=9)

        body = self._get(as_user, users[0])
        assert body["fluxo"] == {"mes": 9, "ano": 2026}
        assert body["consumo"] == {"mes": 7, "ano": 2026}

    def test_recorrencia_futura_e_o_primeiro_fluxo(self, session, users, as_user):
        # início em outubro NÃO é histórico (>= corrente); é o 1º mês com fluxo
        _add_recorrencia(session, users[0].id, dia=5, mes_inicio=10, ano_inicio=2026)

        body = self._get(as_user, users[0])
        assert body["fluxo"] == {"mes": 10, "ano": 2026}

    def test_recorrencia_encerrada_no_passado_conta_como_historico(
        self, session, users, as_user
    ):
        # vigência jan–mar/2026 (fechada): sem fluxo corrente/futuro, mas o
        # passado existe → regra 1 → corrente (não o fallback ago)
        _add_recorrencia(
            session, users[0].id, dia=5,
            mes_inicio=1, ano_inicio=2026, mes_fim=3, ano_fim=2026,
        )

        body = self._get(as_user, users[0])
        assert body["fluxo"] == {"mes": 7, "ano": 2026}

    def test_parcela_cancelada_nao_conta_nem_como_historico_nem_como_fluxo(
        self, session, users, as_user
    ):
        _add_parcelada(session, users[0].id, n=1, mes0=6, cancelado=True)  # passado
        _add_parcelada(session, users[0].id, n=1, mes0=9, cancelado=True)  # futuro

        body = self._get(as_user, users[0])
        assert body["fluxo"] == {"mes": 8, "ano": 2026}  # fallback

    def test_horizonte_60_meses_dentro_conta_alem_cai_no_fallback(
        self, session, users, as_user
    ):
        # jul/2026 + 60 meses = jul/2031 (última competência varrida)
        _add_parcelada(session, users[0].id, n=1, mes0=7, ano0=2031)   # borda: entra
        _add_parcelada(session, users[1].id, n=1, mes0=8, ano0=2031)   # 61 meses: fora

        assert self._get(as_user, users[0])["fluxo"] == {"mes": 7, "ano": 2031}
        assert self._get(as_user, users[1])["fluxo"] == {"mes": 8, "ano": 2026}

    def test_fallback_vira_o_ano_em_dezembro(self, mocker, users, as_user):
        mocker.patch(
            "app.services.estatisticas.hoje", return_value=dt.date(2026, 12, 15)
        )

        body = self._get(as_user, users[0])
        assert body["fluxo"] == {"mes": 1, "ano": 2027}
        assert body["consumo"] == {"mes": 12, "ano": 2026}


class TestProjection:
    """GET /statistics/projection — série de N meses de FLUXO do Bloco 2
    (PLANO_DASHBOARD_DOIS_BLOCOS + §"PROJEÇÃO (Bloco 2)"): series[0] = primeiro
    mês FUTURO com fluxo — NUNCA o corrente (Bloco 1), fallback mês seguinte;
    meses seguintes contínuos, zeros quando sem fluxo. hoje congelado em
    15/07/2026 (fixture clock)."""

    def _series(self, as_user, user, **params):
        resp = as_user(user).get("/statistics/projection", params=params)
        assert resp.status_code == 200
        return resp.json()["series"]

    def test_12_meses_sem_fluxo_futuro_comeca_no_mes_seguinte_e_vira_o_ano(
        self, session, users, as_user
    ):
        # Só histórico (à vista em junho), nada à frente → fallback = mês
        # seguinte (ago/2026); a série de 12 vai até jul/2027, contínua, com a
        # virada dez/2026 → jan/2027.
        _add_avista(session, users[0].id, dt.date(2026, 6, 10))

        series = self._series(as_user, users[0])
        assert len(series) == 12
        assert (series[0]["mes"], series[0]["ano"]) == (8, 2026)
        esperado = [(m, 2026) for m in range(8, 13)] + [(m, 2027) for m in range(1, 8)]
        assert [(i["mes"], i["ano"]) for i in series] == esperado

    def test_nunca_comeca_no_corrente_mesmo_com_fluxo_nele(
        self, session, users, as_user
    ):
        # Fluxo no corrente (parcela jul) E à frente (ago/set): o corrente é o
        # Bloco 1 — a série pula para o primeiro mês FUTURO com fluxo.
        _add_parcelada(session, users[0].id, n=3, mes0=7)  # jul, ago, set

        series = self._series(as_user, users[0], meses=2)
        assert [(i["mes"], i["ano"]) for i in series] == [(8, 2026), (9, 2026)]

    def test_sem_historico_comeca_no_primeiro_mes_com_fluxo(
        self, session, users, as_user
    ):
        _add_parcelada(session, users[0].id, n=1, mes0=9)  # ago vazio, fluxo em set

        series = self._series(as_user, users[0])
        assert (series[0]["mes"], series[0]["ano"]) == (9, 2026)
        assert _q(series[0]["despesas"]) == Decimal("1200.00")
        # crédito não pago → também é "a pagar" (eixo §"A pagar e Saldo")
        assert _q(series[0]["a_pagar"]) == Decimal("1200.00")

    def test_saldo_e_consistencia_cruzada_com_monthly(self, session, users, as_user):
        # salário 10000 desde jan + parcelada 1200/12x de jan (parcelas
        # jan–dez/2026): a série começa em ago/2026 (1º futuro com fluxo), tem
        # receitas e despesas em 2026 e só receitas em 2027.
        _add_recorrencia(session, users[0].id, dia=20)
        _add_parcelada(session, users[0].id)

        series = self._series(as_user, users[0])
        assert (series[0]["mes"], series[0]["ano"]) == (8, 2026)
        for item in series:
            # saldo = caixa fim de mês (receitas − TODAS as saídas); a_pagar é
            # o recorte de crédito, NUNCA o subtraendo do saldo.
            assert _q(item["saldo"]) == _q(item["receitas"]) - _q(item["despesas"])
            assert _q(item["a_pagar"]) <= _q(item["despesas"])

        # consistência cruzada: item da série == topo (projeção integral) do
        # /monthly do mesmo mês — mesma semântica de fluxo, item a item.
        for item in (series[0], series[2], series[5]):  # ago/out/2026, jan/2027
            monthly = as_user(users[0]).get(
                "/statistics/monthly", params={"mes": item["mes"], "ano": item["ano"]}
            ).json()
            assert _q(item["receitas"]) == _q(monthly["receitas"])
            assert _q(item["despesas"]) == _q(monthly["despesas"])
            assert _q(item["saldo"]) == _q(monthly["saldo"])
            assert _q(item["a_pagar"]) == _q(monthly["a_pagar"])

    def test_mes_sem_fluxo_no_meio_entra_com_zeros(self, session, users, as_user):
        # fluxo em ago e out, set vazio: setembro aparece na série com zeros
        # (contínua, não pula o mês).
        _add_parcelada(session, users[0].id, n=1, mes0=8)
        _add_parcelada(session, users[0].id, n=1, mes0=10)

        series = self._series(as_user, users[0], meses=3)
        assert [(i["mes"], i["ano"]) for i in series] == [(8, 2026), (9, 2026), (10, 2026)]
        assert _q(series[1]["receitas"]) == Decimal("0.00")
        assert _q(series[1]["despesas"]) == Decimal("0.00")
        assert _q(series[1]["a_pagar"]) == Decimal("0.00")
        assert _q(series[1]["saldo"]) == Decimal("0.00")

    def test_virada_de_ano_em_dezembro(self, mocker, session, users, as_user):
        # hoje em dez/2026, sem fluxo futuro → fallback = jan/2027 (o "mês
        # seguinte" do início da projeção também vira o ano).
        mocker.patch(
            "app.services.estatisticas.hoje", return_value=dt.date(2026, 12, 15)
        )
        _add_avista(session, users[0].id, dt.date(2026, 11, 10))

        series = self._series(as_user, users[0], meses=3)
        assert [(i["mes"], i["ano"]) for i in series] == [
            (1, 2027), (2, 2027), (3, 2027)
        ]

    def test_meses_1_so_o_inicio_da_projecao(self, session, users, as_user):
        _add_avista(session, users[0].id, dt.date(2026, 6, 10))

        series = self._series(as_user, users[0], meses=1)
        assert [(i["mes"], i["ano"]) for i in series] == [(8, 2026)]

    def test_default_12_e_limites_1_a_60(self, users, as_user):
        assert len(self._series(as_user, users[0])) == 12       # default
        assert len(self._series(as_user, users[0], meses=60)) == 60
        for invalido in (0, 61):
            resp = as_user(users[0]).get(
                "/statistics/projection", params={"meses": invalido}
            )
            assert resp.status_code == 422


class TestEvolution:
    """GET /statistics/evolution — série CONSUMO dos últimos N meses (Resumo,
    Seção 3, PLANO_RESUMO): o espelho PRA TRÁS do /projection. Âncora = mês
    corrente INCLUÍDO (meses=N = corrente + N−1 pra trás), cronológica, zeros
    para mês sem dado. hoje congelado em 15/07/2026 (fixture clock)."""

    def _series(self, as_user, user, **params):
        resp = as_user(user).get("/statistics/evolution", params=params)
        assert resp.status_code == 200
        return resp.json()["series"]

    def test_default_3_meses_cronologico_terminando_no_corrente(self, users, as_user):
        series = self._series(as_user, users[0])
        assert [(i["mes"], i["ano"]) for i in series] == [
            (5, 2026), (6, 2026), (7, 2026)
        ]
        for item in series:  # sem dados → zeros, série contínua
            assert _q(item["receitas"]) == Decimal("0.00")
            assert _q(item["despesas"]) == Decimal("0.00")
            assert _q(item["saldo"]) == Decimal("0.00")

    def test_consumo_parcelada_inteira_no_mes_da_compra(self, session, users, as_user):
        # compra 12x em 15/jun: consumo conta R$1200 em jun; a parcela de jul
        # NÃO conta (é fatia de fluxo — o /evolution é a lente do gasto).
        _add_parcelada(session, users[0].id, mes0=6)

        series = self._series(as_user, users[0])
        assert _q(series[0]["despesas"]) == Decimal("0.00")     # mai
        assert _q(series[1]["despesas"]) == Decimal("1200.00")  # jun: valor cheio
        assert _q(series[2]["despesas"]) == Decimal("0.00")     # jul: sem compra

    def test_bate_com_o_consumo_do_monthly_mes_a_mes(self, session, users, as_user):
        # endpoint-vs-endpoint: a fonte única não diverge do Dashboard — cada
        # item da série == campo `consumo` do /monthly do mesmo mês.
        _add_recorrencia(session, users[0].id, dia=5)
        _add_parcelada(session, users[0].id, mes0=5)
        _add_avista(session, users[0].id, dt.date(2026, 6, 10))

        for item in self._series(as_user, users[0], meses=4):
            monthly = as_user(users[0]).get(
                "/statistics/monthly", params={"mes": item["mes"], "ano": item["ano"]}
            ).json()
            assert _q(item["receitas"]) == _q(monthly["consumo"]["receitas"])
            assert _q(item["despesas"]) == _q(monthly["consumo"]["despesas"])
            assert _q(item["saldo"]) == _q(monthly["consumo"]["saldo"])

    def test_virada_de_ano_no_horizonte(self, mocker, session, users, as_user):
        # hoje = fev/2027; meses=4 cruza a virada: nov/2026..fev/2027
        mocker.patch(
            "app.services.estatisticas.hoje", return_value=dt.date(2027, 2, 15)
        )
        _add_avista(session, users[0].id, dt.date(2026, 12, 10), valor="70.00")

        series = self._series(as_user, users[0], meses=4)
        assert [(i["mes"], i["ano"]) for i in series] == [
            (11, 2026), (12, 2026), (1, 2027), (2, 2027)
        ]
        assert _q(series[1]["despesas"]) == Decimal("70.00")

    def test_mes_vazio_no_meio_entra_com_zeros(self, session, users, as_user):
        _add_avista(session, users[0].id, dt.date(2026, 5, 10), tipo="receita",
                    valor="100.00")
        _add_avista(session, users[0].id, dt.date(2026, 7, 10), valor="30.00")

        series = self._series(as_user, users[0])
        assert _q(series[0]["saldo"]) == Decimal("100.00")
        assert _q(series[1]["receitas"]) == Decimal("0.00")  # jun vazio
        assert _q(series[1]["despesas"]) == Decimal("0.00")
        assert _q(series[2]["saldo"]) == Decimal("-30.00")

    def test_isolamento_entre_usuarios(self, session, users, as_user):
        _add_avista(session, users[1].id, dt.date(2026, 7, 10))

        series = self._series(as_user, users[0])
        assert _q(series[2]["despesas"]) == Decimal("0.00")

    def test_meses_1_e_limites_1_a_60(self, users, as_user):
        series = self._series(as_user, users[0], meses=1)
        assert [(i["mes"], i["ano"]) for i in series] == [(7, 2026)]
        assert len(self._series(as_user, users[0], meses=60)) == 60
        for invalido in (0, 61):
            resp = as_user(users[0]).get(
                "/statistics/evolution", params={"meses": invalido}
            )
            assert resp.status_code == 422


class TestEvolutionCategories:
    """GET /statistics/evolution/categories — série por categoria (CONSUMO, só
    despesas), categoria-major: cada `serie` alinhada por índice ao eixo
    `meses`, zeros onde a categoria não teve gasto. hoje congelado em
    15/07/2026 (fixture clock)."""

    def _get(self, as_user, user, **params):
        resp = as_user(user).get("/statistics/evolution/categories", params=params)
        assert resp.status_code == 200
        return resp.json()

    def test_series_alinhadas_ao_eixo_com_zeros_e_ordenacao(
        self, session, users, as_user
    ):
        _add_avista(session, users[0].id, dt.date(2026, 5, 10), valor="100.00",
                    categoria="Mercado")
        _add_avista(session, users[0].id, dt.date(2026, 7, 10), valor="40.00",
                    categoria="Mercado")
        _add_avista(session, users[0].id, dt.date(2026, 6, 10), valor="60.00",
                    categoria="Transporte")

        body = self._get(as_user, users[0])
        assert body["meses"] == [
            {"mes": 5, "ano": 2026}, {"mes": 6, "ano": 2026}, {"mes": 7, "ano": 2026}
        ]
        # ordenação por total desc: Mercado (140) antes de Transporte (60)
        assert [c["categoria"] for c in body["categorias"]] == ["Mercado", "Transporte"]
        por_nome = {c["categoria"]: c for c in body["categorias"]}
        assert [_q(v) for v in por_nome["Mercado"]["serie"]] == [
            Decimal("100.00"), Decimal("0.00"), Decimal("40.00")
        ]
        assert [_q(v) for v in por_nome["Transporte"]["serie"]] == [
            Decimal("0.00"), Decimal("60.00"), Decimal("0.00")
        ]
        assert _q(por_nome["Mercado"]["total"]) == Decimal("140.00")

    def test_ultima_coluna_bate_com_o_donut_de_consumo_do_monthly(
        self, session, users, as_user
    ):
        # endpoint-vs-endpoint: a coluna do mês corrente == categorias_consumo
        # do /monthly (o Resumo é o aprofundamento do MESMO donut).
        _add_parcelada(session, users[0].id, mes0=7)  # Eletrônicos 1200 em jul
        _add_avista(session, users[0].id, dt.date(2026, 7, 10), valor="80.00",
                    categoria="Mercado")
        _add_recorrencia(session, users[0].id, dia=5, tipo="despesa",
                         categoria="Moradia", valor="2000.00")

        body = self._get(as_user, users[0])
        monthly = as_user(users[0]).get(
            "/statistics/monthly", params={"mes": 7, "ano": 2026}
        ).json()
        ultima_coluna = {
            c["categoria"]: _q(c["serie"][-1])
            for c in body["categorias"]
            if _q(c["serie"][-1]) != Decimal("0.00")
        }
        donut = {c["categoria"]: _q(c["total"]) for c in monthly["categorias_consumo"]}
        assert ultima_coluna == donut

    def test_receita_nao_vira_categoria(self, session, users, as_user):
        _add_recorrencia(session, users[0].id, dia=5)  # receita Salário
        _add_avista(session, users[0].id, dt.date(2026, 7, 3), tipo="receita",
                    valor="500.00")

        assert self._get(as_user, users[0])["categorias"] == []

    def test_recorrencia_despesa_presente_em_todos_os_meses(
        self, session, users, as_user
    ):
        _add_recorrencia(session, users[0].id, dia=5, tipo="despesa",
                         categoria="Moradia", valor="2000.00")

        body = self._get(as_user, users[0], meses=3)
        (moradia,) = body["categorias"]
        assert moradia["categoria"] == "Moradia"
        assert [_q(v) for v in moradia["serie"]] == [Decimal("2000.00")] * 3
        assert _q(moradia["total"]) == Decimal("6000.00")

    def test_sem_dados_eixo_presente_categorias_vazias(self, users, as_user):
        body = self._get(as_user, users[0])
        assert len(body["meses"]) == 3
        assert body["categorias"] == []


class TestComparison:
    """GET /statistics/comparison — Seção 2 do Resumo: atual vs anterior vs
    média, totais e por categoria, base CONSUMO. `meses=N` = meses FECHADOS
    (o baseline da média); o corrente NUNCA entra na média (comparação não
    circular). hoje congelado em 15/07/2026 (fixture clock)."""

    def _get(self, as_user, user, **params):
        resp = as_user(user).get("/statistics/comparison", params=params)
        assert resp.status_code == 200
        return resp.json()

    def _gastos_mai_jun_jul(self, session, uid):
        """Despesas à vista: mai=100, jun=200 (fechados), jul=600 (corrente)."""
        _add_avista(session, uid, dt.date(2026, 5, 10), valor="100.00",
                    categoria="Mercado")
        _add_avista(session, uid, dt.date(2026, 6, 10), valor="200.00",
                    categoria="Mercado")
        _add_avista(session, uid, dt.date(2026, 7, 10), valor="600.00",
                    categoria="Mercado")

    def test_media_so_dos_meses_fechados_nao_inclui_o_corrente(
        self, session, users, as_user
    ):
        # O teste do AJUSTE 1: com hoje=jul e meses=2, media = média de
        # mai+jun = 150.00 — NÃO (mai+jun+jul)/3 = 300.00.
        self._gastos_mai_jun_jul(session, users[0].id)

        totais = self._get(as_user, users[0], meses=2)["totais"]
        assert _q(totais["media"]["despesas"]) == Decimal("150.00")
        assert _q(totais["atual"]["despesas"]) == Decimal("600.00")
        assert _q(totais["anterior"]["despesas"]) == Decimal("200.00")  # jun

    def test_variacoes_vs_anterior_e_vs_media(self, session, users, as_user):
        self._gastos_mai_jun_jul(session, users[0].id)

        totais = self._get(as_user, users[0], meses=2)["totais"]
        # (600−200)/200 = +200%; (600−150)/150 = +300%
        assert _q(totais["variacao_vs_anterior"]["despesas"]) == Decimal("200.00")
        assert _q(totais["variacao_vs_media"]["despesas"]) == Decimal("300.00")
        # sem receitas: base zero → variação None (nunca inventa %)
        assert totais["variacao_vs_anterior"]["receitas"] is None
        assert totais["variacao_vs_media"]["receitas"] is None

    def test_ancora_e_consistencia_com_o_consumo_do_monthly(
        self, session, users, as_user
    ):
        # endpoint-vs-endpoint: `atual` == campo consumo do /monthly corrente.
        self._gastos_mai_jun_jul(session, users[0].id)
        _add_recorrencia(session, users[0].id, dia=5)  # receita em todos os meses

        body = self._get(as_user, users[0])
        assert (body["mes"], body["ano"]) == (7, 2026)
        monthly = as_user(users[0]).get(
            "/statistics/monthly", params={"mes": 7, "ano": 2026}
        ).json()
        for campo in ("receitas", "despesas", "saldo"):
            assert _q(body["totais"]["atual"][campo]) == _q(monthly["consumo"][campo])

    def test_receitas_nos_totais_e_invariante_do_saldo_da_media(
        self, session, users, as_user
    ):
        self._gastos_mai_jun_jul(session, users[0].id)
        _add_recorrencia(session, users[0].id, dia=5)  # 10000/mês desde jan

        totais = self._get(as_user, users[0], meses=2)["totais"]
        assert _q(totais["media"]["receitas"]) == Decimal("10000.00")
        assert _q(totais["variacao_vs_media"]["receitas"]) == Decimal("0.00")
        # saldo da média = receitas − despesas da média (invariante preservada)
        assert _q(totais["media"]["saldo"]) == (
            _q(totais["media"]["receitas"]) - _q(totais["media"]["despesas"])
        )

    def test_categoria_que_sumiu_atual_zero_variacao_menos_100(
        self, session, users, as_user
    ):
        # Transporte só em jun: no corrente é base alinhada em zero.
        _add_avista(session, users[0].id, dt.date(2026, 6, 10), valor="80.00",
                    categoria="Transporte")

        (transporte,) = self._get(as_user, users[0], meses=2)["categorias"]
        assert transporte["categoria"] == "Transporte"
        assert _q(transporte["atual"]) == Decimal("0.00")
        assert _q(transporte["anterior"]) == Decimal("80.00")
        assert _q(transporte["media"]) == Decimal("40.00")  # 80/2 (N fixo)
        assert _q(transporte["variacao_vs_anterior"]) == Decimal("-100.00")
        assert _q(transporte["variacao_vs_media"]) == Decimal("-100.00")

    def test_categoria_que_surgiu_base_zero_variacao_none(
        self, session, users, as_user
    ):
        _add_avista(session, users[0].id, dt.date(2026, 7, 10), valor="90.00",
                    categoria="Lazer")

        (lazer,) = self._get(as_user, users[0], meses=2)["categorias"]
        assert _q(lazer["atual"]) == Decimal("90.00")
        assert _q(lazer["anterior"]) == _q(lazer["media"]) == Decimal("0.00")
        assert lazer["variacao_vs_anterior"] is None  # base zero — nunca "+∞"
        assert lazer["variacao_vs_media"] is None

    def test_media_denominador_fixo_e_quantize(self, session, users, as_user):
        # Gasto em 1 dos 3 fechados (mai): media = 100/3 = 33.33 (HALF_UP),
        # não 100/1 — mês ausente conta como zero no denominador fixo.
        _add_avista(session, users[0].id, dt.date(2026, 5, 10), valor="100.00",
                    categoria="Mercado")

        (mercado,) = self._get(as_user, users[0], meses=3)["categorias"]
        assert _q(mercado["media"]) == Decimal("33.33")

    def test_categorias_ordenadas_por_atual_desc(self, session, users, as_user):
        _add_avista(session, users[0].id, dt.date(2026, 7, 10), valor="50.00",
                    categoria="Transporte")
        _add_avista(session, users[0].id, dt.date(2026, 7, 11), valor="300.00",
                    categoria="Mercado")

        nomes = [c["categoria"] for c in self._get(as_user, users[0])["categorias"]]
        assert nomes == ["Mercado", "Transporte"]

    def test_meses_1_media_igual_ao_unico_fechado(self, session, users, as_user):
        # ge=1: com 1 mês fechado, media == anterior (jun) — o mínimo válido.
        self._gastos_mai_jun_jul(session, users[0].id)

        totais = self._get(as_user, users[0], meses=1)["totais"]
        assert _q(totais["media"]["despesas"]) == _q(
            totais["anterior"]["despesas"]
        ) == Decimal("200.00")

    def test_sem_dados_zeros_e_variacoes_none(self, users, as_user):
        body = self._get(as_user, users[0])
        assert body["categorias"] == []
        assert _q(body["totais"]["atual"]["despesas"]) == Decimal("0.00")
        assert body["totais"]["variacao_vs_anterior"]["despesas"] is None

    def test_limites_ge_1_le_60(self, users, as_user):
        assert len(self._get(as_user, users[0], meses=60)) == 4  # 200 OK
        for invalido in (0, 61):
            resp = as_user(users[0]).get(
                "/statistics/comparison", params={"meses": invalido}
            )
            assert resp.status_code == 422


class TestHighlights:
    """GET /statistics/highlights — destaques do mês (Resumo, Seção 1), base
    CONSUMO: a MESMA lista do donut (recorrência concorre, pela data da
    ocorrência). Contagem decomposta lançadas/recorrentes, com o invariante
    total == lancadas + recorrentes. hoje congelado em 15/07/2026."""

    def _get(self, as_user, user, mes=7, ano=2026):
        resp = as_user(user).get(
            "/statistics/highlights", params={"mes": mes, "ano": ano}
        )
        assert resp.status_code == 200
        return resp.json()

    def _add_despesa(self, session, uid, data, valor, descricao, categoria="Mercado"):
        session.add(
            Transacao(
                usuario_id=uid, tipo="despesa", data=data, descricao=descricao,
                valor=Decimal(valor), categoria=categoria, forma_pagamento="Pix",
            )
        )
        session.commit()

    def test_maior_despesa_com_descricao_categoria_e_data(
        self, session, users, as_user
    ):
        self._add_despesa(session, users[0].id, dt.date(2026, 7, 10), "80.00",
                          "feira")
        self._add_despesa(session, users[0].id, dt.date(2026, 7, 12), "250.00",
                          "tênis", categoria="Vestuário")

        maior = self._get(as_user, users[0])["maior_despesa"]
        assert _q(maior["valor"]) == Decimal("250.00")
        assert maior["descricao"] == "tênis"
        assert maior["categoria"] == "Vestuário"
        assert maior["data"] == "2026-07-12"

    def test_dia_de_maior_gasto_soma_o_dia_inteiro(self, session, users, as_user):
        # dia 10 soma 110 (50+60) e ganha do dia 12 (100), mesmo sem ter a
        # maior despesa individual.
        self._add_despesa(session, users[0].id, dt.date(2026, 7, 10), "50.00", "a")
        self._add_despesa(session, users[0].id, dt.date(2026, 7, 10), "60.00", "b")
        self._add_despesa(session, users[0].id, dt.date(2026, 7, 12), "100.00", "c")

        body = self._get(as_user, users[0])
        assert body["dia_maior_gasto"]["data"] == "2026-07-10"
        assert _q(body["dia_maior_gasto"]["total"]) == Decimal("110.00")
        assert _q(body["maior_despesa"]["valor"]) == Decimal("100.00")  # a do dia 12

    def test_recorrencia_concorre_aos_destaques(self, session, users, as_user):
        _add_recorrencia(session, users[0].id, dia=5, tipo="despesa",
                         categoria="Moradia", valor="2000.00")
        self._add_despesa(session, users[0].id, dt.date(2026, 7, 10), "80.00", "feira")

        body = self._get(as_user, users[0])
        assert body["maior_despesa"]["descricao"] == "Moradia"
        assert body["maior_despesa"]["data"] == "2026-07-05"  # ocorrência clampada
        assert body["dia_maior_gasto"]["data"] == "2026-07-05"
        assert _q(body["dia_maior_gasto"]["total"]) == Decimal("2000.00")

    def test_invariante_total_igual_lancadas_mais_recorrentes(
        self, session, users, as_user
    ):
        # O teste do AJUSTE 2, com AMBAS as fontes: 2 Transacao (receita E
        # despesa — a contagem é de movimentações, não só gasto) + 2
        # ocorrências de recorrência.
        _add_avista(session, users[0].id, dt.date(2026, 7, 3), tipo="receita",
                    valor="500.00")
        self._add_despesa(session, users[0].id, dt.date(2026, 7, 10), "80.00", "feira")
        _add_recorrencia(session, users[0].id, dia=5)  # receita recorrente
        _add_recorrencia(session, users[0].id, dia=8, tipo="despesa",
                         categoria="Moradia", valor="2000.00")

        body = self._get(as_user, users[0])
        assert body["num_transacoes_total"] == 4
        assert body["num_lancadas"] == 2
        assert body["num_recorrentes"] == 2
        assert body["num_transacoes_total"] == (
            body["num_lancadas"] + body["num_recorrentes"]
        )

    def test_empate_de_valor_ganha_a_data_mais_recente(self, session, users, as_user):
        self._add_despesa(session, users[0].id, dt.date(2026, 7, 5), "100.00", "antiga")
        self._add_despesa(session, users[0].id, dt.date(2026, 7, 20), "100.00", "recente")

        body = self._get(as_user, users[0])
        assert body["maior_despesa"]["descricao"] == "recente"
        # empate no total do dia também: ganha o dia mais recente
        assert body["dia_maior_gasto"]["data"] == "2026-07-20"

    def test_consumo_parcelada_destaca_no_mes_da_compra(self, session, users, as_user):
        _add_parcelada(session, users[0].id, mes0=6)  # compra 15/jun, 12x

        jun = self._get(as_user, users[0], mes=6)
        assert _q(jun["maior_despesa"]["valor"]) == Decimal("1200.00")  # valor cheio
        assert jun["num_lancadas"] == 1  # a pai conta UMA vez

        jul = self._get(as_user, users[0], mes=7)  # a parcela de jul NÃO conta
        assert jul["maior_despesa"] is None
        assert jul["num_transacoes_total"] == 0

    def test_mes_vazio_campos_none_e_contagens_zero(self, users, as_user):
        body = self._get(as_user, users[0])
        assert body["maior_despesa"] is None
        assert body["dia_maior_gasto"] is None
        assert body["num_transacoes_total"] == 0
        assert body["num_lancadas"] == body["num_recorrentes"] == 0

    def test_mes_so_com_receitas_sem_destaques_mas_conta(self, session, users, as_user):
        _add_avista(session, users[0].id, dt.date(2026, 7, 3), tipo="receita",
                    valor="500.00")

        body = self._get(as_user, users[0])
        assert body["maior_despesa"] is None  # destaque é de DESPESA
        assert body["dia_maior_gasto"] is None
        assert body["num_transacoes_total"] == 1  # mas a movimentação conta

    def test_validacao_de_parametros(self, users, as_user):
        for params in ({"mes": 0, "ano": 2026}, {"mes": 13, "ano": 2026},
                       {"mes": 7, "ano": 1999}, {"mes": 7}, {}):
            resp = as_user(users[0]).get("/statistics/highlights", params=params)
            assert resp.status_code == 422, params


class TestCoverage:
    """GET /statistics/coverage — competências DISTINTAS com dado de CONSUMO
    até o corrente (florescimento do Resumo: ≥2 → S2, ≥3 → S3). Base consumo:
    parcelada 12x = UM mês (o da compra); vigência de recorrência expande em
    competências, clampada no corrente; futuro não conta. hoje congelado em
    15/07/2026 (fixture clock)."""

    def _coverage(self, as_user, user):
        resp = as_user(user).get("/statistics/coverage")
        assert resp.status_code == 200
        return resp.json()["meses_com_dados"]

    def test_sem_dados_zero(self, users, as_user):
        assert self._coverage(as_user, users[0]) == 0

    def test_competencias_distintas_nao_transacoes(self, session, users, as_user):
        # 2 transações no mesmo mês = 1 competência; + 1 noutro mês = 2.
        _add_avista(session, users[0].id, dt.date(2026, 6, 5))
        _add_avista(session, users[0].id, dt.date(2026, 6, 20))
        _add_avista(session, users[0].id, dt.date(2026, 7, 10))

        assert self._coverage(as_user, users[0]) == 2

    def test_parcelada_12x_conta_um_mes_nao_doze(self, session, users, as_user):
        # A justificativa da base CONSUMO: por fluxo seriam 12 competências
        # de fatura; o gasto aconteceu num mês só — o da compra.
        _add_parcelada(session, users[0].id, mes0=1)  # 12x desde jan/2026

        assert self._coverage(as_user, users[0]) == 1

    def test_vigencia_aberta_expande_ate_o_corrente(self, session, users, as_user):
        # desde abr/2026, sem fim: abr, mai, jun, jul (corrente) = 4 — o
        # futuro que a vigência aberta geraria NÃO conta.
        _add_recorrencia(session, users[0].id, dia=5, mes_inicio=4)

        assert self._coverage(as_user, users[0]) == 4

    def test_vigencia_fechada_no_passado_conta_o_periodo(self, session, users, as_user):
        _add_recorrencia(session, users[0].id, dia=5, mes_inicio=1,
                         mes_fim=3, ano_fim=2026)  # jan–mar

        assert self._coverage(as_user, users[0]) == 3

    def test_clamp_no_corrente_futuro_nao_conta(self, session, users, as_user):
        # Pós-datada DENTRO do corrente (20/jul > hoje 15) conta — a
        # competência é o corrente; ago/2026 e vigência a partir de out, não.
        _add_avista(session, users[0].id, dt.date(2026, 7, 20))
        _add_avista(session, users[0].id, dt.date(2026, 8, 10))
        _add_recorrencia(session, users[0].id, dia=5, mes_inicio=10)

        assert self._coverage(as_user, users[0]) == 1  # só jul

    def test_uniao_transacao_e_vigencia_sem_dupla_contagem(
        self, session, users, as_user
    ):
        # vigência mai–jun + transação em jun: {mai, jun} = 2, não 3.
        _add_recorrencia(session, users[0].id, dia=5, mes_inicio=5,
                         mes_fim=6, ano_fim=2026)
        _add_avista(session, users[0].id, dt.date(2026, 6, 10))

        assert self._coverage(as_user, users[0]) == 2

    def test_vigencia_fechada_no_futuro_clampa_no_corrente(
        self, session, users, as_user
    ):
        # jun–set: conta jun e jul (corrente); ago/set ficam para quando chegarem.
        _add_recorrencia(session, users[0].id, dia=5, mes_inicio=6,
                         mes_fim=9, ano_fim=2026)

        assert self._coverage(as_user, users[0]) == 2

    def test_isolamento_entre_usuarios(self, session, users, as_user):
        _add_avista(session, users[1].id, dt.date(2026, 6, 10))

        assert self._coverage(as_user, users[0]) == 0
        assert self._coverage(as_user, users[1]) == 1

    def test_florescimento_cresce_com_o_historico(self, session, users, as_user):
        # A régua do front na prática: 1 mês → só S1; 2 → S2; 3 → S3.
        _add_avista(session, users[0].id, dt.date(2026, 7, 10))
        assert self._coverage(as_user, users[0]) == 1
        _add_avista(session, users[0].id, dt.date(2026, 6, 10))
        assert self._coverage(as_user, users[0]) == 2
        _add_avista(session, users[0].id, dt.date(2026, 3, 10))
        assert self._coverage(as_user, users[0]) == 3


def _add_cartao(session, uid, nome="Nubank", tipo="Crédito"):
    c = Cartao(usuario_id=uid, nome=nome, tipo=tipo)
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


class TestSpendingByCard:
    """GET /statistics/spending-by-card — gasto por cartão do mês (Resumo,
    Seção 1 — PLANO_RESUMO), base CONSUMO. DESPESA-ONLY, agrupado por cartao_id
    CRU (crédito/débito/ambos, sem olhar Cartao.tipo); cartao_id NULL (PIX/à
    vista + recorrências) em `sem_cartao` (campo SEPARADO — cartoes fica limpo).
    Invariante: sum(cartoes)+sem_cartao == total == consumo.despesas do
    /monthly. hoje congelado em 15/07/2026 (fixture clock do módulo)."""

    def _get(self, as_user, user, mes=7, ano=2026):
        resp = as_user(user).get(
            "/statistics/spending-by-card", params={"mes": mes, "ano": ano}
        )
        assert resp.status_code == 200
        return resp.json()

    def _add_despesa_cartao(self, session, uid, data, valor, cartao_id,
                            forma="Crédito", categoria="Compras"):
        session.add(
            Transacao(
                usuario_id=uid, tipo="despesa", data=data, descricao="compra",
                valor=Decimal(valor), categoria=categoria,
                forma_pagamento=forma, cartao_id=cartao_id, parcelado=False,
            )
        )
        session.commit()

    def test_total_fecha_com_consumo_do_monthly(self, session, users, as_user):
        # INVARIANTE CENTRAL: sum(cartoes) + sem_cartao == total ==
        # consumo.despesas do /monthly (nada perdido nem duplicado). Cenário
        # misto: parcelada + avulsa no cartão 1, PIX e recorrência sem cartão.
        _add_cartao(session, users[0].id, nome="Nubank")            # id 1
        _add_parcelada(session, users[0].id, mes0=7)                # 1200 cheio, cartão 1
        self._add_despesa_cartao(session, users[0].id, dt.date(2026, 7, 8),
                                 "300.00", cartao_id=1)             # avulsa cartão 1
        _add_avista(session, users[0].id, dt.date(2026, 7, 10), valor="50.00")  # PIX
        _add_recorrencia(session, users[0].id, dia=5, tipo="despesa",
                         categoria="Moradia", valor="2000.00")      # sem cartão

        body = self._get(as_user, users[0])
        monthly = as_user(users[0]).get(
            "/statistics/monthly", params={"mes": 7, "ano": 2026}
        ).json()

        soma = sum((_q(c["total"]) for c in body["cartoes"]), Decimal("0.00"))
        assert soma + _q(body["sem_cartao"]) == _q(body["total"])
        assert _q(body["total"]) == _q(monthly["consumo"]["despesas"])
        # composição: cartão 1 = 1200 (pai cheia) + 300 (avulsa); sem cartão =
        # 50 (PIX) + 2000 (recorrência)
        assert _q(body["cartoes"][0]["total"]) == Decimal("1500.00")
        assert _q(body["sem_cartao"]) == Decimal("2050.00")

    def test_debito_no_cartao_cai_no_cartao_nao_em_sem_cartao(
        self, session, users, as_user
    ):
        # Agrupa por cartao_id CRU: compra no DÉBITO com cartao_id de um cartão
        # tipo Débito conta NAQUELE cartão, não em sem_cartao (não olha o tipo).
        _add_cartao(session, users[0].id, nome="Inter Débito", tipo="Débito")  # id 1
        self._add_despesa_cartao(session, users[0].id, dt.date(2026, 7, 10),
                                 "120.00", cartao_id=1, forma="Débito")

        body = self._get(as_user, users[0])
        assert _q(body["sem_cartao"]) == Decimal("0.00")
        assert len(body["cartoes"]) == 1
        assert body["cartoes"][0]["cartao_nome"] == "Inter Débito"
        assert _q(body["cartoes"][0]["total"]) == Decimal("120.00")

    def test_pix_a_vista_vai_para_sem_cartao(self, session, users, as_user):
        _add_avista(session, users[0].id, dt.date(2026, 7, 10), valor="75.00")

        body = self._get(as_user, users[0])
        assert body["cartoes"] == []
        assert _q(body["sem_cartao"]) == Decimal("75.00")
        assert _q(body["total"]) == Decimal("75.00")

    def test_parcelada_valor_cheio_no_cartao_nao_a_parcela(
        self, session, users, as_user
    ):
        # 12x no cartão 1 em jul → valor CHEIO (1200) no cartão em jul; a parcela
        # (100) não aparece (fatia de fluxo). Reusa o precedente do consumo.
        _add_cartao(session, users[0].id, nome="Nubank")  # id 1
        _add_parcelada(session, users[0].id, mes0=7)      # 1200/12x, cartão 1

        body = self._get(as_user, users[0])
        assert _q(body["cartoes"][0]["total"]) == Decimal("1200.00")  # cheio, não 100
        assert _q(body["sem_cartao"]) == Decimal("0.00")
        # a parcela de agosto NÃO vira consumo em ago (compra foi em jul)
        ago = self._get(as_user, users[0], mes=8)
        assert ago["cartoes"] == [] and _q(ago["sem_cartao"]) == Decimal("0.00")

    def test_ordenacao_por_total_desc(self, session, users, as_user):
        _add_cartao(session, users[0].id, nome="Cartão A")  # id 1
        _add_cartao(session, users[0].id, nome="Cartão B")  # id 2
        self._add_despesa_cartao(session, users[0].id, dt.date(2026, 7, 5),
                                 "100.00", cartao_id=1)
        self._add_despesa_cartao(session, users[0].id, dt.date(2026, 7, 6),
                                 "500.00", cartao_id=2)

        body = self._get(as_user, users[0])
        assert [c["cartao_nome"] for c in body["cartoes"]] == ["Cartão B", "Cartão A"]
        assert [_q(c["total"]) for c in body["cartoes"]] == [
            Decimal("500.00"), Decimal("100.00")
        ]

    def test_receita_no_cartao_nao_entra_despesa_only(self, session, users, as_user):
        # Despesa-only: uma receita atribuída a cartão (ex. estorno) não conta —
        # nem no cartão nem em sem_cartao; só a despesa entra.
        _add_cartao(session, users[0].id, nome="Nubank")  # id 1
        session.add(
            Transacao(
                usuario_id=users[0].id, tipo="receita", data=dt.date(2026, 7, 3),
                descricao="estorno", valor=Decimal("400.00"), categoria="Outros",
                forma_pagamento="Crédito", cartao_id=1, parcelado=False,
            )
        )
        session.commit()
        self._add_despesa_cartao(session, users[0].id, dt.date(2026, 7, 10),
                                 "60.00", cartao_id=1)

        body = self._get(as_user, users[0])
        assert _q(body["cartoes"][0]["total"]) == Decimal("60.00")
        assert _q(body["total"]) == Decimal("60.00")

    def test_mes_vazio_200_listas_e_zeros(self, users, as_user):
        body = self._get(as_user, users[0])
        assert body["cartoes"] == []
        assert _q(body["sem_cartao"]) == Decimal("0.00")
        assert _q(body["total"]) == Decimal("0.00")

    def test_isolamento_entre_usuarios(self, session, users, as_user):
        _add_cartao(session, users[1].id, nome="Do B")  # id 1, user B
        self._add_despesa_cartao(session, users[1].id, dt.date(2026, 7, 10),
                                 "90.00", cartao_id=1)

        body = self._get(as_user, users[0])
        assert body["cartoes"] == [] and _q(body["sem_cartao"]) == Decimal("0.00")

    def test_validacao_de_parametros(self, users, as_user):
        for params in ({"mes": 0, "ano": 2026}, {"mes": 13, "ano": 2026},
                       {"mes": 7, "ano": 1999}, {"mes": 7}, {}):
            resp = as_user(users[0]).get(
                "/statistics/spending-by-card", params=params
            )
            assert resp.status_code == 422, params
