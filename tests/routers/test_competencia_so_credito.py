"""Só o CRÉDITO deriva competência de fatura — a compra no débito guarda o
cartão em que aconteceu e NÃO vira dívida a pagar.

O defeito, medido em 27/08/2026: a condição do POST dizia "Crédito avulso" no
comentário e não testava forma de pagamento nenhuma — quem decidia era o cartão
ter `dia_vencimento`. Uma despesa no DÉBITO num cartão "Ambos" gravava
fatura_mes=10/2026, virava fatura aberta de R$ 250,00 vencendo 10/10 e comia
R$ 250,00 do limite. Dinheiro que já saiu da conta aparecendo como dívida.

GEOMETRIA DA FIXTURE — e por que ela é ESTA e não outra.
Cartão "Ambos", fech. 3 / venc. 10 / offset 1, compra em 10/08/2026. A compra é
depois do fechamento (10 > 3), então o mês-base anda +1 e a competência
derivada seria **(10, 2026)** — um valor CONCRETO e NÃO-NULO.

Isso é o ponto todo. Um cartão de tipo "Débito" sem `dia_vencimento` seria
fixture INÚTIL aqui: ele já grava NULL hoje, com o defeito intacto, porque cai
no `card.dia_vencimento` falsy — o teste passaria verde sem distinguir nada.
Só a fixture que TEM competência a derivar separa "a régua funcionou" de "não
havia nada a derivar". O controle de crédito na mesma fixture (que exige
exatamente 10/2026) prova que o caminho está vivo, não desligado.
"""

import datetime as dt
from decimal import Decimal

from app.models.card import Cartao
from app.models.transaction import Transacao
from app.services.faturas import _fatura_cartao_avulso

# A compra e a competência que ela geraria SE fosse crédito.
DATA_COMPRA = "2026-08-10"
COMPETENCIA_SE_FOSSE_CREDITO = (10, 2026)
HOJE_FIXO = dt.date(2026, 8, 15)


