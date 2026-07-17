"""Chamada ao Gemini: texto redigido -> JSON no schema FaturaExtraida.

Usa EXCLUSIVAMENTE a env var GEMINI_SPIKE_API_KEY — nunca a GEMINI_API_KEY
de produção. Structured output (response_schema) força o shape; o prompt
carrega a semântica (as regras do parser são instruções, não regex).
"""

from __future__ import annotations

import os
import sys

from google import genai
from google.genai import types

from schema import FaturaExtraida

ENV_KEY = "GEMINI_SPIKE_API_KEY"
MODELO_DEFAULT = "gemini-2.5-flash"

PROMPT_REGRAS = """\
Você recebe o texto extraído de uma fatura de cartão de crédito brasileira.
Devolva APENAS o JSON no schema fornecido, com TODAS as transações impressas na fatura.

Regras de interpretação:

- "Parcela X/Y" (e variações: "X/Y", "Parc X de Y"): preencha parcela={indice: X, total: Y}.
  X é a parcela DESTA fatura. Extraia SOMENTE o que está impresso — NUNCA invente as
  parcelas futuras. valor_brl é o valor da parcela do mês.

- IOF: tipo="iof", como linha própria (senão a fatura não fecha).

- Estorno/crédito de compra (ex.: "Estorno de ..."): tipo="compra" com valor_brl NEGATIVO
  (ex.: "-50.00"), para abater dentro dos gastos. NÃO classifique estorno como ajuste_saldo.

- Compra internacional: valor_brl é o valor EM REAIS da linha principal; preencha
  internacional={moeda_orig, valor_orig, taxa} com o que a fatura mostrar (taxa=null se
  a fatura não mostrar a conversão).

- Seção "Pagamentos e Financiamentos" (pagamento da fatura, saldo restante/anterior):
  tipo="pagamento" (para pagamentos, preservando o sinal impresso — normalmente negativo)
  ou tipo="ajuste_saldo" (para saldo restante/anterior). Essas linhas NUNCA são compra.

- Múltiplos finais de cartão na mesma fatura: é a MESMA fatura; preencha portador_final
  (4 dígitos) em cada linha quando a fatura agrupar por portador; null quando não houver.

- Datas em ISO YYYY-MM-DD. O ano é inferido POR TRANSAÇÃO pelos limites do período
  (periodo.de / periodo.ate): numa fatura de 2025-12-06 a 2026-01-06, "20 DEZ" é
  2025-12-20 e "03 JAN" é 2026-01-03 — linhas de dezembro pertencem ao ano anterior.

- Valores: string decimal com PONTO como separador e SEM separador de milhar
  (ex.: "3412.88"), preservando o sinal impresso na fatura.

- competencia {mes, ano}: derive do vencimento/período de fechamento da fatura.

- Totais DECLARADOS pelo banco (extraia os números IMPRESSOS na fatura — nunca some as
  linhas você mesmo):
  * total_compras_periodo: a soma de COMPRAS do ciclo que o banco declara.
  * total_iof_periodo: o total de IOF do ciclo SE o banco mostrar separado; senão "0.00"
    (quando o IOF já está embutido no total de compras).
  * total_a_pagar: o líquido a pagar da fatura (pode embutir saldo anterior e pagamentos).
  Exemplos reais:
  * Itaú junta tudo: "Total dos lançamentos atuais R$93,95" -> total_compras_periodo="93.95",
    total_iof_periodo="0.00"; "Total desta fatura R$0,00" (já quitada) -> total_a_pagar="0.00".
  * Nubank separa: "Total de compras ... R$202,65" -> total_compras_periodo="202.65";
    "IOF de compras internacionais R$3,41" -> total_iof_periodo="3.41";
    "Total a pagar R$206,06" -> total_a_pagar="206.06".
  * NÃO confunda com "Total da fatura anterior", "Fatura anterior" ou "Saldo financiado" —
    são de ciclos passados e JAMAIS entram nesses campos.

--- TEXTO DA FATURA ---
"""


def obter_api_key() -> str:
    key = os.environ.get(ENV_KEY)
    if not key:
        sys.exit(
            f"ERRO: a env var {ENV_KEY} não está definida.\n"
            f"Este spike usa uma chave PRÓPRIA — NUNCA use a GEMINI_API_KEY de produção.\n"
            f'Defina antes de rodar:  $env:{ENV_KEY} = "sua-chave-do-spike"'
        )
    return key


def extrair_fatura(texto: str, modelo: str, api_key: str) -> str:
    """Devolve o JSON CRU (texto) da resposta — a validação Pydantic é do chamador,
    que precisa do cru para salvar em .raw.json quando o schema rejeitar."""
    client = genai.Client(api_key=api_key)
    resposta = client.models.generate_content(
        model=modelo,
        contents=PROMPT_REGRAS + texto,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=FaturaExtraida,
        ),
    )
    return resposta.text or ""
