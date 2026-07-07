"""§1.3.1 no endpoint — GET /statistics/monthly com realizado/a_vir.

Topo da resposta = PROJEÇÃO integral (shape antigo preservado); realizado e
a_vir são a decomposição do mês corrente pelo dia. hoje congelado em
15/07/2026 via patch em app.services.estatisticas.hoje (onde a marcação vive).
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.models.installment import Parcela
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.models.transaction import Transacao

HOJE = dt.date(2026, 7, 15)


def _q(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


@pytest.fixture(autouse=True)
def clock(mocker):
    mocker.patch("app.services.estatisticas.hoje", return_value=HOJE)


def _add_recorrencia(session, uid, dia, valor="10000.00", mes_inicio=1, ano_inicio=2026):
    rec = Recorrencia(
        usuario_id=uid, tipo="receita", categoria="Salário",
        forma_pagamento="Pix", dia_do_mes=dia, descricao="Salário",
    )
    session.add(rec)
    session.flush()
    session.add(
        RecorrenciaVigencia(
            recorrencia_id=rec.id, valor=Decimal(valor),
            mes_inicio=mes_inicio, ano_inicio=ano_inicio,
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
                   categoria="Eletrônicos"):
    """Pai parcelada (data no dia 15 de mes0/ano0) + n parcelas por competência."""
    total = Decimal(valor_total)
    pai = Transacao(
        usuario_id=uid, tipo="despesa", data=dt.date(ano0, mes0, 15),
        descricao="compra parcelada", valor=total, categoria=categoria,
        forma_pagamento="Crédito", cartao_id=1, parcelado=True, total_parcelas=n,
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
                descricao="compra parcelada", categoria=categoria, cartao_id=1,
                fatura_mes=m, fatura_ano=a,
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
