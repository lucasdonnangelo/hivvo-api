"""Tratamento de erro e telemetria das chamadas ao Gemini da importação.

FONTE ÚNICA dos handlers por classe de erro, da telemetria de resposta e do
truncamento da mensagem da API. A importação de fatura
(services/import_fatura/gemini.py) e a de extrato
(services/import_extrato/gemini.py) EXECUTAM ESTE CÓDIGO — não têm cópia dele.
Fecha a parte operacional da #31: até 29/07 a fatura tinha os 6 handlers e a
telemetria (#38) e o extrato tinha um `except Exception` nu, o MESMO ponto cego,
já em código que não era mais espelho. Portar (copiar) teria reaberto a
divergência no primeiro handler novo.

O que NÃO mora aqui, de propósito:
  * `_get_client` — singleton POR módulo (chave/timeout dedicados, mesmo padrão
    T-21 do assistente), e os testes de safety fazem monkeypatch nele no módulo
    de cada um. Construir o client é independente de tratar o erro dele.
  * o prompt e as mensagens que nomeiam o documento (ver MensagensErro).

--- LOGGER INJETADO ---

`gerar_com_retry` recebe o logger do CHAMADOR e este módulo nunca cria um
próprio. O prefixo das linhas é "[import]" nos DOIS módulos, então é o NOME do
logger (`...import_fatura.gemini` vs `...import_extrato.gemini`) que diz qual
importação falhou — um logger deste módulo apagaria essa distinção em produção,
que é a única coisa que separa as duas no stream de log.

--- PII/logs ---

O texto importado NUNCA vai para log. EXCEÇÃO DELIBERADA (#38): em erro de API
loga-se também `e.message` — o campo `message` da resposta de erro da Gemini,
TRUNCADO em MAX_MSG_API — porque sem ele um 400 é indistinguível de um 429 em
produção. NUNCA `str(e)` nem `e.details`: os dois embutem o JSON inteiro da
resposta.

ASSIMETRIA que o próximo leitor precisa conhecer, porque ela NÃO é simétrica
entre os dois consumidores: a fatura é dado do TITULAR; o extrato carrega PII de
TERCEIROS (nome, CPF, agência e conta de contrapartes de Pix/TED, que não
consentiram — por isso a redação de services/import_extrato/redacao.py existe).
O `message` é seguro porque descreve a FORMA da requisição, não o conteúdo dela
("API key not valid", "Request contains an invalid argument", "The request timed
out") — a API não ecoa o prompt. Mas o RESIDUAL, se um dia ela ecoar, é PIOR no
extrato do que na fatura. O truncamento em MAX_MSG_API é o que o limita, e
abaixo dele não há rede: a LoggingIntegration do sentry_sdk está ativa com os
defaults (breadcrumb em INFO, evento em ERROR) e o `_before_send` de
core/observability NÃO varre breadcrumb nem logentry (#39) — toda string logada
aqui sai do servidor como está.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

import httpx
from fastapi import HTTPException
from google.genai import errors as genai_errors

from app.core.config import settings
from app.core.gemini_generation import STATUS_SEM_RETRY

# --- Mensagens ao usuário ---------------------------------------------------
#
# Uma string por CAUSA (#38). Antes, seis falhas distintas — quota, entrada
# rejeitada, credencial errada, 5xx, timeout e o desconhecido — compartilhavam a
# mesma string, e o log guardava só a classe da exceção: nem o usuário nem a
# produção conseguiam separar "espere" de "isso não vai melhorar".
#
# As TRÊS daqui são compartilhadas porque já falam de "importação", sem nomear o
# documento. As outras duas ficam em cada módulo: elas dizem "esta fatura" /
# "este extrato" — e isso é ARTIGO, não só substantivo, então um template com
# placeholder acertaria o substantivo e erraria o gênero.
#
# Os STATUS HTTP seguem todos 503. Mudar isso é contrato com o hivvo-web (#38:
# 429 e 400 merecem status próprio) e tem trava de teste própria.

MSG_INDISPONIVEL = (
    "Serviço de importação temporariamente indisponível. Tente novamente em instantes."
)
MSG_QUOTA = "Limite de uso da importação atingido. Tente novamente em alguns minutos."
MSG_CREDENCIAL = (
    "Importação indisponível por configuração do serviço. Avise o suporte — "
    "tentar de novo não resolve."
)


@dataclass(frozen=True)
class MensagensErro:
    """As 5 mensagens de um consumidor: 2 obrigatórias, 3 com default compartilhado.

    `entrada` e `timeout` nomeiam o documento ("esta fatura" / "este extrato") e
    por isso NÃO têm default — quem consome é obrigado a escrever a sua. As três
    restantes vêm prontas e iguais para todo mundo; `indisponivel` em particular
    é contrato travado por teste com o front, não a mude aqui.
    """

    entrada: str
    timeout: str
    indisponivel: str = MSG_INDISPONIVEL
    quota: str = MSG_QUOTA
    credencial: str = MSG_CREDENCIAL


# Teto do que se loga da mensagem de erro da API. Ela vai para o Sentry como
# evento (logger.error) — 200 chars bastam para o motivo e cortam qualquer eco
# de payload que a API resolva incluir. Ver a nota de PII/logs no docstring.
MAX_MSG_API = 200


def _curto(texto: object) -> str:
    """Corta a mensagem da API em MAX_MSG_API — ver a nota de PII/logs no
    docstring do módulo. Marca o corte para o leitor do log não confundir
    truncamento nosso com mensagem curta da API."""
    s = "" if texto is None else str(texto)
    return s if len(s) <= MAX_MSG_API else s[:MAX_MSG_API] + "…[truncado]"


def _retry_delay_pedido(e: genai_errors.ClientError, logger: logging.Logger) -> str | None:
    """Quanto o servidor pediu para esperar num 429, das DUAS fontes possíveis:
    o header HTTP `Retry-After` e o `RetryInfo.retryDelay` que a Gemini põe em
    error.details (que é o formato que ela costuma usar de fato).

    SÓ PARA LOG — a importação não retenta 429 por decisão explícita: o usuário
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


