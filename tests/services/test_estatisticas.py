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

from sqlmodel import select

from app.models.installment import Parcela
from app.models.transaction import Transacao
from app.routers.ai import _total_parcelas_proximo_mes
from app.services.estatisticas import (
    _agregar,
    _buscar_mes,
    _lancamentos_ano,
    _lancamentos_mes,
)

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
