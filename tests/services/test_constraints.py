"""Batch 6 / T-11 — constraints de integridade aplicadas no banco.

Reforço além do Pydantic: inserir dado inválido via ORM deve falhar no commit.
SQLite (do fixture `session`) enforça CHECK e UNIQUE; estas mesmas constraints
vão para o Postgres via migration. FK não é exercitada aqui (SQLite não a
enforça por padrão) — cascade do T-14 é coberto pela migration, não por teste.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.installment import Parcela
from app.models.transaction import Transacao


def _tx(session, **over):
    defaults = dict(
        usuario_id=1,
        tipo="despesa",
        data=dt.date(2026, 1, 15),
        descricao="x",
        valor=Decimal("10.00"),
        categoria="Compras",
    )
    defaults.update(over)
    session.add(Transacao(**defaults))


def _parc(session, **over):
    defaults = dict(
        usuario_id=1,
        transacao_id=1,
        numero_parcela=1,
        total_parcelas=3,
        valor_parcela=Decimal("10.00"),
        data_vencimento=dt.date(2026, 2, 10),
        descricao="x",
        categoria="Compras",
    )
    defaults.update(over)
    session.add(Parcela(**defaults))


class TestT11Transacoes:
    def test_valor_zero_rejeitado(self, session):
        _tx(session, valor=Decimal("0.00"))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_valor_negativo_rejeitado(self, session):
        _tx(session, valor=Decimal("-1.00"))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_valor_nulo_rejeitado(self, session):
        _tx(session, valor=None)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_tipo_invalido_rejeitado(self, session):
        _tx(session, tipo="investimento")
        with pytest.raises(IntegrityError):
            session.commit()

    def test_fatura_mes_fora_intervalo_rejeitado(self, session):
        _tx(session, fatura_mes=13)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_fatura_mes_nulo_aceito(self, session):
        _tx(session, fatura_mes=None)
        session.commit()  # avulsa sem cartão — não levanta

    def test_valido_passa(self, session):
        _tx(session, tipo="receita", valor=Decimal("100.00"), fatura_mes=12)
        session.commit()


class TestT11Parcelas:
    def test_valor_parcela_zero_rejeitado(self, session):
        _parc(session, valor_parcela=Decimal("0.00"))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_numero_parcela_maior_que_total_rejeitado(self, session):
        _parc(session, numero_parcela=5, total_parcelas=3)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_fatura_mes_fora_intervalo_rejeitado(self, session):
        _parc(session, fatura_mes=0)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_unique_transacao_numero_parcela(self, session):
        _parc(session, transacao_id=99, numero_parcela=1)
        session.commit()
        _parc(session, transacao_id=99, numero_parcela=1)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_mesma_numero_em_transacoes_distintas_passa(self, session):
        _parc(session, transacao_id=1, numero_parcela=1)
        _parc(session, transacao_id=2, numero_parcela=1)
        session.commit()  # UNIQUE é por (transacao_id, numero_parcela)
