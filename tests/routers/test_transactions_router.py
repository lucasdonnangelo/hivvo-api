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


# --- Round-trip do caminho de SUCESSO: criação parcelada → fatura ---
# Fecha o gap apontado na investigação: havia teste de atomicidade/FALHA (T-41)
# e da absorção da última parcela (acima), mas nenhum provava a compra parcelada
# chegando às agregações de fatura (GET /cards e GET /cards/{id}/invoices).
#
# Compra 26/06 num cartão que fecha dia 3 (26 > 3 → ciclo seguinte) com offset 1:
# a 1ª parcela cai na fatura (8, 2026) — que também é a fatura ABERTA em 26/06 —
# e as demais avançam mês a mês até (5, 2027). `hoje` fixado (T-27): só a fatura
# aberta de GET /cards usa o relógio; a derivação das parcelas vem de data+cartão.
HOJE_FIXO = dt.date(2026, 6, 26)
FATURA_ABERTA = (8, 2026)
FATURAS_ESPERADAS = [
    (8, 2026), (9, 2026), (10, 2026), (11, 2026), (12, 2026),
    (1, 2027), (2, 2027), (3, 2027), (4, 2027), (5, 2027),
]


class TestCriacaoParceladaRoundTripAteFatura:
    def test_round_trip_criacao_parcelada_ate_fatura(self, session, users, as_user, mocker):
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id)
        client = as_user(user_a)

        # POST /transactions — crédito parcelado 10x de R$ 4.500
        resp = post_parcelada(
            client, valor="4500.00", n=10, cartao_id=card.id,
            data="2026-06-26", descricao="Notebook Dell", categoria="Outros",
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["parcelas_criadas"] == 10
        assert body["parcelado"] is True
        # A fatura da transação-pai vem das parcelas — a linha-pai não a carrega
        assert body["fatura_mes"] is None
        assert body["fatura_ano"] is None

        # 10 parcelas, numeradas 1..10, com usuario_id/cartao_id corretos
        parcelas = session.exec(
            select(Parcela)
            .where(Parcela.transacao_id == body["id"])
            .order_by(Parcela.numero_parcela)
        ).all()
        assert [p.numero_parcela for p in parcelas] == list(range(1, 11))
        assert all(p.usuario_id == user_a.id for p in parcelas)
        assert all(p.cartao_id == card.id for p in parcelas)
        assert all(p.total_parcelas == 10 for p in parcelas)

        # Soma das parcelas == total da compra (a absorção da última com resto
        # está coberta em TestT41.../test_sucesso_persiste_transacao_e_parcelas)
        soma = sum((Decimal(str(p.valor_parcela)) for p in parcelas), Decimal("0.00"))
        assert soma == Decimal("4500.00")

        # fatura_mes/ano avançam mês a mês a partir da fatura derivada
        assert [(p.fatura_mes, p.fatura_ano) for p in parcelas] == FATURAS_ESPERADAS

        # GET /cards: só a parcela da fatura aberta entra no "usado"
        (card_body,) = client.get("/cards").json()
        assert (card_body["fatura_aberta_mes"], card_body["fatura_aberta_ano"]) == FATURA_ABERTA
        assert Decimal(str(card_body["fatura_aberta_total"])) == Decimal("450.00")

        # GET /cards/{id}/invoices: 10 faturas, uma por mês, R$ 450 cada
        invoices = client.get(f"/cards/{card.id}/invoices").json()
        assert len(invoices) == 10
        assert {(f["mes"], f["ano"]) for f in invoices} == set(FATURAS_ESPERADAS)
        assert all(Decimal(str(f["total"])) == Decimal("450.00") for f in invoices)
        assert all(f["total_itens"] == 1 for f in invoices)

        # GET /cards/{id}/invoices/{ano}/{mes}: detalhe da fatura aberta
        mes, ano = FATURA_ABERTA
        detalhe = client.get(f"/cards/{card.id}/invoices/{ano}/{mes}").json()
        assert Decimal(str(detalhe["total"])) == Decimal("450.00")
        assert len(detalhe["parcelas"]) == 1
        assert detalhe["parcelas"][0]["numero_parcela"] == 1
        # A transação-pai parcelada não entra como avulsa
        assert detalhe["avulsas"] == []

    def test_transacao_pai_parcelada_fatura_none_e_ignorada_nas_avulsas(
        self, session, users, as_user, mocker
    ):
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id)
        client = as_user(user_a)

        body = post_parcelada(
            client, valor="4500.00", n=10, cartao_id=card.id, data="2026-06-26"
        ).json()

        # A linha-pai persistida tem fatura_mes/ano None (a fatura vem das parcelas)
        pai = session.get(Transacao, body["id"])
        assert pai.parcelado is True
        assert pai.fatura_mes is None
        assert pai.fatura_ano is None

        # A agregação de avulsas filtra parcelado=False → ignora a transação-pai;
        # o total da fatura aberta vem só da parcela, sem dupla contagem.
        mes, ano = FATURA_ABERTA
        detalhe = client.get(f"/cards/{card.id}/invoices/{ano}/{mes}").json()
        assert detalhe["avulsas"] == []
        assert Decimal(str(detalhe["total"])) == Decimal("450.00")


