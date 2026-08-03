"""Chamadas ao Gemini do import de EXTRATO (duas, mesmo encanamento `_gerar`):

1. `extrair_extrato` — texto redigido -> JSON no schema ExtratoExtraido.
2. `categorizar_linhas` — N linhas -> categoria de cada uma, em UMA chamada
   (Batch 2; N chamadas explodiriam a latência do preview).

Usa EXCLUSIVAMENTE GEMINI_IMPORT_API_KEY (chave dedicada, tier pago, custo
isolado) — a MESMA da importação de fatura, NUNCA a GEMINI_API_KEY do assistente
(restrição do batch: sem chave nova). Structured output (response_schema) força o
shape; o prompt carrega a semântica da classificação em baldes.

DÍVIDA PAGA (#31, parte operacional): o encanamento de ERRO era espelhado de
services/import_fatura/gemini.py — e em 29/07 deixou de ser espelho: o #38 deu à
fatura telemetria e 6 handlers por classe, e aqui ficou um `except Exception` nu.
Agora o tratamento de erro e a telemetria vêm de app/core/gemini_erros.py, que
os DOIS módulos executam (não é cópia). Segue morando aqui só o que é do extrato:
o prompt, o client e as duas mensagens que nomeiam o documento. O `_get_client`
NÃO foi consolidado de propósito: é singleton por módulo e os testes de safety
fazem monkeypatch nele em cada um.

PROMPT_REGRAS é o prompt VALIDADO no spike (scripts/spike_extrato/llm.py) com UMA
adição de produção: capturar o `rendimento` do RESUMO. Não altere as regras sem
revalidar contra extratos reais.

PII/logs: o texto do extrato passa por aqui — nada dele pode ir para log. Em erro
loga-se também a `message` da API TRUNCADA em 200 chars (a exceção deliberada do
#38, agora valendo para os dois módulos): sem ela um 400 é indistinguível de um
429 em produção, que é o ponto cego que a consolidação existe para fechar. NUNCA
`str(e)` nem `details`.

ATENÇÃO ao que essa herança significa AQUI e não significa na fatura: a fatura é
dado do TITULAR; o extrato carrega PII de TERCEIROS (contrapartes de Pix/TED que
não consentiram — é o que `redacao.py` tenta cobrir). A `message` é segura porque
descreve a FORMA da requisição, não o conteúdo ("API key not valid", "Request
contains an invalid argument"); o RESIDUAL, se a API um dia ecoar payload, é
pior aqui do que lá. O truncamento é o que o limita; abaixo dele o #39 pôs uma
rede (scrub de logentry/breadcrumb em core/observability) que casa FORMATO
conhecido e não alcança texto livre — não é substituta desta regra.
"""

from __future__ import annotations

import logging
import time  # noqa: F401  — os testes fazem monkeypatch em `gemini.time.sleep`
from dataclasses import dataclass

from fastapi import HTTPException
from google import genai
from google.genai import types
from pydantic import ValidationError

from app.core.config import settings
from app.core.gemini_erros import MensagensErro, gerar_com_retry
from app.core.gemini_generation import AFC_DESLIGADO, THINKING_CONFIG, http_options
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

# As DUAS mensagens que nomeiam o documento — o que sobra de específico do
# extrato depois do #31. As outras três (indisponível, quota, credencial) vêm de
# gemini_erros iguais para os dois módulos; a `indisponivel` em particular é a
# ÚNICA string que o extrato usava para tudo antes deste batch, e continua sendo
# o que o 5xx devolve.
#
# Nota: `categorizar_linhas` também passa por aqui, então uma falha DELA usaria a
# mensagem de leitura do extrato. Não vale parametrizar: o chamador
# (enriquecimento._sugerir_categorias) captura a HTTPException e degrada para
# preview sem sugestão — essa mensagem nunca chega ao usuário.
_MSG_ENTRADA = (
    "Não foi possível processar este extrato: a extração rejeitou o arquivo enviado."
)
_MSG_TIMEOUT = (
    "A leitura do extrato passou do tempo limite. Tente novamente; se persistir, "
    "o extrato pode ser grande demais."
)

_MENSAGENS = MensagensErro(entrada=_MSG_ENTRADA, timeout=_MSG_TIMEOUT)

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

    Retry, telemetria e mapeamento de erro são de `gerar_com_retry`
    (app/core/gemini_erros), o MESMO código que a fatura executa — não uma cópia
    dele. O logger vai injetado porque é o NOME dele que separa extrato de fatura
    no log (o prefixo "[import]" é o mesmo nos dois).

    `_get_client()` roda AQUI, fora do runner, de propósito: ele levanta
    HTTPException própria quando falta a chave, e lá dentro o `except Exception`
    final trocaria "GEMINI_IMPORT_API_KEY não configurada" pela mensagem
    genérica. Também é o que mantém UMA chamada a `_get_client` por `_gerar`.
    """
    client = _get_client()

    def _chamada():
        return client.models.generate_content(
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
                # Terceiro default de provedor explicitado (depois de safety e
                # thinking): não usamos tools, então isto é inócuo hoje — o
                # ponto é não herdar em silêncio. Ver o docstring de lá.
                automatic_function_calling=AFC_DESLIGADO,
            ),
        )

    return gerar_com_retry(_chamada, logger=logger, mensagens=_MENSAGENS)


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
