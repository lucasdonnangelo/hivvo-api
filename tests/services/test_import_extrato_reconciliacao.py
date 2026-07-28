"""Balance walk do extrato — os três estados (BATE com rendimento / NÃO BATE /
N/A sem saldos) e o rendimento entrando no cálculo.

MUTAÇÃO: remover `+ rendimento` do walk (reconciliacao.py) faz
test_walk_bate_com_rendimento FALHAR — o fixture só fecha COM o rendimento.
"""

from decimal import Decimal

from app.schemas.import_extrato import ExtratoExtraido
from app.services.import_extrato.reconciliacao import TOLERANCIA, reconciliar
from tests.fixtures.extratos_validados import EXTRATO_COM_RENDIMENTO


def _extrato(linhas, saldo_inicial=None, saldo_final=None, rendimento="0.00"):
    return ExtratoExtraido.model_validate(
        {
            "banco": "Sintético",
            "saldo_inicial": saldo_inicial,
            "saldo_final": saldo_final,
            "rendimento": rendimento,
            "linhas": [
                {"data": "2026-06-01", "descricao": d, "valor": v, "balde": b}
                for d, v, b in linhas
            ],
        }
    )


def test_walk_bate_com_rendimento():
    rec = reconciliar(ExtratoExtraido.model_validate(EXTRATO_COM_RENDIMENTO), TOLERANCIA)

    assert rec.aplicavel is True
    assert rec.rendimento == Decimal("4.56")
    assert rec.soma_receitas == Decimal("500.00")
    assert rec.soma_debitos == Decimal("120.00")
    assert rec.soma_pagamentos == Decimal("200.00")
    # 1000.00 + 4.56 + 500 − 120 − 200 = 1184.56
    assert rec.saldo_final_calc == Decimal("1184.56")
    assert rec.saldo_final_declarado == Decimal("1184.56")
    assert rec.diferenca == Decimal("0.00")
    assert rec.bate is True


def test_walk_sem_o_rendimento_no_calculo_nao_fecharia():
    # Guarda explícita do ACHADO 1: o MESMO extrato, com rendimento "0.00",
    # NÃO bate — prova que o rendimento é o que fecha (o oposto da mutação).
    dados = {**EXTRATO_COM_RENDIMENTO, "rendimento": "0.00"}
    rec = reconciliar(ExtratoExtraido.model_validate(dados), TOLERANCIA)
    assert rec.diferenca == Decimal("-4.56")
    assert rec.bate is False


def test_walk_nao_bate_com_linha_faltando():
    # falta a receita de 500 -> não fecha
    rec = reconciliar(
        _extrato(
            [("Compra", "120.00", "debito"), ("Pgto fatura", "200.00", "pagamento_fatura")],
            saldo_inicial="1000.00",
            saldo_final="1184.56",
            rendimento="4.56",
        ),
        TOLERANCIA,
    )
    assert rec.bate is False
    assert rec.diferenca == Decimal("-500.00")


def test_walk_na_quando_faltam_saldos():
    rec = reconciliar(
        _extrato([("Pix recebido", "500.00", "receita")]),  # sem saldos
        TOLERANCIA,
    )
    assert rec.aplicavel is False
    assert rec.bate is False  # N/A nunca "bate"


def test_walk_na_com_apenas_um_saldo():
    # só saldo_inicial -> ainda N/A (precisa dos dois)
    rec = reconciliar(
        _extrato([("Pix", "500.00", "receita")], saldo_inicial="1000.00"),
        TOLERANCIA,
    )
    assert rec.aplicavel is False
    assert rec.bate is False


def test_pagamento_fatura_entra_no_walk_como_saida():
    # pagamento_fatura NÃO é consumo, mas É saída de caixa: sai do saldo.
    rec = reconciliar(
        _extrato(
            [("Pgto fatura", "300.00", "pagamento_fatura")],
            saldo_inicial="1000.00",
            saldo_final="700.00",
        ),
        TOLERANCIA,
    )
    assert rec.soma_pagamentos == Decimal("300.00")
    assert rec.bate is True


def test_fronteira_da_tolerancia():
    # exatamente na tolerância (R$ 0,02) ainda bate...
    na_borda = _extrato(
        [("Pix", "100.00", "receita")], saldo_inicial="0.00", saldo_final="99.98"
    )
    assert reconciliar(na_borda, TOLERANCIA).bate is True

    # ...um centavo além, não
    passou = _extrato(
        [("Pix", "100.00", "receita")], saldo_inicial="0.00", saldo_final="99.97"
    )
    assert reconciliar(passou, TOLERANCIA).bate is False
