"""#9 Fase 1 — aviso de compra caindo em fatura JÁ marcada como paga.

POST /transactions passa a devolver `avisos` (default []): quando QUALQUER
competência tocada pela compra tem PagamentoFatura.pago=True, entra um aviso
codigo="fatura_paga" com as competências atingidas (estrutura pura — a copy
é do frontend). NÃO-bloqueante: o lançamento sempre persiste (201) e nada é
materializado — pagamentos_fatura fica intacto (detecção read-only).

Geometria dos testes: cartão fech. 3 / venc. 10 / offset 1, compra 15/01/2026
(após o fechamento) → à vista cai na competência (3, 2026); parcelada 3x cai
em (3, 2026), (4, 2026) e (5, 2026) — mesma derivação provada em
test_transactions_router.TestT35RederivacaoDeFatura.
"""

import datetime as dt

from sqlmodel import select

from app.models.card import Cartao
from app.models.pagamento_fatura import PagamentoFatura
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


def marca_pagamento(session, usuario_id, cartao_id, mes, ano, pago=True):
    """Seed direto do registro de pagamento (a detecção é read-only — não
    importa COMO o registro nasceu, só a chave natural + pago)."""
    session.add(
        PagamentoFatura(
            usuario_id=usuario_id,
            cartao_id=cartao_id,
            fatura_mes=mes,
            fatura_ano=ano,
            pago=pago,
            data_pagamento=dt.date(2026, mes, 10) if pago else None,
        )
    )
    session.commit()


def post_transacao(client, **overrides):
    payload = {
        "tipo": "despesa",
        "data": "2026-01-15",
        "descricao": "Compra Retroativa",
        "valor": "300.00",
        "categoria": "Compras",
        "forma_pagamento": "Crédito",
    }
    payload.update(overrides)
    return client.post("/transactions", json=payload)


def post_parcelada(client, n=3, **overrides):
    return post_transacao(client, parcelado=True, total_parcelas=n, **overrides)


class TestAvisoAVista:
    def test_avista_em_fatura_paga_gera_aviso_e_persiste(self, session, users, as_user):
        user_a, _ = users
        card = make_card(session, user_a.id)
        marca_pagamento(session, user_a.id, card.id, 3, 2026)

        resp = post_transacao(as_user(user_a), cartao_id=card.id)
        assert resp.status_code == 201  # NÃO-bloqueante: 201 mesmo com aviso
        body = resp.json()
        assert body["avisos"] == [
            {
                "codigo": "fatura_paga",
                "competencias": [
                    {"cartao_id": card.id, "fatura_mes": 3, "fatura_ano": 2026}
                ],
            }
        ]

        # O lançamento persistiu normalmente, com a competência intacta
        criada = session.get(Transacao, body["id"])
        assert criada is not None
        assert (criada.fatura_mes, criada.fatura_ano) == (3, 2026)

        # Nada materializado: o único registro de pagamento é o seed, inalterado
        pagamentos = session.exec(select(PagamentoFatura)).all()
        assert len(pagamentos) == 1
        assert pagamentos[0].pago is True

    def test_registro_pago_false_nao_gera_aviso(self, session, users, as_user):
        # Mutação: pago=False = "não paguei" — equivale à ausência p/ o aviso
        user_a, _ = users
        card = make_card(session, user_a.id)
        marca_pagamento(session, user_a.id, card.id, 3, 2026, pago=False)

        body = post_transacao(as_user(user_a), cartao_id=card.id).json()
        assert body["avisos"] == []

    def test_fatura_paga_de_outra_competencia_nao_gera_aviso(self, session, users, as_user):
        # Mutação: paga em (4, 2026); a compra cai em (3, 2026) → sem aviso
        user_a, _ = users
        card = make_card(session, user_a.id)
        marca_pagamento(session, user_a.id, card.id, 4, 2026)

        body = post_transacao(as_user(user_a), cartao_id=card.id).json()
        assert body["avisos"] == []

    def test_pagamento_de_outro_usuario_nao_vaza(self, session, users, as_user):
        # Isolamento: user_b tem a MESMA competência paga no cartão dele;
        # a compra de user_a não pode disparar aviso por causa disso.
        user_a, user_b = users
        card_a = make_card(session, user_a.id)
        card_b = make_card(session, user_b.id)
        marca_pagamento(session, user_b.id, card_b.id, 3, 2026)

        body = post_transacao(as_user(user_a), cartao_id=card_a.id).json()
        assert body["avisos"] == []


class TestAvisoParcelada:
    def test_uma_parcela_em_fatura_paga_dispara_aviso(self, session, users, as_user):
        # 3x → competências (3..5, 2026); só (4, 2026) está paga → aviso com
        # exatamente essa competência (QUALQUER parcela atingida dispara).
        user_a, _ = users
        card = make_card(session, user_a.id)
        marca_pagamento(session, user_a.id, card.id, 4, 2026)

        resp = post_parcelada(as_user(user_a), cartao_id=card.id)
        assert resp.status_code == 201
        body = resp.json()
        assert body["parcelas_criadas"] == 3
        assert body["avisos"] == [
            {
                "codigo": "fatura_paga",
                "competencias": [
                    {"cartao_id": card.id, "fatura_mes": 4, "fatura_ano": 2026}
                ],
            }
        ]

    def test_multiplas_faturas_pagas_listadas_em_ordem_cronologica(
        self, session, users, as_user
    ):
        user_a, _ = users
        card = make_card(session, user_a.id)
        # Seed fora de ordem — a resposta deve sair (3, 2026) antes de (5, 2026)
        marca_pagamento(session, user_a.id, card.id, 5, 2026)
        marca_pagamento(session, user_a.id, card.id, 3, 2026)

        body = post_parcelada(as_user(user_a), cartao_id=card.id).json()
        assert len(body["avisos"]) == 1
        assert body["avisos"][0]["competencias"] == [
            {"cartao_id": card.id, "fatura_mes": 3, "fatura_ano": 2026},
            {"cartao_id": card.id, "fatura_mes": 5, "fatura_ano": 2026},
        ]

    def test_nenhuma_parcela_em_fatura_paga_avisos_vazio(self, session, users, as_user):
        user_a, _ = users
        card = make_card(session, user_a.id)

        body = post_parcelada(as_user(user_a), cartao_id=card.id).json()
        assert body["avisos"] == []


class TestSemCompetencia:
    def test_compra_normal_sem_fatura_paga_avisos_vazio(self, session, users, as_user):
        user_a, _ = users
        card = make_card(session, user_a.id)

        body = post_transacao(as_user(user_a), cartao_id=card.id).json()
        assert body["avisos"] == []

    def test_compra_sem_cartao_avisos_vazio(self, session, users, as_user):
        # Mutação forte: EXISTE fatura paga do usuário, mas a compra não tem
        # cartão → não toca competência alguma → sem aviso.
        user_a, _ = users
        card = make_card(session, user_a.id)
        marca_pagamento(session, user_a.id, card.id, 3, 2026)

        body = post_transacao(as_user(user_a), forma_pagamento="PIX").json()
        assert body["avisos"] == []

    def test_cartao_sem_dia_vencimento_avisos_vazio(self, session, users, as_user):
        # À vista em cartão sem dia_vencimento: fatura_mes/ano ficam None
        # (a criação não deriva competência) → sem aviso possível.
        user_a, _ = users
        card = make_card(session, user_a.id, dia_vencimento=None)
        marca_pagamento(session, user_a.id, card.id, 3, 2026)

        body = post_transacao(as_user(user_a), cartao_id=card.id).json()
        assert body["fatura_mes"] is None
        assert body["avisos"] == []
