"""Testes unitários puros de app/services/faturas.py — sem banco.

Convenções do domínio (Hivvo_Referencia §5; auditoria interna de arquitetura, T-32):
- Compra com dia > dia_fechamento entra no ciclo seguinte; compra NO dia
  exato do fechamento entra na fatura atual.
- mes_offset_vencimento desloca fechamento → vencimento.
- Dia de vencimento clampado pelo último dia do mês.
- fatura_mes/fatura_ano derivados da data de VENCIMENTO da parcela.
"""

import datetime as dt

from app.models.card import Cartao
from app.services.faturas import (
    _add_months,
    _current_open_fatura,
    _data_vencimento_parcela,
    _fatura_cartao_avulso,
    _fatura_vencimento,
)


def make_card(
    dia_fechamento=3,
    dia_vencimento=10,
    mes_offset_vencimento=1,
) -> Cartao:
    return Cartao(
        usuario_id=1,
        nome="Cartão Teste",
        tipo="Crédito",
        dia_fechamento=dia_fechamento,
        dia_vencimento=dia_vencimento,
        mes_offset_vencimento=mes_offset_vencimento,
    )


class TestAddMonths:
    def test_soma_simples(self):
        assert _add_months(dt.date(2026, 1, 15), 1) == dt.date(2026, 2, 15)

    def test_zero_meses_mantem_data(self):
        assert _add_months(dt.date(2026, 6, 11), 0) == dt.date(2026, 6, 11)

    def test_virada_dezembro_janeiro(self):
        assert _add_months(dt.date(2025, 12, 15), 1) == dt.date(2026, 1, 15)

    def test_clamp_fevereiro_28(self):
        # 2026 não é bissexto
        assert _add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)

    def test_clamp_fevereiro_29_bissexto(self):
        assert _add_months(dt.date(2024, 1, 31), 1) == dt.date(2024, 2, 29)

    def test_clamp_mes_de_30_dias(self):
        assert _add_months(dt.date(2026, 1, 31), 3) == dt.date(2026, 4, 30)

    def test_salto_maior_que_12_meses(self):
        # 25 meses: cruza dois anos
        assert _add_months(dt.date(2026, 3, 10), 25) == dt.date(2028, 4, 10)


class TestDataVencimentoParcela:
    def test_sem_cartao_soma_meses_da_compra(self):
        venc = _data_vencimento_parcela(dt.date(2026, 1, 15), 1, None)
        assert venc == dt.date(2026, 2, 15)
        venc3 = _data_vencimento_parcela(dt.date(2026, 1, 15), 3, None)
        assert venc3 == dt.date(2026, 4, 15)

    def test_cartao_sem_dia_vencimento_usa_fallback(self):
        card = make_card(dia_fechamento=3, dia_vencimento=None)
        venc = _data_vencimento_parcela(dt.date(2026, 1, 15), 2, card)
        assert venc == dt.date(2026, 3, 15)

    def test_compra_no_dia_exato_do_fechamento_entra_na_fatura_atual(self):
        card = make_card(dia_fechamento=3, dia_vencimento=10, mes_offset_vencimento=1)
        # dia 3 == fechamento: ciclo de janeiro → vencimento fevereiro
        venc = _data_vencimento_parcela(dt.date(2026, 1, 3), 1, card)
        assert venc == dt.date(2026, 2, 10)

    def test_compra_apos_fechamento_entra_no_ciclo_seguinte(self):
        card = make_card(dia_fechamento=3, dia_vencimento=10, mes_offset_vencimento=1)
        # dia 4 > fechamento 3: ciclo de fevereiro → vencimento março
        venc = _data_vencimento_parcela(dt.date(2026, 1, 4), 1, card)
        assert venc == dt.date(2026, 3, 10)

    def test_offset_zero(self):
        card = make_card(dia_fechamento=20, dia_vencimento=28, mes_offset_vencimento=0)
        venc = _data_vencimento_parcela(dt.date(2026, 1, 10), 1, card)
        assert venc == dt.date(2026, 1, 28)

    def test_offset_um(self):
        card = make_card(dia_fechamento=20, dia_vencimento=28, mes_offset_vencimento=1)
        venc = _data_vencimento_parcela(dt.date(2026, 1, 10), 1, card)
        assert venc == dt.date(2026, 2, 28)

    def test_offset_dois(self):
        card = make_card(dia_fechamento=25, dia_vencimento=5, mes_offset_vencimento=2)
        venc = _data_vencimento_parcela(dt.date(2026, 1, 10), 1, card)
        assert venc == dt.date(2026, 3, 5)

    def test_clamp_vencimento_31_em_fevereiro(self):
        card = make_card(dia_fechamento=25, dia_vencimento=31, mes_offset_vencimento=1)
        venc = _data_vencimento_parcela(dt.date(2026, 1, 10), 1, card)
        assert venc == dt.date(2026, 2, 28)

    def test_clamp_vencimento_31_em_fevereiro_bissexto(self):
        card = make_card(dia_fechamento=25, dia_vencimento=31, mes_offset_vencimento=1)
        venc = _data_vencimento_parcela(dt.date(2024, 1, 10), 1, card)
        assert venc == dt.date(2024, 2, 29)

    def test_clamp_vencimento_31_em_mes_de_30_dias(self):
        card = make_card(dia_fechamento=25, dia_vencimento=31, mes_offset_vencimento=1)
        venc = _data_vencimento_parcela(dt.date(2026, 3, 10), 1, card)
        assert venc == dt.date(2026, 4, 30)

    def test_virada_dezembro_janeiro(self):
        card = make_card(dia_fechamento=20, dia_vencimento=10, mes_offset_vencimento=1)
        # compra 28/12 (após fechamento) → ciclo jan/2026 → vencimento fev/2026
        venc = _data_vencimento_parcela(dt.date(2025, 12, 28), 1, card)
        assert venc == dt.date(2026, 2, 10)

    def test_virada_de_ano_pelo_offset(self):
        card = make_card(dia_fechamento=20, dia_vencimento=10, mes_offset_vencimento=1)
        # compra 10/12 (antes do fechamento) → ciclo dez/2025 → vencimento jan/2026
        venc = _data_vencimento_parcela(dt.date(2025, 12, 10), 1, card)
        assert venc == dt.date(2026, 1, 10)

    def test_progressao_das_parcelas(self):
        card = make_card(dia_fechamento=3, dia_vencimento=10, mes_offset_vencimento=1)
        compra = dt.date(2026, 1, 15)  # após fechamento → 1ª fatura em fev, venc. mar
        assert _data_vencimento_parcela(compra, 1, card) == dt.date(2026, 3, 10)
        assert _data_vencimento_parcela(compra, 2, card) == dt.date(2026, 4, 10)
        # parcela 12 cruza o ano: fev/2026 + 11 = jan/2027 → vencimento fev/2027
        assert _data_vencimento_parcela(compra, 12, card) == dt.date(2027, 2, 10)


