"""F-16 + F-22 nos schemas de IA — pydantic puro, sem banco.

- F-16: ChatRequest.sessao_id é uuid.UUID (malformado rejeitado).
- F-22: SuggestCategoryRequest.descricao tem teto generoso (500) de ENTRADA.
- T-37 (não-regressão): HistoricoResponseItem é schema de RELEITURA — `text`
  NÃO pode ganhar max_length (não rejeitar dado já persistido no banco).
"""

import datetime as dt
import uuid

import pytest
from pydantic import ValidationError

from app.schemas.ai import ChatRequest, HistoricoResponseItem, SuggestCategoryRequest


class TestChatRequestSessaoId:
    def _make(self, sessao_id):
        return ChatRequest(mensagem="oi", mes=6, ano=2026, sessao_id=sessao_id)

    def test_uuid_valido_aceito(self):
        u = uuid.uuid4()
        assert self._make(str(u)).sessao_id == u

    def test_string_nao_uuid_rejeitada(self):
        with pytest.raises(ValidationError):
            self._make("nao-e-uuid")


class TestSuggestCategoryDescricaoMaxLength:
    def test_no_limite_passa(self):
        assert SuggestCategoryRequest(descricao="d" * 500).descricao == "d" * 500

    def test_acima_do_limite_rejeitada(self):
        with pytest.raises(ValidationError):
            SuggestCategoryRequest(descricao="d" * 501)


class TestHistoricoResponseItemSemMaxLength:
    """Schema de releitura: texto longo do banco passa intacto (lição T-37)."""

    def test_texto_muito_longo_passa(self):
        texto = "x" * 10_000  # bem acima de qualquer limite de entrada
        item = HistoricoResponseItem(role="assistant", text=texto, created_at=dt.datetime.utcnow())
        assert item.text == texto

    def test_text_nao_tem_max_length_no_schema(self):
        # Garante que ninguém adicionou um constraint de tamanho ao campo de releitura
        meta = HistoricoResponseItem.model_fields["text"].metadata
        assert all(getattr(m, "max_length", None) is None for m in meta)
