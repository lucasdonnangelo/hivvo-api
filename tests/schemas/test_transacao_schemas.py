"""T-35 (parte de schema) + T-33 (borda da API) — pydantic puro, sem banco.

TransacaoUpdate: valor > 0, tipo válido, fatura_mes/fatura_ano removidos
(derivados — cliente não define). TransacaoCreate: rejeição de valor
insuficiente para o número de parcelas (nenhuma parcela pode ficar <= 0).
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.transaction import TransacaoCreate, TransacaoUpdate


class TestTransacaoUpdateValor:
    @pytest.mark.parametrize("valor", ["0", "-10.00", "0.00"])
    def test_valor_nao_positivo_rejeitado(self, valor):
        with pytest.raises(ValidationError, match="valor deve ser positivo"):
            TransacaoUpdate(valor=Decimal(valor))

    def test_valor_positivo_aceito(self):
        assert TransacaoUpdate(valor=Decimal("150.00")).valor == Decimal("150.00")

    def test_virgula_decimal_continua_normalizada(self):
        assert TransacaoUpdate(valor="150,00").valor == Decimal("150.00")

    def test_virgula_decimal_nao_positiva_rejeitada(self):
        with pytest.raises(ValidationError, match="valor deve ser positivo"):
            TransacaoUpdate(valor="-150,00")


class TestTransacaoUpdateTipo:
    def test_tipo_invalido_rejeitado(self):
        with pytest.raises(ValidationError, match="tipo deve ser"):
            TransacaoUpdate(tipo="transferencia")

    @pytest.mark.parametrize("tipo", ["receita", "despesa"])
    def test_tipos_validos_aceitos(self, tipo):
        assert TransacaoUpdate(tipo=tipo).tipo == tipo


class TestTransacaoUpdateFaturaDerivada:
    def test_fatura_mes_e_ano_nao_sao_mais_campos(self):
        assert "fatura_mes" not in TransacaoUpdate.model_fields
        assert "fatura_ano" not in TransacaoUpdate.model_fields

    def test_fatura_enviada_pelo_cliente_e_ignorada(self):
        # Pydantic ignora campos desconhecidos: não entram no payload do update.
        update = TransacaoUpdate(fatura_mes=7, fatura_ano=2030)
        assert update.model_dump(exclude_unset=True) == {}

    def test_update_parcial_vazio_continua_valido(self):
        assert TransacaoUpdate().model_dump(exclude_unset=True) == {}


def make_create(valor: str, total_parcelas: int) -> TransacaoCreate:
    return TransacaoCreate(
        tipo="despesa",
        data="2026-01-15",
        descricao="Compra Teste",
        valor=Decimal(valor),
        categoria="Compras",
        parcelado=True,
        total_parcelas=total_parcelas,
    )


class TestT33TransacaoCreateValorMinimoPorParcela:
    def test_valor_abaixo_de_um_centavo_por_parcela_rejeitado(self):
        # R$ 0,10 em 12× geraria última parcela −0,01 — rejeitar na borda (422).
        with pytest.raises(ValidationError, match="valor muito baixo para o número de parcelas"):
            make_create("0.10", 12)

    def test_limite_exato_um_centavo_por_parcela_aceito(self):
        transacao = make_create("0.12", 12)
        assert transacao.valor == Decimal("0.12")
        assert transacao.total_parcelas == 12

    def test_valor_normal_continua_aceito(self):
        assert make_create("1200.00", 12).valor == Decimal("1200.00")
