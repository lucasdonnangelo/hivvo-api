"""Fase 2 — POST /ai/suggest-category (raiz do FE-08) + guarda do /ai/chat.

A sugestão de categoria é one-shot e stateless: nada em chat_messages, nenhum
sessao_id, nenhuma janela de 50 mensagens. O chat real segue persistindo.
Gemini sempre mockado (patch em app.routers.ai._gemini_generate — sem rede).
"""

import uuid

from sqlmodel import select

from app.models.category import CategoriaCustomizada
from app.models.chat import ChatMessage


def suggest(client, **overrides):
    payload = {"descricao": "iFood almoço", "valor": "45.90", "tipo": "despesa"}
    payload.update(overrides)
    return client.post("/ai/suggest-category", json=payload)


class TestSuggestCategoryStateless:
    def test_nao_persiste_nada_e_retorna_sugestao(self, session, users, as_user, mocker):
        mocker.patch("app.routers.ai._gemini_generate", return_value="Alimentação")
        client = as_user(users[0])
        assert session.exec(select(ChatMessage)).all() == []

        response = suggest(client)
        assert response.status_code == 200
        assert response.json() == {"categoria": "Alimentação"}

        # Prova do FE-08 no servidor: zero linhas em chat_messages — logo,
        # nenhum sessao_id foi criado e nada entra na janela de 50 mensagens
        assert session.exec(select(ChatMessage)).all() == []

    def test_categoria_customizada_do_usuario_e_aceita(self, session, users, as_user, mocker):
        user_a, _ = users
        session.add(CategoriaCustomizada(usuario_id=user_a.id, nome="Mercado", tipo="despesa"))
        session.commit()
        mocker.patch("app.routers.ai._gemini_generate", return_value="Mercado")

        response = suggest(as_user(user_a), descricao="Compras do mês no Carrefour")
        assert response.json() == {"categoria": "Mercado"}

    def test_resposta_fora_da_lista_cai_em_outros(self, session, users, as_user, mocker):
        mocker.patch("app.routers.ai._gemini_generate", return_value="Categoria Inventada")

        response = suggest(as_user(users[0]))
        assert response.json() == {"categoria": "Outros"}

    def test_resposta_com_decoracao_e_normalizada(self, session, users, as_user, mocker):
        mocker.patch("app.routers.ai._gemini_generate", return_value='"alimentação".')

        response = suggest(as_user(users[0]))
        assert response.json() == {"categoria": "Alimentação"}


class TestChatSeguePersistindo:
    def test_chat_persiste_user_e_assistant_com_sessao(self, session, users, as_user, mocker):
        """Guarda do refactor _gemini_generate: o chat real DEVE persistir."""
        mocker.patch("app.routers.ai._gemini_generate", return_value="Sua análise.")
        client = as_user(users[0])
        sessao = str(uuid.uuid4())

        response = client.post(
            "/ai/chat",
            json={"mensagem": "Como estão meus gastos?", "mes": 6, "ano": 2026,
                  "sessao_id": sessao},
        )
        assert response.status_code == 200
        assert response.json()["resposta"] == "Sua análise."

        mensagens = session.exec(select(ChatMessage)).all()
        assert [m.role for m in mensagens] == ["user", "assistant"]
        assert [m.text for m in mensagens] == ["Como estão meus gastos?", "Sua análise."]
        assert all(str(m.sessao_id) == sessao for m in mensagens)


class TestChatSessaoIdValidacao:
    """F-16: sessao_id é uuid.UUID no schema — malformado vira 422, não 500."""

    def _chat(self, client, sessao_id):
        return client.post(
            "/ai/chat",
            json={"mensagem": "oi", "mes": 6, "ano": 2026, "sessao_id": sessao_id},
        )

    def test_sessao_id_invalido_retorna_422(self, session, users, as_user, mocker):
        # Não deve nem chegar ao Gemini — falha na validação de entrada
        spy = mocker.patch("app.routers.ai._gemini_generate", return_value="x")
        response = self._chat(as_user(users[0]), "nao-e-um-uuid-valido-com-36-chars-aa")
        assert response.status_code == 422
        spy.assert_not_called()

    def test_sessao_id_uuid_valido_ok(self, session, users, as_user, mocker):
        mocker.patch("app.routers.ai._gemini_generate", return_value="Análise.")
        response = self._chat(as_user(users[0]), str(uuid.uuid4()))
        assert response.status_code == 200
        assert response.json()["resposta"] == "Análise."
