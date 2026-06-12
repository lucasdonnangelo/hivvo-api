"""Testes de app/services/parcelas.py (_criar_parcelas) via sessão SQLite em memória.

Regra de arredondamento (decisão fixa, Hivvo_Referencia §5): valor/n com
ROUND_HALF_UP em 2 casas; a ÚLTIMA parcela absorve a diferença.
SQLite coage Numeric para float — todo valor monetário lido do banco é
normalizado com Decimal(str(x)) antes de comparar.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.transaction import Transacao
from app.services.parcelas import _criar_parcelas


def make_transacao(session, valor: str, total_parcelas: int, data=dt.date(2026, 1, 15), cartao_id=None):
    transacao = Transacao(
        usuario_id=1,
        tipo="despesa",
        data=data,
        descricao="Compra Teste",
        valor=Decimal(valor),
        categoria="Compras",
        forma_pagamento="Crédito",
        cartao_id=cartao_id,
        parcelado=True,
        total_parcelas=total_parcelas,
    )
    session.add(transacao)
    session.commit()
    session.refresh(transacao)
    return transacao


def parcelas_do_banco(session, transacao_id: int) -> list[Parcela]:
    return session.exec(
        select(Parcela)
        .where(Parcela.transacao_id == transacao_id)
        .order_by(Parcela.numero_parcela)
    ).all()


def valores(parcelas: list[Parcela]) -> list[Decimal]:
    return [Decimal(str(p.valor_parcela)) for p in parcelas]


class TestDivisaoExata:
    def test_valores_e_soma(self, session):
        transacao = make_transacao(session, "1200.00", 12)
        retorno = _criar_parcelas(session, transacao, None)

        parcelas = parcelas_do_banco(session, transacao.id)
        assert retorno == 12
        assert len(parcelas) == 12
        assert valores(parcelas) == [Decimal("100.00")] * 12
        assert sum(valores(parcelas)) == Decimal("1200.00")

    def test_campos_derivados(self, session):
        transacao = make_transacao(session, "1200.00", 12, data=dt.date(2026, 1, 15))
        _criar_parcelas(session, transacao, None)

        parcelas = parcelas_do_banco(session, transacao.id)
        for i, p in enumerate(parcelas, start=1):
            assert p.numero_parcela == i
            assert p.total_parcelas == 12
            assert p.descricao == f"Compra Teste ({i}/12)"
            assert p.categoria == "Compras"
            assert p.usuario_id == 1
            # fatura derivada da data de VENCIMENTO da parcela
            assert p.fatura_mes == p.data_vencimento.month
            assert p.fatura_ano == p.data_vencimento.year

    def test_vencimentos_sem_cartao(self, session):
        transacao = make_transacao(session, "300.00", 3, data=dt.date(2025, 11, 30))
        _criar_parcelas(session, transacao, None)

        parcelas = parcelas_do_banco(session, transacao.id)
        # compra + i meses, com clamp (30/11 + 3 = 28/02/2026)
        assert [p.data_vencimento for p in parcelas] == [
            dt.date(2025, 12, 30),
            dt.date(2026, 1, 30),
            dt.date(2026, 2, 28),
        ]


class TestArredondamento:
    def test_dizima_ultima_absorve_para_cima(self, session):
        # 100/3 = 33.333… → base 33.33; última = 100 − 66.66 = 33.34
        transacao = make_transacao(session, "100.00", 3)
        _criar_parcelas(session, transacao, None)

        vals = valores(parcelas_do_banco(session, transacao.id))
        assert vals == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
        assert sum(vals) == Decimal("100.00")

    def test_base_arredonda_para_cima_ultima_absorve_para_baixo(self, session):
        # 0.50/3 = 0.1667 → base 0.17 (ROUND_HALF_UP); última = 0.50 − 0.34 = 0.16
        transacao = make_transacao(session, "0.50", 3)
        _criar_parcelas(session, transacao, None)

        vals = valores(parcelas_do_banco(session, transacao.id))
        assert vals == [Decimal("0.17"), Decimal("0.17"), Decimal("0.16")]
        assert sum(vals) == Decimal("0.50")

    def test_soma_sempre_igual_ao_valor_total(self, session):
        casos = [("1000.00", 7), ("99.99", 4), ("2543.17", 11), ("10.00", 6)]
        for valor, n in casos:
            transacao = make_transacao(session, valor, n)
            _criar_parcelas(session, transacao, None)
            vals = valores(parcelas_do_banco(session, transacao.id))
            assert len(vals) == n
            assert sum(vals) == Decimal(valor), f"caso {valor} em {n}x"


class TestComCartao:
    def test_ciclo_do_cartao_aplicado(self, session):
        card = Cartao(
            usuario_id=1,
            nome="Nubank",
            tipo="Crédito",
            dia_fechamento=3,
            dia_vencimento=10,
            mes_offset_vencimento=1,
        )
        session.add(card)
        session.commit()
        session.refresh(card)

        # compra 15/01 (após fechamento dia 3) → 1ª fatura fev → vencimento 10/03
        transacao = make_transacao(session, "600.00", 2, data=dt.date(2026, 1, 15), cartao_id=card.id)
        _criar_parcelas(session, transacao, card)

        parcelas = parcelas_do_banco(session, transacao.id)
        assert [p.data_vencimento for p in parcelas] == [dt.date(2026, 3, 10), dt.date(2026, 4, 10)]
        assert [(p.fatura_mes, p.fatura_ano) for p in parcelas] == [(3, 2026), (4, 2026)]
        assert all(p.cartao_id == card.id for p in parcelas)
        assert sum(valores(parcelas)) == Decimal("600.00")


class TestT33ValorPequeno:
    def test_valor_abaixo_de_um_centavo_por_parcela_levanta_valueerror(self, session):
        # R$ 0,10 em 12×: base 0.01, última seria 0.10 − 0.11 = −0.01.
        # Comportamento correto (Batch 3a): o service rejeita antes de criar
        # qualquer parcela — invariante "nenhuma parcela <= 0".
        transacao = make_transacao(session, "0.10", 12)
        with pytest.raises(ValueError, match="pelo menos R\\$ 0,01"):
            _criar_parcelas(session, transacao, None)

        assert parcelas_do_banco(session, transacao.id) == []

    def test_limite_exato_um_centavo_por_parcela_aceito(self, session):
        # R$ 0,12 em 12× é o mínimo válido: 12 parcelas de R$ 0,01.
        transacao = make_transacao(session, "0.12", 12)
        _criar_parcelas(session, transacao, None)

        vals = valores(parcelas_do_banco(session, transacao.id))
        assert vals == [Decimal("0.01")] * 12
        assert all(v > Decimal("0.00") for v in vals)
