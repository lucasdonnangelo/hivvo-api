"""Config de GERAÇÃO compartilhada das chamadas ao Gemini da importação.

FONTE ÚNICA de thinking budget, timeout do client e política de retry por
status. Tanto a importação de fatura (services/import_fatura/gemini.py) quanto a
de extrato (services/import_extrato/gemini.py) importam daqui — nunca redefinem
nem copiam os valores. Mesmo molde e mesmo motivo do gemini_safety (F-06): os
dois módulos são espelhados de propósito (ver a DÍVIDA CONSCIENTE no docstring
do gemini do extrato), e um parâmetro de geração que more em dois lugares vai
ser esquecido em um deles — foi exatamente o que aconteceu com o safety.

Módulo neutro: depende de `settings`, de nada de router/service.

--- THINKING_BUDGET = 1024 ---

Sem thinking_config, o modelo raciocina SEM TETO. Matriz medida numa fatura Itaú
real de 6 páginas / 95 transações (scripts/spike_import/repro_fatura_grande.py):

    thinking ausente : 63,9s / 88,6s / 65,6s   (thoughts 8.694 / 13.245 / 8.694)
    thinking 1024    : 31,5s                   (thoughts 927)
    thinking 0       : 35,6s                   (mas devolveu periodo=null)

Todas com finish_reason=STOP e reconciliação 0.00 — o problema NUNCA foi volume
nem truncamento. É a duração do thinking, que varia ±39% entre execuções
IDÊNTICAS e atravessa o deadline da request.

NÃO "simplifique" para 0: o 0 foi igualmente rápido (35,6s vs 31,5s) e PERDEU o
campo `periodo` na Itaú — e `periodo` é o que infere o ano de cada transação
("20 DEZ" numa fatura 2025-12-06→2026-01-06 é 2025). 1024 é o menor teto medido
que preserva a extração completa.

Efeito colateral que vale conhecer: o orçamento de saída (65k) é COMPARTILHADO
entre thinking e resposta. Com o thinking limitado a 1024, ele deixa de poder
consumir o orçamento inteiro — o que fecha a falha latente de resposta vazia por
MAX_TOKENS numa fatura maior que as medidas.

--- STATUS_SEM_RETRY ---

DEADLINE_EXCEEDED é o servidor batendo no X-Server-Timeout que o SDK deriva do
nosso timeout: o relógio JÁ estourou. Retentar dobra a espera do usuário e o
custo por uma chance baixa — a request morre no timeout do cliente de qualquer
jeito. UNAVAILABLE (sobrecarga real do provedor) continua sendo retentado: é o
caso em que esperar 2s resolve.

--- AFC_DESLIGADO ---

O SDK liga o Automatic Function Calling por DEFAULT. Hoje é inócuo — a
importação não passa `tools`, então não há função para o modelo chamar e o loop
automático nunca roda. Desligar é explicitação, não conserto: é o TERCEIRO
default de provedor que herdamos sem escolher, depois do safety_settings (F-06)
e do thinking_config (que custou 63,9-88,6s por fatura até ser medido). O padrão
já se repetiu vezes suficientes para a regra ser "o que o provedor decide por
nós, decidimos nós" — e o dia em que alguém acrescentar `tools` a uma destas
chamadas, o AFC não vira comportamento novo de surpresa.
"""

from google.genai import types

from app.core.config import settings

THINKING_BUDGET = 1024

THINKING_CONFIG = types.ThinkingConfig(thinking_budget=THINKING_BUDGET)

# Status de ServerError (5xx) que NÃO são retentados — ver o docstring.
STATUS_SEM_RETRY = frozenset({"DEADLINE_EXCEEDED"})

# Automatic Function Calling explicitamente DESLIGADO — ver o docstring.
AFC_DESLIGADO = types.AutomaticFunctionCallingConfig(disable=True)


def http_options() -> types.HttpOptions:
    """HttpOptions dos clients da importação, com o timeout de GEMINI_IMPORT_TIMEOUT_MS.

    É FUNÇÃO, não constante: uma constante de módulo congelaria o valor no
    import, antes de o .env/ambiente do processo ser aplicado sobre Settings.
    Nenhum consumidor deve voltar a construir HttpOptions na mão — é assim que o
    timeout chega igual aos dois módulos.

    ATENÇÃO: este valor não é só o teto do lado do cliente. O SDK deriva dele o
    header X-Server-Timeout, então o prazo vale dos DOIS lados — apertá-lo aqui
    faz o servidor abortar (DEADLINE_EXCEEDED), não só o httpx desistir.
    """
    return types.HttpOptions(timeout=settings.GEMINI_IMPORT_TIMEOUT_MS)
