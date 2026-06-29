"""Batch 6 / T-10 — _buscar_mes com range de datas (sargável).

A troca de extract(month/year) por range [1º dia do mês, 1º dia do mês seguinte)
deve retornar EXATAMENTE as mesmas linhas de antes, incluindo a borda dez→jan.
"""

import datetime as dt
from decimal import Decimal

from app.models.transaction import Transacao
from app.services.estatisticas import _buscar_mes


def _add(session, data: dt.date, uid: int = 1):
    session.add(
        Transacao(
            usuario_id=uid,
            tipo="despesa",
            data=data,
            descricao=data.isoformat(),
            valor=Decimal("10.00"),
            categoria="Compras",
        )
    )


class TestBuscarMesT10:
    def test_retorna_apenas_o_mes_pedido(self, session):
        _add(session, dt.date(2025, 11, 30))  # mês anterior
        _add(session, dt.date(2025, 12, 1))  # primeiro dia (inclusivo)
        _add(session, dt.date(2025, 12, 31))  # último dia (inclusivo)
        _add(session, dt.date(2026, 1, 1))  # mês seguinte (exclusivo)
        session.commit()

        rows = _buscar_mes(session, 1, 12, 2025)
        assert sorted(t.data for t in rows) == [dt.date(2025, 12, 1), dt.date(2025, 12, 31)]

    def test_borda_dezembro_para_janeiro(self, session):
        _add(session, dt.date(2025, 12, 31))
        _add(session, dt.date(2026, 1, 1))
        session.commit()

        dez = _buscar_mes(session, 1, 12, 2025)
        jan = _buscar_mes(session, 1, 1, 2026)
        assert [t.data for t in dez] == [dt.date(2025, 12, 31)]
        assert [t.data for t in jan] == [dt.date(2026, 1, 1)]

    def test_fevereiro_bissexto(self, session):
        _add(session, dt.date(2024, 2, 29))  # 2024 é bissexto
        _add(session, dt.date(2024, 3, 1))
        session.commit()

        fev = _buscar_mes(session, 1, 2, 2024)
        assert [t.data for t in fev] == [dt.date(2024, 2, 29)]

    def test_isolamento_por_usuario(self, session):
        _add(session, dt.date(2026, 5, 10), uid=1)
        _add(session, dt.date(2026, 5, 11), uid=2)
        session.commit()

        rows = _buscar_mes(session, 1, 5, 2026)  # uid=1
        assert [t.data for t in rows] == [dt.date(2026, 5, 10)]
