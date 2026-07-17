"""Redação best-effort de PII antes de enviar ao modelo.

É rede, NÃO garantia — alinhamento de expectativa (decisão de Política de
17/07): apenas CPF e finais de cartão são confiáveis aqui. O NOME do titular
é sabidamente frágil (o spike provou: o nome cadastrado difere do nome legal
impresso na fatura, e layout=True pode grudar tokens) e o ENDEREÇO não é
redigido — ambos vão como estão para o Gemini (chave dedicada, tier pago,
que não treina com os dados). Não invista em fazer o nome "funcionar".

- CPF (formatado e 11 dígitos corridos) -> [CPF]
- Nomes do usuário (nome_completo/username) -> [TITULAR], best-effort
- Finais de cartão: PSEUDONIMIZADOS com mapa reversível (não redigidos),
  porque o sinal multi-portador faz parte do dado extraído. O Gemini vê
  '0001'/'0002'; `restaurar_finais` desfaz o mapa localmente na resposta.
"""

from __future__ import annotations

import re
from typing import Sequence

from app.schemas.import_fatura import FaturaExtraida

CPF_FORMATADO = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
CPF_CORRIDO = re.compile(r"(?<!\d)\d{11}(?!\d)")

# Finais são detectados por CONTEXTO (como as faturas os imprimem:
# "final 6042", "•••• 6042", "**** 6042", "xxxx 6042") — nunca por
# "qualquer 4 dígitos", que pegaria anos e valores.
PADRAO_FINAL_COM_CONTEXTO = re.compile(
    r"(?:final\s+|•+\s*|\*{2,}\s*|x{4}\s*)(\d{4})", re.IGNORECASE
)


def _boundary(final: str) -> re.Pattern[str]:
    # Sem dígito, ponto ou vírgula colados: evita corromper um "6042"
    # dentro de "6.042,00", de um ano ou de um número maior.
    return re.compile(rf"(?<![\d.,]){re.escape(final)}(?![\d.,])")


def redigir(texto: str, nomes: Sequence[str]) -> tuple[str, dict[str, str]]:
    """Devolve (texto_redigido, mapa_reverso pseudo -> final_real)."""
    texto = CPF_FORMATADO.sub("[CPF]", texto)
    texto = CPF_CORRIDO.sub("[CPF]", texto)

    for nome in nomes:
        nome = nome.strip()
        if nome:
            texto = re.sub(re.escape(nome), "[TITULAR]", texto, flags=re.IGNORECASE)

    finais = list(dict.fromkeys(PADRAO_FINAL_COM_CONTEXTO.findall(texto)))
    mapa_reverso: dict[str, str] = {}
    for i, final in enumerate(finais, start=1):
        pseudo = f"{i:04d}"
        texto = _boundary(final).sub(pseudo, texto)
        mapa_reverso[pseudo] = final
    return texto, mapa_reverso


def restaurar_finais(fatura: FaturaExtraida, mapa_reverso: dict[str, str]) -> None:
    """Desfaz a pseudonimização na resposta validada (in place)."""
    if not mapa_reverso:
        return
    for t in fatura.transacoes:
        if t.portador_final in mapa_reverso:
            t.portador_final = mapa_reverso[t.portador_final]
        for pseudo, final in mapa_reverso.items():
            t.descricao = _boundary(pseudo).sub(final, t.descricao)
