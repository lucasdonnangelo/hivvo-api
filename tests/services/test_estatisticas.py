"""Estatísticas — _buscar_mes (T-10) e a visão FLUXO por competência (Fase 1).

- TestBuscarMesT10: a troca de extract(month/year) por range [1º dia, 1º dia do
  mês seguinte) retorna EXATAMENTE as mesmas linhas de antes (Batch 6 / T-10).
  _buscar_mes segue sendo o bloco da Fonte 3 e NÃO mudou.
- TestFluxoPorCompetencia: _lancamentos_mes agrega por competência de fatura
  (parcelas + avulsas faturadas + à vista/receitas por data), sem dupla
  contagem — corrige o T-39 (PLANO_PROJECAO §2).
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlmodel import select

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.pagamento_fatura import PagamentoFatura
from app.models.recorrencia import Recorrencia, RecorrenciaVigencia
from app.models.transaction import Transacao
from app.routers.ai import _total_parcelas_proximo_mes
from app.services.estatisticas import (
    _agregar,
    _buscar_mes,
    _categorias,
    _lancamentos_ano,
    _lancamentos_consumo_ano,
    _lancamentos_consumo_horizonte,
    _lancamentos_consumo_mes,
    _lancamentos_mes,
    _mes_atras,
    _soma_a_pagar,
)
from app.services.parcelas import _criar_parcelas

_ZERO = Decimal("0.00")


def _q(x) -> Decimal:
    # SQLite coage Numeric via float — normaliza para comparar dinheiro.
    return Decimal(str(x)).quantize(Decimal("0.01"))


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


def _add_parcelada(session, valor_total, n, mes0, ano0, uid=1, categoria="Compras"):
    """Cria a transação-PAI parcelada (fatura_mes=None) + n parcelas materializadas
    por competência a partir de (mes0, ano0), avançando mês a mês. Retorna o pai."""
    total = Decimal(str(valor_total))
    pai = Transacao(
        usuario_id=uid,
        tipo="despesa",
        data=dt.date(ano0, mes0, 15),
        descricao="compra parcelada",
        valor=total,
        categoria=categoria,
        forma_pagamento="Crédito",
        cartao_id=1,
        parcelado=True,
        total_parcelas=n,
    )
    session.add(pai)
    session.flush()  # obtém pai.id

    base = (total / n).quantize(Decimal("0.01"))
    m, a = mes0, ano0
    for i in range(1, n + 1):
        val = base if i < n else total - base * (n - 1)  # última absorve resto
        session.add(
            Parcela(
                usuario_id=uid,
                transacao_id=pai.id,
                numero_parcela=i,
                total_parcelas=n,
                valor_parcela=val,
                data_vencimento=dt.date(a, m, 10),
                descricao="compra parcelada",
                categoria=categoria,
                cartao_id=1,
                fatura_mes=m,
                fatura_ano=a,
            )
        )
        m += 1
        if m == 13:
            m, a = 1, a + 1
    session.commit()
    return pai


class TestFluxoPorCompetencia:
    """PLANO_PROJECAO §2/§7 — a visão FLUXO distribui a compra parcelada pela
    competência de fatura, sem dupla contagem (T-39)."""

    def test_invariante_soma_dos_12_meses_igual_valor_cheio(self, session):
        # R$1200 em 12x, competência jan..dez/2026. Fluxo distribui, não perde
        # nem cria dinheiro: a soma das despesas ao longo dos 12 meses == 1200.
        _add_parcelada(session, "1200.00", 12, 1, 2026)

        total = _ZERO
        for m in range(1, 13):
            _, despesas = _agregar(_lancamentos_mes(session, 1, m, 2026))
            total += despesas
        assert _q(total) == Decimal("1200.00")

    def test_mes_da_compra_mostra_a_parcela_nao_o_valor_cheio(self, session):
        # Antes (T-39): jan mostrava R$1200. Agora mostra só a parcela de jan.
        _add_parcelada(session, "1200.00", 12, 1, 2026)

        _, despesas = _agregar(_lancamentos_mes(session, 1, 1, 2026))  # jan/2026
        assert _q(despesas) == Decimal("100.00")

    def test_mes_futuro_com_parcela_retorna_valor_da_parcela_nao_zero(self, session):
        # Antes: mês futuro = zero. Agora: a parcela que cai lá.
        _add_parcelada(session, "1200.00", 12, 1, 2026)

        receitas, despesas = _agregar(_lancamentos_mes(session, 1, 6, 2026))  # jun/2026
        assert _q(despesas) == Decimal("100.00")
        assert receitas == _ZERO

    def test_avulsa_de_cartao_soma_na_competencia_nao_na_data(self, session):
        # Compra avulsa de crédito em 20/jan, faturada em fev — conta em fev.
        session.add(
            Transacao(
                usuario_id=1,
                tipo="despesa",
                data=dt.date(2026, 1, 20),
                descricao="avulsa crédito",
                valor=Decimal("300.00"),
                categoria="Eletrônicos",
                forma_pagamento="Crédito",
                cartao_id=1,
                parcelado=False,
                fatura_mes=2,
                fatura_ano=2026,
            )
        )
        session.commit()

        _, desp_jan = _agregar(_lancamentos_mes(session, 1, 1, 2026))
        _, desp_fev = _agregar(_lancamentos_mes(session, 1, 2, 2026))
        assert desp_jan == _ZERO  # não conta no mês da compra (data)
        assert _q(desp_fev) == Decimal("300.00")  # conta na competência (fatura)

    def test_a_vista_e_receita_somam_por_data(self, session):
        # Sem cartão / não faturadas: contam pela data da transação.
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 1, 10),
                descricao="mercado", valor=Decimal("50.00"), categoria="Mercado",
                forma_pagamento="Débito", parcelado=False,
            )
        )
        session.add(
            Transacao(
                usuario_id=1, tipo="receita", data=dt.date(2026, 1, 5),
                descricao="salário", valor=Decimal("5000.00"), categoria="Salário",
                forma_pagamento="Pix", parcelado=False,
            )
        )
        session.commit()

        receitas, despesas = _agregar(_lancamentos_mes(session, 1, 1, 2026))
        assert _q(receitas) == Decimal("5000.00")
        assert _q(despesas) == Decimal("50.00")

    def test_total_parcelas_proximo_mes_deriva_de_competencia_ignora_pago(self, session):
        # PLANO §1.3: pago deixou de ser fonte de verdade. Uma parcela paga que
        # vence no próximo mês AINDA conta; cancelada NÃO conta.
        pai = _add_parcelada(session, "600.00", 3, 8, 2026)  # (8,2026)/(9)/(10)
        # marca a parcela de competência (9,2026) como paga
        parcela_set = session.exec(
            select(Parcela).where(Parcela.fatura_mes == 9, Parcela.fatura_ano == 2026)
        ).all()
        for p in parcela_set:
            p.pago = True
        # parcela cancelada na mesma competência (9,2026) — pai próprio para não
        # colidir no UNIQUE(transacao_id, numero_parcela) do pai anterior.
        outro_pai = Transacao(
            usuario_id=1, tipo="despesa", data=dt.date(2026, 9, 1),
            descricao="outra", valor=Decimal("999.00"), categoria="Compras",
            forma_pagamento="Crédito", cartao_id=1, parcelado=True, total_parcelas=1,
        )
        session.add(outro_pai)
        session.flush()
        session.add(
            Parcela(
                usuario_id=1, transacao_id=outro_pai.id, numero_parcela=1, total_parcelas=1,
                valor_parcela=Decimal("999.00"), data_vencimento=dt.date(2026, 9, 10),
                descricao="cancelada", categoria="Compras", cartao_id=1,
                fatura_mes=9, fatura_ano=2026, cancelado=True,
            )
        )
        session.commit()

        # mês de referência 8/2026 → próximo mês = 9/2026, parcela de R$200 (paga)
        total = _total_parcelas_proximo_mes(session, 1, 8, 2026)
        assert _q(total) == Decimal("200.00")


class TestFluxoAnual:
    """Adendo Fase 1 — yearly_stats (gráfico "Evolução mensal") em FLUXO.

    O anual deve bater, mês a mês, com o mensal (card × gráfico não discordam),
    e uma compra que atravessa anos distribui as parcelas por competência entre
    os anos (invariante: soma dos anos == valor cheio)."""

    def test_anual_bate_com_mensal_mes_a_mes(self, session):
        # Mistura as 3 fontes num único ano:
        _add_parcelada(session, "1200.00", 12, 1, 2026)  # parcelas jan..dez/2026
        # avulsa de crédito faturada em mar/2026
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 2, 25),
                descricao="avulsa", valor=Decimal("300.00"), categoria="Eletrônicos",
                forma_pagamento="Crédito", cartao_id=1, parcelado=False,
                fatura_mes=3, fatura_ano=2026,
            )
        )
        # à vista + receita em maio/2026
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 5, 10),
                descricao="mercado", valor=Decimal("80.00"), categoria="Mercado",
                forma_pagamento="Débito", parcelado=False,
            )
        )
        session.add(
            Transacao(
                usuario_id=1, tipo="receita", data=dt.date(2026, 5, 5),
                descricao="salário", valor=Decimal("5000.00"), categoria="Salário",
                forma_pagamento="Pix", parcelado=False,
            )
        )
        session.commit()

        por_mes = _lancamentos_ano(session, 1, 2026)
        for m in range(1, 13):
            anual_rec, anual_desp = _agregar(por_mes[m])
            mensal_rec, mensal_desp = _agregar(_lancamentos_mes(session, 1, m, 2026))
            assert _q(anual_rec) == _q(mensal_rec), f"receitas divergem no mês {m}"
            assert _q(anual_desp) == _q(mensal_desp), f"despesas divergem no mês {m}"

    def test_compra_atravessa_anos_distribui_por_competencia(self, session):
        # R$1200 em 12x a partir de ago/2026: 5 parcelas em 2026 (ago–dez),
        # 7 em 2027 (jan–jul). Cada ano soma sua parte; total == valor cheio.
        _add_parcelada(session, "1200.00", 12, 8, 2026)

        def _despesas_ano(ano):
            por_mes = _lancamentos_ano(session, 1, ano)
            total = _ZERO
            for m in range(1, 13):
                total += _agregar(por_mes[m])[1]
            return total

        d2026 = _despesas_ano(2026)
        d2027 = _despesas_ano(2027)
        assert _q(d2026) == Decimal("500.00")  # 5 × R$100
        assert _q(d2027) == Decimal("700.00")  # 7 × R$100
        assert _q(d2026 + d2027) == Decimal("1200.00")  # invariante


def _add_recorrencia(
    session,
    tipo="receita",
    categoria="Salário",
    valor="10000.00",
    mes_inicio=1,
    ano_inicio=2026,
    mes_fim=None,
    ano_fim=None,
    uid=1,
    ativa=True,
    dia=5,
):
    """Cria recorrência + primeira vigência. Retorna a Recorrencia (para
    adicionar mais vigências no teste de edição versionada)."""
    rec = Recorrencia(
        usuario_id=uid,
        tipo=tipo,
        categoria=categoria,
        forma_pagamento="Pix",
        dia_do_mes=dia,
        descricao=categoria,
        ativa=ativa,
    )
    session.add(rec)
    session.flush()
    session.add(
        RecorrenciaVigencia(
            recorrencia_id=rec.id,
            valor=Decimal(valor),
            mes_inicio=mes_inicio,
            ano_inicio=ano_inicio,
            mes_fim=mes_fim,
            ano_fim=ano_fim,
        )
    )
    session.commit()
    return rec


class TestRecorrenciaNaProjecao:
    """Fase 2b — a recorrência como QUARTA fonte da agregação de fluxo.

    As 3 fontes da Fase 1 permanecem idênticas; a recorrência soma por cima,
    por competência do MÊS (sem fatura/cartão — PLANO §3.4)."""

    def test_salario_aberto_soma_nas_receitas_do_mes_atual_e_futuros(self, session):
        _add_recorrencia(session)  # R$10000, aberta desde jan/2026

        for mes, ano in [(1, 2026), (7, 2026), (12, 2027), (1, 2031)]:
            receitas, despesas = _agregar(_lancamentos_mes(session, 1, mes, ano))
            assert _q(receitas) == Decimal("10000.00"), (mes, ano)
            assert despesas == _ZERO
        # antes do início não gera
        receitas, _ = _agregar(_lancamentos_mes(session, 1, 12, 2025))
        assert receitas == _ZERO

    def test_lancamento_de_recorrencia_marcado_e_demais_nao(self, session):
        _add_recorrencia(session)
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 3, 10),
                descricao="mercado", valor=Decimal("50.00"), categoria="Mercado",
                forma_pagamento="Débito", parcelado=False,
            )
        )
        session.commit()

        lancamentos = _lancamentos_mes(session, 1, 3, 2026)
        flags = {(l.categoria, l.recorrente) for l in lancamentos}
        assert flags == {("Salário", True), ("Mercado", False)}

    def test_despesa_recorrente_soma_nas_despesas_e_no_donut(self, session):
        _add_recorrencia(session, tipo="despesa", categoria="Moradia", valor="2000.00")

        lancamentos = _lancamentos_mes(session, 1, 5, 2026)
        _, despesas = _agregar(lancamentos)
        assert _q(despesas) == Decimal("2000.00")

        donut = _categorias(lancamentos)
        assert [(c.categoria, _q(c.total)) for c in donut] == [("Moradia", Decimal("2000.00"))]

    def test_edicao_versionada_reflete_na_agregacao(self, session):
        # 10000 jan–jul/2026 + 12000 ago/2026–aberto (§3.1.1)
        rec = _add_recorrencia(session, mes_fim=7, ano_fim=2026)
        session.add(
            RecorrenciaVigencia(
                recorrencia_id=rec.id, valor=Decimal("12000.00"),
                mes_inicio=8, ano_inicio=2026,
            )
        )
        session.commit()

        rec_jul, _ = _agregar(_lancamentos_mes(session, 1, 7, 2026))
        rec_ago, _ = _agregar(_lancamentos_mes(session, 1, 8, 2026))
        assert _q(rec_jul) == Decimal("10000.00")
        assert _q(rec_ago) == Decimal("12000.00")

    def test_encerrada_passado_aparece_futuro_some(self, session):
        # Fase 2c: encerrada = vigência FECHADA (jun/2026) + ativa=False (flag
        # de listagem). O passado permanece na projeção; o futuro para.
        _add_recorrencia(
            session, tipo="despesa", categoria="Moradia", valor="2000.00",
            mes_fim=6, ano_fim=2026, ativa=False,
        )

        _, desp_mai = _agregar(_lancamentos_mes(session, 1, 5, 2026))
        _, desp_jul = _agregar(_lancamentos_mes(session, 1, 7, 2026))
        assert _q(desp_mai) == Decimal("2000.00")  # passado preservado
        assert desp_jul == _ZERO  # nenhuma vigência cobre — futuro parou
        assert _categorias(_lancamentos_mes(session, 1, 7, 2026)) == []

    def test_isolamento_por_usuario(self, session):
        _add_recorrencia(session, uid=2)

        receitas, _ = _agregar(_lancamentos_mes(session, 1, 6, 2026))
        assert receitas == _ZERO

    def test_anual_bate_com_mensal_com_recorrencia_no_cenario(self, session):
        # As 4 fontes juntas: parcelas + avulsa faturada + à vista + recorrências
        # (receita versionada no meio do ano + despesa recorrente com fim).
        _add_parcelada(session, "1200.00", 12, 1, 2026)
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 2, 25),
                descricao="avulsa", valor=Decimal("300.00"), categoria="Eletrônicos",
                forma_pagamento="Crédito", cartao_id=1, parcelado=False,
                fatura_mes=3, fatura_ano=2026,
            )
        )
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 5, 10),
                descricao="mercado", valor=Decimal("80.00"), categoria="Mercado",
                forma_pagamento="Débito", parcelado=False,
            )
        )
        session.commit()
        rec = _add_recorrencia(session, mes_fim=7, ano_fim=2026)  # 10000 jan–jul
        session.add(
            RecorrenciaVigencia(
                recorrencia_id=rec.id, valor=Decimal("12000.00"),
                mes_inicio=8, ano_inicio=2026,
            )
        )
        session.commit()
        _add_recorrencia(
            session, tipo="despesa", categoria="Moradia", valor="2000.00",
            mes_inicio=3, ano_inicio=2026, mes_fim=10, ano_fim=2026,
        )

        por_mes = _lancamentos_ano(session, 1, 2026)
        for m in range(1, 13):
            anual_rec, anual_desp = _agregar(por_mes[m])
            mensal_rec, mensal_desp = _agregar(_lancamentos_mes(session, 1, m, 2026))
            assert _q(anual_rec) == _q(mensal_rec), f"receitas divergem no mês {m}"
            assert _q(anual_desp) == _q(mensal_desp), f"despesas divergem no mês {m}"

    def test_lancamentos_ano_faz_numero_fixo_de_queries(self, session):
        # Sem N+1: o anual resolve em 5 SELECTs fixos (3 fontes + 2 da
        # recorrência), independente de quantos meses têm ocorrência.
        _add_recorrencia(session)
        _add_recorrencia(session, tipo="despesa", categoria="Moradia", valor="2000.00")

        selects: list[str] = []

        def _conta(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", _conta)
        try:
            _lancamentos_ano(session, 1, 2026)
        finally:
            event.remove(engine, "before_cursor_execute", _conta)

        assert len(selects) == 5, selects

    def test_lancamentos_ano_com_avulsa_faz_queries_extras_fixas(self, session):
        # Com avulsa faturada, a Fonte 2 carrega os cartões do usuário para
        # derivar o vencimento (§"A pagar e Saldo") e a marcação a_pagar busca
        # os pagamentos confirmados do ano (Leva 2) — 2 SELECTs a mais, fixos
        # (sem N+1), e SÓ quando há lançamento de cartão.
        _add_recorrencia(session)
        _add_recorrencia(session, tipo="despesa", categoria="Moradia", valor="2000.00")
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 6, 25),
                descricao="avulsa", valor=Decimal("300.00"), categoria="Eletrônicos",
                forma_pagamento="Crédito", cartao_id=1, parcelado=False,
                fatura_mes=7, fatura_ano=2026,
            )
        )
        session.commit()

        selects: list[str] = []

        def _conta(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                selects.append(statement)

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", _conta)
        try:
            _lancamentos_ano(session, 1, 2026)
        finally:
            event.remove(engine, "before_cursor_execute", _conta)

        assert len(selects) == 7, selects


HOJE_LEITURAS = dt.date(2026, 7, 15)


class TestLeiturasDoDia:
    """§1.3.1/§1.3.2 — o dia divide o mês CORRENTE em realizado (dia <= hoje) e
    a-vir (dia > hoje); a projeção (todos os lançamentos) segue integral.

    hoje congelado em 15/07/2026 via patch em app.services.estatisticas.hoje
    (onde _lancamentos_mes/_lancamentos_ano leem o relógio)."""

    @pytest.fixture(autouse=True)
    def clock(self, mocker):
        mocker.patch(
            "app.services.estatisticas.hoje", return_value=HOJE_LEITURAS
        )

    def _leituras(self, session, mes, ano, uid=1):
        lanc = _lancamentos_mes(session, uid, mes, ano)
        projecao = _agregar(lanc)
        realizado = _agregar([l for l in lanc if l.realizado])
        a_vir = _agregar([l for l in lanc if not l.realizado])
        return projecao, realizado, a_vir

    def test_recorrencia_dia_futuro_projeta_mas_nao_realiza(self, session):
        _add_recorrencia(session, dia=20)  # dia 20 > hoje 15
        (rec_p, _), (rec_r, _), (rec_v, _) = self._leituras(session, 7, 2026)
        assert _q(rec_p) == Decimal("10000.00")  # projeção conta
        assert rec_r == _ZERO  # realizado NÃO conta
        assert _q(rec_v) == Decimal("10000.00")  # a-vir conta

    def test_recorrencia_dia_passado_realiza(self, session):
        _add_recorrencia(session, dia=10)  # dia 10 < hoje 15
        (rec_p, _), (rec_r, _), (rec_v, _) = self._leituras(session, 7, 2026)
        assert _q(rec_p) == Decimal("10000.00")
        assert _q(rec_r) == Decimal("10000.00")
        assert rec_v == _ZERO

    def test_fronteira_dia_igual_hoje_conta_como_realizado(self, session):
        _add_recorrencia(session, dia=15)  # dia == hoje → <= inclui
        _, (rec_r, _), (rec_v, _) = self._leituras(session, 7, 2026)
        assert _q(rec_r) == Decimal("10000.00")
        assert rec_v == _ZERO

    def test_parcela_vencimento_futuro_projeta_mas_nao_realiza(self, session):
        # 12x de jan/2026: a parcela de julho vence dia 10 por padrão do helper
        # (_add_parcelada usa data_vencimento dia 10) → realizada. Criar caso
        # com vencimento dia 20 exige parcela própria:
        pai = _add_parcelada(session, "1200.00", 12, 1, 2026)
        parcela_jul = session.exec(
            select(Parcela).where(Parcela.fatura_mes == 7, Parcela.fatura_ano == 2026)
        ).one()
        parcela_jul.data_vencimento = dt.date(2026, 7, 20)  # > hoje 15
        session.commit()

        (_, desp_p), (_, desp_r), (_, desp_v) = self._leituras(session, 7, 2026)
        assert _q(desp_p) == Decimal("100.00")  # projeção conta
        assert desp_r == _ZERO  # ainda não venceu
        assert _q(desp_v) == Decimal("100.00")
        # junho (mês passado): a parcela venceu dia 10 → integral/realizada
        (_, desp_p6), (_, desp_r6), (_, desp_v6) = self._leituras(session, 6, 2026)
        assert _q(desp_p6) == _q(desp_r6) == Decimal("100.00")
        assert desp_v6 == _ZERO

    def test_parcela_vencimento_passado_realiza(self, session):
        _add_parcelada(session, "1200.00", 12, 1, 2026)  # julho vence dia 10 < 15
        (_, desp_p), (_, desp_r), (_, desp_v) = self._leituras(session, 7, 2026)
        assert _q(desp_p) == _q(desp_r) == Decimal("100.00")
        assert desp_v == _ZERO

    def test_invariante_realizado_mais_a_vir_igual_projecao(self, session):
        # 4 fontes juntas no mês corrente, com itens antes E depois do dia 15
        _add_parcelada(session, "1200.00", 12, 1, 2026)  # parcela jul vence dia 10
        _add_recorrencia(session, dia=20)  # receita a vir
        _add_recorrencia(session, tipo="despesa", categoria="Moradia",
                         valor="2000.00", dia=5)  # despesa realizada
        session.add(  # à vista (Fonte 3)
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 7, 10),
                descricao="mercado", valor=Decimal("80.00"), categoria="Mercado",
                forma_pagamento="Débito", parcelado=False,
            )
        )
        session.add(  # avulsa faturada em jul (Fonte 2)
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 6, 25),
                descricao="avulsa", valor=Decimal("300.00"), categoria="Eletrônicos",
                forma_pagamento="Crédito", cartao_id=1, parcelado=False,
                fatura_mes=7, fatura_ano=2026,
            )
        )
        session.commit()

        (rp, dp), (rr, dr), (rv, dv) = self._leituras(session, 7, 2026)
        assert _q(rr + rv) == _q(rp)  # receitas: realizado + a_vir == projeção
        assert _q(dr + dv) == _q(dp)  # despesas idem
        # decomposição exata: a recorrência dia 20 e a avulsa faturada estão a
        # vir (a avulsa corta pelo vencimento derivado — sem cartão no banco,
        # fallback = fim do mês, 31/jul > hoje 15).
        assert _q(rv) == Decimal("10000.00")
        assert _q(dv) == Decimal("300.00")

    def test_mes_passado_e_futuro_integrais_sem_a_vir(self, session):
        _add_recorrencia(session, dia=20, mes_inicio=1, ano_inicio=2026)
        for mes in (6, 8):  # passado e futuro; dia 20 > hoje 15 é irrelevante
            (rec_p, _), (rec_r, _), (rec_v, _) = self._leituras(session, mes, 2026)
            assert _q(rec_p) == _q(rec_r) == Decimal("10000.00")
            assert rec_v == _ZERO  # a_vir só existe no mês corrente

    def test_fonte_3_integral_no_mes_corrente(self, session):
        # À vista com data FUTURA (dia 20 > hoje 15) segue realizada (§1.3.2:
        # à vista já ocorreu por definição — o corte por dia não se aplica).
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 7, 20),
                descricao="à vista futura", valor=Decimal("50.00"), categoria="Mercado",
                forma_pagamento="Débito", parcelado=False,
            )
        )
        session.commit()

        (_, desp_p), (_, desp_r), (_, desp_v) = self._leituras(session, 7, 2026)
        assert _q(desp_p) == _q(desp_r) == Decimal("50.00")
        assert desp_v == _ZERO

    def test_fonte_2_corta_pelo_vencimento_derivado_do_cartao(self, session):
        # Furo 1 fechado (§"A pagar e Saldo"): a avulsa faturada corta pelo
        # dia_vencimento do CARTÃO no mês corrente — dia 20 (> hoje 15) fica a
        # vir; dia 10 (< hoje) realiza.
        for dia, valor in ((20, "300.00"), (10, "100.00")):
            card = Cartao(usuario_id=1, nome=f"Cartão dia {dia}", tipo="Crédito",
                          dia_vencimento=dia)
            session.add(card)
            session.flush()
            session.add(
                Transacao(
                    usuario_id=1, tipo="despesa", data=dt.date(2026, 6, 25),
                    descricao=f"avulsa dia {dia}", valor=Decimal(valor),
                    categoria="Eletrônicos", forma_pagamento="Crédito",
                    cartao_id=card.id, parcelado=False,
                    fatura_mes=7, fatura_ano=2026,
                )
            )
        session.commit()

        (_, desp_p), (_, desp_r), (_, desp_v) = self._leituras(session, 7, 2026)
        assert _q(desp_p) == Decimal("400.00")  # projeção integral
        assert _q(desp_r) == Decimal("100.00")  # venceu dia 10
        assert _q(desp_v) == Decimal("300.00")  # vence dia 20

    def test_fonte_2_sem_dia_de_vencimento_fallback_fim_do_mes(self, session):
        # Cartão sem linha no banco (ou sem dia_vencimento): vencimento
        # desconhecido → fim do mês (conservador) — fica a vir até o dia 31.
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 6, 25),
                descricao="avulsa", valor=Decimal("300.00"), categoria="Eletrônicos",
                forma_pagamento="Crédito", cartao_id=1, parcelado=False,
                fatura_mes=7, fatura_ano=2026,
            )
        )
        session.commit()

        (_, desp_p), (_, desp_r), (_, desp_v) = self._leituras(session, 7, 2026)
        assert _q(desp_p) == _q(desp_v) == Decimal("300.00")
        assert desp_r == _ZERO

    def test_flags_do_anual_batem_com_o_mensal_no_mes_corrente(self, session):
        _add_parcelada(session, "1200.00", 12, 1, 2026)
        _add_recorrencia(session, dia=20)
        card = Cartao(usuario_id=1, nome="Nubank", tipo="Crédito", dia_vencimento=20)
        session.add(card)
        session.flush()
        session.add(  # avulsa faturada em jul — cobre as flags da Fonte 2
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 6, 25),
                descricao="avulsa", valor=Decimal("300.00"), categoria="Eletrônicos",
                forma_pagamento="Crédito", cartao_id=card.id, parcelado=False,
                fatura_mes=7, fatura_ano=2026,
            )
        )
        session.commit()

        mensal = _lancamentos_mes(session, 1, 7, 2026)
        anual_jul = _lancamentos_ano(session, 1, 2026)[7]
        chave = lambda l: (l.tipo, str(_q(l.valor)), l.categoria, l.recorrente, l.realizado, l.a_pagar)  # noqa: E731
        assert sorted(map(chave, mensal)) == sorted(map(chave, anual_jul))


class TestAPagar:
    """§"A pagar e Saldo" (regra da Leva 2 — PLANO_3D): "a pagar" = só CRÉDITO
    cuja FATURA não está confirmada paga (PagamentoFatura pago=True) — a vencer
    OU atrasada, tanto faz; a presunção "venceu = saiu" morreu. Parcela sem
    cartão (carnê): presunção por vencimento. À vista e recorrência saem no ato
    → nunca a pagar. hoje congelado em 15/07/2026."""

    @pytest.fixture(autouse=True)
    def clock(self, mocker):
        mocker.patch(
            "app.services.estatisticas.hoje", return_value=HOJE_LEITURAS
        )

    def _a_pagar(self, session, mes, ano, uid=1):
        return _q(_soma_a_pagar(_lancamentos_mes(session, uid, mes, ano)))

    def _confirmar_fatura(self, session, cartao_id, mes, ano=2026, pago=True):
        """Semeia a confirmação de pagamento da fatura (Leva 2)."""
        session.add(
            PagamentoFatura(
                usuario_id=1, cartao_id=cartao_id, fatura_mes=mes,
                fatura_ano=ano, pago=pago,
                data_pagamento=HOJE_LEITURAS if pago else None,
            )
        )
        session.commit()

    def _parcela_unica(self, session, mes, dia_venc, pago=False):
        """Compra 1x com a única parcela na fatura de (mes)/2026 (cartão id=1).
        pago=True = a FATURA do cartão foi confirmada paga (PagamentoFatura)."""
        _add_parcelada(session, "100.00", 1, mes, 2026)
        p = session.exec(select(Parcela)).one()
        p.data_vencimento = dt.date(2026, mes, dia_venc)
        session.add(p)
        session.commit()
        if pago:
            self._confirmar_fatura(session, p.cartao_id, mes)

    def _avulsa(self, session, dia_vencimento_cartao, fatura_mes=7):
        """Avulsa de cartão faturada em (fatura_mes)/2026; cartão com o dia dado
        (None = sem cartão no banco → fallback fim do mês)."""
        cartao_id = 999
        if dia_vencimento_cartao is not None:
            card = Cartao(usuario_id=1, nome="Nubank", tipo="Crédito",
                          dia_vencimento=dia_vencimento_cartao)
            session.add(card)
            session.flush()
            cartao_id = card.id
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 6, 25),
                descricao="avulsa", valor=Decimal("300.00"), categoria="Eletrônicos",
                forma_pagamento="Crédito", cartao_id=cartao_id, parcelado=False,
                fatura_mes=fatura_mes, fatura_ano=2026,
            )
        )
        session.commit()

    # ---- FURO 3: à vista/recorrência saem no ato — fora, independente de data

    def test_a_vista_fora_mesmo_com_data_futura(self, session):
        for dia in (10, 20):  # passada e futura vs hoje 15
            _add(session, dt.date(2026, 7, dia))
        session.commit()
        assert self._a_pagar(session, 7, 2026) == _ZERO

    def test_recorrencia_despesa_fora_mesmo_a_vir(self, session):
        _add_recorrencia(session, tipo="despesa", categoria="Moradia",
                         valor="2000.00", dia=20)  # a vir (20 > 15), e ainda assim fora
        assert self._a_pagar(session, 7, 2026) == _ZERO

    # ---- Fonte 1 (parcelas): segue a FATURA (PagamentoFatura) — Leva 2

    def test_parcela_a_vencer_nao_confirmada_dentro(self, session):
        self._parcela_unica(session, mes=7, dia_venc=20)
        assert self._a_pagar(session, 7, 2026) == Decimal("100.00")

    def test_parcela_atrasada_vencida_nao_confirmada_continua_dentro(self, session):
        # Vencida (dia 10 <= hoje 15) e fatura não confirmada — NÃO some.
        self._parcela_unica(session, mes=7, dia_venc=10)
        assert self._a_pagar(session, 7, 2026) == Decimal("100.00")

    def test_parcela_vencida_com_fatura_confirmada_fora(self, session):
        self._parcela_unica(session, mes=7, dia_venc=10, pago=True)
        assert self._a_pagar(session, 7, 2026) == _ZERO

    def test_parcela_confirmada_antecipada_fora(self, session):
        # Confirmação antecipada (fatura fechada, vencimento dia 20 > hoje 15):
        # a saída ocorreu — sai do a_pagar.
        self._parcela_unica(session, mes=7, dia_venc=20, pago=True)
        assert self._a_pagar(session, 7, 2026) == _ZERO

    def test_parcela_sem_cartao_presuncao_por_vencimento(self, session):
        # Carnê (sem cartão) não tem fatura confirmável → presunção por
        # vencimento (decisão da Leva 2): a vencer dentro, vencida fora.
        self._parcela_unica(session, mes=7, dia_venc=20)
        p = session.exec(select(Parcela)).one()
        p.cartao_id = None
        session.add(p)
        session.commit()
        assert self._a_pagar(session, 7, 2026) == Decimal("100.00")  # a vencer

        p.data_vencimento = dt.date(2026, 7, 10)  # vencida → presumida paga
        session.add(p)
        session.commit()
        assert self._a_pagar(session, 7, 2026) == _ZERO

    # ---- Fonte 2 (avulsas): seguem a FATURA — a presunção por data morreu

    def test_avulsa_nao_confirmada_dentro(self, session):
        self._avulsa(session, dia_vencimento_cartao=20)  # vence 20/jul > hoje 15
        assert self._a_pagar(session, 7, 2026) == Decimal("300.00")

    def test_avulsa_vencida_sem_confirmacao_continua_dentro(self, session):
        # Leva 2 INVERTE a regra antiga: avulsa vencida (dia 10) e a que vence
        # hoje (15) NÃO somem mais por presunção — ficam até confirmar a fatura.
        self._avulsa(session, dia_vencimento_cartao=10)
        self._avulsa(session, dia_vencimento_cartao=15)
        assert self._a_pagar(session, 7, 2026) == Decimal("600.00")

    def test_avulsa_com_fatura_confirmada_fora(self, session):
        self._avulsa(session, dia_vencimento_cartao=10)  # vencida e confirmada
        t = session.exec(select(Transacao).where(Transacao.fatura_mes == 7)).one()
        self._confirmar_fatura(session, t.cartao_id, 7)
        assert self._a_pagar(session, 7, 2026) == _ZERO

    def test_avulsa_de_cartao_apagado_nao_confirmada_dentro(self, session):
        # Cartão sem row (id fantasma): sem confirmação possível → permanece
        # a pagar (antes dependia do fallback fim-do-mês; agora é pela fatura).
        self._avulsa(session, dia_vencimento_cartao=None)
        assert self._a_pagar(session, 7, 2026) == Decimal("300.00")

    # ---- Regra única para qualquer mês

    def test_mes_futuro_a_pagar_so_o_credito(self, session):
        self._parcela_unica(session, mes=8, dia_venc=10)  # crédito: dentro
        self._avulsa(session, dia_vencimento_cartao=10, fatura_mes=8)  # dentro
        _add(session, dt.date(2026, 8, 10))  # à vista: fora
        _add_recorrencia(session, tipo="despesa", categoria="Moradia",
                         valor="2000.00", dia=5)  # recorrência: fora
        session.commit()

        lanc = _lancamentos_mes(session, 1, 8, 2026)
        _, despesas = _agregar(lanc)
        assert _q(_soma_a_pagar(lanc)) == Decimal("400.00")
        assert _q(despesas) == Decimal("2410.00")  # projeção integral intacta

    def test_mes_passado_nada_confirmado_tudo_permanece(self, session):
        # Leva 2: sem confirmação, parcela E avulsa de mês passado continuam
        # a pagar (a avulsa vencida não some mais por presunção).
        self._parcela_unica(session, mes=6, dia_venc=10)
        self._avulsa(session, dia_vencimento_cartao=10, fatura_mes=6)
        assert self._a_pagar(session, 6, 2026) == Decimal("400.00")

    # ---- Testes-guarda da FRONTEIRA (Leva 2): pagamento não governa a
    # projeção, e Parcela.pago está MORTO na camada de estatísticas

    def _fotografia(self, session):
        lanc = _lancamentos_mes(session, 1, 7, 2026)
        anual = _lancamentos_ano(session, 1, 2026)
        return (
            _agregar(lanc),
            _agregar([l for l in lanc if l.realizado]),
            _agregar([l for l in lanc if not l.realizado]),
            _agregar(_lancamentos_consumo_mes(session, 1, 7, 2026)),
            [_agregar(anual[m]) for m in range(1, 13)],
        )

    def test_alternar_parcela_pago_nao_muda_nada(self, session):
        # Parcela.pago está OBSOLETO: alternar não move NADA — nem o a_pagar
        # (que agora deriva de PagamentoFatura), nem projeção/realizado/
        # a_vir/consumo/anual.
        _add_parcelada(session, "1200.00", 12, 1, 2026)
        _add_recorrencia(session, dia=20)

        antes, a_pagar_antes = self._fotografia(session), self._a_pagar(session, 7, 2026)

        parcela_jul = session.exec(
            select(Parcela).where(Parcela.fatura_mes == 7, Parcela.fatura_ano == 2026)
        ).one()
        parcela_jul.pago = True
        parcela_jul.data_pagamento = HOJE_LEITURAS
        session.add(parcela_jul)
        session.commit()

        depois, a_pagar_depois = self._fotografia(session), self._a_pagar(session, 7, 2026)
        assert antes == depois
        assert a_pagar_antes == a_pagar_depois == Decimal("100.00")

    def test_alternar_pagamento_fatura_so_muda_o_a_pagar(self, session):
        # O guarda da fronteira, agora sobre a fonte NOVA: a projeção
        # integral, realizado/a_vir, consumo e o anual derivam de data/
        # competência — alternar PagamentoFatura não pode mexer em NENHUM
        # deles; só o a_pagar reage, nos dois sentidos (confirmar/desmarcar).
        _add_parcelada(session, "1200.00", 12, 1, 2026)
        _add_recorrencia(session, dia=20)

        antes = self._fotografia(session)
        assert self._a_pagar(session, 7, 2026) == Decimal("100.00")

        self._confirmar_fatura(session, 1, 7)  # cartão 1, jul/2026
        depois = self._fotografia(session)
        assert antes == depois  # nada da projeção se moveu
        assert self._a_pagar(session, 7, 2026) == _ZERO  # só o a_pagar reagiu

        # Desmarcar (pago=False) → volta ao a_pagar, projeção segue imóvel.
        pagamento = session.exec(select(PagamentoFatura)).one()
        pagamento.pago = False
        pagamento.data_pagamento = None
        session.add(pagamento)
        session.commit()
        assert self._fotografia(session) == antes
        assert self._a_pagar(session, 7, 2026) == Decimal("100.00")


class TestConsumoMensal:
    """§"Fase 3b" (PLANO_PROJECAO) — a visão CONSUMO conta a compra INTEIRA no
    mês da COMPRA (transação-pai por `data`), não fatiada por competência.

    Invariante-âncora: Σ das parcelas de fluxo ao longo do tempo == a despesa de
    consumo no mês da compra (§Fase 3b). Receita coincide entre as visões; só a
    despesa com fatura (parcelada + avulsa de cartão) muda de mês."""

    def test_parcelada_consumo_no_mes_da_compra_igual_soma_das_parcelas(self, session):
        # R$1200 em 12x, compra em 15/jan/2026 (data do pai). Fluxo distribui
        # R$100/mês por 12 meses; consumo conta R$1200 inteiro em jan.
        _add_parcelada(session, "1200.00", 12, 1, 2026)

        soma_fluxo = _ZERO
        for m in range(1, 13):
            soma_fluxo += _agregar(_lancamentos_mes(session, 1, m, 2026))[1]

        _, desp_consumo_jan = _agregar(_lancamentos_consumo_mes(session, 1, 1, 2026))
        assert _q(desp_consumo_jan) == Decimal("1200.00")   # valor cheio no mês da compra
        assert _q(desp_consumo_jan) == _q(soma_fluxo)        # invariante Σparcelas==consumo

        # mês seguinte: fluxo tem a parcela de fev; consumo NÃO (compra foi em jan)
        _, desp_consumo_fev = _agregar(_lancamentos_consumo_mes(session, 1, 2, 2026))
        assert desp_consumo_fev == _ZERO

    def test_a_vista_e_receita_consumo_igual_fluxo(self, session):
        # Sem cartão / não faturadas: as duas visões contam pela mesma data.
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 1, 10),
                descricao="mercado", valor=Decimal("50.00"), categoria="Mercado",
                forma_pagamento="Débito", parcelado=False,
            )
        )
        session.add(
            Transacao(
                usuario_id=1, tipo="receita", data=dt.date(2026, 1, 5),
                descricao="salário", valor=Decimal("5000.00"), categoria="Salário",
                forma_pagamento="Pix", parcelado=False,
            )
        )
        session.commit()

        rec_f, desp_f = _agregar(_lancamentos_mes(session, 1, 1, 2026))
        rec_c, desp_c = _agregar(_lancamentos_consumo_mes(session, 1, 1, 2026))
        assert (_q(rec_c), _q(desp_c)) == (_q(rec_f), _q(desp_f))
        assert (_q(rec_c), _q(desp_c)) == (Decimal("5000.00"), Decimal("50.00"))

    def test_avulsa_cartao_consumo_no_mes_da_compra_fluxo_na_fatura(self, session):
        # Avulsa de crédito comprada em 20/jan, faturada em fev.
        # CONSUMO conta em jan (data da compra); FLUXO conta em fev (competência).
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 1, 20),
                descricao="avulsa crédito", valor=Decimal("300.00"),
                categoria="Eletrônicos", forma_pagamento="Crédito", cartao_id=1,
                parcelado=False, fatura_mes=2, fatura_ano=2026,
            )
        )
        session.commit()

        _, desp_consumo_jan = _agregar(_lancamentos_consumo_mes(session, 1, 1, 2026))
        _, desp_consumo_fev = _agregar(_lancamentos_consumo_mes(session, 1, 2, 2026))
        _, desp_fluxo_jan = _agregar(_lancamentos_mes(session, 1, 1, 2026))
        _, desp_fluxo_fev = _agregar(_lancamentos_mes(session, 1, 2, 2026))

        assert _q(desp_consumo_jan) == Decimal("300.00")  # consumo: mês da compra
        assert desp_consumo_fev == _ZERO
        assert desp_fluxo_jan == _ZERO
        assert _q(desp_fluxo_fev) == Decimal("300.00")    # fluxo: mês da fatura

    def test_recorrencia_consumo_igual_fluxo(self, session):
        # Recorrência não passa por fatura (§3.4) — idêntica nas duas visões.
        _add_recorrencia(session)  # receita R$10000, aberta desde jan/2026

        rec_f, _ = _agregar(_lancamentos_mes(session, 1, 7, 2026))
        rec_c, _ = _agregar(_lancamentos_consumo_mes(session, 1, 7, 2026))
        assert _q(rec_c) == _q(rec_f) == Decimal("10000.00")

    def test_compra_cancelada_via_delete_nao_entra_em_nenhuma_visao(self, session):
        # Cancelar a compra inteira = DELETE /transactions (pai + parcelas somem
        # juntas). As duas visões excluem automaticamente — a invariante se mantém.
        pai = _add_parcelada(session, "1200.00", 12, 1, 2026)
        for p in session.exec(
            select(Parcela).where(Parcela.transacao_id == pai.id)
        ).all():
            session.delete(p)
        session.delete(pai)
        session.commit()

        _, desp_consumo = _agregar(_lancamentos_consumo_mes(session, 1, 1, 2026))
        assert desp_consumo == _ZERO
        for m in range(1, 13):  # fluxo: nenhuma parcela sobrou em nenhum mês
            assert _agregar(_lancamentos_mes(session, 1, m, 2026))[1] == _ZERO

    def test_receita_coincide_fluxo_consumo(self, session):
        # Receita nunca passa por cartão — sempre por data; coincide nas visões.
        session.add(
            Transacao(
                usuario_id=1, tipo="receita", data=dt.date(2026, 3, 5),
                descricao="salário", valor=Decimal("7000.00"), categoria="Salário",
                forma_pagamento="Pix", parcelado=False,
            )
        )
        session.commit()

        rec_f, desp_f = _agregar(_lancamentos_mes(session, 1, 3, 2026))
        rec_c, desp_c = _agregar(_lancamentos_consumo_mes(session, 1, 3, 2026))
        assert _q(rec_c) == _q(rec_f) == Decimal("7000.00")
        assert desp_c == desp_f == _ZERO

    def test_cancelamento_por_parcela_diverge_fluxo_cai_consumo_mantem(self, session):
        # A rota PUT /installments/{id} cancelado=true é VIVA e alcançável (só sem
        # UI). O FLUXO respeita Parcela.cancelado (cai a parcela); o CONSUMO soma a
        # transação-PAI pelo valor CHEIO e NÃO enxerga o cancelado (a pai não tem
        # flag). Esta divergência é o comportamento ESPERADO da Opção A, fixado aqui.
        # Opção A: quando cancelamento por-parcela virar operação de usuário
        # (UI + rota viva), migrar p/ Opção B (§Fase 3b) — a invariante volta a fechar.
        _add_parcelada(session, "1200.00", 12, 1, 2026)  # 12x R$100, compra em jan
        p3 = session.exec(
            select(Parcela).where(Parcela.fatura_mes == 3, Parcela.fatura_ano == 2026)
        ).one()
        p3.cancelado = True
        session.commit()

        # FLUXO: o mês da parcela cancelada (mar) cai a R$0 (filtro cancelado==False).
        _, desp_fluxo_mar = _agregar(_lancamentos_mes(session, 1, 3, 2026))
        assert desp_fluxo_mar == _ZERO

        # CONSUMO: o mês da compra (jan) mantém o valor CHEIO — não reflete o cancelado.
        _, desp_consumo_jan = _agregar(_lancamentos_consumo_mes(session, 1, 1, 2026))
        assert _q(desp_consumo_jan) == Decimal("1200.00")

        # Invariante DIVERGE por exatamente a parcela cancelada: fluxo soma 1100
        # (11×100), consumo 1200. Divergência conhecida e aceita (§Fase 3b).
        soma_fluxo = _ZERO
        for m in range(1, 13):
            soma_fluxo += _agregar(_lancamentos_mes(session, 1, m, 2026))[1]
        assert _q(soma_fluxo) == Decimal("1100.00")
        assert _q(desp_consumo_jan) - _q(soma_fluxo) == Decimal("100.00")

    def test_invariante_valor_nao_divisivel_usa_split_real_do_app(self, session):
        # Valor que NÃO divide redondo: R$100 em 3x → 33,33 / 33,33 / 33,34.
        # Usa o split REAL do app (_criar_parcelas), não um recálculo à mão, para
        # provar que a soma das parcelas de FLUXO volta EXATAMENTE ao total do
        # CONSUMO — pegaria qualquer resíduo de arredondamento que não fechasse.
        pai = Transacao(
            usuario_id=1, tipo="despesa", data=dt.date(2026, 1, 15),
            descricao="compra 3x", valor=Decimal("100.00"), categoria="Compras",
            forma_pagamento="Crédito", cartao_id=None, parcelado=True, total_parcelas=3,
        )
        session.add(pai)
        session.flush()  # obtém pai.id para as parcelas
        _criar_parcelas(session, pai, None)  # split real; sem cartão → i meses após a compra
        session.commit()

        # Sanidade: o split real soma o total e joga o resíduo na última parcela.
        parcelas = session.exec(
            select(Parcela)
            .where(Parcela.transacao_id == pai.id)
            .order_by(Parcela.numero_parcela)
        ).all()
        assert [p.valor_parcela for p in parcelas] == [
            Decimal("33.33"), Decimal("33.33"), Decimal("33.34")
        ]

        # CONSUMO no mês da compra (jan) = valor cheio da pai.
        _, desp_consumo_jan = _agregar(_lancamentos_consumo_mes(session, 1, 1, 2026))
        assert _q(desp_consumo_jan) == Decimal("100.00")

        # Σ das parcelas de FLUXO ao longo dos meses == consumo, SEM resíduo (varre
        # 2026 e 2027 para não depender de onde as parcelas caem).
        soma_fluxo = _ZERO
        for ano in (2026, 2027):
            for m in range(1, 13):
                soma_fluxo += _agregar(_lancamentos_mes(session, 1, m, ano))[1]
        assert _q(soma_fluxo) == Decimal("100.00")
        assert _q(soma_fluxo) == _q(desp_consumo_jan)  # invariante exata, valor quebrado


def _conta_selects(session, fn):
    """Executa fn() contando os SELECTs emitidos (padrão dos testes de N+1)."""
    selects: list[str] = []

    def _conta(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", _conta)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", _conta)
    return selects


class TestConsumoAnualEHorizonte:
    """PLANO_RESUMO §Backend — a fonte única do Resumo: _lancamentos_consumo_ano
    (o espelho consumo do _lancamentos_ano) e _lancamentos_consumo_horizonte
    (o espelho PRA TRÁS do /projection: âncora = mês corrente INCLUÍDO,
    meses=N = corrente + N−1 pra trás, cache por ano).

    Invariante central: anual/horizonte batem mês a mês com
    _lancamentos_consumo_mes — zero drift vs o donut do Dashboard."""

    def test_consumo_anual_bate_com_mensal_mes_a_mes(self, session):
        # Cenário cheio das 2 fontes do consumo: parcelada que atravessa anos
        # (pai em ago), avulsa faturada (compra fev, fatura mar — consumo conta
        # em FEV), à vista, receita versionada e despesa recorrente com fim.
        _add_parcelada(session, "1200.00", 12, 8, 2026)
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 2, 25),
                descricao="avulsa", valor=Decimal("300.00"), categoria="Eletrônicos",
                forma_pagamento="Crédito", cartao_id=1, parcelado=False,
                fatura_mes=3, fatura_ano=2026,
            )
        )
        session.add(
            Transacao(
                usuario_id=1, tipo="despesa", data=dt.date(2026, 5, 10),
                descricao="mercado", valor=Decimal("80.00"), categoria="Mercado",
                forma_pagamento="Débito", parcelado=False,
            )
        )
        session.commit()
        rec = _add_recorrencia(session, mes_fim=7, ano_fim=2026)
        session.add(
            RecorrenciaVigencia(
                recorrencia_id=rec.id, valor=Decimal("12000.00"),
                mes_inicio=8, ano_inicio=2026,
            )
        )
        session.commit()
        _add_recorrencia(
            session, tipo="despesa", categoria="Moradia", valor="2000.00",
            mes_inicio=3, ano_inicio=2026, mes_fim=10, ano_fim=2026,
        )

        por_mes = _lancamentos_consumo_ano(session, 1, 2026)
        for m in range(1, 13):
            anual = tuple(map(_q, _agregar(por_mes[m])))
            mensal = tuple(map(_q, _agregar(_lancamentos_consumo_mes(session, 1, m, 2026))))
            assert anual == mensal, f"consumo diverge no mês {m}"

        # consumo: a parcelada conta INTEIRA no mês da compra (ago)...
        assert _q(_agregar(por_mes[8])[1]) == Decimal("3200.00")  # 1200 + Moradia 2000
        # ...e as parcelas seguintes NÃO contam (set = só a Moradia)
        assert _q(_agregar(por_mes[9])[1]) == Decimal("2000.00")

    def test_consumo_ano_faz_numero_fixo_de_queries(self, session):
        # Sem N+1: 3 SELECTs fixos (1 de transações + 2 da recorrência),
        # independente de quantos meses têm dado. Parcelas nunca são lidas.
        _add_parcelada(session, "1200.00", 12, 1, 2026)
        _add_recorrencia(session)
        _add_recorrencia(session, tipo="despesa", categoria="Moradia", valor="2000.00")

        selects = _conta_selects(
            session, lambda: _lancamentos_consumo_ano(session, 1, 2026)
        )
        assert len(selects) == 3, selects

    def test_horizonte_ancora_corrente_cronologico_e_virada_de_ano(
        self, session, mocker
    ):
        # hoje = fev/2027; meses=4 → nov/2026..fev/2027, do mais antigo ao
        # corrente, contínuo (dez e fev vazios entram com zeros).
        mocker.patch(
            "app.services.estatisticas.hoje", return_value=dt.date(2027, 2, 15)
        )
        _add(session, dt.date(2026, 11, 5))  # despesa 10.00
        _add(session, dt.date(2027, 1, 8))
        session.commit()

        serie = _lancamentos_consumo_horizonte(session, 1, 4)
        assert [(m, a) for m, a, _ in serie] == [
            (11, 2026), (12, 2026), (1, 2027), (2, 2027)
        ]
        assert [_q(_agregar(lanc)[1]) for _, _, lanc in serie] == [
            Decimal("10.00"), Decimal("0.00"), Decimal("10.00"), Decimal("0.00")
        ]

    def test_horizonte_bate_com_consumo_mensal_mes_a_mes(self, session, mocker):
        mocker.patch(
            "app.services.estatisticas.hoje", return_value=dt.date(2026, 7, 15)
        )
        _add_parcelada(session, "1200.00", 12, 5, 2026)  # compra em mai
        _add_recorrencia(session)

        for m, a, lanc in _lancamentos_consumo_horizonte(session, 1, 6):
            horizonte = tuple(map(_q, _agregar(lanc)))
            mensal = tuple(map(_q, _agregar(_lancamentos_consumo_mes(session, 1, m, a))))
            assert horizonte == mensal, f"horizonte diverge em {m}/{a}"

    def test_horizonte_carrega_cada_ano_e_recorrencias_uma_vez(self, session, mocker):
        # meses=13 cruza dois anos: 2 SELECTs de recorrência (buscada UMA vez
        # para o horizonte inteiro) + 1 SELECT de transações por ano = 4 fixos
        # — sem N+1 (13 chamadas mensais custariam 39).
        mocker.patch(
            "app.services.estatisticas.hoje", return_value=dt.date(2026, 7, 15)
        )
        _add_recorrencia(session)

        selects = _conta_selects(
            session, lambda: _lancamentos_consumo_horizonte(session, 1, 13)
        )
        assert len(selects) == 4, selects

    def test_mes_atras_aritmetica_de_competencia(self):
        assert _mes_atras(7, 2026, 0) == (7, 2026)
        assert _mes_atras(7, 2026, 2) == (5, 2026)
        assert _mes_atras(1, 2027, 1) == (12, 2026)   # virada pra trás
        assert _mes_atras(7, 2026, 59) == (8, 2021)   # horizonte máximo (60)


class TestDetalhesDaTrilhaConsumo:
    """PLANO_RESUMO (/highlights) — data/descricao no LancamentoFluxo são
    preenchidos APENAS pela trilha consumo MENSAL (C1 pela Transacao, C4 pela
    ocorrência da recorrência); nas trilhas de fluxo ficam None e a agregação
    ignora os campos novos (extensão aditiva)."""

    def test_consumo_mensal_carrega_detalhes_fluxo_nao(self, session):
        _add(session, dt.date(2026, 7, 10))
        session.commit()
        _add_recorrencia(session)  # receita Salário, dia 5

        consumo = _lancamentos_consumo_mes(session, 1, 7, 2026)
        assert consumo and all(
            l.data is not None and l.descricao is not None for l in consumo
        )
        # a ocorrência da recorrência traz a data clampada do mês
        (ocorrencia,) = [l for l in consumo if l.recorrente]
        assert ocorrencia.data == dt.date(2026, 7, 5)
        assert ocorrencia.descricao == "Salário"

        fluxo = _lancamentos_mes(session, 1, 7, 2026)
        assert fluxo and all(l.data is None and l.descricao is None for l in fluxo)
