"""Chamadas ao Gemini do import de EXTRATO (duas, mesmo encanamento `_gerar`):

1. `extrair_extrato` — texto redigido -> JSON no schema ExtratoExtraido.
2. `categorizar_linhas` — N linhas -> categoria de cada uma, em UMA chamada
   (Batch 2; N chamadas explodiriam a latência do preview).

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
loga-se apenas a CLASSE da exceção — e, nos 5xx, o `status` da API (enum fixo do
protocolo: UNAVAILABLE, DEADLINE_EXCEEDED...), que é o que decide o retry. NUNCA
a `message`, `str(e)` ou `details`: os três podem ecoar o payload. (Os 6 handlers
por causa e a `message` truncada existem só na fatura por enquanto — #38.)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from fastapi import HTTPException
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from app.core.config import settings
from app.core.gemini_generation import STATUS_SEM_RETRY, THINKING_CONFIG, http_options
from app.core.gemini_safety import SAFETY_SETTINGS
from app.schemas.import_extrato import CategorizacaoLote, ExtratoExtraido

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

# Prompt da categorização em LOTE — mesma semântica do /ai/suggest-category
# ("responda com o nome de UMA categoria, exatamente como está na lista"),
# estendida para N itens numa chamada e endereçada por índice.
PROMPT_CATEGORIAS = """\
Você classifica transações financeiras pessoais em categorias.

Para CADA item da lista abaixo, devolva o `indice` recebido e UMA `categoria`,
escrita EXATAMENTE como está na lista do TIPO daquele item. Não invente
categorias, não explique e não omita itens: devolva um item de resposta para
CADA item recebido, com o MESMO indice.

Categorias para itens de tipo "despesa": {despesa}
Categorias para itens de tipo "receita": {receita}

Se um item não se encaixar claramente em nenhuma, use "Outros".

Formato de cada item recebido: indice | tipo | valor | descrição

--- ITENS ---
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
            # Fonte única do timeout (core/gemini_generation) — a fatura usa a
            # MESMA função. Não construa HttpOptions aqui.
            http_options=http_options(),
        )
    return _client


def _gerar(contents: str, response_schema: type) -> str:
    """Uma chamada ao Gemini do import de extrato: JSON CRU (texto) da resposta.

    Encanamento ÚNICO das duas chamadas do extrato (extração e categorização em
    lote): client dedicado (GEMINI_IMPORT_API_KEY), temperature 0, structured
    output e — F-06 — safety_settings EXPLÍCITO, a fonte única compartilhada com
    o assistente (app/core/gemini_safety), mais o thinking_config da fonte única
    de geração (app/core/gemini_generation). Uma chamada nova neste módulo não
    tem como esquecer a moderação nem o teto de raciocínio: ela passa por aqui.

    Retry no padrão do assistente: max_attempts = len(GEMINI_RETRY_WAITS) + 1
    (o usuário está esperando; retry longo é para job assíncrono). Nem todo 5xx
    entra nesse orçamento: os status de STATUS_SEM_RETRY saem, porque o relógio
    já estourou.
    """
    client = _get_client()
    max_attempts = len(settings.GEMINI_RETRY_WAITS) + 1
    for attempt in range(1, max_attempts + 1):
        try:
            resposta = client.models.generate_content(
                model=settings.GEMINI_IMPORT_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    safety_settings=SAFETY_SETTINGS,
                    # Teto EXPLÍCITO no raciocínio (fonte única em
                    # app/core/gemini_generation, a MESMA da fatura). Sem ele o
                    # thinking não tem teto e atravessa o deadline sozinho — o
                    # motivo do 1024 (e por que NÃO é 0) está no docstring de lá.
                    # Passa por _gerar, então vale para a extração E para a
                    # categorização em lote.
                    thinking_config=THINKING_CONFIG,
                ),
            )
            return resposta.text or ""
        except genai_errors.ServerError as e:
            status = getattr(e, "status", None)
            if status in STATUS_SEM_RETRY:
                # DEADLINE_EXCEEDED: o relógio já estourou (o servidor bateu no
                # X-Server-Timeout derivado do NOSSO timeout). Retentar dobraria
                # a espera do usuário e o custo por uma chance baixa. UNAVAILABLE
                # (sobrecarga real) segue retentando no orçamento abaixo.
                logger.error(
                    "[import] Gemini 5xx SEM retry na tentativa %d/%d — status=%s "
                    "(limite do client: %dms)",
                    attempt, max_attempts, status,
                    settings.GEMINI_IMPORT_TIMEOUT_MS,
                )
                raise HTTPException(
                    status_code=503,
                    detail="Serviço de importação temporariamente indisponível. Tente novamente em instantes.",
                )
            if attempt < max_attempts:
                wait = settings.GEMINI_RETRY_WAITS[attempt - 1]
                logger.warning(
                    "[import] Gemini 5xx, tentativa %d/%d — status=%s "
                    "— aguardando %ds",
                    attempt, max_attempts, status, wait,
                )
                time.sleep(wait)
                continue
            logger.error(
                "[import] Gemini 5xx após %d tentativas — status=%s",
                max_attempts, status,
            )
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


def extrair_extrato(texto_redigido: str) -> str:
    """Devolve o JSON CRU (texto) da resposta — a validação Pydantic é do
    chamador, que mapeia rejeição de schema para 502 sem vazar o conteúdo.
    """
    return _gerar(PROMPT_REGRAS + texto_redigido, ExtratoExtraido)


@dataclass(frozen=True)
class PedidoCategoria:
    """Um item a categorizar. `indice` é a chave de volta (não a posição)."""

    indice: int
    descricao: str
    valor: str
    tipo: str  # "despesa" (balde debito) | "receita"


def categorizar_linhas(
    pedidos: list[PedidoCategoria],
    nomes_despesa: list[str],
    nomes_receita: list[str],
) -> dict[int, str]:
    """Categoriza TODAS as linhas numa chamada ÚNICA -> {indice: categoria CRUA}.

    Uma chamada, não N: com 20-60 linhas por extrato, N chamadas seriam N× a
    latência EM SÉRIE — o preview explodiria. O prompt aqui é minúsculo perto do
    texto do extrato que a extração já envia numa chamada só.

    O casamento contra a lista do usuário NÃO é feito aqui: quem chama aplica
    `categorias.casar_categoria` com a lista do TIPO da linha (assim um débito
    nunca recebe "Salário"). Índice devolvido fora do pedido é descartado —
    alinhamento é por chave explícita, nunca por posição.
    """
    if not pedidos:
        return {}

    linhas_pedido = "\n".join(
        f"{p.indice} | {p.tipo} | {p.valor} | {p.descricao}" for p in pedidos
    )
    prompt = PROMPT_CATEGORIAS.format(
        despesa=", ".join(dict.fromkeys(nomes_despesa)),
        receita=", ".join(dict.fromkeys(nomes_receita)),
    ) + linhas_pedido

    raw = _gerar(prompt, CategorizacaoLote)
    try:
        lote = CategorizacaoLote.model_validate_json(raw)
    except ValidationError as e:
        # Sem o conteúdo: o ValidationError embute os VALORES rejeitados.
        logger.warning(
            "[import] categorização rejeitada pelo schema: %d erros", len(e.errors())
        )
        raise HTTPException(
            status_code=502, detail="A categorização retornou dados inválidos."
        )

    validos = {p.indice for p in pedidos}
    return {i.indice: i.categoria for i in lote.itens if i.indice in validos}
