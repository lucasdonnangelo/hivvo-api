"""T-40 — validators do CartaoUpdate (pydantic puro, sem banco).

CartaoUpdate replica os validators do CartaoCreate (tipo; dias 1..31) e
adiciona mes_offset_vencimento >= 0. Todos None-safe: update parcial não
exige nenhum campo.
"""

import pytest
from pydantic import ValidationError

from app.schemas.card import CartaoCreate, CartaoUpdate


class TestTipo:
    def test_tipo_invalido_rejeitado(self):
        with pytest.raises(ValidationError, match="tipo deve ser"):
            CartaoUpdate(tipo="Alimentação")

    @pytest.mark.parametrize("tipo", ["Crédito", "Débito", "Ambos"])
    def test_tipos_validos_aceitos(self, tipo):
        assert CartaoUpdate(tipo=tipo).tipo == tipo


class TestDias:
    @pytest.mark.parametrize("campo", ["dia_vencimento", "dia_fechamento"])
    @pytest.mark.parametrize("dia", [0, 32, -1])
    def test_dia_fora_de_1_a_31_rejeitado(self, campo, dia):
        with pytest.raises(ValidationError, match="dia deve estar entre 1 e 31"):
            CartaoUpdate(**{campo: dia})

    @pytest.mark.parametrize("campo", ["dia_vencimento", "dia_fechamento"])
    @pytest.mark.parametrize("dia", [1, 31])
    def test_limites_validos_aceitos(self, campo, dia):
        assert getattr(CartaoUpdate(**{campo: dia}), campo) == dia


class TestMesOffset:
    def test_offset_negativo_rejeitado(self):
        with pytest.raises(ValidationError, match="mes_offset_vencimento deve ser >= 0"):
            CartaoUpdate(mes_offset_vencimento=-1)

    @pytest.mark.parametrize("offset", [0, 1, 2])
    def test_offsets_validos_aceitos(self, offset):
        assert CartaoUpdate(mes_offset_vencimento=offset).mes_offset_vencimento == offset

    def test_offset_negativo_rejeitado_tambem_na_criacao(self):
        # Sem isto, nasceria cartão com offset negativo que o update rejeita —
        # e que quebra a matemática de fatura que os testes de services assumem.
        with pytest.raises(ValidationError, match="mes_offset_vencimento deve ser >= 0"):
            CartaoCreate(nome="Nubank", tipo="Crédito", mes_offset_vencimento=-1)


def test_update_parcial_vazio_continua_valido():
    update = CartaoUpdate()
    assert update.model_dump(exclude_unset=True) == {}
