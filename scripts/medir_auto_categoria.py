#!/usr/bin/env python3
"""
medir_auto_categoria.py — cobertura da CAMADA 2 da auto-categoria sobre faturas reais.

A suíte prova que o código faz o que diz; ISTO prova que o que ele diz é útil.
Um matcher que jogasse tudo em "Alimentação" passaria em todo teste de unidade
e marcaria 100% de cobertura — por isso o relatório mostra a distribuição por
categoria e a lista dos que caíram fora, não só a porcentagem.

Roda o código de PRODUÇÃO (`app.services.categorias.casar_categoria_detalhado`)
com HISTÓRICO VAZIO — a primeira importação, quando a camada 1 ainda não tem o
que dizer e a camada 2 é tudo que existe. Sem Gemini, sem banco.

Instrumento de:
  - toda mexida na tabela de regras (`KEYWORDS_*` / `ADQUIRENTES`);
  - #40 (o rótulo do banco entrando ou não na descrição muda o número);
  - #42 (generalizar a camada 1 para token de lojista).

    python scripts/medir_auto_categoria.py scripts/spike_import/out/*.json
    python scripts/medir_auto_categoria.py --detalhe fatura.json

As faturas de entrada são o JSON de `FaturaExtraida` (o que o preview devolve
em `fatura`). Os dumps de `scripts/spike_import/out/` são GITIGNORED e devem
continuar sendo — são a fatura de uma pessoa. Para regressão em CI, sem dado
real, ver `tests/services/test_categorias_regras.py` + o corpus sintético em
`tests/fixtures/faturas_sinteticas.py`.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.services.categorias as categorias  # noqa: E402
from app.services.categorias import (  # noqa: E402
    CATEGORIAS_PADRAO,
    KEYWORDS_REDES,
    casar_categoria_detalhado,
)

NOMES_DESPESA = [c.nome for c in CATEGORIAS_PADRAO if c.tipo == "despesa"]


def linhas_materializaveis(caminho: Path) -> list[dict]:
    """As linhas que VIRAM lançamento — as únicas que têm categoria.

    Mesmo recorte de `import_fatura.enriquecimento.indices_materializaveis`:
    compra/iof com valor != 0 (o estorno entra; ele leva categoria).
    """
    fatura = json.loads(caminho.read_text(encoding="utf-8"))
    if "transacoes" not in fatura:
        raise ValueError(f"{caminho.name}: não parece um FaturaExtraida (sem 'transacoes')")
    return [
        t
        for t in fatura["transacoes"]
        if t.get("tipo") in ("compra", "iof") and Decimal(t["valor_brl"]) != 0
    ]


def _medir(linhas: list[dict]) -> list[tuple[dict, str, str | None]]:
    return [(t, *casar_categoria_detalhado(t["descricao"], NOMES_DESPESA)) for t in linhas]


def _sem_redes():
    """Desliga as REDES NOMEADAS para separar o que é portátil do que é marca.

    A diferença entre os dois números é o quanto da cobertura depende de uma
    lista de marcas brasileiras que só cresce (manutenção) — informação que a
    porcentagem sozinha esconde.
    """
    guardadas = categorias._KEYWORDS
    redes = {(categorias._normalizar(k), a) for k, a in KEYWORDS_REDES}
    categorias._KEYWORDS = [par for par in guardadas if par not in redes]
    return guardadas


def relatar(caminho: Path, detalhe: bool) -> None:
    linhas = linhas_materializaveis(caminho)
    if not linhas:
        print(f"{caminho.name}: nenhuma linha materializável")
        return

    guardadas = _sem_redes()
    genericas = _medir(linhas)
    categorias._KEYWORDS = guardadas
    completo = _medir(linhas)

    def cobertura(resultado):
        n = sum(1 for _, _, passe in resultado if passe is not None)
        return n, 100.0 * n / len(linhas)

    ng, pg = cobertura(genericas)
    nc, pc = cobertura(completo)

    print(f"\n{'=' * 74}")
    print(f"{caminho.name}  —  {len(linhas)} linhas materializáveis")
    print(f"{'=' * 74}")
    print(f"  só regras genéricas : {ng:>4}/{len(linhas)} = {pg:5.1f}%")
    print(f"  genéricas + redes   : {nc:>4}/{len(linhas)} = {pc:5.1f}%")

    if not detalhe:
        return

    # PRECISÃO, não só recall: a distribuição é o que denuncia um matcher que
    # está só empurrando tudo para o balde mais populoso da tabela.
    print(f"\n  --- distribuição por categoria ({nc} sugeridas) ---")
    por_categoria = defaultdict(list)
    for t, categoria, passe in completo:
        if passe:
            por_categoria[categoria].append((t["descricao"], passe))
    for categoria in sorted(por_categoria, key=lambda c: -len(por_categoria[c])):
        itens = por_categoria[categoria]
        print(f"\n  ### {categoria}  ({len(itens)})")
        for descricao, passe in sorted(itens):
            print(f"      {descricao:26} {passe}")

    fora = [t for t, _, passe in completo if passe is None]
    print(f"\n  --- sem sugestão ({len(fora)}) ---")
    for t in fora:
        print(f"      R$ {t['valor_brl']:>9}  {t['descricao']}")

    print("\n  --- por regra ---")
    for etiqueta, n in Counter(p for _, _, p in completo if p).most_common():
        print(f"      {n:>3}x  {etiqueta}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("faturas", nargs="+", type=Path, help="JSON(s) de FaturaExtraida")
    parser.add_argument(
        "--detalhe",
        action="store_true",
        help="lista as linhas agrupadas por categoria atribuída e as que ficaram fora",
    )
    args = parser.parse_args()

    erros = 0
    for caminho in args.faturas:
        try:
            relatar(caminho, args.detalhe)
        except (OSError, ValueError, KeyError) as e:
            print(f"{caminho}: {e.__class__.__name__}: {e}", file=sys.stderr)
            erros += 1
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
