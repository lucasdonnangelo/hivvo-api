"""T-36 — isolamento entre usuários nas agregações de GET /cards.

Antes do fix, as agregações de fatura filtravam só por cartao_id + fatura:
parcelas/avulsas de OUTRO usuário apontando para o cartão (dado legado ou
escrito antes da validação de propriedade) inflavam o total exibido ao dono.
"""

import datetime as dt
from decimal import Decimal

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.transaction import Transacao

HOJE_FIXO = dt.date(2026, 6, 10)
# Cartão: fechamento 25, vencimento 5, offset 1 → em 10/06 a fatura aberta é (7, 2026)
FATURA_ABERTA = (7, 2026)


def make_card(session, usuario_id: int) -> Cartao:
    card = Cartao(
        usuario_id=usuario_id,
        nome="Nubank",
        tipo="Crédito",
        dia_fechamento=25,
        dia_vencimento=5,
        mes_offset_vencimento=1,
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def add_avulsa(session, usuario_id: int, cartao_id: int, valor: str) -> Transacao:
    t = Transacao(
        usuario_id=usuario_id,
        tipo="despesa",
        data=dt.date(2026, 6, 1),
        descricao="Avulsa",
        valor=Decimal(valor),
        categoria="Compras",
        forma_pagamento="Crédito",
        cartao_id=cartao_id,
        parcelado=False,
        fatura_mes=FATURA_ABERTA[0],
        fatura_ano=FATURA_ABERTA[1],
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def add_parcela(session, usuario_id: int, cartao_id: int, valor: str) -> Parcela:
    base = Transacao(
        usuario_id=usuario_id,
        tipo="despesa",
        data=dt.date(2026, 6, 1),
        descricao="Parcelada",
        valor=Decimal(valor),
        categoria="Compras",
        forma_pagamento="Crédito",
        cartao_id=cartao_id,
        parcelado=True,
        total_parcelas=1,
    )
    session.add(base)
    session.commit()
    session.refresh(base)
    p = Parcela(
        usuario_id=usuario_id,
        transacao_id=base.id,
        numero_parcela=1,
        total_parcelas=1,
        valor_parcela=Decimal(valor),
        data_vencimento=dt.date(2026, 7, 5),
        descricao="Parcelada (1/1)",
        categoria="Compras",
        cartao_id=cartao_id,
        fatura_mes=FATURA_ABERTA[0],
        fatura_ano=FATURA_ABERTA[1],
    )
    session.add(p)
    session.commit()
    return p


class TestT36IsolamentoEntreUsuarios:
    def test_totais_do_cartao_excluem_dados_de_outro_usuario(
        self, session, users, as_user, mocker
    ):
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, user_b = users
        card = make_card(session, user_a.id)

        # Dados legítimos do dono: R$ 100 em parcela + R$ 50 avulsa = R$ 150
        add_parcela(session, user_a.id, card.id, "100.00")
        add_avulsa(session, user_a.id, card.id, "50.00")

        # Poluição do usuário B na mesma fatura do cartão de A (simula dado
        # legado, anterior à validação de propriedade no update)
        add_parcela(session, user_b.id, card.id, "999.00")
        add_avulsa(session, user_b.id, card.id, "999.00")

        response = as_user(user_a).get("/cards")
        assert response.status_code == 200
        (card_body,) = response.json()
        assert (card_body["fatura_aberta_mes"], card_body["fatura_aberta_ano"]) == FATURA_ABERTA
        assert Decimal(str(card_body["fatura_aberta_total"])) == Decimal("150.00")
