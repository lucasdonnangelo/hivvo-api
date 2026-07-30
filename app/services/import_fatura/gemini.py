"""Chamada ao Gemini da importação: texto redigido -> JSON no schema FaturaExtraida.

Usa EXCLUSIVAMENTE GEMINI_IMPORT_API_KEY (chave dedicada, tier pago, custo
isolado) — NUNCA a GEMINI_API_KEY do assistente. Structured output
(response_schema) força o shape; o prompt carrega a semântica (as regras do
parser são instruções, não regex).

PROMPT_REGRAS é o prompt VALIDADO no spike de 17/07 (Nubank + Itaú, ambas
reconciliando) — não altere as regras sem revalidar contra faturas reais.

PII/logs: o texto da fatura passa por aqui — nada dele pode ir para log.
EXCEÇÃO DELIBERADA (#38): em erro de API, loga-se também `e.message` — o campo
`message` da resposta de erro da Gemini, TRUNCADO em _MAX_MSG_API — porque sem
ele um 400 é indistinguível de um 429 na produção. NUNCA `str(e)` nem
`e.details`: os dois embutem o JSON inteiro da resposta. Vale lembrar que a
LoggingIntegration do sentry_sdk está ativa com os defaults (breadcrumb em INFO,
evento em ERROR) e o `_before_send` de core/observability NÃO varre breadcrumb
nem logentry — então toda string logada aqui sai do servidor como está.

Telemetria (#38): a resposta do Gemini era descartada inteira (só `.text` era
lido). Agora finish_reason/parts/usage_metadata vão para o log em toda chamada
bem-sucedida — é o que distingue truncamento por MAX_TOKENS de JSON malformado,
que hoje colidem no mesmo 502 do router.
"""

from __future__ import annotations

import logging
import time

import httpx
from fastapi import HTTPException
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import settings
from app.core.gemini_generation import STATUS_SEM_RETRY, THINKING_CONFIG, http_options
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

# Mensagens do usuário, uma por CAUSA (#38). Antes, seis falhas distintas
# — quota, entrada rejeitada, credencial errada, 5xx, timeout e o desconhecido —
# compartilhavam a mesma string, e o log guardava só a classe da exceção: nem o
# usuário nem a produção conseguiam separar "espere" de "isso não vai melhorar".
# Os STATUS HTTP seguem todos 503, como antes — este batch mexe em texto e log,
# não em contrato (#38: 429 e 400 merecem status próprio, mas isso é contrato).
_MSG_INDISPONIVEL = (
    "Serviço de importação temporariamente indisponível. Tente novamente em instantes."
)
_MSG_QUOTA = (
    "Limite de uso da importação atingido. Tente novamente em alguns minutos."
)
_MSG_ENTRADA = (
    "Não foi possível processar esta fatura: a extração rejeitou o arquivo enviado."
)
_MSG_CREDENCIAL = (
    "Importação indisponível por configuração do serviço. Avise o suporte — "
    "tentar de novo não resolve."
)
_MSG_TIMEOUT = (
    "A leitura da fatura passou do tempo limite. Tente novamente; se persistir, "
    "a fatura pode ser grande demais."
)

# Teto do que se loga da mensagem de erro da API. Ela vai para o Sentry como
# evento (logger.error) — 200 chars bastam para o motivo e cortam qualquer
# eco de payload que a API resolva incluir.
_MAX_MSG_API = 200

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
            # Fonte única do timeout (core/gemini_generation) — o extrato usa a
            # MESMA função. Não construa HttpOptions aqui.
            http_options=http_options(),
        )
    return _client


def _curto(texto: object) -> str:
    """Corta a mensagem da API em _MAX_MSG_API — ver a nota de PII/Sentry no
    docstring do módulo. Marca o corte para o leitor do log não confundir
    truncamento nosso com mensagem curta da API."""
    s = "" if texto is None else str(texto)
    return s if len(s) <= _MAX_MSG_API else s[:_MAX_MSG_API] + "…[truncado]"


