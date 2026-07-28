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

CPF_FORMATADO = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
CPF_CORRIDO = re.compile(r"(?<!\d)\d{11}(?!\d)")

# Agência/conta por CONTEXTO (o rótulo impresso) — nunca por "qualquer número",
# que pegaria valores e datas. O separador entre rótulo e número admite só
# espaço/ponto/dois-pontos, então "Pagamento de conta de luz 50,00" NÃO casa
# (há letras entre "conta" e o número). Só o número é substituído; o rótulo
# permanece (o Gemini ainda vê que a linha é uma transferência).
AGENCIA = re.compile(
    r"(ag[êe]ncia|\bag)(\.?\s*:?\s*)(\d{3,6}(?:-?\d)?)", re.IGNORECASE
)
CONTA = re.compile(
    r"(conta(?:\s+corrente)?|\bc/?c\b)(\.?\s*:?\s*)(\d{3,}(?:-?\d)?)", re.IGNORECASE
)


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
