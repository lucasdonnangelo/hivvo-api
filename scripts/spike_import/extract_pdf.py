"""Extração determinística da camada de texto do PDF (sem OCR)."""

from __future__ import annotations

from pathlib import Path

import pdfplumber

# Abaixo disso, o PDF quase certamente é escaneado/imagem (sem camada de
# texto). OCR está fora de escopo: reporta e pula.
MIN_CHARS_TEXTO = 200


def extrair_texto(caminho: Path) -> str:
    """Concatena o texto de todas as páginas, preservando o layout colunar
    (layout=True ajuda o LLM a manter data | descrição | valor alinhados)."""
    partes: list[str] = []
    with pdfplumber.open(caminho) as pdf:
        for pagina in pdf.pages:
            partes.append(pagina.extract_text(layout=True) or "")
    return "\n".join(partes).strip()


def tem_camada_de_texto(texto: str) -> bool:
    return len(texto) >= MIN_CHARS_TEXTO