class TestOrdenacaoEstavel:
    """T-29 — GET /transactions ordena por data DESC, id DESC (desempate
    determinístico). Sem o tiebreak, transações do mesmo dia saíam em ordem
    de heap do Postgres (a criada por último não vinha no topo)."""

    def test_mesmo_dia_ordena_por_id_desc(self, session, users, as_user):
        client = as_user(users[0])

        # 3 transações no MESMO dia, criadas em sequência → ids crescentes
        ids = [
            post_transacao(client, data="2026-06-26", descricao=f"T{i}").json()["id"]
            for i in range(3)
        ]
        assert ids == sorted(ids)  # criação em ordem crescente de id

        returned = [t["id"] for t in client.get("/transactions").json()]
        # mais recente (maior id) primeiro
        assert returned == sorted(ids, reverse=True)

    def test_datas_diferentes_data_desc_depois_id_desc(self, session, users, as_user):
        client = as_user(users[0])

        # Dia mais antigo (25) e dia mais recente (26), dois lançamentos cada,
        # criados intercalando os dias para provar que a ordem final não é só id.
        a1 = post_transacao(client, data="2026-06-25", descricao="A1").json()["id"]
        b1 = post_transacao(client, data="2026-06-26", descricao="B1").json()["id"]
        a2 = post_transacao(client, data="2026-06-25", descricao="A2").json()["id"]
        b2 = post_transacao(client, data="2026-06-26", descricao="B2").json()["id"]

        returned = [t["id"] for t in client.get("/transactions").json()]
        # Entre dias: data DESC (26 antes de 25). Dentro do dia: id DESC.
        assert returned == [b2, b1, a2, a1]

    def test_avulsas_do_detalhe_de_fatura_mesmo_dia_ordena_por_id_desc(
        self, session, users, as_user, mocker
    ):
        # O detalhe de fatura também lista Transacao (avulsas) com o mesmo
        # desempate. Direção inalterada (já era data DESC); aqui a rede garante
        # o id DESC entre avulsas do mesmo dia na mesma fatura.
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id)
        client = as_user(user_a)

        # 3 avulsas de crédito no mesmo dia → mesma fatura (8/2026), ids crescentes
        ids = [
            post_transacao(
                client, data="2026-06-26", descricao=f"Av{i}", cartao_id=card.id
            ).json()["id"]
            for i in range(3)
        ]
        mes, ano = FATURA_ABERTA
        detalhe = client.get(f"/cards/{card.id}/invoices/{ano}/{mes}").json()
        returned = [t["id"] for t in detalhe["avulsas"]]
        assert returned == sorted(ids, reverse=True)


