"""§1.3.1 no endpoint — GET /statistics/monthly com realizado/a_vir.

Topo da resposta = PROJEÇÃO integral (shape antigo preservado); realizado e
a_vir são a decomposição do mês corrente pelo dia. hoje congelado em
15/07/2026 via patch em app.services.estatisticas.hoje (onde a marcação vive).
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlmodel import select

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

    def test_parcela_pago_obsoleto_nao_mexe_em_nada(self, session, users, as_user):
        # Parcela.pago está MORTO na camada de estatísticas: alternar a coluna
        # obsoleta não muda a resposta INTEIRA do /monthly — nem o a_pagar.
        _add_parcelada(session, users[0].id)

        def _monthly():
            return as_user(users[0]).get(
                "/statistics/monthly", params={"mes": 7, "ano": 2026}
            ).json()

        antes = _monthly()
        parcela_jul = session.exec(
            select(Parcela).where(Parcela.fatura_mes == 7, Parcela.fatura_ano == 2026)
        ).one()
        parcela_jul.pago = True
        parcela_jul.data_pagamento = HOJE
        session.add(parcela_jul)
        session.commit()
        depois = _monthly()

        assert _q(antes["a_pagar"]) == Decimal("100.00")
        assert antes == depois  # resposta byte a byte igual, a_pagar incluso


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
