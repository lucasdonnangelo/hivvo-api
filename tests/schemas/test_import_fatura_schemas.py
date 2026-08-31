"""Rejeições e normalizações do schema da importação (porte do spike)."""

import pytest
from pydantic import ValidationError

from app.schemas.import_fatura import (
    Competencia,
    FaturaExtraida,
    ParcelaInfo,
    Transacao,
    normalizar_decimal,
)


@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ("3.412,88", "3412.88"),
        ("3412.88", "3412.88"),
        ("-60,00", "-60.00"),
        ("R$ 1.234,56", "1234.56"),
        ("0,00", "0.00"),
    ],
)
def test_normalizar_decimal_formatos_brasileiros(bruto, esperado):
    assert normalizar_decimal(bruto) == esperado


def test_normalizar_decimal_rejeita_o_que_nao_parseia():
    with pytest.raises(ValueError, match="não parseável"):
        normalizar_decimal("R$ abc")


def _transacao(**overrides):
    base = {
        "data": "2026-07-02",
        "descricao": "Compra",
        "valor_brl": "10.00",
        "tipo": "compra",
    }
    return {**base, **overrides}


def test_transacao_rejeita_data_nao_iso():
    with pytest.raises(ValidationError):
        Transacao.model_validate(_transacao(data="02/07/2026"))


def test_transacao_normaliza_valor_pt_br():
    t = Transacao.model_validate(_transacao(valor_brl="1.234,56"))
    assert t.valor_brl == "1234.56"


def test_transacao_rejeita_tipo_desconhecido():
    with pytest.raises(ValidationError):
        Transacao.model_validate(_transacao(tipo="cashback"))


@pytest.mark.parametrize(("indice", "total"), [(5, 3), (0, 3)])
def test_parcela_indice_fora_do_total(indice, total):
    with pytest.raises(ValidationError, match="parcela inconsistente"):
        ParcelaInfo.model_validate({"indice": indice, "total": total})


def test_parcela_no_limite_do_total_passa():
    p = ParcelaInfo.model_validate({"indice": 3, "total": 3})
    assert (p.indice, p.total) == (3, 3)


@pytest.mark.parametrize("mes", [0, 13])
def test_competencia_mes_invalido(mes):
    with pytest.raises(ValidationError, match="mês fora de 1..12"):
        Competencia.model_validate({"mes": mes, "ano": 2026})


def test_fatura_normaliza_totais_declarados():
    fatura = FaturaExtraida.model_validate(
        {
            "banco": "Sintético",
            "competencia": {"mes": 7, "ano": 2026},
            "total_a_pagar": "233,85",
            "total_compras_periodo": "R$ 230,00",
            "total_iof_periodo": "3,85",
            "transacoes": [],
        }
    )
    assert fatura.total_a_pagar == "233.85"
    assert fatura.total_compras_periodo == "230.00"
    assert fatura.total_iof_periodo == "3.85"


def test_fatura_rejeita_campo_obrigatorio_ausente():
    with pytest.raises(ValidationError):
        FaturaExtraida.model_validate({"banco": "Sintético"})