class TestT10FiltroSargavel:
    """T-10: GET /transactions com range de datas. As mesmas linhas de antes em
    todos os combos de mes/ano (incluindo borda dez e mes isolado entre anos)."""

    def _seed(self, client):
        post_transacao(client, data="2025-12-31", descricao="dez2025")
        post_transacao(client, data="2026-01-15", descricao="jan2026")
        post_transacao(client, data="2026-02-15", descricao="fev2026")
        post_transacao(client, data="2027-01-20", descricao="jan2027")

    def _descrs(self, client, query=""):
        return {t["descricao"] for t in client.get(f"/transactions{query}").json()}

    def test_mes_e_ano(self, session, users, as_user):
        client = as_user(users[0])
        self._seed(client)
        assert self._descrs(client, "?mes=1&ano=2026") == {"jan2026"}

    def test_so_ano(self, session, users, as_user):
        client = as_user(users[0])
        self._seed(client)
        assert self._descrs(client, "?ano=2026") == {"jan2026", "fev2026"}

    def test_so_mes_qualquer_ano(self, session, users, as_user):
        client = as_user(users[0])
        self._seed(client)
        assert self._descrs(client, "?mes=1") == {"jan2026", "jan2027"}

    def test_sem_filtro_retorna_tudo(self, session, users, as_user):
        client = as_user(users[0])
        self._seed(client)
        assert len(client.get("/transactions").json()) == 4

    def test_borda_dezembro(self, session, users, as_user):
        client = as_user(users[0])
        self._seed(client)
        assert self._descrs(client, "?mes=12&ano=2025") == {"dez2025"}


class TestT12Paginacao:
    """T-12: limit (default 100, clamp 500), offset estável e /export sem teto.
    Mantém array nu — sem envelope {items,total}."""

    def _seed(self, session, usuario_id, n):
        # Mesma data → ordenação cai no desempate id DESC (T-29). Insere via sessão
        # (rápido) o suficiente para passar do teto de 500.
        for _ in range(n):
            session.add(
                Transacao(
                    usuario_id=usuario_id,
                    tipo="despesa",
                    data=dt.date(2026, 1, 1),
                    descricao="x",
                    valor=Decimal("10.00"),
                    categoria="C",
                )
            )
        session.commit()

    def test_default_limita_em_100(self, session, users, as_user):
        self._seed(session, users[0].id, 501)
        assert len(as_user(users[0]).get("/transactions").json()) == 100

    def test_limit_acima_de_500_clampa(self, session, users, as_user):
        self._seed(session, users[0].id, 501)
        # 1000 não dá 422 — é clampado a 500
        assert len(as_user(users[0]).get("/transactions?limit=1000").json()) == 500

    def test_offset_pagina_sem_overlap_e_estavel(self, session, users, as_user):
        self._seed(session, users[0].id, 501)
        client = as_user(users[0])
        page1 = [t["id"] for t in client.get("/transactions?limit=5&offset=0").json()]
        page2 = [t["id"] for t in client.get("/transactions?limit=5&offset=5").json()]
        assert len(page1) == 5 and len(page2) == 5
        assert set(page1).isdisjoint(page2)  # sem overlap entre páginas
        # data DESC, id DESC: página 1 são os maiores ids; página 2 vem logo abaixo
        assert min(page1) > max(page2)
        assert page1 == sorted(page1, reverse=True)

    def test_offset_alem_do_fim_retorna_vazio(self, session, users, as_user):
        self._seed(session, users[0].id, 501)
        assert as_user(users[0]).get("/transactions?limit=10&offset=600").json() == []

    def test_export_retorna_tudo_sem_teto(self, session, users, as_user):
        self._seed(session, users[0].id, 501)
        export = as_user(users[0]).get("/transactions/export").json()
        assert len(export) == 501  # mais que o limite da listagem
        ids = [t["id"] for t in export]
        assert ids == sorted(ids, reverse=True)  # mesma ordenação estável
