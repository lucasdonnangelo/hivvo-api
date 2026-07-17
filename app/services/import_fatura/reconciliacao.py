"""Reconciliação determinística — o guarda-costas da extração por LLM.

Tudo em Decimal, calculado AQUI (nunca pelo modelo).

Âncora primário: o CONSUMO BRUTO do ciclo que o BANCO declara
(total_compras_periodo + total_iof_periodo) — independente das linhas
itemizadas, senão o cheque é circular. NÃO ancorar no "total a pagar":
ele é líquido (embute saldo anterior e pagamentos) e dá falso NÃO BATE
(caso Itaú da validação de 17/07).

  ancora      = total_compras_periodo + total_iof_periodo (declarados)
  soma_gastos = soma das linhas tipo {compra, iof}
                (estornos são compra com valor negativo -> abatem sozinhos)
  bate        = |soma_gastos - ancora| <= tolerância

Cheque secundário (diagnóstico da semântica do "a pagar" de cada banco —
pode legitimamente NÃO bater, ex.: pagamento de ciclo anterior listado na
fatura, caso Nubank da validação):
  soma_gastos + excluidos  vs  total_a_pagar
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.schemas.import_fatura import FaturaExtraida, TipoTransacao

TIPOS_GASTO = (TipoTransacao.compra, TipoTransacao.iof)
CENT = Decimal("0.01")

# Tolerância validada no spike (R$ 0,02). Constante de módulo — promover
# para Settings só se um dia precisar variar por ambiente.
TOLERANCIA = Decimal("0.02")


@dataclass
class Reconciliacao:
    ancora: Decimal  # compras + IOF do ciclo, DECLARADOS pelo banco
    soma_gastos: Decimal
    excluidos: Decimal
    total_a_pagar: Decimal
    diferenca: Decimal  # soma_gastos - ancora (cheque primário)
    bate: bool
    diferenca_secundaria: Decimal  # (soma_gastos + excluidos) - total_a_pagar
    bate_secundario: bool


def reconciliar(fatura: FaturaExtraida, tolerancia: Decimal) -> Reconciliacao:
    soma_gastos = Decimal("0")
    excluidos = Decimal("0")
    for t in fatura.transacoes:
        valor = Decimal(t.valor_brl)
        if t.tipo in TIPOS_GASTO:
            soma_gastos += valor
        else:
            excluidos += valor

    ancora = Decimal(fatura.total_compras_periodo) + Decimal(fatura.total_iof_periodo)
    total_a_pagar = Decimal(fatura.total_a_pagar)
    diferenca = (soma_gastos - ancora).quantize(CENT)
    diferenca_sec = (soma_gastos + excluidos - total_a_pagar).quantize(CENT)
    return Reconciliacao(
        ancora=ancora.quantize(CENT),
        soma_gastos=soma_gastos.quantize(CENT),
        excluidos=excluidos.quantize(CENT),
        total_a_pagar=total_a_pagar.quantize(CENT),
        diferenca=diferenca,
        bate=abs(diferenca) <= tolerancia,
        diferenca_secundaria=diferenca_sec,
        bate_secundario=abs(diferenca_sec) <= tolerancia,
    )