class TestFaturaCartaoAvulso:
    def test_compra_antes_do_fechamento(self):
        card = make_card(dia_fechamento=3, dia_vencimento=10, mes_offset_vencimento=1)
        assert _fatura_cartao_avulso(dt.date(2026, 1, 2), card) == (2, 2026)

    def test_compra_no_dia_do_fechamento(self):
        card = make_card(dia_fechamento=3, dia_vencimento=10, mes_offset_vencimento=1)
        assert _fatura_cartao_avulso(dt.date(2026, 1, 3), card) == (2, 2026)

    def test_compra_apos_fechamento(self):
        card = make_card(dia_fechamento=3, dia_vencimento=10, mes_offset_vencimento=1)
        assert _fatura_cartao_avulso(dt.date(2026, 1, 4), card) == (3, 2026)

    def test_cartao_sem_dia_fechamento(self):
        card = make_card(dia_fechamento=None, dia_vencimento=10, mes_offset_vencimento=1)
        assert _fatura_cartao_avulso(dt.date(2026, 1, 25), card) == (2, 2026)

    def test_virada_dezembro_janeiro(self):
        card = make_card(dia_fechamento=3, dia_vencimento=10, mes_offset_vencimento=1)
        # compra 15/12 (após fechamento) → ciclo jan/2026 → fatura fev/2026
        assert _fatura_cartao_avulso(dt.date(2025, 12, 15), card) == (2, 2026)

    def test_clamp_do_dia_de_vencimento(self):
        # vencimento 31 com fatura em fevereiro: dia clampado, mês/ano preservados
        card = make_card(dia_fechamento=25, dia_vencimento=31, mes_offset_vencimento=0)
        assert _fatura_cartao_avulso(dt.date(2026, 2, 10), card) == (2, 2026)


class TestFaturaVencimento:
    def test_sem_dia_vencimento_retorna_none(self):
        card = make_card(dia_vencimento=None)
        assert _fatura_vencimento(card, 6, 2026) is None

    def test_vencimento_normal(self):
        card = make_card(dia_vencimento=10)
        assert _fatura_vencimento(card, 6, 2026) == dt.date(2026, 6, 10)

    def test_clamp_em_fevereiro(self):
        card = make_card(dia_vencimento=31)
        assert _fatura_vencimento(card, 2, 2026) == dt.date(2026, 2, 28)

    def test_clamp_em_fevereiro_bissexto(self):
        card = make_card(dia_vencimento=31)
        assert _fatura_vencimento(card, 2, 2024) == dt.date(2024, 2, 29)


class TestCurrentOpenFatura:
    def test_hoje_antes_do_fechamento(self):
        card = make_card(dia_fechamento=3, dia_vencimento=10, mes_offset_vencimento=1)
        mes, ano, venc = _current_open_fatura(card, dt.date(2026, 6, 2))
        assert (mes, ano) == (7, 2026)
        assert venc == dt.date(2026, 7, 10)

    def test_hoje_no_dia_do_fechamento(self):
        card = make_card(dia_fechamento=3, dia_vencimento=10, mes_offset_vencimento=1)
        mes, ano, venc = _current_open_fatura(card, dt.date(2026, 6, 3))
        assert (mes, ano) == (7, 2026)
        assert venc == dt.date(2026, 7, 10)

    def test_hoje_apos_fechamento(self):
        card = make_card(dia_fechamento=3, dia_vencimento=10, mes_offset_vencimento=1)
        mes, ano, venc = _current_open_fatura(card, dt.date(2026, 6, 4))
        assert (mes, ano) == (8, 2026)
        assert venc == dt.date(2026, 8, 10)

    def test_virada_de_ano(self):
        card = make_card(dia_fechamento=20, dia_vencimento=10, mes_offset_vencimento=1)
        mes, ano, venc = _current_open_fatura(card, dt.date(2025, 12, 28))
        assert (mes, ano) == (2, 2026)
        assert venc == dt.date(2026, 2, 10)

    def test_cartao_sem_dia_vencimento_retorna_venc_none(self):
        card = make_card(dia_fechamento=20, dia_vencimento=None, mes_offset_vencimento=1)
        mes, ano, venc = _current_open_fatura(card, dt.date(2026, 6, 11))
        assert (mes, ano) == (7, 2026)
        assert venc is None
