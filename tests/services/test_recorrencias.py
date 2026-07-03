"""Fase 2a — algoritmo puro da recorrência (PLANO_PROJECAO §3.4).

Função pura: recebe Recorrencia + vigências + (mes, ano) e computa, sem banco.
Cobre os edge cases do §3.4: clamp de dia, vigência aberta até o horizonte
(60 meses), vigência com fim, início no meio do ano, edição versionada na
fronteira exata, soft delete e virada de ano (comparação por tupla (ano, mes)).
"""

import datetime as dt
import uuid
from decimal import Decimal

from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.services.recorrencias import data_ocorrencia, valor_no_mes

DEZ_MIL = Decimal("10000.00")
DOZE_MIL = Decimal("12000.00")


def _rec(**over) -> Recorrencia:
    defaults = dict(
        usuario_id=1,
        tipo="receita",
        categoria="Salário",
        forma_pagamento="Pix",
        dia_do_mes=5,
        descricao="Salário",
    )
    defaults.update(over)
    return Recorrencia(**defaults)


def _vig(**over) -> RecorrenciaVigencia:
    defaults = dict(
        recorrencia_id=uuid.uuid4(),
        valor=DEZ_MIL,
        mes_inicio=1,
        ano_inicio=2026,
    )
    defaults.update(over)
    return RecorrenciaVigencia(**defaults)


def _prox_mes(mes: int, ano: int) -> tuple[int, int]:
    return (1, ano + 1) if mes == 12 else (mes + 1, ano)


class TestClampDataOcorrencia:
    """dia_do_mes não afeta SE gera — só a DATA, clampada ao último dia do mês."""

    def test_dia_31_em_mes_de_30_dias_vira_30(self):
        assert data_ocorrencia(_rec(dia_do_mes=31), 4, 2026) == dt.date(2026, 4, 30)

    def test_dia_31_em_fevereiro_nao_bissexto_vira_28(self):
        assert data_ocorrencia(_rec(dia_do_mes=31), 2, 2026) == dt.date(2026, 2, 28)

    def test_dia_31_em_fevereiro_bissexto_vira_29(self):
        assert data_ocorrencia(_rec(dia_do_mes=31), 2, 2028) == dt.date(2028, 2, 29)

    def test_dia_30_em_fevereiro_tambem_clampa(self):
        assert data_ocorrencia(_rec(dia_do_mes=30), 2, 2026) == dt.date(2026, 2, 28)

    def test_dia_dentro_do_mes_fica_intocado(self):
        assert data_ocorrencia(_rec(dia_do_mes=5), 2, 2026) == dt.date(2026, 2, 5)

    def test_dia_31_em_mes_de_31_dias_fica_31(self):
        assert data_ocorrencia(_rec(dia_do_mes=31), 1, 2026) == dt.date(2026, 1, 31)


class TestVigenciaAbertaSemFim:
    """Salário padrão: vigência única sem fim gera em todo mês até o horizonte."""

    def test_gera_em_todos_os_60_meses_a_frente(self):
        rec = _rec()
        vigencias = [_vig(mes_inicio=1, ano_inicio=2026)]
        mes, ano = 1, 2026
        for _ in range(60):
            assert valor_no_mes(rec, vigencias, mes, ano) == DEZ_MIL, (mes, ano)
            mes, ano = _prox_mes(mes, ano)
        assert (mes, ano) == (1, 2031)  # sanidade: andou 60 meses de verdade

    def test_nao_gera_antes_do_inicio(self):
        rec = _rec()
        vigencias = [_vig(mes_inicio=1, ano_inicio=2026)]
        assert valor_no_mes(rec, vigencias, 12, 2025) is None
        assert valor_no_mes(rec, vigencias, 1, 2025) is None


class TestVigenciaComFim:
    def test_gera_ate_o_fim_inclusive_e_para_depois(self):
        rec = _rec()
        vigencias = [_vig(mes_inicio=1, ano_inicio=2026, mes_fim=6, ano_fim=2026)]
        assert valor_no_mes(rec, vigencias, 1, 2026) == DEZ_MIL
        assert valor_no_mes(rec, vigencias, 6, 2026) == DEZ_MIL  # fim é inclusive
        assert valor_no_mes(rec, vigencias, 7, 2026) is None
        assert valor_no_mes(rec, vigencias, 6, 2027) is None  # mesmo mês, ano seguinte


class TestComecaNoMeioDoAno:
    def test_nao_gera_antes_de_mes_inicio(self):
        rec = _rec()
        vigencias = [_vig(mes_inicio=8, ano_inicio=2026)]
        assert valor_no_mes(rec, vigencias, 7, 2026) is None
        assert valor_no_mes(rec, vigencias, 8, 2026) == DEZ_MIL


class TestEdicaoVersionada:
    """Duas vigências consecutivas sem gap nem sobreposição (aumento de salário).

    R$10.000 jan–jul/2026 + R$12.000 ago/2026–aberto: mês anterior ao corte usa
    o valor antigo, mês do corte em diante usa o novo (§3.1.1).
    """

    def _vigencias(self):
        return [
            _vig(valor=DEZ_MIL, mes_inicio=1, ano_inicio=2026, mes_fim=7, ano_fim=2026),
            _vig(valor=DOZE_MIL, mes_inicio=8, ano_inicio=2026),
        ]

    def test_fronteira_exata_julho_antigo_agosto_novo(self):
        rec = _rec()
        assert valor_no_mes(rec, self._vigencias(), 7, 2026) == DEZ_MIL
        assert valor_no_mes(rec, self._vigencias(), 8, 2026) == DOZE_MIL

    def test_passado_mantem_antigo_e_futuro_usa_novo(self):
        rec = _rec()
        assert valor_no_mes(rec, self._vigencias(), 1, 2026) == DEZ_MIL
        assert valor_no_mes(rec, self._vigencias(), 12, 2027) == DOZE_MIL
        assert valor_no_mes(rec, self._vigencias(), 12, 2025) is None  # antes de tudo

    def test_nao_depende_da_ordem_da_lista(self):
        rec = _rec()
        invertidas = list(reversed(self._vigencias()))
        assert valor_no_mes(rec, invertidas, 7, 2026) == DEZ_MIL
        assert valor_no_mes(rec, invertidas, 8, 2026) == DOZE_MIL


class TestSoftDelete:
    def test_inativa_nao_gera_em_nenhum_mes(self):
        rec = _rec(ativa=False)
        vigencias = [_vig(mes_inicio=1, ano_inicio=2026)]  # aberta, cobriria tudo
        assert valor_no_mes(rec, vigencias, 1, 2026) is None  # passado
        assert valor_no_mes(rec, vigencias, 7, 2026) is None  # corrente
        assert valor_no_mes(rec, vigencias, 7, 2030) is None  # futuro


class TestViradaDeAno:
    """Comparação por tupla (ano, mes) — não só mês (dez=12 > fev=2)."""

    def test_vigencia_dez_2026_a_fev_2027(self):
        rec = _rec()
        vigencias = [_vig(mes_inicio=12, ano_inicio=2026, mes_fim=2, ano_fim=2027)]
        assert valor_no_mes(rec, vigencias, 11, 2026) is None
        assert valor_no_mes(rec, vigencias, 12, 2026) == DEZ_MIL
        assert valor_no_mes(rec, vigencias, 1, 2027) == DEZ_MIL
        assert valor_no_mes(rec, vigencias, 2, 2027) == DEZ_MIL
        assert valor_no_mes(rec, vigencias, 3, 2027) is None
