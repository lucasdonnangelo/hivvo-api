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

    def test_criacao_debito_com_null_cai_no_default(self):
        # Regressão: débito manda null nos 4 campos de fatura. mes_offset era int
        # não-anulável → null dava 422 e travava a criação de cartão de débito.
        # Agora null cai no default 1 (inócuo, débito não usa offset).
        card = CartaoCreate(
            nome="Nu Débito",
            tipo="Débito",
            limite=None,
            dia_fechamento=None,
            dia_vencimento=None,
            mes_offset_vencimento=None,
        )
        assert card.mes_offset_vencimento == 1


def test_update_parcial_vazio_continua_valido():
    update = CartaoUpdate()
    assert update.model_dump(exclude_unset=True) == {}


class TestFechamentoVencimentoNoCreate:
    """offset 0 ("mesmo mês") exige vencimento DEPOIS do fechamento — a fatura
    não pode vencer antes de fechar. offset >= 1: qualquer par é válido.
    O update NÃO valida no schema (é parcial) — a mescla vive no router."""

    @pytest.mark.parametrize("venc", [5, 10])  # antes E no mesmo dia do fechamento
    def test_mesmo_mes_vencimento_nao_posterior_rejeitado(self, venc):
        with pytest.raises(ValidationError, match="mesmo mês do fechamento"):
            CartaoCreate(
                nome="Nubank", tipo="Crédito",
                dia_fechamento=10, dia_vencimento=venc, mes_offset_vencimento=0,
            )

    def test_mesmo_mes_vencimento_posterior_aceito(self):
        card = CartaoCreate(
            nome="Nubank", tipo="Crédito",
            dia_fechamento=10, dia_vencimento=15, mes_offset_vencimento=0,
        )
        assert card.dia_vencimento == 15

    @pytest.mark.parametrize("fech, venc", [(25, 5), (10, 10), (5, 25)])
    def test_mes_seguinte_qualquer_par_aceito(self, fech, venc):
        # offset 1: o mês virou entre fechar e vencer — venc < fech é o caso comum.
        card = CartaoCreate(
            nome="Nubank", tipo="Crédito",
            dia_fechamento=fech, dia_vencimento=venc, mes_offset_vencimento=1,
        )
        assert card.mes_offset_vencimento == 1

    def test_offset_zero_sem_dias_nao_aciona_a_regra(self):
        # Dias ausentes (crédito sem datas ainda é aceito; débito nem as tem):
        # não há o que comparar — a regra não dispara.
        card = CartaoCreate(nome="Nubank", tipo="Crédito", mes_offset_vencimento=0)
        assert card.dia_fechamento is None
