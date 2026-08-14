"""O "hoje" do job é America/Sao_Paulo, não UTC (#6, Batch 1).

O servidor de produção roda em UTC. Um job disparado de madrugada em UTC está
no DIA ANTERIOR em Brasília: entre 21h e meia-noite, `date.today()` do
servidor já é amanhã. O aviso sairia com o alvo errado — e sem erro nenhum,
porque um dia deslocado é uma data perfeitamente válida.

`core.dates.hoje()` (America/Sao_Paulo) é a fonte única disso, e é o que o
script usa. Estes testes provam que duas execuções em INSTANTES UTC muito
diferentes, mas no mesmo dia de Brasília, resolvem o MESMO dia — e que a
virada acontece à meia-noite de São Paulo, não à de Greenwich.
"""

import datetime as dt

import pytest

from app.core import dates
from app.services.notificacoes.consulta import DIAS_DE_ANTECEDENCIA

UTC = dt.timezone.utc


@pytest.fixture()
def relogio(mocker):
    """Congela o instante UTC que `hoje()` enxerga.

    `hoje()` chama `dt.datetime.now(TZ_PRODUTO)`, e o `now(tz)` do CPython
    converte para o fuso pedido — é exatamente essa conversão que está sob
    teste, então o duplo reproduz o comportamento real com `astimezone`.
    """

    def _congelar(instante_utc: dt.datetime):
        falso = mocker.patch.object(dates.dt, "datetime", wraps=dt.datetime)
        falso.now.side_effect = lambda tz=None: instante_utc.astimezone(tz)

    return _congelar


class TestHojeSegueSaoPaulo:
    def test_madrugada_utc_ainda_e_o_dia_anterior_em_brasilia(self, relogio):
        # 14/08 02:30 UTC == 13/08 23:30 em São Paulo (UTC-3).
        relogio(dt.datetime(2026, 8, 14, 2, 30, tzinfo=UTC))

        assert dates.hoje() == dt.date(2026, 8, 13)

    def test_meio_dia_utc_do_mesmo_dia_de_brasilia(self, relogio):
        # 13/08 15:00 UTC == 13/08 12:00 em São Paulo.
        relogio(dt.datetime(2026, 8, 13, 15, 0, tzinfo=UTC))

        assert dates.hoje() == dt.date(2026, 8, 13)

    def test_a_virada_e_a_meia_noite_de_sao_paulo(self, relogio):
        # 14/08 03:00 UTC == 14/08 00:00 em São Paulo — agora sim virou.
        relogio(dt.datetime(2026, 8, 14, 3, 0, tzinfo=UTC))

        assert dates.hoje() == dt.date(2026, 8, 14)


def test_fronteira_de_fuso_resolve_o_mesmo_alvo(relogio):
    """Duas execuções, o mesmo aviso.

    Perto da meia-noite UTC e ao meio-dia: mesmo dia em Brasília, logo o mesmo
    `hoje`, o mesmo alvo de vencimento e a mesma `data_referencia` do guard —
    a segunda execução cai no UNIQUE em vez de mandar um segundo e-mail.
    Em UTC os dois instantes seriam 14/08 e 13/08: dias diferentes, alvos
    diferentes, e o guard de um não barraria o outro.
    """
    relogio(dt.datetime(2026, 8, 14, 2, 30, tzinfo=UTC))
    hoje_madrugada = dates.hoje()

    relogio(dt.datetime(2026, 8, 13, 15, 0, tzinfo=UTC))
    hoje_meio_dia = dates.hoje()

    assert hoje_madrugada == hoje_meio_dia == dt.date(2026, 8, 13)

    alvos = {h + dt.timedelta(days=DIAS_DE_ANTECEDENCIA) for h in (hoje_madrugada, hoje_meio_dia)}
    assert alvos == {dt.date(2026, 8, 16)}

    # E o contraste que explica por que isso importa: em UTC, os dois
    # instantes cairiam em dias diferentes.
    assert dt.datetime(2026, 8, 14, 2, 30, tzinfo=UTC).date() != dt.datetime(
        2026, 8, 13, 15, 0, tzinfo=UTC
    ).date()
