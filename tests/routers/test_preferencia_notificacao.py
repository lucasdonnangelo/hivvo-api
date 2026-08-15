"""A preferência de aviso pelo caminho da API (#6, Batch 2).

O filtro em si já é provado em `test_notificacoes_consulta.py`. O que estes
testes cobrem é a JUNTA: o toggle da tela chega até o job. Uma preferência que
persiste mas não é lida, ou lida mas não persiste, passa nos dois testes
separados e falha no produto.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models.card import Cartao
from app.models.transaction import Transacao
from app.models.user import Usuario
from app.services.notificacoes.envio import executar

HOJE = dt.date(2026, 8, 14)
ALVO = dt.date(2026, 8, 17)


@pytest.fixture()
def enviado(mocker):
    return mocker.patch(
        "app.services.notificacoes.envio.resend.Emails.send", return_value={"id": "fake"}
    )


def _fatura(session, usuario) -> Cartao:
    cartao = Cartao(
        usuario_id=usuario.id,
        nome="Nubank",
        tipo="Crédito",
        dia_vencimento=ALVO.day,
        dia_fechamento=5,
        mes_offset_vencimento=0,
    )
    session.add(cartao)
    session.commit()
    session.refresh(cartao)
    session.add(
        Transacao(
            usuario_id=usuario.id,
            tipo="despesa",
            data=dt.date(2026, 7, 20),
            descricao="Compra",
            valor=Decimal("100.00"),
            categoria="Outros",
            forma_pagamento="Crédito",
            cartao_id=cartao.id,
            fatura_mes=ALVO.month,
            fatura_ano=ALVO.year,
        )
    )
    session.commit()
    return cartao


class TestPutDaPreferencia:
    def test_desligar_persiste_e_volta_no_corpo(self, as_user, users, session):
        client = as_user(users[0])

        resp = client.put("/auth/me", json={"notificar_vencimento": False})

        assert resp.status_code == 200
        assert resp.json()["notificar_vencimento"] is False
        session.refresh(users[0])
        assert users[0].notificar_vencimento is False

    def test_religar_volta_ao_padrao(self, as_user, users, session):
        client = as_user(users[0])
        client.put("/auth/me", json={"notificar_vencimento": False})

        resp = client.put("/auth/me", json={"notificar_vencimento": True})

        assert resp.json()["notificar_vencimento"] is True
        session.refresh(users[0])
        assert users[0].notificar_vencimento is True

    def test_false_sozinho_nao_e_confundido_com_payload_vazio(self, as_user, users):
        """O payload que a tela MAIS manda não pode cair no "ao menos um campo".

        `{"notificar_vencimento": false}` tem o campo informado — e um validador
        que só enxerga nome/username o trataria como PUT no-op e devolveria 422
        dizendo "informe ao menos um campo". O bug não aparece em teste de
        schema que exercita só os campos antigos; aparece no primeiro clique.
        """
        resp = as_user(users[0]).put("/auth/me", json={"notificar_vencimento": False})

        assert resp.status_code == 200

    def test_payload_realmente_vazio_continua_422(self, as_user, users):
        """A guarda original não pode ter sido afrouxada junto."""
        assert as_user(users[0]).put("/auth/me", json={}).status_code == 422

    def test_get_me_expoe_o_estado_para_a_tela(self, as_user, users):
        """Sem isto a UI só poderia ASSUMIR o default — e um toggle que mostra
        o valor errado é pior que nenhum toggle."""
        resp = as_user(users[0]).get("/auth/me")

        assert resp.status_code == 200
        assert resp.json()["notificar_vencimento"] is True  # nasce ligado

    def test_um_usuario_nao_desliga_o_aviso_do_outro(self, as_user, users, session):
        """Identidade sai do current_user, nunca do corpo.

        O ataque: mandar o `id` do outro no payload. O campo é ignorado pelo
        schema, e quem é atualizado continua sendo quem está autenticado.
        """
        ana, bruno = users

        resp = as_user(ana).put(
            "/auth/me", json={"notificar_vencimento": False, "id": bruno.id}
        )

        assert resp.status_code == 200
        session.refresh(ana)
        session.refresh(bruno)
        assert ana.notificar_vencimento is False
        assert bruno.notificar_vencimento is True  # intocado

    def test_sem_sessao_nao_altera(self, session):
        """Guarda de autenticação: sem usuário logado, ninguém desliga nada."""
        from fastapi.testclient import TestClient

        from app.core.database import get_session
        from main import app

        app.dependency_overrides[get_session] = lambda: session
        try:
            anonimo = TestClient(app, base_url="http://testserver/api/v1")
            resp = anonimo.put("/auth/me", json={"notificar_vencimento": False})
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 401


class TestOTogglePeloCaminhoCompleto:
    def test_desligar_pela_api_impede_o_envio(self, as_user, users, session, enviado):
        """A JUNTA: o clique na tela chega ao job.

        Antes do PUT o usuário recebe; depois, não. É o que prova que a coluna
        que o toggle grava é a MESMA que a consulta lê.
        """
        ana = users[0]
        _fatura(session, ana)

        # Antes: recebe.
        resultado, _ = executar(session, HOJE, apenas_usuario_id=ana.id)
        assert resultado.enviados == 1
        assert enviado.call_count == 1

        as_user(ana).put("/auth/me", json={"notificar_vencimento": False})

        # Depois: some da leva — e no dia seguinte, quando o guard não barra mais.
        resultado, avisos = executar(
            session, HOJE + dt.timedelta(days=1), apenas_usuario_id=ana.id
        )
        assert avisos == []
        assert resultado.enviados == 0
        assert enviado.call_count == 1  # nenhum e-mail novo

    def test_religar_volta_a_receber(self, as_user, users, session, enviado):
        ana = users[0]
        _fatura(session, ana)
        as_user(ana).put("/auth/me", json={"notificar_vencimento": False})
        assert executar(session, HOJE, apenas_usuario_id=ana.id)[1] == []

        as_user(ana).put("/auth/me", json={"notificar_vencimento": True})

        resultado, _ = executar(session, HOJE, apenas_usuario_id=ana.id)
        assert resultado.enviados == 1
