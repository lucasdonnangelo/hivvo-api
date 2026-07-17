"""Extração determinística da camada de texto do PDF (sem OCR).

Tudo em memória (BytesIO) — o arquivo nunca é gravado em disco.
PDF escaneado/imagem (sem camada de texto) é detectado pelo chamador via
`tem_camada_de_texto`; OCR está fora de escopo por design.
"""

from __future__ import annotations

import io
import logging

import pdfplumber

# O pdfminer (motor do pdfplumber) loga o CONTEÚDO do PDF token a token em
# DEBUG — vazaria a fatura inteira se o nível global baixasse. O texto da
# fatura nunca vai para log: trava em WARNING independente da config global.
logging.getLogger("pdfminer").setLevel(logging.WARNING)

# Abaixo disso, o PDF quase certamente é escaneado/imagem (sem camada de
# texto). Limiar validado no spike.
MIN_CHARS_TEXTO = 200


class PaginasDemaisError(Exception):
    """PDF excede o limite de páginas — checado ANTES de extrair o texto."""

    def __init__(self, paginas: int) -> None:
        self.paginas = paginas
        super().__init__(f"PDF com {paginas} páginas")


def extrair_texto(dados: bytes, max_paginas: int) -> tuple[str, int]:
    """Concatena o texto de todas as páginas; devolve (texto, nº de páginas).

    layout=True preserva o alinhamento colunar (data | descrição | valor),
    que ajuda o LLM a manter as linhas íntegras.
    """
    partes: list[str] = []
    with pdfplumber.open(io.BytesIO(dados)) as pdf:
        paginas = len(pdf.pages)
        if paginas > max_paginas:
            raise PaginasDemaisError(paginas)
        for pagina in pdf.pages:
            partes.append(pagina.extract_text(layout=True) or "")
    return "\n".join(partes).strip(), paginas


def tem_camada_de_texto(texto: str) -> bool:
    return len(texto) >= MIN_CHARS_TEXTO
