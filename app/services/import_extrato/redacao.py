"""Redação best-effort de PII antes de enviar o extrato ao modelo.

É rede, NÃO garantia — alinhamento de expectativa, igual à redação da fatura.
Diferença de eixo: o extrato classifica em BALDES, não tem portador de cartão a
pseudonimizar — então a assinatura é mais simples (devolve só o texto, sem mapa
reverso) e NÃO há `restaurar_*`.

O que é redigido (ACHADO 2 — PII de terceiros, além do titular):
- CPF (formatado e 11 dígitos corridos) -> [CPF]. O MESMO regex cobre o CPF do
  TITULAR e o de CONTRAPARTES (Pix/TED) — nada disso é preciso para classificar.
- Agência e conta (por CONTEXTO: "Ag: 1234", "Conta corrente 000123456",
  "C/C 12345-6") -> [AGENCIA]/[CONTA]. Cobre as do titular e as de contraparte.
- Nome(s) do titular (nome_completo/username) -> [TITULAR], best-effort.

Resíduo DOCUMENTADO (não coberto, por design): o NOME de contraparte em Pix/TED
("Pix enviado - FULANO DE TAL") é sinal de classificação e é frágil de casar por
regex — não temos a string do terceiro para redigir (só a do titular). Vai como
está para o Gemini (chave dedicada, tier pago, que não treina com os dados).
Nada disso é necessário para classificar em balde. Não invista em fazer o nome de
contraparte "funcionar".
"""

from __future__ import annotations

import re
from typing import Sequence

# Os padrões moram em core/scrub.py desde o #39: eram DUPLICADOS aqui e na
# redação da fatura, e os hooks do Sentry passaram a ser um terceiro consumidor.
# O buraco do CPF mascarado (#35) fecha lá, uma vez, para os três.
from app.core.scrub import AGENCIA, CONTA, CPF_CORRIDO, CPF_FORMATADO


def redigir(texto: str, nomes: Sequence[str]) -> str:
    """Devolve o texto redigido (best-effort). Sem mapa reverso: o extrato não
    pseudonimiza portador (ao contrário da fatura)."""
    texto = CPF_FORMATADO.sub("[CPF]", texto)
    texto = CPF_CORRIDO.sub("[CPF]", texto)

    texto = AGENCIA.sub(r"\1\2[AGENCIA]", texto)
    texto = CONTA.sub(r"\1\2[CONTA]", texto)

    for nome in nomes:
        nome = nome.strip()
        if nome:
            texto = re.sub(re.escape(nome), "[TITULAR]", texto, flags=re.IGNORECASE)
    return texto
