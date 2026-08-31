"""Contrato do extrato: baldes, magnitude do valor, cartao_citado só em
pagamento_fatura, rendimento com default, normalização decimal e datas ISO."""

import pytest
from pydantic import ValidationError

from app.schemas.import_extrato import Balde, ExtratoExtraido, LinhaExtrato


def _linha(**over):
    base = {
        "data": "2026-06-05",
        "descricao": "Pix recebido",
        "valor": "500.00",
        "balde": "receita",
    }
    base.update(over)
    return LinhaExtrato.model_validate(base)


def test_valor_vira_magnitude_positiva_independente_do_sinal_impresso():
    # O modelo pode mandar o sinal impresso (débito negativo); a direção vem do
    # balde, então o valor é sempre magnitude positiva.
    assert _linha(valor="-120.00", balde="debito").valor == "120.00"
    assert _linha(valor="120,00", balde="debito").valor == "120.00"
    assert _linha(valor="R$ 1.234,56", balde="receita").valor == "1234.56"


def test_cartao_citado_so_sobrevive_em_pagamento_fatura():
    # fora de pagamento_fatura, é zerado (dado limpo)
    assert _linha(balde="receita", cartao_citado="Nubank").cartao_citado is None
    assert _linha(balde="debito", cartao_citado="Nubank").cartao_citado is None
    # dentro, é preservado; string vazia normaliza para None
    assert _linha(balde="pagamento_fatura", cartao_citado="Nubank").cartao_citado == "Nubank"
    assert _linha(balde="pagamento_fatura", cartao_citado="  ").cartao_citado is None


def test_balde_invalido_rejeitado():
    with pytest.raises(ValidationError):
        _linha(balde="investimento")


def test_data_nao_iso_rejeitada():
    with pytest.raises(ValidationError):
        _linha(data="05/06/2026")


def test_rendimento_default_quando_ausente():
    extrato = ExtratoExtraido.model_validate(
        {"banco": "Nubank", "linhas": []}
    )
    assert extrato.rendimento == "0.00"
    assert extrato.saldo_inicial is None
    assert extrato.saldo_final is None


def test_rendimento_e_saldos_normalizam_e_preservam_sinal():
    extrato = ExtratoExtraido.model_validate(
        {
            "banco": "Nubank",
            "saldo_inicial": "-60,00",
            "saldo_final": "R$ 1.234,56",
            "rendimento": "4,56",
            "linhas": [],
        }
    )
    assert extrato.saldo_inicial == "-60.00"  # conta negativa preserva sinal
    assert extrato.saldo_final == "1234.56"
    assert extrato.rendimento == "4.56"


def test_valor_nao_parseavel_rejeitado():
    with pytest.raises(ValidationError):
        _linha(valor="abc")
