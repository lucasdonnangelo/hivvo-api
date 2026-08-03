"""Padrões de PII e redação best-effort — FONTE ÚNICA dos regexes (#39).

Dois consumidores, com propósitos DIFERENTES, e a diferença importa:

  1. **Boundary de importação** (`services/import_*/redacao.py`) — redige ANTES
     de mandar o texto ao Gemini. É o controle primário daquele caminho.
  2. **Hooks do Sentry** (`core/observability.py`) — redige o que já está numa
     string de log a caminho de fora. É DEFESA EM PROFUNDIDADE, não o controle:
     o controle é não pôr conteúdo em log (ver a auditoria no #39).

Os regexes nasceram duplicados entre `import_fatura/redacao.py` e
`import_extrato/redacao.py` (idênticos, usados identicamente). Ficam aqui para
que o buraco conhecido do CPF MASCARADO (#35 — `***.456.789-**` não casa nenhum
dos dois padrões) tenha UM lugar para ser fechado, servindo aos três consumidores
de uma vez.

`EMAIL` é usado SÓ pelos hooks do Sentry, de propósito: pô-lo em `redigir()`
mudaria o texto que chega ao Gemini — mudança de comportamento num boundary que
não é o que o #39 trata.

--- LIMITE, declarado ---

Isto casa FORMATO, não semântica. Texto livre — descrição de lojista, nome de
contraparte de Pix/TED — não tem forma para casar e passa inteiro. É por isso
que a redação aqui não substitui manter conteúdo fora do log.
"""

from __future__ import annotations

import re

CPF_FORMATADO = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
CPF_CORRIDO = re.compile(r"(?<!\d)\d{11}(?!\d)")

# Agência/conta por CONTEXTO (o rótulo impresso) — nunca por "qualquer número",
# que pegaria valores e datas. O separador entre rótulo e número admite só
# espaço/ponto/dois-pontos, então "Pagamento de conta de luz 50,00" NÃO casa
# (há letras entre "conta" e o número). Só o número é substituído; o rótulo
# permanece (quem lê ainda vê que a linha é uma transferência).
AGENCIA = re.compile(r"(ag[êe]ncia|\bag)(\.?\s*:?\s*)(\d{3,6}(?:-?\d)?)", re.IGNORECASE)
CONTA = re.compile(
    r"(conta(?:\s+corrente)?|\bc/?c\b)(\.?\s*:?\s*)(\d{3,}(?:-?\d)?)", re.IGNORECASE
)

# Só os hooks do Sentry usam (ver docstring). O caso que motivou: o erro do
# Resend em auth.py ecoa o endereço do destinatário, e ele vem no COMEÇO da
# mensagem — truncar não alcança, só o padrão alcança.
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Teto de texto de terceiro em log. Mesmo valor e mesmo marcador que o #38 já
# aplicava à mensagem da API da Gemini (MAX_MSG_API), agora disponível para os
# sinks que ficaram de fora daquele lote (ai.py, auth.py).
MAX_TEXTO_LOG = 200
MARCA_TRUNCADO = "…[truncado]"


def curto(texto: object, limite: int = MAX_TEXTO_LOG) -> str:
    """Corta texto de terceiro em `limite`, marcando o corte.

    A marca não é enfeite: sem ela o leitor do log confunde truncamento nosso
    com mensagem curta da API.
    """
    s = "" if texto is None else str(texto)
    return s if len(s) <= limite else s[:limite] + MARCA_TRUNCADO


def redigir_pii(texto: str) -> str:
    """Redige as PII de FORMA CONHECIDA de uma string qualquer (best-effort).

    Sem `nomes`: no ponto em que os hooks do Sentry rodam não há usuário em
    contexto para pseudonimizar o titular — ao contrário do boundary, que tem.

    Ordem importa: EMAIL primeiro, senão `CPF_CORRIDO` pode comer 11 dígitos de
    dentro de um endereço e quebrar o casamento do e-mail inteiro.
    """
    texto = EMAIL.sub("[EMAIL]", texto)
    texto = CPF_FORMATADO.sub("[CPF]", texto)
    texto = CPF_CORRIDO.sub("[CPF]", texto)
    texto = AGENCIA.sub(r"\1\2[AGENCIA]", texto)
    texto = CONTA.sub(r"\1\2[CONTA]", texto)
    return texto