def make_card_ambos(session, usuario_id: int) -> Cartao:
    """Cartão que faz débito E crédito — o caso onde o defeito aparecia.

    'Ambos' é a forma mais comum de cartão real (Nubank, Inter) e é justamente
    um dos tipos que o seletor do formulário passa a oferecer no débito.
    """
    card = Cartao(
        usuario_id=usuario_id,
        nome="Nubank",
        tipo="Ambos",
        limite=Decimal("5000.00"),
        dia_fechamento=3,
        dia_vencimento=10,
        mes_offset_vencimento=1,
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def payload(**over):
    base = dict(
        tipo="despesa",
        data=DATA_COMPRA,
        descricao="Padaria",
        valor="250.00",
        categoria="Mercado",
    )
    base.update(over)
    return base


class TestFixtureDistingue:
    def test_a_fixture_TEM_competencia_a_derivar(self, session, users):
        """Guarda da própria fixture: se a derivação desse NULL aqui, todo o
        resto deste arquivo passaria verde sem provar nada."""
        card = make_card_ambos(session, users[0].id)
        assert _fatura_cartao_avulso(dt.date(2026, 8, 10), card) == COMPETENCIA_SE_FOSSE_CREDITO


class TestPostNaoDerivaForaDoCredito:
    def test_debito_com_cartao_grava_o_cartao_e_NAO_grava_competencia(
        self, session, users, as_user
    ):
        """O conserto inteiro numa asserção: o dado que faltava passa a ser
        guardado, e o dado errado não é criado no lugar dele."""
        user, _ = users
        card = make_card_ambos(session, user.id)

        r = as_user(user).post(
            "/transactions", json=payload(forma_pagamento="Débito", cartao_id=card.id)
        )
        assert r.status_code == 201, r.text

        tx = session.get(Transacao, r.json()["id"])
        session.refresh(tx)
        assert tx.cartao_id == card.id  # a atribuição: em QUAL cartão aconteceu
        assert tx.fatura_mes is None  # a cobrança: NÃO existe
        assert tx.fatura_ano is None

    def test_credito_no_MESMO_cartao_continua_derivando(self, session, users, as_user):
        """Controle. Sem ele, um `return False` incondicional passaria."""
        user, _ = users
        card = make_card_ambos(session, user.id)

        r = as_user(user).post(
            "/transactions", json=payload(forma_pagamento="Crédito", cartao_id=card.id)
        )
        assert r.status_code == 201, r.text

        tx = session.get(Transacao, r.json()["id"])
        session.refresh(tx)
        assert (tx.fatura_mes, tx.fatura_ano) == COMPETENCIA_SE_FOSSE_CREDITO

    def test_lista_BRANCA_pix_dinheiro_e_ted_tambem_nao_derivam(
        self, session, users, as_user
    ):
        """A régua é lista branca, não "tudo menos Débito".

        PIX, Dinheiro e TED/DOC com cartão são o mesmo caso do débito — o
        dinheiro já saiu. Uma lista negra deixaria os três vazarem para a
        fatura, em silêncio.
        """
        user, _ = users
        card = make_card_ambos(session, user.id)
        client = as_user(user)

        for forma in ("PIX", "Dinheiro", "TED/DOC"):
            r = client.post(
                "/transactions", json=payload(forma_pagamento=forma, cartao_id=card.id)
            )
            assert r.status_code == 201, r.text
            tx = session.get(Transacao, r.json()["id"])
            session.refresh(tx)
            assert tx.fatura_mes is None, f"{forma} vazou para a fatura"
            assert tx.fatura_ano is None, f"{forma} vazou para a fatura"


class TestCruzamentoComOEstorno:
    """O cruzamento com o #48 — e por que ele precisa de teste próprio.

    O #48 deixou o cartão DISPONÍVEL no estorno de propósito: devolução que cai
    na fatura é caso real, e o POST deriva a competência certa para ela (o
    estorno ABATE na fatura dele). Aquela decisão foi tomada quando `showCartao`
    era `isCredito && !recorrente` — ou seja, estorno com cartão só existia no
    crédito.

    Esta leva mudou a condição para `(isCredito || isDebito)`, e `showCartao`
    NÃO é gated por `isEstorno`. Logo a combinação estorno + Débito + cartão
    passou a ser alcançável pela tela, e ela não existia quando o #48 foi
    verificado. A lista branca protege por construção, mas "por construção" é
    exatamente o que se afirma sem medir.

    E aqui o dano seria de sinal INVERTIDO, não igual ao da despesa: estorno
    compõe fatura como valor NEGATIVO (`valor_avulsa_liquido`), então um estorno
    no débito com competência derivada viraria crédito fantasma ABATENDO uma
    fatura que ele nunca tocou — a régua anti-subconta do #9 pelo avesso.
    """

    def test_estorno_no_debito_guarda_o_cartao_e_NAO_ganha_competencia(
        self, session, users, as_user
    ):
        user, _ = users
        card = make_card_ambos(session, user.id)

        r = as_user(user).post(
            "/transactions",
            json=payload(tipo="estorno", forma_pagamento="Débito", cartao_id=card.id),
        )
        assert r.status_code == 201, r.text

        tx = session.get(Transacao, r.json()["id"])
        session.refresh(tx)
        assert tx.tipo == "estorno"
        assert tx.cartao_id == card.id
        assert tx.fatura_mes is None
        assert tx.fatura_ano is None

    def test_estorno_no_CREDITO_continua_abatendo_a_fatura_do_48(
        self, session, users, as_user, mocker
    ):
        """O par: a decisão do #48 segue intacta. Sem isto, a régua nova poderia
        ter fechado a porta que aquele batch abriu de propósito."""
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        mocker.patch("app.routers.invoices.hoje", return_value=HOJE_FIXO)
        user, _ = users
        card = make_card_ambos(session, user.id)
        client = as_user(user)

        client.post(
            "/transactions", json=payload(forma_pagamento="Crédito", cartao_id=card.id)
        )
        r = client.post(
            "/transactions",
            json=payload(
                tipo="estorno", forma_pagamento="Crédito", cartao_id=card.id, valor="90.00"
            ),
        )
        assert r.status_code == 201, r.text

        tx = session.get(Transacao, r.json()["id"])
        session.refresh(tx)
        assert (tx.fatura_mes, tx.fatura_ano) == COMPETENCIA_SE_FOSSE_CREDITO

        # 250,00 da despesa − 90,00 do estorno, na mesma competência.
        (fatura,) = client.get(f"/cards/{card.id}/invoices").json()
        assert Decimal(str(fatura["total"])) == Decimal("160.00")


class TestFormaPagamentoERestritaPeloTIPO:
    def test_grafia_fora_do_conjunto_morre_com_422(self, session, users, as_user):
        """A restrição é o TIPO, não um `if` (precedente do #48).

        `forma_pagamento` virou a régua que decide se a compra entra em fatura.
        Uma régua que compara strings é derrotada em silêncio pela próxima
        grafia divergente — e havia uma no repo ("Pix" vs "PIX"). Com o
        Literal, a grafia errada não chega até a comparação.
        """
        user, _ = users
        card = make_card_ambos(session, user.id)
        client = as_user(user)

        for grafia in ("credito", "CRÉDITO", "Credito", "Crédito "):
            r = client.post(
                "/transactions", json=payload(forma_pagamento=grafia, cartao_id=card.id)
            )
            assert r.status_code == 422, f"{grafia!r} passou: {r.text}"


class TestOsNUMEROSQueOUsuarioVe:
    """A prova escrita contra o dinheiro na tela, não contra a coluna gravada."""

    def test_debito_no_cartao_nao_vira_fatura_aberta_nem_come_limite(
        self, session, users, as_user, mocker
    ):
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        mocker.patch("app.routers.invoices.hoje", return_value=HOJE_FIXO)
        user, _ = users
        card = make_card_ambos(session, user.id)
        client = as_user(user)

        r = client.post(
            "/transactions", json=payload(forma_pagamento="Débito", cartao_id=card.id)
        )
        assert r.status_code == 201, r.text

        # Antes do conserto: [{'mes': 10, 'ano': 2026, 'total': '250.00',
        # 'data_vencimento': '2026-10-10', 'total_itens': 1, 'status': 'aberta'}]
        assert client.get(f"/cards/{card.id}/invoices").json() == []

        (visao,) = client.get("/cards").json()
        assert Decimal(str(visao["limite_usado"])) == Decimal("0.00")
        # O ciclo aberto do cartão CONTINUA existindo (o cartão faz crédito) —
        # o que ele não tem é conteúdo. Asserção é sobre o total, não sobre a
        # ausência da competência.
        assert Decimal(str(visao["fatura_aberta_total"])) == Decimal("0.00")

    def test_credito_no_mesmo_cartao_AINDA_vira_fatura_e_come_limite(
        self, session, users, as_user, mocker
    ):
        """O par do teste acima. Juntos eles provam que o corte é a forma de
        pagamento — mesma fixture, mesma data, mesmo valor, único delta."""
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        mocker.patch("app.routers.invoices.hoje", return_value=HOJE_FIXO)
        user, _ = users
        card = make_card_ambos(session, user.id)
        client = as_user(user)

        r = client.post(
            "/transactions", json=payload(forma_pagamento="Crédito", cartao_id=card.id)
        )
        assert r.status_code == 201, r.text

        (fatura,) = client.get(f"/cards/{card.id}/invoices").json()
        assert (fatura["mes"], fatura["ano"]) == COMPETENCIA_SE_FOSSE_CREDITO
        assert Decimal(str(fatura["total"])) == Decimal("250.00")

        (visao,) = client.get("/cards").json()
        assert Decimal(str(visao["limite_usado"])) == Decimal("250.00")


class TestPutRederivaQuandoAFormaMuda:
    """O terceiro estado: o EditTransactionModal oferece trocar a forma de
    pagamento mas NÃO expõe cartao_id. Antes, o PUT só rederivava quando `data`
    ou `cartao_id` vinham no payload — trocar só a forma deixava a competência
    velha, e a compra seguia na fatura depois de deixar de ser dívida."""

    def _cria_credito(self, session, users, as_user):
        user, _ = users
        card = make_card_ambos(session, user.id)
        client = as_user(user)
        r = client.post(
            "/transactions", json=payload(forma_pagamento="Crédito", cartao_id=card.id)
        )
        assert r.status_code == 201, r.text
        tx = session.get(Transacao, r.json()["id"])
        session.refresh(tx)
        assert (tx.fatura_mes, tx.fatura_ano) == COMPETENCIA_SE_FOSSE_CREDITO
        return client, card, tx

    def test_trocar_SO_a_forma_para_debito_ZERA_a_competencia(
        self, session, users, as_user
    ):
        client, card, tx = self._cria_credito(session, users, as_user)

        r = client.put(f"/transactions/{tx.id}", json={"forma_pagamento": "Débito"})
        assert r.status_code == 200, r.text

        session.refresh(tx)
        assert tx.cartao_id == card.id  # o cartão FICA: é atribuição
        assert tx.fatura_mes is None  # a competência SAI: não é mais dívida
        assert tx.fatura_ano is None

    def test_trocar_a_forma_de_volta_para_credito_REDERIVA(
        self, session, users, as_user
    ):
        """O inverso, para o gatilho não poder ser um `= None` incondicional."""
        client, card, tx = self._cria_credito(session, users, as_user)

        client.put(f"/transactions/{tx.id}", json={"forma_pagamento": "Débito"})
        r = client.put(f"/transactions/{tx.id}", json={"forma_pagamento": "Crédito"})
        assert r.status_code == 200, r.text

        session.refresh(tx)
        assert (tx.fatura_mes, tx.fatura_ano) == COMPETENCIA_SE_FOSSE_CREDITO

    def test_a_compra_sai_da_fatura_na_tela_quando_vira_debito(
        self, session, users, as_user, mocker
    ):
        mocker.patch("app.routers.cards.hoje", return_value=HOJE_FIXO)
        mocker.patch("app.routers.invoices.hoje", return_value=HOJE_FIXO)
        client, card, tx = self._cria_credito(session, users, as_user)
        assert len(client.get(f"/cards/{card.id}/invoices").json()) == 1

        client.put(f"/transactions/{tx.id}", json={"forma_pagamento": "Débito"})

        assert client.get(f"/cards/{card.id}/invoices").json() == []
        (visao,) = client.get("/cards").json()
        assert Decimal(str(visao["limite_usado"])) == Decimal("0.00")
