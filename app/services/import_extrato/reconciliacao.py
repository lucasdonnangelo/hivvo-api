"""Balance walk do extrato — o guarda-costas da classificação por LLM.

Tudo em Decimal, calculado AQUI (nunca pelo modelo):

  saldo_final_calc = saldo_inicial + rendimento
                     + Σreceita − Σdebito − Σpagamento_fatura
  bate             = |saldo_final_calc − saldo_final_declarado| <= tolerância

ACHADO 1 — RENDIMENTO: o "Rendimento líquido" vem do RESUMO (não é linha de
movimentação), então entra no walk como um crédito à parte de Σreceita. Sem ele,
extratos que rendem não fecham. Materializá-lo como receita é no batch de commit,
não aqui.

Repare: pagamento_fatura NÃO é consumo, mas É saída de caixa — por isso entra no
walk como saída. O walk prova que os três baldes PARTICIONAM o extrato: linha
perdida, duplicada ou com sinal trocado (receita<->debito) não fecha.

Limite conhecido: uma linha no balde ERRADO mas na MESMA direção de caixa (ex.:
aplicação de investimento jogada em "debito") AINDA fecha o walk — esse caso só a
conferência manual pega (é achado de design do spike, não bug).

Só reconcilia quando saldo_inicial E saldo_final foram extraídos; senão N/A.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.schemas.import_extrato import Balde, ExtratoExtraido

CENT = Decimal("0.01")

# Tolerância validada no spike (R$ 0,02). Constante de módulo — promover para
# Settings só se um dia precisar variar por ambiente (mesma decisão da fatura).
TOLERANCIA = Decimal("0.02")


@dataclass
class Reconciliacao:
    aplicavel: bool  # False quando faltam saldos impressos
    saldo_inicial: Decimal
    rendimento: Decimal
    soma_receitas: Decimal
    soma_debitos: Decimal
    soma_pagamentos: Decimal
    saldo_final_calc: Decimal
    saldo_final_declarado: Decimal
    diferenca: Decimal  # saldo_final_calc − saldo_final_declarado
    bate: bool


def reconciliar(extrato: ExtratoExtraido, tolerancia: Decimal) -> Reconciliacao:
    soma = {b: Decimal("0") for b in Balde}
    for linha in extrato.linhas:
        soma[linha.balde] += Decimal(linha.valor)

    aplicavel = extrato.saldo_inicial is not None and extrato.saldo_final is not None
    si = Decimal(extrato.saldo_inicial) if extrato.saldo_inicial is not None else Decimal("0")
    sf_declarado = (
        Decimal(extrato.saldo_final) if extrato.saldo_final is not None else Decimal("0")
    )
    rendimento = Decimal(extrato.rendimento)
    sf_calc = (
        si
        + rendimento
        + soma[Balde.receita]
        - soma[Balde.debito]
        - soma[Balde.pagamento_fatura]
    )
    diferenca = (sf_calc - sf_declarado).quantize(CENT)
    return Reconciliacao(
        aplicavel=aplicavel,
        saldo_inicial=si.quantize(CENT),
        rendimento=rendimento.quantize(CENT),
        soma_receitas=soma[Balde.receita].quantize(CENT),
        soma_debitos=soma[Balde.debito].quantize(CENT),
        soma_pagamentos=soma[Balde.pagamento_fatura].quantize(CENT),
        saldo_final_calc=sf_calc.quantize(CENT),
        saldo_final_declarado=sf_declarado.quantize(CENT),
        diferenca=diferenca,
        bate=aplicavel and abs(diferenca) <= tolerancia,
    )
