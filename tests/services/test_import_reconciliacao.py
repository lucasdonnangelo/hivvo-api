"""Reconciliação da importação — fixtures com os números REAIS validados no
spike (17/07): Nubank 233,85 e Itaú 88,40, ambos batendo no cheque primário.
"""

from decimal import Decimal

from app.schemas.import_fatura import FaturaExtraida
from app.services.import_fatura.reconciliacao import TOLERANCIA, reconciliar
from tests.fixtures.faturas_validadas import ITAU, NUBANK


def _fatura_minima(transacoes, total_compras, iof="0.00", a_pagar=None):
    return FaturaExtraida.model_validate(
        {
            "banco": "Sintético",
            "competencia": {"mes": 7, "ano": 2026},
            "total_a_pagar": a_pagar if a_pagar is not None else total_compras,
            "total_compras_periodo": total_compras,
            "total_iof_periodo": iof,
            "transacoes": [
                {"data": "2026-07-01", "descricao": d, "valor_brl": v, "tipo": t}
                for d, v, t in transacoes
            ],
        }
    )


def test_nubank_real_bate_no_primario_e_nao_no_secundario():
    rec = reconciliar(FaturaExtraida.model_validate(NUBANK), TOLERANCIA)

    assert rec.ancora == Decimal("233.85")  # 230.00 compras + 3.85 IOF declarados
    assert rec.soma_gastos == Decimal("233.85")
    assert rec.diferenca == Decimal("0.00")
    assert rec.bate is True

    # O pagamento de 12/06 é do ciclo ANTERIOR: o secundário NÃO bater aqui é
    # o comportamento validado no run real — não um bug (por isso o secundário
    # é diagnóstico, nunca gate).
    assert rec.excluidos == Decimal("-60.00")
    assert rec.total_a_pagar == Decimal("233.85")
    assert rec.diferenca_secundaria == Decimal("-60.00")
    assert rec.bate_secundario is False


def test_itau_real_iof_embutido_e_fatura_quitada():
    rec = reconciliar(FaturaExtraida.model_validate(ITAU), TOLERANCIA)

    # IOF embutido no total de compras => total_iof_periodo "0.00"
    assert rec.ancora == Decimal("88.40")
    assert rec.soma_gastos == Decimal("88.40")
    assert rec.diferenca == Decimal("0.00")
    assert rec.bate is True

    # Fatura já quitada (a pagar 0.00): ancorar no "a pagar" daria falso NÃO
    # BATE — a âncora certa é o consumo bruto declarado. Secundário fecha.
    assert rec.excluidos == Decimal("-88.40")
    assert rec.total_a_pagar == Decimal("0.00")
    assert rec.diferenca_secundaria == Decimal("0.00")
    assert rec.bate_secundario is True


def test_estorno_e_compra_negativa_que_abate_os_gastos():
    fatura = _fatura_minima(
        [
            ("Compra qualquer", "100.00", "compra"),
            ("Estorno de compra qualquer", "-30.00", "compra"),
        ],
        total_compras="70.00",
    )
    rec = reconciliar(fatura, TOLERANCIA)
    assert rec.soma_gastos == Decimal("70.00")
    assert rec.bate is True


def test_nao_bate_quando_falta_linha_em_relacao_ao_declarado():
    incompleta = {**NUBANK, "transacoes": NUBANK["transacoes"][1:]}  # sem a de 120.00
    rec = reconciliar(FaturaExtraida.model_validate(incompleta), TOLERANCIA)
    assert rec.bate is False
    assert rec.diferenca == Decimal("-120.00")


def test_fronteira_da_tolerancia():
    # exatamente na tolerância (R$ 0,02) ainda bate...
    na_borda = _fatura_minima([("Compra", "99.98", "compra")], total_compras="100.00")
    assert reconciliar(na_borda, TOLERANCIA).bate is True

    # ...um centavo além, não
    passou = _fatura_minima([("Compra", "99.97", "compra")], total_compras="100.00")
    assert reconciliar(passou, TOLERANCIA).bate is False
