"""T-36 — isolamento entre usuários nas agregações de GET /cards.

Antes do fix, as agregações de fatura filtravam só por cartao_id + fatura:
parcelas/avulsas de OUTRO usuário apontando para o cartão (dado legado ou
escrito antes da validação de propriedade) inflavam o total exibido ao dono.
"""

import datetime as dt
from decimal import Decimal

from app.models.card import Cartao
from app.models.installment import Parcela
from app.models.pagamento_fatura import PagamentoFatura
from app.models.transaction import Transacao

HOJE_FIXO = dt.date(2026, 6, 10)
# Cartão: fechamento 25, vencimento 5, offset 1 → em 10/06 a fatura aberta é (7, 2026)
FATURA_ABERTA = (7, 2026)
# Competências usadas pelos testes de limite comprometido. PASSADO e FUTURO em
# volta da aberta não são decoração: um cálculo que volte a olhar UMA
# competência precisa DIVERGIR do esperado, e para isso a fixture tem que ter
# competência dos dois lados da aberta, com valores distintos.
PASSADA_FECHADA = (6, 2026)  # fecha em 25/05/2026 → pagável em 10/06 (PUT aceita)
FUTURA = (8, 2026)


def make_card(session, usuario_id: int, limite: str | None = None) -> Cartao:
    card = Cartao(
        usuario_id=usuario_id,
        nome="Nubank",
        tipo="Crédito",
        limite=Decimal(limite) if limite is not None else None,
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


class TestCartaoDebitoSemFatura:
    """Cartão de débito não tem fatura: limite/fechamento/vencimento não se aplicam.

    Estes testes fixam o contrato do backend para os dois jeitos que o débito
    pode chegar: campos AUSENTES e campos EXPLICITAMENTE null (é assim que o
    form do hivvo-web manda). O caso null quebrava com 422 em mes_offset_vencimento
    (int não-anulável) — ver test_criar_debito_com_campos_null_retorna_201.
    """

    def test_criar_debito_sem_campos_de_fatura_retorna_201(self, users, as_user):
        (user_a, _) = users
        response = as_user(user_a).post("/cards", json={"nome": "Nubank Débito", "tipo": "Débito"})
        assert response.status_code == 201
        body = response.json()
        assert body["tipo"] == "Débito"
        assert body["limite"] is None
        assert body["dia_fechamento"] is None
        assert body["dia_vencimento"] is None

    def test_criar_debito_com_campos_null_retorna_201(self, users, as_user):
        # Payload EXATO do form de débito: null nos 4 campos de fatura. Antes do fix,
        # mes_offset_vencimento (int não-anulável) rejeitava o null com 422 e o toast
        # genérico do front escondia o motivo. Agora null cai no default 1.
        (user_a, _) = users
        response = as_user(user_a).post(
            "/cards",
            json={
                "nome": "Nubank Débito",
                "tipo": "Débito",
                "limite": None,
                "dia_fechamento": None,
                "dia_vencimento": None,
                "mes_offset_vencimento": None,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["tipo"] == "Débito"
        assert body["mes_offset_vencimento"] == 1

    def test_criar_credito_sem_campos_de_fatura_continua_aceito(self, users, as_user):
        # Comportamento atual da API preservado: crédito sem os campos ainda é
        # aceito pelo backend (a obrigatoriedade de fatura no crédito vive no form).
        (user_a, _) = users
        response = as_user(user_a).post("/cards", json={"nome": "Nubank", "tipo": "Crédito"})
        assert response.status_code == 201
        assert response.json()["tipo"] == "Crédito"


class TestBloqueioEdicaoDatasComCompras:
    """PUT /cards/{id}: dia_fechamento/dia_vencimento só mudam se o cartão NÃO
    tem compras — alterá-los com fatura já materializada causaria incoerência
    silenciosa (fatura_mes congelado vs. leituras que usam o dia novo)."""

    def test_editar_datas_sem_compras_200(self, session, users, as_user):
        user_a, _ = users
        card = make_card(session, user_a.id)  # fechamento 25, vencimento 5
        resp = as_user(user_a).put(
            f"/cards/{card.id}", json={"dia_fechamento": 20, "dia_vencimento": 8}
        )
        assert resp.status_code == 200
        assert resp.json()["dia_fechamento"] == 20
        assert resp.json()["dia_vencimento"] == 8

    def test_editar_datas_com_parcela_422(self, session, users, as_user):
        user_a, _ = users
        card = make_card(session, user_a.id)
        add_parcela(session, user_a.id, card.id, "100.00")
        resp = as_user(user_a).put(f"/cards/{card.id}", json={"dia_fechamento": 20})
        assert resp.status_code == 422
        assert "novo cartão" in resp.json()["detail"]

    def test_editar_datas_com_avulsa_422(self, session, users, as_user):
        user_a, _ = users
        card = make_card(session, user_a.id)
        add_avulsa(session, user_a.id, card.id, "50.00")
        resp = as_user(user_a).put(f"/cards/{card.id}", json={"dia_vencimento": 9})
        assert resp.status_code == 422

    def test_editar_offset_com_compras_422(self, session, users, as_user):
        # mes_offset_vencimento corrompe a materialização igual aos dias → bloqueado.
        user_a, _ = users
        card = make_card(session, user_a.id)  # offset 1
        add_parcela(session, user_a.id, card.id, "100.00")
        resp = as_user(user_a).put(f"/cards/{card.id}", json={"mes_offset_vencimento": 0})
        assert resp.status_code == 422

    def test_editar_outros_campos_com_compras_200(self, session, users, as_user):
        # Datas AUSENTES no body (só nome): compras não bloqueiam outros campos.
        user_a, _ = users
        card = make_card(session, user_a.id)
        add_parcela(session, user_a.id, card.id, "100.00")
        resp = as_user(user_a).put(f"/cards/{card.id}", json={"nome": "Renomeado"})
        assert resp.status_code == 200
        assert resp.json()["nome"] == "Renomeado"

    def test_datas_iguais_as_atuais_com_compras_200(self, session, users, as_user):
        # Reenviar os MESMOS valores de data (edição de outro campo no form) não
        # é "mudar" → passa mesmo com compras.
        user_a, _ = users
        card = make_card(session, user_a.id)
        add_parcela(session, user_a.id, card.id, "100.00")
        resp = as_user(user_a).put(
            f"/cards/{card.id}",
            json={"nome": "Novo", "dia_fechamento": 25, "dia_vencimento": 5},
        )
        assert resp.status_code == 200
        assert resp.json()["nome"] == "Novo"


class TestValidacaoFechamentoVencimento:
    """Regra fechamento×vencimento: com mes_offset_vencimento=0 ("mesmo mês") a
    fatura não pode vencer antes de (nem no dia de) fechar. No update PARCIAL o
    router mescla o body com o cartão atual e valida o RESULTADO — mas só quando
    o update toca algum campo da regra (nome/limite num cartão pré-existente
    inválido seguem editáveis; borda do cartão preso: PENDENCIAS #34)."""

    def _card_invalido_preexistente(self, session, usuario_id: int) -> Cartao:
        # Direto na sessão (bypassa o schema): simula cartão criado ANTES da
        # validação — offset 0 com vencimento antes do fechamento.
        card = Cartao(
            usuario_id=usuario_id, nome="Legado", tipo="Crédito",
            dia_fechamento=20, dia_vencimento=10, mes_offset_vencimento=0,
        )
        session.add(card)
        session.commit()
        session.refresh(card)
        return card

    def test_create_mesmo_mes_vencimento_antes_422(self, users, as_user):
        user_a, _ = users
        resp = as_user(user_a).post(
            "/cards",
            json={
                "nome": "Nubank", "tipo": "Crédito",
                "dia_fechamento": 10, "dia_vencimento": 5,
                "mes_offset_vencimento": 0,
            },
        )
        assert resp.status_code == 422
        assert "mesmo mês do fechamento" in str(resp.json())

    def test_create_mesmo_mes_vencimento_depois_201(self, users, as_user):
        user_a, _ = users
        resp = as_user(user_a).post(
            "/cards",
            json={
                "nome": "Nubank", "tipo": "Crédito",
                "dia_fechamento": 10, "dia_vencimento": 15,
                "mes_offset_vencimento": 0,
            },
        )
        assert resp.status_code == 201

    def test_create_mes_seguinte_vencimento_antes_201(self, users, as_user):
        # offset 1: venc < fech é o arranjo comum (fecha dia 25, vence dia 5).
        user_a, _ = users
        resp = as_user(user_a).post(
            "/cards",
            json={
                "nome": "Nubank", "tipo": "Crédito",
                "dia_fechamento": 25, "dia_vencimento": 5,
                "mes_offset_vencimento": 1,
            },
        )
        assert resp.status_code == 201

    def test_update_offset_para_zero_com_datas_atuais_invalidas_422(
        self, session, users, as_user
    ):
        # Mescla: só o offset no body; fechamento 25 / vencimento 5 vêm do
        # cartão → resultado offset=0 com venc<fech é inválido.
        user_a, _ = users
        card = make_card(session, user_a.id)  # fech 25, venc 5, offset 1
        resp = as_user(user_a).put(f"/cards/{card.id}", json={"mes_offset_vencimento": 0})
        assert resp.status_code == 422
        assert "mesmo mês do fechamento" in resp.json()["detail"]

    def test_update_datas_para_conjunto_invalido_422(self, session, users, as_user):
        user_a, _ = users
        card = make_card(session, user_a.id)
        resp = as_user(user_a).put(
            f"/cards/{card.id}",
            json={"dia_fechamento": 22, "dia_vencimento": 20, "mes_offset_vencimento": 0},
        )
        assert resp.status_code == 422

    def test_update_para_conjunto_valido_200(self, session, users, as_user):
        # O escape do cartão inválido SEM lançamentos: corrigir as datas passa.
        user_a, _ = users
        card = self._card_invalido_preexistente(session, user_a.id)
        resp = as_user(user_a).put(f"/cards/{card.id}", json={"mes_offset_vencimento": 1})
        assert resp.status_code == 200
        assert resp.json()["mes_offset_vencimento"] == 1

    def test_update_nome_em_cartao_invalido_preexistente_200(
        self, session, users, as_user
    ):
        # O carve-out: o update não toca campo da regra → a mescla nem roda e a
        # edição de nome/limite não trava no cartão que nasceu inválido.
        user_a, _ = users
        card = self._card_invalido_preexistente(session, user_a.id)
        resp = as_user(user_a).put(f"/cards/{card.id}", json={"nome": "Renomeado"})
        assert resp.status_code == 200
        assert resp.json()["nome"] == "Renomeado"

    def test_update_nome_em_cartao_valido_200(self, session, users, as_user):
        user_a, _ = users
        card = make_card(session, user_a.id)
        resp = as_user(user_a).put(f"/cards/{card.id}", json={"nome": "Novo nome"})
        assert resp.status_code == 200
        assert resp.json()["nome"] == "Novo nome"


class TestTemLancamentosNoGetCards:
    """GET /cards expõe `tem_lancamentos` para o front desabilitar os campos de
    data no form de edição (mesma composição do bloqueio, sem query extra)."""

    def test_tem_lancamentos_true_com_compra_false_sem(self, session, users, as_user, mocker):
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        com = make_card(session, user_a.id)
        add_parcela(session, user_a.id, com.id, "100.00")
        sem = make_card(session, user_a.id)

        cards = {c["id"]: c for c in as_user(user_a).get("/cards").json()}
        assert cards[com.id]["tem_lancamentos"] is True
        assert cards[sem.id]["tem_lancamentos"] is False


# --- Helpers de competência arbitrária (limite comprometido) -----------------
# Os helpers de cima gravam SEMPRE em FATURA_ABERTA, que é exatamente o que um
# teste de "soma todas as competências" não pode usar.


def add_avulsa_em(
    session,
    usuario_id: int,
    cartao_id: int,
    valor: str,
    competencia: tuple[int, int],
    tipo: str = "despesa",
) -> Transacao:
    mes, ano = competencia
    t = Transacao(
        usuario_id=usuario_id,
        tipo=tipo,
        data=dt.date(2026, 6, 1),
        descricao=f"Avulsa {tipo} {valor}",
        valor=Decimal(valor),
        categoria="Compras",
        forma_pagamento="Crédito",
        cartao_id=cartao_id,
        parcelado=False,
        fatura_mes=mes,
        fatura_ano=ano,
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def add_parcelada_em(
    session,
    usuario_id: int,
    cartao_id: int,
    parcelas: list[tuple[str, tuple[int, int]]],
    descricao: str = "Parcelada",
) -> list[Parcela]:
    """Compra parcelada REAL: transação-pai + uma parcela por competência.

    `parcelas` = [(valor, (mes, ano)), ...] na ordem dos números de parcela — o
    mesmo formato materializado por services/parcelas e pelo import de fatura
    (todas as parcelas existem no banco desde a criação, inclusive as FUTURAS).
    """
    n = len(parcelas)
    total = sum(Decimal(v) for v, _ in parcelas)
    base = Transacao(
        usuario_id=usuario_id,
        tipo="despesa",
        data=dt.date(2026, 6, 1),
        descricao=descricao,
        valor=total,
        categoria="Compras",
        forma_pagamento="Crédito",
        cartao_id=cartao_id,
        parcelado=True,
        total_parcelas=n,
    )
    session.add(base)
    session.commit()
    session.refresh(base)

    criadas = []
    for i, (valor, (mes, ano)) in enumerate(parcelas, start=1):
        p = Parcela(
            usuario_id=usuario_id,
            transacao_id=base.id,
            numero_parcela=i,
            total_parcelas=n,
            valor_parcela=Decimal(valor),
            data_vencimento=dt.date(ano, mes, 5),
            descricao=f"{descricao} ({i}/{n})",
            categoria="Compras",
            cartao_id=cartao_id,
            fatura_mes=mes,
            fatura_ano=ano,
        )
        session.add(p)
        criadas.append(p)
    session.commit()
    for p in criadas:
        session.refresh(p)
    return criadas


def competencias_a_partir(
    competencia: tuple[int, int], n: int
) -> list[tuple[int, int]]:
    """`n` competências consecutivas a partir de (mes, ano), virando o ano.

    Uma parcelada longa (10x, 12x, 24x) atravessa dezembro — que é justamente o
    caso em que "somar todas as competências" tem que continuar valendo.
    """
    mes, ano = competencia
    base = ano * 12 + (mes - 1)
    return [((base + k) % 12 + 1, (base + k) // 12) for k in range(n)]


def get_card(client, card_id: int) -> dict:
    return {c["id"]: c for c in client.get("/cards").json()}[card_id]


class TestLimiteComprometido:
    """`limite_usado` = o que resta em aberto em TODAS as competências, abatido
    pelos pagamentos confirmados, com clamp de cobertura POR FATURA.

    O defeito que estes testes fixam: a barra do cartão chamava de "usado" o
    `fatura_aberta_total`, que é UMA competência. O limite se "recuperava"
    sozinho na virada do mês e uma compra em 24x quase não aparecia.
    """

    def test_limite_usado_soma_TODAS_as_competencias_nao_so_a_aberta(
        self, session, users, as_user, mocker
    ):
        # Cinco competências com valores DISTINTOS dos dois lados da aberta.
        # Nenhum subconjunto soma o total, então nenhum recorte de competência
        # (só a aberta, só a primeira, só a última) acerta 3133 por acidente.
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id, limite="10000.00")

        add_avulsa_em(session, user_a.id, card.id, "111.00", (5, 2026))  # passada
        add_avulsa_em(session, user_a.id, card.id, "222.00", (6, 2026))  # passada
        add_avulsa_em(session, user_a.id, card.id, "400.00", FATURA_ABERTA)
        add_avulsa_em(session, user_a.id, card.id, "800.00", (8, 2026))  # futura
        add_avulsa_em(session, user_a.id, card.id, "1600.00", (9, 2026))  # futura

        body = get_card(as_user(user_a), card.id)

        assert Decimal(str(body["limite_usado"])) == Decimal("3133.00")
        # A fatura aberta continua sendo a fatura aberta — mesmo nome, mesmo
        # valor. O que mudou é que ela deixou de responder "quanto do limite".
        assert Decimal(str(body["fatura_aberta_total"])) == Decimal("400.00")

    def test_defeito_medido_duas_parceladas_na_parcela_3(
        self, session, users, as_user, mocker
    ):
        # A medição que abriu o batch: limite 10.000, uma parcelada de 1.000 em
        # 10x e outra de 1.200 em 12x, ambas na parcela 3. A tela mostrava
        # R$ 200,00 usado / R$ 9.800,00 disponível — R$ 200 é a fatura do mês.
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id, limite="10000.00")

        # parcela 3 cai na aberta (7/2026) → 1 e 2 no passado, 4..n no futuro
        # (e a 12x atravessa dezembro, chegando a 04/2027)
        competencias = competencias_a_partir((5, 2026), 12)
        add_parcelada_em(
            session,
            user_a.id,
            card.id,
            [("100.00", c) for c in competencias[:10]],
            descricao="A 10x",
        )
        add_parcelada_em(
            session,
            user_a.id,
            card.id,
            [("100.00", c) for c in competencias[:12]],
            descricao="B 12x",
        )

        body = get_card(as_user(user_a), card.id)

        assert Decimal(str(body["fatura_aberta_total"])) == Decimal("200.00")
        assert Decimal(str(body["limite_usado"])) == Decimal("2200.00")

    def test_fatura_paga_LIBERA_limite_no_valor_pago(
        self, session, users, as_user, mocker
    ):
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        mocker.patch("app.routers.invoices.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id, limite="10000.00")

        add_avulsa_em(session, user_a.id, card.id, "500.00", PASSADA_FECHADA)
        add_avulsa_em(session, user_a.id, card.id, "1000.00", FUTURA)
        client = as_user(user_a)

        assert Decimal(str(get_card(client, card.id)["limite_usado"])) == Decimal(
            "1500.00"
        )

        mes, ano = PASSADA_FECHADA
        resp = client.put(
            f"/invoices/{card.id}/{ano}/{mes}/pagamento", json={"pago": True}
        )
        assert resp.status_code == 200

        # Pagou a de 500 → sobra a futura de 1000. Sem a subtração, seguiria 1500.
        assert Decimal(str(get_card(client, card.id)["limite_usado"])) == Decimal(
            "1000.00"
        )

    def test_valor_pago_acima_do_total_nao_libera_limite_de_OUTRA_competencia(
        self, session, users, as_user, mocker
    ):
        """O clamp POR FATURA (min(valor_pago, total)).

        `valor_pago` é SNAPSHOT do total no instante da confirmação, não
        derivado. Cancelar uma parcela DEPOIS de marcar paga deixa valor_pago
        ACIMA do total atual daquela fatura. Subtrair Σ(valor_pago) global
        deixaria a sobra vazar para OUTRA competência e liberar limite que
        ninguém pagou. A ORDEM é o teste: pagar primeiro, cancelar depois.
        """
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        mocker.patch("app.routers.invoices.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id, limite="10000.00")
        client = as_user(user_a)

        # Fatura passada = 300 + 200 = 500, cada parcela na sua transação.
        add_parcelada_em(
            session, user_a.id, card.id, [("300.00", PASSADA_FECHADA)], "Fica"
        )
        (some,) = add_parcelada_em(
            session, user_a.id, card.id, [("200.00", PASSADA_FECHADA)], "Some"
        )
        add_avulsa_em(session, user_a.id, card.id, "1000.00", FUTURA)

        mes, ano = PASSADA_FECHADA
        pago = client.put(
            f"/invoices/{card.id}/{ano}/{mes}/pagamento", json={"pago": True}
        )
        assert pago.status_code == 200
        assert Decimal(str(pago.json()["valor_pago"])) == Decimal("500.00")

        # AGORA cancela: o total da fatura cai para 300, o valor_pago fica 500.
        assert (
            client.put(f"/installments/{some.id}", json={"cancelado": True}).status_code
            == 200
        )

        # Com clamp: min(500, 300) = 300 → a fatura contribui 0, sobra a futura.
        # Sem clamp: 300 − 500 = −200 vazaria e o total cairia para 800.
        assert Decimal(str(get_card(client, card.id)["limite_usado"])) == Decimal(
            "1000.00"
        )

    def test_pagamento_NAO_confirmado_com_valor_pago_sujo_nao_libera_limite(
        self, session, users, as_user, mocker
    ):
        """`pago=False` é "não confirmado" — equivale à ausência de registro.

        O registro é montado à mão de propósito: o PUT limpa `valor_pago` ao
        reverter, então este estado (pago=False COM valor_pago) só chega por
        dado legado. O CHECK do banco permite (`NOT pago OR valor_pago IS NOT
        NULL` só exige o valor QUANDO pago). Sem o filtro `pago == True` na
        consulta, esse resto liberaria limite que ninguém confirmou ter pago.
        """
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id, limite="10000.00")
        add_avulsa_em(session, user_a.id, card.id, "500.00", PASSADA_FECHADA)

        mes, ano = PASSADA_FECHADA
        session.add(
            PagamentoFatura(
                usuario_id=user_a.id,
                cartao_id=card.id,
                fatura_mes=mes,
                fatura_ano=ano,
                pago=False,
                valor_pago=Decimal("500.00"),
            )
        )
        session.commit()

        body = get_card(as_user(user_a), card.id)
        assert Decimal(str(body["limite_usado"])) == Decimal("500.00")

    def test_estorno_ABATE_o_limite_usado(self, session, users, as_user, mocker):
        """Par inseparável _cond_avulsas_fatura + valor_avulsa_liquido.

        Antes deste batch a soma do GET /cards era `tipo == "despesa"` com
        `Transacao.valor` cru: o MESMO estorno abatia em
        GET /cards/{id}/invoices e no "A pagar", e não abatia na barra de
        limite — dois números para a mesma fatura, em duas telas.
        """
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id, limite="10000.00")

        add_avulsa_em(session, user_a.id, card.id, "500.00", FATURA_ABERTA)
        add_avulsa_em(
            session, user_a.id, card.id, "200.00", FATURA_ABERTA, tipo="estorno"
        )
        add_avulsa_em(session, user_a.id, card.id, "1000.00", FUTURA)

        body = get_card(as_user(user_a), card.id)

        assert Decimal(str(body["fatura_aberta_total"])) == Decimal("300.00")
        assert Decimal(str(body["limite_usado"])) == Decimal("1300.00")

    def test_parcela_cancelada_devolve_limite_em_TODAS_as_competencias(
        self, session, users, as_user, mocker
    ):
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id, limite="10000.00")
        client = as_user(user_a)

        parcelas = add_parcelada_em(
            session,
            user_a.id,
            card.id,
            [
                ("250.00", PASSADA_FECHADA),
                ("250.00", FATURA_ABERTA),
                ("250.00", FUTURA),
                ("250.00", (9, 2026)),
            ],
        )
        assert Decimal(str(get_card(client, card.id)["limite_usado"])) == Decimal(
            "1000.00"
        )

        # Cancelar a parcela FUTURA devolve limite sem tocar na fatura aberta.
        assert (
            client.put(
                f"/installments/{parcelas[3].id}", json={"cancelado": True}
            ).status_code
            == 200
        )

        body = get_card(client, card.id)
        assert Decimal(str(body["limite_usado"])) == Decimal("750.00")
        assert Decimal(str(body["fatura_aberta_total"])) == Decimal("250.00")

    def test_avulsa_sem_competencia_nao_compoe_limite_mas_conta_como_lancamento(
        self, session, users, as_user, mocker
    ):
        """Cartão sem dia_vencimento: a avulsa é gravada com fatura_mes nulo.

        Não compõe fatura (logo fica fora de `limite_usado`), mas É compra — e
        `tem_lancamentos` precisa dizer True, senão o front habilita os campos
        de data que o PUT recusa com 422.
        """
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = Cartao(
            usuario_id=user_a.id,
            nome="Sem datas",
            tipo="Crédito",
            limite=Decimal("5000.00"),
        )
        session.add(card)
        session.commit()
        session.refresh(card)

        t = Transacao(
            usuario_id=user_a.id,
            tipo="despesa",
            data=dt.date(2026, 6, 1),
            descricao="Sem competência",
            valor=Decimal("300.00"),
            categoria="Compras",
            forma_pagamento="Crédito",
            cartao_id=card.id,
            parcelado=False,
        )
        session.add(t)
        session.commit()

        body = get_card(as_user(user_a), card.id)
        assert Decimal(str(body["limite_usado"])) == Decimal("0.00")
        assert body["tem_lancamentos"] is True

    def test_limite_usado_exclui_dados_de_outro_usuario(
        self, session, users, as_user, mocker
    ):
        # T-36 no eixo novo: a soma multi-competência não pode reintroduzir o
        # vazamento entre usuários que a soma da fatura aberta já fecha.
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, user_b = users
        card = make_card(session, user_a.id, limite="10000.00")

        add_avulsa_em(session, user_a.id, card.id, "400.00", FUTURA)
        add_avulsa_em(session, user_b.id, card.id, "999.00", FUTURA)
        add_parcelada_em(session, user_b.id, card.id, [("999.00", PASSADA_FECHADA)])

        body = get_card(as_user(user_a), card.id)
        assert Decimal(str(body["limite_usado"])) == Decimal("400.00")


def add_estorno(session, usuario_id: int, cartao_id: int, valor: str) -> Transacao:
    """Estorno de cartão na fatura aberta — valor POSITIVO no banco, sinal
    aplicado na leitura (valor_avulsa_liquido)."""
    t = Transacao(
        usuario_id=usuario_id,
        tipo="estorno",
        data=dt.date(2026, 6, 1),
        descricao="Estorno",
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


class TestComposicaoCanonicaNoGetCards:
    """GET /cards soma avulsas pela fonte única da composição.

    A soma era `tipo == "despesa"` com `Transacao.valor` cru, fora do par
    inseparável `_cond_avulsas_fatura` + `valor_avulsa_liquido`. O MESMO estorno
    abatia em GET /cards/{id}/invoices e no "A pagar" do dashboard, e não abatia
    aqui — dois números para a mesma fatura, em duas telas.
    """

    def test_estorno_ABATE_a_fatura_aberta(self, session, users, as_user, mocker):
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id)

        add_avulsa(session, user_a.id, card.id, "500.00")
        add_estorno(session, user_a.id, card.id, "200.00")

        (body,) = as_user(user_a).get("/cards").json()
        assert Decimal(str(body["fatura_aberta_total"])) == Decimal("300.00")

    def test_cartao_SO_com_estorno_tem_lancamentos_true(
        self, session, users, as_user, mocker
    ):
        # `cartao_tem_lancamentos` (que o PUT usa para o 422) sempre disse True
        # aqui; a derivação do GET dizia False enquanto filtrava só "despesa".
        # O front habilitaria um campo de data que o servidor recusa.
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        user_a, _ = users
        card = make_card(session, user_a.id)
        add_estorno(session, user_a.id, card.id, "200.00")

        (body,) = as_user(user_a).get("/cards").json()
        assert body["tem_lancamentos"] is True
        assert (
            as_user(user_a)
            .put(f"/cards/{card.id}", json={"dia_fechamento": 20})
            .status_code
            == 422
        )
