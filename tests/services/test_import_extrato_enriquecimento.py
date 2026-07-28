"""Matchers PUROS do enriquecimento do extrato (Batch 2) — sem banco, sem rede.

Cobre as três decisões que o preview propõe: qual cartão é o emissor citado, qual
competência um pagamento quita, e se uma receita já é explicada por uma
recorrência.

VERIFICAÇÃO POR MUTAÇÃO (o teste do "não casa" é o alvo): afrouxar
`casar_recorrencia` — ignorar o valor OU ignorar o dia — faz
`test_nao_casa_por_valor_fora_da_tolerancia` /
`test_nao_casa_por_dia_fora_da_janela` FALHAREM.
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.models.card import Cartao
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.services.import_extrato.enriquecimento import (
    casar_cartoes_por_nome,
    casar_recorrencia,
    competencias_candidatas,
)


def _cartao(nome: str, *, dia_vencimento: int = 13, id: int = 1) -> Cartao:
    return Cartao(
        id=id,
        usuario_id=1,
        nome=nome,
        tipo="Crédito",
        dia_vencimento=dia_vencimento,
        dia_fechamento=5,
        mes_offset_vencimento=1,
    )


def _recorrencia(
    *,
    tipo: str = "receita",
    dia_do_mes: int = 5,
    valor: str = "5000.00",
    mes_inicio: int = 1,
    ano_inicio: int = 2026,
    mes_fim: int | None = None,
    ano_fim: int | None = None,
) -> tuple[Recorrencia, list[RecorrenciaVigencia]]:
    rec = Recorrencia(
        usuario_id=1,
        tipo=tipo,
        categoria="Salário",
        forma_pagamento="Pix",
        dia_do_mes=dia_do_mes,
        descricao="Salário ACME",
    )
    vigencia = RecorrenciaVigencia(
        recorrencia_id=rec.id,
        valor=Decimal(valor),
        mes_inicio=mes_inicio,
        ano_inicio=ano_inicio,
        mes_fim=mes_fim,
        ano_fim=ano_fim,
    )
    return rec, [vigencia]


# --- casar_cartoes_por_nome ---------------------------------------------------


def test_citado_casa_cartao_mais_especifico():
    cartoes = [_cartao("Nubank Ultravioleta", id=1), _cartao("Itaú Click", id=2)]
    assert [c.id for c in casar_cartoes_por_nome(cartoes, "Nubank")] == [1]


def test_cartao_casa_citado_mais_especifico():
    """Contenção nos dois sentidos: o extrato pode ser mais específico que o cadastro."""
    cartoes = [_cartao("Nubank", id=1)]
    assert [c.id for c in casar_cartoes_por_nome(cartoes, "Nubank Ultravioleta")] == [1]


def test_acento_e_caixa_nao_impedem_o_casamento():
    cartoes = [_cartao("Itaú Uniclass", id=2)]
    assert [c.id for c in casar_cartoes_por_nome(cartoes, "ITAU")] == [2]


def test_emissor_diferente_nao_casa():
    cartoes = [_cartao("Inter Mastercard", id=3)]
    assert casar_cartoes_por_nome(cartoes, "Itaú") == []


def test_linha_sem_banco_citado_deixa_todos_candidatos():
    """Sem emissor citado, quem desempata é competência + valor — não filtrar aqui."""
    cartoes = [_cartao("Nubank", id=1), _cartao("Itaú Click", id=2)]
    assert len(casar_cartoes_por_nome(cartoes, None)) == 2


# --- competencias_candidatas --------------------------------------------------


def test_pagamento_no_vencimento_casa_a_competencia_do_mes():
    cartao = _cartao("Nubank", dia_vencimento=13)
    assert competencias_candidatas(cartao, dt.date(2026, 6, 13)) == [(6, 2026, 0)]


def test_pagamento_na_borda_da_janela_ainda_casa():
    cartao = _cartao("Nubank", dia_vencimento=13)
    assert competencias_candidatas(cartao, dt.date(2026, 6, 23)) == [(6, 2026, 10)]


def test_pagamento_fora_da_janela_nao_casa_nenhuma_competencia():
    cartao = _cartao("Nubank", dia_vencimento=13)
    assert competencias_candidatas(cartao, dt.date(2026, 6, 24)) == []


def test_competencia_vizinha_atravessa_a_virada_de_ano():
    """Pagamento em 30/12 quita a fatura que VENCE em 05/01 do ano seguinte."""
    cartao = _cartao("Nubank", dia_vencimento=5)
    assert competencias_candidatas(cartao, dt.date(2026, 12, 30)) == [(1, 2027, 6)]


# --- casar_recorrencia --------------------------------------------------------


def test_casa_salario_no_valor_e_no_dia():
    recs = [_recorrencia()]
    casada = casar_recorrencia(recs, dt.date(2026, 6, 5), Decimal("5000.00"))
    assert casada is not None
    rec, vigente, mes, ano = casada
    assert (rec.descricao, vigente, mes, ano) == ("Salário ACME", Decimal("5000.00"), 6, 2026)


def test_casa_com_valor_dentro_da_tolerancia_relativa():
    """5000 ± 5% = ±250: 5200 ainda é o mesmo salário (líquido varia)."""
    recs = [_recorrencia()]
    assert casar_recorrencia(recs, dt.date(2026, 6, 5), Decimal("5200.00")) is not None


def test_nao_casa_por_valor_fora_da_tolerancia():
    """MUTAÇÃO: ignorar o valor no casamento faz este teste falhar."""
    recs = [_recorrencia()]
    assert casar_recorrencia(recs, dt.date(2026, 6, 5), Decimal("5300.00")) is None


def test_casa_na_borda_da_janela_de_dias():
    recs = [_recorrencia(dia_do_mes=5)]
    assert casar_recorrencia(recs, dt.date(2026, 6, 10), Decimal("5000.00")) is not None


def test_nao_casa_por_dia_fora_da_janela():
    """MUTAÇÃO: ignorar o dia no casamento faz este teste falhar."""
    recs = [_recorrencia(dia_do_mes=5)]
    assert casar_recorrencia(recs, dt.date(2026, 6, 11), Decimal("5000.00")) is None


def test_nao_casa_fora_da_vigencia():
    """Recorrência encerrada em maio não explica receita de junho (valor_no_mes -> None)."""
    recs = [_recorrencia(mes_fim=5, ano_fim=2026)]
    assert casar_recorrencia(recs, dt.date(2026, 6, 5), Decimal("5000.00")) is None


def test_recorrencia_de_despesa_nunca_explica_entrada_de_caixa():
    recs = [_recorrencia(tipo="despesa")]
    assert casar_recorrencia(recs, dt.date(2026, 6, 5), Decimal("5000.00")) is None


def test_casa_competencia_vizinha_na_virada_de_ano():
    """Salário do dia 1º de janeiro creditado em 30/12 casa a competência 01/2027."""
    recs = [_recorrencia(dia_do_mes=1, mes_inicio=1, ano_inicio=2027)]
    casada = casar_recorrencia(recs, dt.date(2026, 12, 30), Decimal("5000.00"))
    assert casada is not None
    _, _, mes, ano = casada
    assert (mes, ano) == (1, 2027)


def test_entre_duas_recorrencias_vence_a_de_dia_mais_proximo():
    perto = _recorrencia(dia_do_mes=5)
    longe = _recorrencia(dia_do_mes=9)
    casada = casar_recorrencia([longe, perto], dt.date(2026, 6, 5), Decimal("5000.00"))
    assert casada is not None
    assert casada[0].id == perto[0].id


@pytest.mark.parametrize("valor", ["4750.00", "5250.00"])
def test_bordas_exatas_da_tolerancia_de_valor_casam(valor):
    recs = [_recorrencia()]
    assert casar_recorrencia(recs, dt.date(2026, 6, 5), Decimal(valor)) is not None