def _log_telemetria(resposta: object, logger: logging.Logger) -> None:
    """Uma linha com finish_reason + anatomia das parts + usage_metadata.

    Só metadado numérico — nada do conteúdo importado, que é o que atravessa os
    módulos que chamam aqui.

    O guard NÃO é decorativo: o `return` do chamador mora dentro do `try`, então
    uma telemetria que levante (candidato vazio, usage_metadata None, campo que
    o SDK renomeie numa versão futura) transformaria uma extração BEM-SUCEDIDA
    em 503. Loga com exc_info em vez de engolir — senão o guard vira exatamente
    o ponto cego que o #38 existe para fechar.
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


def gerar_com_retry(
    chamada: Callable[[], object],
    *,
    logger: logging.Logger,
    mensagens: MensagensErro,
) -> str:
    """Executa `chamada` com retry e devolve o JSON CRU (texto) da resposta.

    `chamada` é um callable de ZERO argumentos que faz o `generate_content` — o
    client já resolvido, o modelo e a config são do chamador. O client fica de
    fora de propósito: `_get_client` levanta HTTPException própria quando falta
    a chave, e chamá-lo aqui dentro faria o `except Exception` final trocar
    "GEMINI_IMPORT_API_KEY não configurada" pela mensagem genérica.

    Retry no padrão do assistente: max_attempts = len(GEMINI_RETRY_WAITS) + 1
    (o usuário está esperando; retry longo é para job assíncrono). SÓ 5xx é
    retentado — 429 não é, de propósito (ver _retry_delay_pedido) — e nem TODO
    5xx: os status de STATUS_SEM_RETRY (core/gemini_generation) saem do
    orçamento porque o relógio já estourou.

    Toda falha vira 503; o que o #38 mudou é que cada CAUSA tem mensagem e log
    próprios.
    """
    max_attempts = len(settings.GEMINI_RETRY_WAITS) + 1
    for attempt in range(1, max_attempts + 1):
        inicio = time.perf_counter()
        try:
            resposta = chamada()
            _log_telemetria(resposta, logger)
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
                raise HTTPException(status_code=503, detail=mensagens.timeout)

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
            raise HTTPException(status_code=503, detail=mensagens.indisponivel)
        except genai_errors.ClientError as e:
            # 4xx NÃO é retentado (não melhora sozinho) e até o #38 caía no
            # balde genérico junto com timeout de rede.
            decorrido = time.perf_counter() - inicio
            code = getattr(e, "code", None)
            status = getattr(e, "status", None)
            msg = _curto(getattr(e, "message", None))

            if code == 429:
                logger.error(
                    "[import] Gemini 429 quota/rate limit — status=%s "
                    "retry_delay_pedido=%s decorrido=%.1fs msg=%s",
                    status, _retry_delay_pedido(e, logger), decorrido, msg,
                )
                raise HTTPException(status_code=503, detail=mensagens.quota)

            if code == 400:
                logger.error(
                    "[import] Gemini 400 rejeitou a entrada — status=%s "
                    "decorrido=%.1fs msg=%s",
                    status, decorrido, msg,
                )
                raise HTTPException(status_code=503, detail=mensagens.entrada)

            if code in (401, 403):
                logger.error(
                    "[import] Gemini %s credencial/permissão — status=%s msg=%s "
                    "— checar GEMINI_IMPORT_API_KEY; NÃO é falha transitória",
                    code, status, msg,
                )
                raise HTTPException(status_code=503, detail=mensagens.credencial)

            logger.error(
                "[import] Gemini 4xx não mapeado — code=%s status=%s "
                "decorrido=%.1fs msg=%s",
                code, status, decorrido, msg,
            )
            raise HTTPException(status_code=503, detail=mensagens.indisponivel)
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
            raise HTTPException(status_code=503, detail=mensagens.timeout)
        except Exception as e:
            # Rede de segurança. Com repr + traceback: se algo cair AQUI, é
            # porque não foi previsto — e aí o nome da classe sozinho não basta
            # (foi exatamente esse log que travou o diagnóstico do #38).
            decorrido = time.perf_counter() - inicio
            logger.exception(
                "[import] falha inesperada na chamada ao Gemini após %.1fs: %r",
                decorrido, e,
            )
            raise HTTPException(status_code=503, detail=mensagens.indisponivel)
    raise HTTPException(  # inalcançável — toda iteração retorna ou levanta
        status_code=503, detail=mensagens.indisponivel
    )
