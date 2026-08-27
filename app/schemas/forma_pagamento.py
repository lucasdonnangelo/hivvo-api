"""Fonte ÚNICA das formas de pagamento — e da única que gera fatura.

Por que é um `Literal` e não um `str` com validador: a régua que decide se uma
compra vira dívida de fatura passou a ser a forma de pagamento
(`faturas.deriva_competencia`), e uma régua que compara strings é derrotada em
silêncio pela próxima grafia divergente. O precedente é o #48
(`reclassificar_como: Literal["estorno"] | None`): **a restrição é o TIPO, não
um `if`** — grafia fora do conjunto morre com 422 no Pydantic, sem código
próprio, e nenhum payload adulterado escolhe forma arbitrária.

O conjunto foi ENUMERADO do frontend, não de memória — as três telas de
transação (`AddTransactionPage.tsx`, `EditTransactionModal.tsx`,
`TransactionsPage.tsx`) declaram a MESMA lista de cinco. A recorrência oferece
a lista sem "Crédito" (`SettingsPage.tsx`), e o tipo abaixo materializa isso:
o modelo já dizia "recorrência não passa por cartão (§3.4)" em COMENTÁRIO —
agora o comentário é o tipo.
"""

from typing import Literal, get_args

# As cinco formas que o formulário de transação oferece.
FormaPagamento = Literal["Débito", "Crédito", "PIX", "Dinheiro", "TED/DOC"]

# A recorrência nunca passa por cartão (PLANO_PROJECAO §3.4) — logo "Crédito"
# não é uma forma válida para ela. Derivado do conjunto acima, nunca reescrito
# à mão: acrescentar uma forma nova lá a propaga para cá sozinha.
FormaPagamentoRecorrencia = Literal["Débito", "PIX", "Dinheiro", "TED/DOC"]

# LISTA BRANCA: a ÚNICA forma de pagamento que vira dívida de fatura.
#
# É lista branca, e não "tudo menos Débito", porque as duas falham para lados
# opostos. Branca falha FECHADO — uma grafia divergente faz um crédito NÃO
# aparecer na fatura, que é visível e o usuário reclama. Negra falharia ABERTO
# — PIX, Dinheiro e TED/DOC com cartão vazariam pela brecha e virariam dívida
# falsa e silenciosa, que é o dano que o gate da Fase 1 barrou.
FORMA_PAGAMENTO_FATURADA: FormaPagamento = "Crédito"

# Invariante de construção: a forma faturada precisa existir no conjunto. Uma
# renomeação que esqueça a constante quebra o import, não a fatura.
assert FORMA_PAGAMENTO_FATURADA in get_args(FormaPagamento)
assert FORMA_PAGAMENTO_FATURADA not in get_args(FormaPagamentoRecorrencia)
