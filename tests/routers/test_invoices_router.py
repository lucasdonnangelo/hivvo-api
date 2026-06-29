"""Batch 8 / T-17 — GET /cards/{id}/invoices agregado no banco (GROUP BY).

A reescrita (SUM/COUNT GROUP BY fatura) deve dar valores IDÊNTICOS aos da
varredura anterior: total por fatura, total_itens (parcelas + avulsas) e
total_parcelas_pagas (só parcelas). Parcela cancelada e avulsa não-despesa
ficam de fora; parcelas+avulsas na MESMA fatura somam juntas.
"""

import datetime as dt
from decimal import Decimal

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.transaction import Transacao


def _card(session, usuario_id):
    card = Cartao(
        usuario_id=usuario_id,
        nome="Nubank",
        tipo="Crédito",
        dia_fechamento=3,
        dia_vencimento=10,
        mes_offset_vencimento=1,
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def _parcela(session, usuario_id, cartao_id, transacao_id, mes, ano, valor, pago=False, cancelado=False):
    session.add(
        Parcela(
            usuario_id=usuario_id,
            transacao_id=transacao_id,
            numero_parcela=1,
            total_parcelas=1,
            valor_parcela=Decimal(valor),
            data_vencimento=dt.date(ano, mes, 10),
            descricao="p",
            categoria="C",
            cartao_id=cartao_id,
            fatura_mes=mes,
            fatura_ano=ano,
            pago=pago,
            cancelado=cancelado,
        )
    )


def _avulsa(session, usuario_id, cartao_id, mes, ano, valor, tipo="despesa"):
    session.add(
        Transacao(
            usuario_id=usuario_id,
            tipo=tipo,
            data=dt.date(ano, mes, 5),
            descricao="a",
            valor=Decimal(valor),
            categoria="C",
            cartao_id=cartao_id,
            parcelado=False,
            fatura_mes=mes,
            fatura_ano=ano,
        )
    )


class TestT17InvoicesAgregacao:
    def test_totais_por_fatura_identicos(self, session, users, as_user):
        user_a, _ = users
        card = _card(session, user_a.id)

        # Fatura (3, 2026): parcela paga 100 + parcela não-paga 50 + avulsa 30
        _parcela(session, user_a.id, card.id, 1, 3, 2026, "100.00", pago=True)
        _parcela(session, user_a.id, card.id, 2, 3, 2026, "50.00", pago=False)
        _avulsa(session, user_a.id, card.id, 3, 2026, "30.00")
        # Fatura (4, 2026): uma parcela 200
        _parcela(session, user_a.id, card.id, 3, 4, 2026, "200.00", pago=False)
        # Excluídos: parcela cancelada e avulsa que é receita
        _parcela(session, user_a.id, card.id, 4, 3, 2026, "999.00", cancelado=True)
        _avulsa(session, user_a.id, card.id, 3, 2026, "999.00", tipo="receita")
        session.commit()

        faturas = as_user(user_a).get(f"/cards/{card.id}/invoices").json()
        por_chave = {(f["mes"], f["ano"]): f for f in faturas}

        # Ordenação (ano, mes) desc
        assert [(f["mes"], f["ano"]) for f in faturas] == [(4, 2026), (3, 2026)]

        f3 = por_chave[(3, 2026)]
        assert Decimal(str(f3["total"])) == Decimal("180.00")  # 100 + 50 + 30
        assert f3["total_itens"] == 3
        assert f3["total_parcelas_pagas"] == 1

        f4 = por_chave[(4, 2026)]
        assert Decimal(str(f4["total"])) == Decimal("200.00")
        assert f4["total_itens"] == 1
        assert f4["total_parcelas_pagas"] == 0

    def test_cartao_sem_movimento_retorna_lista_vazia(self, session, users, as_user):
        user_a, _ = users
        card = _card(session, user_a.id)
        assert as_user(user_a).get(f"/cards/{card.id}/invoices").json() == []
