"""Chamada ao Gemini: texto redigido do extrato -> JSON no schema ExtratoExtraido.

Usa EXCLUSIVAMENTE a env var GEMINI_SPIKE_API_KEY — nunca a GEMINI_API_KEY de
produção. Structured output (response_schema) força o shape; o prompt carrega a
semântica da classificação em baldes.
"""

from __future__ import annotations

import os
import sys

from google import genai
from google.genai import types

from schema import ExtratoExtraido

ENV_KEY = "GEMINI_SPIKE_API_KEY"
MODELO_DEFAULT = "gemini-2.5-flash"

PROMPT_REGRAS = """\
Você recebe o texto extraído de um EXTRATO DE CONTA bancária brasileira (conta
corrente / conta de pagamento — NÃO é fatura de cartão de crédito). Devolva
APENAS o JSON no schema fornecido, com TODAS as movimentações impressas.

Classifique CADA linha em exatamente um `balde`:

- "receita": dinheiro que ENTRA na conta — salário/proventos, "Transferência
  recebida", "Pix recebido de ...", depósito, rendimento/juros da conta,
  estorno/reembolso/devolução recebido na conta.

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

`valor`: sempre a MAGNITUDE positiva (sem sinal), string decimal com PONTO
decimal e SEM separador de milhar (ex.: "1234.56"). A direção vem do balde.

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


def obter_api_key() -> str:
    key = os.environ.get(ENV_KEY)
    if not key:
        sys.exit(
            f"ERRO: a env var {ENV_KEY} não está definida.\n"
            f"Este spike usa uma chave PRÓPRIA — NUNCA use a GEMINI_API_KEY de produção.\n"
            f'Defina antes de rodar:  $env:{ENV_KEY} = "sua-chave-do-spike"'
        )
    return key


def extrair_extrato(texto: str, modelo: str, api_key: str) -> str:
    """Devolve o JSON CRU (texto) da resposta — a validação Pydantic é do
    chamador, que precisa do cru para salvar em .raw.json quando o schema
    rejeitar."""
    client = genai.Client(api_key=api_key)
    resposta = client.models.generate_content(
        model=modelo,
        contents=PROMPT_REGRAS + texto,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=ExtratoExtraido,
        ),
    )
    return resposta.text or ""
