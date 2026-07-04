"""§1.3.1 no endpoint — GET /statistics/monthly com realizado/a_vir.

Topo da resposta = PROJEÇÃO integral (shape antigo preservado); realizado e
a_vir são a decomposição do mês corrente pelo dia. hoje congelado em
15/07/2026 via patch em app.services.estatisticas.hoje (onde a marcação vive).
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.models.recorrencia import Recorrencia, RecorrenciaVigencia

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
