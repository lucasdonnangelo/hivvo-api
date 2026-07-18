"""Chamada ao Gemini da importação: texto redigido -> JSON no schema FaturaExtraida.

Usa EXCLUSIVAMENTE GEMINI_IMPORT_API_KEY (chave dedicada, tier pago, custo
isolado) — NUNCA a GEMINI_API_KEY do assistente. Structured output
(response_schema) força o shape; o prompt carrega a semântica (as regras do
parser são instruções, não regex).

PROMPT_REGRAS é o prompt VALIDADO no spike de 17/07 (Nubank + Itaú, ambas
reconciliando) — não altere as regras sem revalidar contra faturas reais.

PII/logs: o texto da fatura passa por aqui — nada dele pode ir para log.
Em erro, loga-se apenas a CLASSE da exceção.
"""

from __future__ import annotations

import logging
import time

from fastapi import HTTPException
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import settings
from app.core.gemini_safety import SAFETY_SETTINGS
from app.schemas.import_fatura import FaturaExtraida

logger = logging.getLogger(__name__)

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

# Client singleton próprio da importação (chave e timeout dedicados) — mesmo
# padrão T-21 do assistente (routers/ai.py), instância SEPARADA de propósito.
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.GEMINI_IMPORT_API_KEY:
            raise HTTPException(
                status_code=503,
                detail="Importação indisponível: GEMINI_IMPORT_API_KEY não configurada.",
            )
        _client = genai.Client(
            api_key=settings.GEMINI_IMPORT_API_KEY,
            http_options=types.HttpOptions(timeout=settings.GEMINI_IMPORT_TIMEOUT_MS),
        )
    return _client


def extrair_fatura(texto_redigido: str) -> str:
    """Devolve o JSON CRU (texto) da resposta — a validação Pydantic é do
    chamador, que mapeia rejeição de schema para 502 sem vazar o conteúdo.

    Retry no padrão do assistente: max_attempts = len(GEMINI_RETRY_WAITS) + 1
    (o usuário está esperando; retry longo é para job assíncrono).
    """
    client = _get_client()
    max_attempts = len(settings.GEMINI_RETRY_WAITS) + 1
    for attempt in range(1, max_attempts + 1):
        try:
            resposta = client.models.generate_content(
                model=settings.GEMINI_IMPORT_MODEL,
                contents=PROMPT_REGRAS + texto_redigido,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=FaturaExtraida,
                    # F-06: mesma moderação do assistente (fonte única em
                    # app/core/gemini_safety) — o texto da fatura vai ao modelo.
                    safety_settings=SAFETY_SETTINGS,
                ),
            )
            return resposta.text or ""
        except genai_errors.ServerError:
            if attempt < max_attempts:
                wait = settings.GEMINI_RETRY_WAITS[attempt - 1]
                logger.warning(
                    "[import] Gemini 5xx, tentativa %d/%d — aguardando %ds",
                    attempt, max_attempts, wait,
                )
                time.sleep(wait)
                continue
            logger.error("[import] Gemini 5xx após %d tentativas", max_attempts)
            raise HTTPException(
                status_code=503,
                detail="Serviço de importação temporariamente indisponível. Tente novamente em instantes.",
            )
        except Exception as e:
            # Só a CLASSE no log: a mensagem da exceção pode ecoar payload,
            # e o texto da fatura nunca vai para log.
            logger.error("[import] falha na chamada ao Gemini: %s", e.__class__.__name__)
            raise HTTPException(
                status_code=503,
                detail="Serviço de importação temporariamente indisponível. Tente novamente em instantes.",
            )
    raise HTTPException(  # inalcançável — toda iteração retorna ou levanta
        status_code=503,
        detail="Serviço de importação temporariamente indisponível. Tente novamente em instantes.",
    )
