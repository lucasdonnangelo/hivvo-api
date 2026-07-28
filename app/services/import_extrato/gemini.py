"""Chamada ao Gemini do extrato: texto redigido -> JSON no schema ExtratoExtraido.

Usa EXCLUSIVAMENTE GEMINI_IMPORT_API_KEY (chave dedicada, tier pago, custo
isolado) — a MESMA da importação de fatura, NUNCA a GEMINI_API_KEY do assistente
(restrição do batch: sem chave nova). Structured output (response_schema) força o
shape; o prompt carrega a semântica da classificação em baldes.

DÍVIDA CONSCIENTE: o encanamento (client singleton + retry + mapeamento 503 +
safety) é ESPELHADO de services/import_fatura/gemini.py em vez de compartilhado.
A duplicação é deliberada — extrair um helper comum mexeria no gemini.py da fatura
(cujo teste de safety faz monkeypatch em `_get_client` no módulo da fatura) e
aumentaria o blast-radius. Cada import type possui seu módulo gemini, com seu
próprio teste de safety com mutação. Ver PENDENCIAS_PRIORIZADAS.md (follow-up).

PROMPT_REGRAS é o prompt VALIDADO no spike (scripts/spike_extrato/llm.py) com UMA
adição de produção: capturar o `rendimento` do RESUMO. Não altere as regras sem
revalidar contra extratos reais.

PII/logs: o texto do extrato passa por aqui — nada dele pode ir para log. Em erro,
loga-se apenas a CLASSE da exceção.
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
from app.schemas.import_extrato import ExtratoExtraido

logger = logging.getLogger(__name__)

PROMPT_REGRAS = """\
Você recebe o texto extraído de um EXTRATO DE CONTA bancária brasileira (conta
corrente / conta de pagamento — NÃO é fatura de cartão de crédito). Devolva
APENAS o JSON no schema fornecido, com TODAS as movimentações impressas.

Classifique CADA linha de movimentação em exatamente um `balde`:

- "receita": dinheiro que ENTRA na conta — salário/proventos, "Transferência
  recebida", "Pix recebido de ...", depósito, estorno/reembolso/devolução
  recebido na conta.

- "debito": saída de caixa que É consumo/gasto — "Compra no débito", "Pix
  enviado", "Transferência enviada"/TED, "Pagamento de boleto", saque, tarifa,
  mensalidade, débito automático de conta.

- "pagamento_fatura": pagamento de FATURA DE CARTÃO de crédito — "Pagamento de
  fatura", "Pagamento fatura Nubank/Itaú/...". NÃO é despesa (é quitação do
  cartão). Preencha `cartao_citado` com o banco/cartão nomeado na linha; use
  null se a linha não nomear nenhum.

Desambiguação:
- Pix/TED enviado para uma PESSOA é "debito", nunca "pagamento_fatura".
- "Pagamento de fatura" sem cartão nomeado é "pagamento_fatura" com
  cartao_citado=null (não vire "debito").
- Só use "pagamento_fatura" quando a linha fala explicitamente de FATURA/CARTÃO.
- Se uma linha não parecer nenhum dos três (aplicação/resgate de investimento,
  transferência entre contas próprias), classifique no balde mais próximo pela
  DIREÇÃO do caixa (entrou=receita, saiu=debito) e NÃO invente linhas.

RENDIMENTO (campo `rendimento`, NÃO é linha): muitos extratos trazem no RESUMO um
"Rendimento líquido" / "Rendimento do período" / "Juros/rendimento da conta" —
um total do período, fora da lista de movimentações. Extraia esse número IMPRESSO
para `rendimento` (string decimal com ponto, ex.: "12.34"); use "0.00" se o
extrato não o imprimir. NÃO o duplique como uma linha de "receita": se o
rendimento aparece SÓ no resumo, ele entra apenas em `rendimento`. (Linhas de
crédito de rendimento que apareçam na própria lista de movimentações continuam
sendo classificadas como "receita" normalmente — o campo `rendimento` é só para o
total do RESUMO.)

`valor` de cada linha: sempre a MAGNITUDE positiva (sem sinal), string decimal
com PONTO decimal e SEM separador de milhar (ex.: "1234.56"). A direção vem do
balde.

`data`: ISO YYYY-MM-DD. Infira o ano pelos limites do período (periodo.de /
periodo.ate) quando a linha só trouxer dia/mês.

`periodo` {de, ate}: o período de referência impresso no extrato (null se não
houver).

`saldo_inicial` / `saldo_final`: os saldos IMPRESSOS no extrato, string decimal
COM sinal (negativo se a conta ficou negativa); null se o extrato não imprimir.
Extraia os números IMPRESSOS — NUNCA some as linhas você mesmo.

`banco`: o banco da CONTA (ex.: "Nubank").

--- TEXTO DO EXTRATO ---
"""

# Client singleton próprio do extrato (mesma chave/timeout da fatura, instância
# SEPARADA de propósito — mesmo padrão T-21 do assistente).
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


def extrair_extrato(texto_redigido: str) -> str:
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
                    response_schema=ExtratoExtraido,
                    # F-06: mesma moderação do assistente (fonte única em
                    # app/core/gemini_safety) — o texto do extrato vai ao modelo.
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
            # Só a CLASSE no log: a mensagem da exceção pode ecoar payload, e o
            # texto do extrato nunca vai para log.
            logger.error("[import] falha na chamada ao Gemini: %s", e.__class__.__name__)
            raise HTTPException(
                status_code=503,
                detail="Serviço de importação temporariamente indisponível. Tente novamente em instantes.",
            )
    raise HTTPException(  # inalcançável — toda iteração retorna ou levanta
        status_code=503,
        detail="Serviço de importação temporariamente indisponível. Tente novamente em instantes.",
    )
