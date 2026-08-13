"""Canal de feedback — formulário do app → e-mail (POST /api/v1/feedback).

O Resend é sempre mockado: nenhum e-mail real sai daqui.

O teste que carrega o peso é o da FALHA: sem tabela, um handler que engula o
erro do Resend perde a única cópia da mensagem em silêncio. Ele foi verificado
por MUTAÇÃO — trocar o `raise HTTPException(502)` por log-e-segue (o padrão do
forgot_password, que ali é correto) derruba `test_falha_do_resend_nao_e_engolida`
e mais nada. A saída da mutação está no relatório da sessão.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_session
from app.core.rate_limit import limiter
from main import app

MENSAGEM = "O gráfico de agosto não carrega, fica girando pra sempre."


def _payload(mensagem: str = MENSAGEM, **ctx):
    contexto = {
        "rota_anterior": "/dashboard",
        "versao": "0.1.0 (abc1234)",
        "viewport": "390x844 @3x",
        "layout": "mobile",
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
    }
    contexto.update(ctx)
    return {"mensagem": mensagem, "contexto": contexto}


@pytest.fixture()
def enviado(mocker):
    """Captura o payload entregue ao Resend."""
    return mocker.patch("app.routers.feedback.resend.Emails.send", return_value={"id": "fake"})


class TestEnvio:
    def test_envio_bem_sucedido_devolve_200(self, as_user, users, enviado):
        user_a, _ = users
        resp = as_user(user_a).post("/feedback", json=_payload())

        assert resp.status_code == 200, resp.text
        assert enviado.call_count == 1

    def test_email_sai_do_remetente_configurado_para_a_caixa_de_feedback(
        self, as_user, users, enviado
    ):
        from app.core.config import settings

        user_a, _ = users
        as_user(user_a).post("/feedback", json=_payload())

        payload = enviado.call_args[0][0]
        assert payload["from"] == settings.EMAIL_FROM
        assert payload["to"] == [settings.FEEDBACK_TO]

    def test_reply_to_carrega_o_email_do_usuario(self, as_user, users, enviado):
        """É o que torna o canal uma conversa: responder no cliente de e-mail
        cai direto no usuário, sem ninguém copiar endereço à mão."""
        user_a, _ = users
        as_user(user_a).post("/feedback", json=_payload())

        payload = enviado.call_args[0][0]
        assert payload["reply_to"] == [user_a.email]

    def test_corpo_carrega_a_mensagem_e_o_contexto_capturado(self, as_user, users, enviado):
        user_a, _ = users
        as_user(user_a).post("/feedback", json=_payload())

        corpo = enviado.call_args[0][0]["html"]
        assert MENSAGEM in corpo
        assert f"#{user_a.id}" in corpo
        assert user_a.email in corpo
        assert "0.1.0 (abc1234)" in corpo
        assert "390x844 @3x" in corpo
        assert "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)" in corpo
        # A rota anterior é PISTA, e o e-mail precisa dizer isso — sem o rótulo,
        # "/dashboard" é lido como "o erro foi no dashboard", que não se sabe.
        assert "/dashboard (pista, não confirmação)" in corpo

    def test_sem_rota_anterior_o_email_diz_que_nao_houve(self, as_user, users, enviado):
        """Reload direto em /settings não tem rota anterior. O e-mail precisa
        dizer isso — um campo em branco seria lido como bug do formulário."""
        user_a, _ = users
        as_user(user_a).post("/feedback", json=_payload(rota_anterior=None))

        assert "não registrada" in enviado.call_args[0][0]["html"]

    def test_texto_do_usuario_e_escapado_no_html(self, as_user, users, enviado):
        """Texto livre entra num corpo HTML: um '<' solto quebraria o e-mail
        que você precisa ler."""
        user_a, _ = users
        as_user(user_a).post("/feedback", json=_payload("quebra em <b>negrito</b> & cia"))

        corpo = enviado.call_args[0][0]["html"]
        assert "&lt;b&gt;negrito&lt;/b&gt;" in corpo
        assert "<b>negrito</b>" not in corpo


class TestFalhaDeEnvio:
    def test_falha_do_resend_nao_e_engolida(self, as_user, users, mocker):
        """Sem tabela, 200 aqui perderia a mensagem em silêncio.

        ⚠️ Este é o teste da MUTAÇÃO: trocar o raise do handler por log-e-segue
        (200) faz ele cair. Se um dia alguém "simplificar" o except para ficar
        igual ao do forgot_password, é aqui que aparece.
        """
        mocker.patch(
            "app.routers.feedback.resend.Emails.send",
            side_effect=Exception("Resend fora do ar"),
        )
        user_a, _ = users
        resp = as_user(user_a).post("/feedback", json=_payload())

        assert resp.status_code == 502, resp.text
        assert "Não foi possível enviar" in resp.json()["detail"]

    def test_erro_do_resend_nao_vaza_no_corpo_da_resposta(self, as_user, users, mocker):
        """O texto do provedor pode ecoar endereço — fica no log, não na tela."""
        mocker.patch(
            "app.routers.feedback.resend.Emails.send",
            side_effect=Exception("You can only send testing emails to alice@hivvo.test"),
        )
        user_a, _ = users
        resp = as_user(user_a).post("/feedback", json=_payload())

        assert "alice@hivvo.test" not in resp.text


class TestMensagemVazia:
    @pytest.mark.parametrize("vazia", ["", "   ", "\n\n  \t"])
    def test_corpo_vazio_ou_so_espaco_e_rejeitado_com_mensagem_propria(
        self, as_user, users, enviado, vazia
    ):
        """400 com string limpa, não o 422 de lista do Pydantic.

        A asserção é no TEXTO, não só no status: um 422 genérico passaria por um
        teste que só olhasse "não é 200", e o usuário leria "Value error, ...".
        """
        user_a, _ = users
        resp = as_user(user_a).post("/feedback", json=_payload(vazia))

        assert resp.status_code == 400, resp.text
        assert resp.json()["detail"] == "Escreva sua mensagem antes de enviar."
        assert enviado.call_count == 0


class TestIdentidadeNaoVemDoCliente:
    def test_usuario_id_forjado_no_corpo_e_ignorado(self, as_user, users, enviado):
        """Identidade sai do current_user. Um id vindo do browser é forjável e,
        pior, seria só errado."""
        user_a, user_b = users
        forjado = _payload()
        forjado["usuario_id"] = user_b.id
        forjado["email"] = user_b.email

        resp = as_user(user_a).post("/feedback", json=forjado)

        assert resp.status_code == 200, resp.text
        payload = enviado.call_args[0][0]
        assert payload["reply_to"] == [user_a.email]
        assert f"#{user_a.id}" in payload["html"]
        assert user_b.email not in payload["html"]


class TestLimiteDeEnvio:
    def test_sexto_envio_na_hora_e_barrado(self, session, mocker):
        """5/hora por usuário.

        Sem override de get_current_user, de propósito: o `_user_or_ip_key` lê o
        `sub` do JWT no cookie, então só com login REAL a chave é por usuário —
        sob o override não haveria cookie e a chave degradaria para o IP,
        medindo outra coisa.

        A suíte roda com RATE_LIMIT_ENABLED=false (tests/conftest.py); aqui o
        limiter é religado localmente e desligado no finally, como em
        test_rate_limit.py.
        """
        mocker.patch("app.routers.feedback.resend.Emails.send", return_value={"id": "fake"})
        app.dependency_overrides[get_session] = lambda: session
        limiter.enabled = True
        limiter.reset()
        try:
            client = TestClient(app, base_url="http://testserver/api/v1")
            resp = client.post(
                "/auth/register",
                json={
                    "email": "alice@hivvo.test",
                    "nome_completo": "Alice",
                    "password": "senha-forte-1",
                },
            )
            assert resp.status_code == 201, resp.text

            for i in range(5):
                assert client.post("/feedback", json=_payload()).status_code == 200, i
            assert client.post("/feedback", json=_payload()).status_code == 429
        finally:
            limiter.enabled = False
            limiter.reset()
            app.dependency_overrides.clear()
