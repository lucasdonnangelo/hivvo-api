"""Contrato do spike de EXTRATO: texto do extrato de conta -> JSON estruturado.

Espelha o schema.py do spike_import (fatura): datas `str` ISO (YYYY-MM-DD) e
valores `str` decimais — primitivos evitam surpresa na conversão Pydantic ->
Schema da API Gemini; validadores garantem que o conteúdo parseia de verdade.

Decisão de sinal: a DIREÇÃO do dinheiro vem do `balde`, não do sinal do valor.
`valor` é sempre MAGNITUDE positiva — casa com o CHECK `valor > 0` da Transacao
em produção (direção via `tipo`). Só os SALDOS carregam sinal (cheque especial
existe). Os três baldes:
- receita          -> entrada de caixa
- debito           -> saída de caixa que É consumo (mapeia a tipo="despesa")
- pagamento_fatura -> saída de caixa que NÃO é consumo (vira PagamentoFatura)

A reconciliação (balance walk) NÃO faz parte deste contrato de propósito: LLM
não faz aritmética confiável — o walk é calculado em Python (ver reconcile.py).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import BaseModel, field_validator, model_validator


def normalizar_decimal(bruto: str) -> str:
    """'3.412,88', '3412.88', '-58,95', 'R$ 1.234,56' -> '3412.88' (PRESERVA sinal).

    Num spike de validação, ver a extração vale mais do que punir formato:
    normaliza em vez de rejeitar duro. Só rejeita o que não parseia.
    """
    s = bruto.strip().replace("R$", "").replace(" ", "").replace("\xa0", "")
    if "," in s:
        # vírgula presente => separador decimal pt-BR; pontos são milhar
        s = s.replace(".", "").replace(",", ".")
    try:
        return str(Decimal(s))
    except InvalidOperation:
        raise ValueError(f"valor decimal não parseável: {bruto!r}")


def normalizar_magnitude(bruto: str) -> str:
    """Como normalizar_decimal, mas devolve a MAGNITUDE (sem sinal).

    A direção vem do balde; se o modelo mandar o sinal impresso do extrato
    (débito negativo), abate-se aqui em vez de rejeitar.
    """
    return str(abs(Decimal(normalizar_decimal(bruto))))


def _validar_data_iso(v: str) -> str:
    date.fromisoformat(v)  # levanta ValueError se não for YYYY-MM-DD válido
    return v


class Balde(StrEnum):
    receita = "receita"                    # entrada de caixa
    debito = "debito"                      # saída de caixa que É consumo
    pagamento_fatura = "pagamento_fatura"  # saída de caixa que NÃO é consumo


class Periodo(BaseModel):
    de: str
    ate: str

    _datas = field_validator("de", "ate")(_validar_data_iso)


class LinhaExtrato(BaseModel):
    data: str
    descricao: str
    valor: str  # MAGNITUDE positiva; a direção vem do balde
    balde: Balde
    # só pagamento_fatura: banco/cartão citado na linha; null se a linha não nomeia
    cartao_citado: str | None = None

    _data = field_validator("data")(_validar_data_iso)
    _valor = field_validator("valor")(
        classmethod(lambda cls, v: normalizar_magnitude(v))
    )

    @model_validator(mode="after")
    def _cartao_so_em_pagamento(self) -> "LinhaExtrato":
        # cartao_citado só faz sentido em pagamento_fatura: zera fora dele
        # (dado limpo) e normaliza string vazia -> None.
        if self.balde is not Balde.pagamento_fatura:
            self.cartao_citado = None
        elif self.cartao_citado is not None:
            self.cartao_citado = self.cartao_citado.strip() or None
        return self


class ExtratoExtraido(BaseModel):
    banco: str  # banco da CONTA (ex.: "Nubank")
    periodo: Periodo | None = None
    # saldos IMPRESSOS no extrato, COM sinal (negativo = conta negativa);
    # null quando o extrato não os imprime -> balance walk vira N/A
    saldo_inicial: str | None = None
    saldo_final: str | None = None
    linhas: list[LinhaExtrato]

    _saldos = field_validator("saldo_inicial", "saldo_final")(
        classmethod(lambda cls, v: None if v is None else normalizar_decimal(v))
    )
