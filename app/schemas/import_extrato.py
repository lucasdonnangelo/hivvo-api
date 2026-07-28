"""Contrato da importação de EXTRATO de conta: texto -> JSON estruturado (+ response da rota).

ExtratoExtraido é porte do spike validado (scripts/spike_extrato/schema.py) com
UM acréscimo de produção — o campo `rendimento` (o "Rendimento líquido" do RESUMO
do extrato, que NÃO é linha de movimentação). É usado duas vezes, igual à fatura:
1. Como response_schema do Gemini (força a resposta no shape certo).
2. Como validação local da resposta (cinto e suspensório).
NÃO altere campos ou validadores sem revalidar contra extratos reais.

Datas são `str` ISO (YYYY-MM-DD) e valores são `str` decimais — tipos primitivos
evitam surpresa na conversão Pydantic -> Schema da API Gemini; os validadores
garantem que o conteúdo parseia de verdade.

Decisão de sinal (do spike): a DIREÇÃO do dinheiro vem do `balde`, não do sinal do
valor. `valor` de linha é sempre MAGNITUDE positiva (casa com o CHECK `valor > 0`
da Transacao em produção — direção via `tipo`). Só os SALDOS e o rendimento
carregam sinal (cheque especial existe; rendimento é normalmente positivo).

O balance walk NÃO faz parte deste contrato de propósito: LLM não faz aritmética
confiável — o walk é calculado em Python (ver
app/services/import_extrato/reconciliacao.py) e devolvido em ReconciliacaoExtratoOut,
com decimais como string.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import BaseModel, field_validator, model_validator


def normalizar_decimal(bruto: str) -> str:
    """Aceita '3.412,88', '3412.88', '-58,95', 'R$ 1.234,56' -> '3412.88' (PRESERVA sinal).

    Ver a extração vale mais do que punir formato: normaliza em vez de rejeitar
    duro. Só rejeita o que não parseia.
    Ambiguidade assumida: '3.412' sem vírgula é lido como 3.412 (o prompt pede
    ponto decimal, então ponto sozinho é tratado como decimal).
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
    # ACHADO 1 (produção): o "Rendimento líquido" do RESUMO do extrato — NÃO é
    # linha de movimentação. Entra no balance walk como crédito. Default "0.00"
    # quando o extrato não o imprime.
    rendimento: str = "0.00"
    linhas: list[LinhaExtrato]

    _saldos = field_validator("saldo_inicial", "saldo_final")(
        classmethod(lambda cls, v: None if v is None else normalizar_decimal(v))
    )
    _rendimento = field_validator("rendimento")(
        classmethod(lambda cls, v: normalizar_decimal(v))
    )


class ReconciliacaoExtratoOut(BaseModel):
    """Resultado do balance walk determinístico — decimais como string.

    `bate=False` NÃO é erro HTTP: a rota devolve 200 e o cliente decide.
    `aplicavel=False` quando o extrato não imprime saldo_inicial E saldo_final
    (walk N/A) — aí `bate` é sempre False (não há o que conferir).
    """

    aplicavel: bool
    saldo_inicial: str
    rendimento: str
    soma_receitas: str
    soma_debitos: str
    soma_pagamentos_fatura: str
    saldo_final_calc: str  # saldo_inicial + rendimento + receitas − debitos − pagamentos
    saldo_final_declarado: str
    diferenca: str  # saldo_final_calc − saldo_final_declarado
    bate: bool


class ExtratoPreviewResponse(BaseModel):
    # Sem cartao_id: o extrato é da CONTA, não de um cartão.
    extrato: ExtratoExtraido
    reconciliacao: ReconciliacaoExtratoOut