def _retry_delay_pedido(e: genai_errors.ClientError) -> str | None:
    """Quanto o servidor pediu para esperar num 429, das DUAS fontes possíveis:
    o header HTTP `Retry-After` e o `RetryInfo.retryDelay` que a Gemini põe em
    error.details (que é o formato que ela costuma usar de fato).

    SÓ PARA LOG — este batch não retenta 429 por decisão explícita: o usuário
    está esperando a request e a Gemini costuma pedir dezenas de segundos.
    O número dimensiona a cota e decide o próximo batch.
    """
    try:
        resposta = getattr(e, "response", None)
        cabecalhos = getattr(resposta, "headers", None)
        if cabecalhos is not None:
            header = cabecalhos.get("retry-after")
            if header:
                return str(header)

        detalhes = getattr(e, "details", None)
        if isinstance(detalhes, dict):
            # `details` é o corpo cru: às vezes {"error": {...}}, às vezes já
            # desembrulhado. Aceita os dois.
            interno = detalhes.get("error", detalhes)
            if isinstance(interno, dict):
                for item in interno.get("details") or []:
                    if isinstance(item, dict) and "retryDelay" in item:
                        return str(item["retryDelay"])
    except Exception:
        logger.warning("[import] falha ao ler o retry-delay do 429", exc_info=True)
    return None


def _log_telemetria(resposta: object) -> None:
    """Uma linha com finish_reason + anatomia das parts + usage_metadata.

    Só metadado numérico — nada do conteúdo da fatura, que é o que atravessa
    este módulo.

    O guard NÃO é decorativo: o `return` do chamador mora dentro do `try`, então
    uma telemetria que levante (candidato vazio, usage_metadata None, campo que
    o SDK renomeie numa versão futura) transformaria uma extração BEM-SUCEDIDA
    em 503. Loga com exc_info em vez de engolir — senão o guard vira exatamente
    o ponto cego que este batch existe para fechar.
    """
    try:
        candidatos = getattr(resposta, "candidates", None) or []
        primeiro = candidatos[0] if candidatos else None
        finish_reason = getattr(primeiro, "finish_reason", None)

        partes = []
        conteudo = getattr(primeiro, "content", None)
        if conteudo is not None:
            partes = getattr(conteudo, "parts", None) or []
        thought = sum(1 for p in partes if getattr(p, "thought", False))

        uso = getattr(resposta, "usage_metadata", None)
        logger.info(
            "[import] gemini resposta: finish_reason=%s candidates=%d parts=%d "
            "thought=%d texto=%d prompt_tokens=%s candidates_tokens=%s "
            "thoughts_tokens=%s total_tokens=%s",
            finish_reason,
            len(candidatos),
            len(partes),
            thought,
            len(partes) - thought,
            getattr(uso, "prompt_token_count", None),
            getattr(uso, "candidates_token_count", None),
            getattr(uso, "thoughts_token_count", None),
            getattr(uso, "total_token_count", None),
        )
    except Exception:
        logger.warning(
            "[import] telemetria da resposta do Gemini falhou (a extração seguiu "
            "normalmente)",
            exc_info=True,
        )


