"""Batch 3b — comportamento de endpoint de /transactions.

T-36: cartao_id de outro usuário rejeitado no update.
T-34: DELETE de parcelada apaga as parcelas junto (sem 500 de FK).
T-35: parcelada bloqueia valor/data; avulsa rederiva fatura_mes/ano.
T-41: criação parcelada atômica — falha nas parcelas não persiste nada.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.transaction import Transacao


def make_card(session, usuario_id: int, dia_fechamento=3, dia_vencimento=10, offset=1) -> Cartao:
    card = Cartao(
        usuario_id=usuario_id,
        nome="Nubank",
        tipo="Crédito",
        dia_fechamento=dia_fechamento,
        dia_vencimento=dia_vencimento,
        mes_offset_vencimento=offset,
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def post_transacao(client, **overrides):
    payload = {
        "tipo": "despesa",
        "data": "2026-01-15",
        "descricao": "Compra Teste",
        "valor": "300.00",
        "categoria": "Compras",
        "forma_pagamento": "Crédito",
    }
    payload.update(overrides)
    return client.post("/transactions", json=payload)


def post_parcelada(client, valor="300.00", n=3, **overrides):
    return post_transacao(client, valor=valor, parcelado=True, total_parcelas=n, **overrides)


class TestT36CartaoDeOutroUsuarioNoUpdate:
    def test_update_apontando_cartao_alheio_retorna_404(self, session, users, as_user):
        user_a, user_b = users
        card_a = make_card(session, user_a.id)

        client_b = as_user(user_b)
        transacao_id = post_transacao(client_b).json()["id"]

        response = client_b.put(f"/transactions/{transacao_id}", json={"cartao_id": card_a.id})
        assert response.status_code == 404
        assert response.json()["detail"] == "Cartão não encontrado"
        assert session.get(Transacao, transacao_id).cartao_id is None

    def test_update_com_cartao_proprio_segue_aceito(self, session, users, as_user):
        user_a, _ = users
        card_a = make_card(session, user_a.id)

        client_a = as_user(user_a)
        transacao_id = post_transacao(client_a).json()["id"]

        response = client_a.put(f"/transactions/{transacao_id}", json={"cartao_id": card_a.id})
        assert response.status_code == 200
        assert response.json()["cartao_id"] == card_a.id


class TestT34DeleteParcelada:
    def test_delete_apaga_transacao_e_parcelas_juntas(self, session, users, as_user):
        client = as_user(users[0])
        transacao_id = post_parcelada(client).json()["id"]
        assert (
            len(session.exec(select(Parcela).where(Parcela.transacao_id == transacao_id)).all())
            == 3
        )

        response = client.delete(f"/transactions/{transacao_id}")
        assert response.status_code == 204
        assert session.get(Transacao, transacao_id) is None
        assert session.exec(select(Parcela).where(Parcela.transacao_id == transacao_id)).all() == []


class TestT35ParceladaBloqueiaValorEData:
    @pytest.mark.parametrize("payload", [{"valor": "500.00"}, {"data": "2026-02-01"}])
    def test_editar_valor_ou_data_retorna_400(self, session, users, as_user, payload):
        client = as_user(users[0])
        transacao_id = post_parcelada(client).json()["id"]

        response = client.put(f"/transactions/{transacao_id}", json=payload)
        assert response.status_code == 400
        assert "parcelada" in response.json()["detail"]

    def test_outros_campos_seguem_editaveis(self, session, users, as_user):
        client = as_user(users[0])
        transacao_id = post_parcelada(client).json()["id"]

        response = client.put(f"/transactions/{transacao_id}", json={"descricao": "Renomeada"})
        assert response.status_code == 200
        assert response.json()["descricao"] == "Renomeada"


class TestT35RederivacaoDeFatura:
    def test_mudar_data_rederiva_fatura(self, session, users, as_user):
        # Cartão fech. 3 / venc. 10 / offset 1 — compra 15/01 (após fechamento)
        # entra no ciclo de fev → vencimento em mar → fatura (3, 2026)
        user_a, _ = users
        card = make_card(session, user_a.id)
        client = as_user(user_a)
        body = post_transacao(client, cartao_id=card.id).json()
        assert (body["fatura_mes"], body["fatura_ano"]) == (3, 2026)

        # Nova data 02/01 (antes do fechamento) → ciclo de jan → fatura (2, 2026)
        response = client.put(f"/transactions/{body['id']}", json={"data": "2026-01-02"})
        assert response.status_code == 200
        atualizada = response.json()
        assert (atualizada["fatura_mes"], atualizada["fatura_ano"]) == (2, 2026)

    def test_mudar_cartao_rederiva_fatura(self, session, users, as_user):
        user_a, _ = users
        card1 = make_card(session, user_a.id)  # fech. 3 → compra 15/01 cai em (3, 2026)
        card2 = make_card(session, user_a.id, dia_fechamento=28, dia_vencimento=20, offset=0)
        client = as_user(user_a)
        body = post_transacao(client, cartao_id=card1.id).json()

        # card2: 15/01 antes do fechamento (28) + offset 0 → fatura (1, 2026)
        response = client.put(f"/transactions/{body['id']}", json={"cartao_id": card2.id})
        assert response.status_code == 200
        atualizada = response.json()
        assert (atualizada["fatura_mes"], atualizada["fatura_ano"]) == (1, 2026)

    def test_remover_cartao_limpa_fatura(self, session, users, as_user):
        user_a, _ = users
        card = make_card(session, user_a.id)
        client = as_user(user_a)
        body = post_transacao(client, cartao_id=card.id).json()
        assert body["fatura_mes"] is not None

        response = client.put(f"/transactions/{body['id']}", json={"cartao_id": None})
        assert response.status_code == 200
        atualizada = response.json()
        assert atualizada["cartao_id"] is None
        assert atualizada["fatura_mes"] is None
        assert atualizada["fatura_ano"] is None


class TestT41AtomicidadeDaCriacaoParcelada:
    def test_falha_na_geracao_de_parcelas_nao_persiste_nada(
        self, session, users, as_user, mocker
    ):
        client = as_user(users[0])
        mocker.patch(
            "app.routers.transactions._criar_parcelas", side_effect=RuntimeError("boom")
        )

        with pytest.raises(RuntimeError):
            post_parcelada(client)

        # O endpoint nunca chegou ao commit — após rollback do estado pendente,
        # nem a transação nem parcelas existem (antes do T-41, a transação já
        # estava commitada e ficava órfã como parcelado=True sem parcelas)
        session.rollback()
        assert session.exec(select(Transacao)).all() == []
        assert session.exec(select(Parcela)).all() == []

    def test_sucesso_persiste_transacao_e_parcelas(self, session, users, as_user):
        client = as_user(users[0])
        response = post_parcelada(client, valor="100.00", n=3)
        assert response.status_code == 201
        body = response.json()
        assert body["parcelas_criadas"] == 3

        parcelas = session.exec(
            select(Parcela).where(Parcela.transacao_id == body["id"])
        ).all()
        assert sorted(Decimal(str(p.valor_parcela)) for p in parcelas) == [
            Decimal("33.33"),
            Decimal("33.33"),
            Decimal("33.34"),
        ]
