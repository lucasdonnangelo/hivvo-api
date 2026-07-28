"""Redação best-effort de PII antes de enviar ao modelo.

É rede, não garantia — o input já deve vir anonimizado. Cobre:
- CPF (formatado e 11 dígitos corridos) -> [CPF]
- Nomes passados via --redact -> [TITULAR]

Ao contrário do spike da fatura, NÃO pseudonimiza final de cartão: o eixo do
extrato é a classificação em baldes, não o portador. O risco de PII próprio do
extrato é o NOME DE CONTRAPARTE em PIX/TED ("Pix enviado - FULANO") — que é
também sinal de classificação; cubra-o com --redact "Fulano" no PDF de teste.
Se um pagamento_fatura citar "Nubank"/"Itaú", isso é banco (fica em
cartao_citado), não PII — não é redigido.
"""

from __future__ import annotations

import re
from typing import Sequence

CPF_FORMATADO = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
CPF_CORRIDO = re.compile(r"(?<!\d)\d{11}(?!\d)")


def redigir(texto: str, nomes: Sequence[str]) -> str:
    texto = CPF_FORMATADO.sub("[CPF]", texto)
    texto = CPF_CORRIDO.sub("[CPF]", texto)
    for nome in nomes:
        nome = nome.strip()
        if nome:
            texto = re.sub(re.escape(nome), "[TITULAR]", texto, flags=re.IGNORECASE)
    return texto