def extrair_fatura(texto_redigido: str) -> str:
    """Devolve o JSON CRU (texto) da resposta — a validação Pydantic é do
    chamador, que mapeia rejeição de schema para 502 sem vazar o conteúdo.

    Retry no padrão do assistente: max_attempts = len(GEMINI_RETRY_WAITS) + 1
    (o usuário está esperando; retry longo é para job assíncrono). SÓ 5xx é
    retentado — 429 não é, de propósito (ver _retry_delay_pedido) — e nem TODO
    5xx: os status de STATUS_SEM_RETRY (core/gemini_generation) saem do orçamento
    porque o relógio já estourou.

    Toda falha vira 503, como antes; o que mudou (#38) é que cada CAUSA tem
    mensagem e log próprios.
    """
    client = _get_client()
    max_attempts = len(settings.GEMINI_RETRY_WAITS) + 1
    for attempt in range(1, max_attempts + 1):
        inicio = time.perf_counter()
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
                    # Teto EXPLÍCITO no raciocínio (fonte única em
                    # app/core/gemini_generation). Sem ele o thinking não tem
                    # teto e atravessava o deadline sozinho — o motivo do 1024
                    # (e por que NÃO é 0) está no docstring de lá.
                    thinking_config=THINKING_CONFIG,
                ),
            )
            _log_telemetria(resposta)
            return resposta.text or ""
        except genai_errors.ServerError as e:
            # `status` foi o dado mais caro do #38: DEADLINE_EXCEEDED (o
            # servidor bateu no X-Server-Timeout que o SDK deriva do nosso
            # timeout) e UNAVAILABLE (Gemini fora) pedem correções OPOSTAS, e
            # até então os dois chegavam como "Gemini 5xx" e nada mais. Agora ele
            # também DECIDE o retry, não só documenta a falha.
            decorrido = time.perf_counter() - inicio
            status = getattr(e, "status", None)

            if status in STATUS_SEM_RETRY:
                # DEADLINE_EXCEEDED: o relógio já estourou (o servidor bateu no
                # X-Server-Timeout derivado do NOSSO timeout). Retentar dobraria
                # a espera do usuário e o custo por uma chance baixa. Só este
                # status sai do retry — UNAVAILABLE segue no orçamento abaixo.
                logger.error(
                    "[import] Gemini 5xx SEM retry na tentativa %d/%d — code=%s "
                    "status=%s decorrido=%.1fs msg=%s "
                    "(limite do client: %dms)",
                    attempt, max_attempts, getattr(e, "code", None), status,
                    decorrido, _curto(getattr(e, "message", None)),
                    settings.GEMINI_IMPORT_TIMEOUT_MS,
                )
                raise HTTPException(status_code=503, detail=_MSG_TIMEOUT)

            if attempt < max_attempts:
                wait = settings.GEMINI_RETRY_WAITS[attempt - 1]
                logger.warning(
                    "[import] Gemini 5xx, tentativa %d/%d — code=%s status=%s "
                    "decorrido=%.1fs — aguardando %ds",
                    attempt, max_attempts, getattr(e, "code", None),
                    status, decorrido, wait,
                )
                time.sleep(wait)
                continue
            logger.error(
                "[import] Gemini 5xx após %d tentativas — code=%s status=%s "
                "decorrido=%.1fs msg=%s",
                max_attempts, getattr(e, "code", None), status,
                decorrido, _curto(getattr(e, "message", None)),
            )
            raise HTTPException(status_code=503, detail=_MSG_INDISPONIVEL)
        except genai_errors.ClientError as e:
            # 4xx NÃO é retentado (não melhora sozinho) e até agora caía no
            # balde genérico junto com timeout de rede.
            decorrido = time.perf_counter() - inicio
            code = getattr(e, "code", None)
            status = getattr(e, "status", None)
            msg = _curto(getattr(e, "message", None))

            if code == 429:
                logger.error(
                    "[import] Gemini 429 quota/rate limit — status=%s "
                    "retry_delay_pedido=%s decorrido=%.1fs msg=%s",
                    status, _retry_delay_pedido(e), decorrido, msg,
                )
                raise HTTPException(status_code=503, detail=_MSG_QUOTA)

            if code == 400:
                logger.error(
                    "[import] Gemini 400 rejeitou a entrada — status=%s "
                    "decorrido=%.1fs msg=%s",
                    status, decorrido, msg,
                )
                raise HTTPException(status_code=503, detail=_MSG_ENTRADA)

            if code in (401, 403):
                logger.error(
                    "[import] Gemini %s credencial/permissão — status=%s msg=%s "
                    "— checar GEMINI_IMPORT_API_KEY; NÃO é falha transitória",
                    code, status, msg,
                )
                raise HTTPException(status_code=503, detail=_MSG_CREDENCIAL)

            logger.error(
                "[import] Gemini 4xx não mapeado — code=%s status=%s "
                "decorrido=%.1fs msg=%s",
                code, status, decorrido, msg,
            )
            raise HTTPException(status_code=503, detail=_MSG_INDISPONIVEL)
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            # TimeoutException cobre Read/Connect/Write/PoolTimeout — a família
            # inteira, não só as duas nomeadas. `decorrido` vs. o limite
            # configurado diz se estourou o nosso teto ou morreu antes dele.
            decorrido = time.perf_counter() - inicio
            logger.error(
                "[import] Gemini timeout/conexão: %s após %.1fs "
                "(limite do client: %dms)",
                e.__class__.__name__, decorrido, settings.GEMINI_IMPORT_TIMEOUT_MS,
            )
            raise HTTPException(status_code=503, detail=_MSG_TIMEOUT)
        except Exception as e:
            # Rede de segurança. Com repr + traceback: se algo cair AQUI, é
            # porque não foi previsto — e aí o nome da classe sozinho não basta
            # (foi exatamente esse log que travou o diagnóstico anterior).
            decorrido = time.perf_counter() - inicio
            logger.exception(
                "[import] falha inesperada na chamada ao Gemini após %.1fs: %r",
                decorrido, e,
            )
            raise HTTPException(status_code=503, detail=_MSG_INDISPONIVEL)
    raise HTTPException(  # inalcançável — toda iteração retorna ou levanta
        status_code=503, detail=_MSG_INDISPONIVEL
    )
