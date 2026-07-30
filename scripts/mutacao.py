#!/usr/bin/env python3
"""
mutacao.py — verificação por MUTAÇÃO: quebra a regra no código e exige que o teste caia.

Um teste que continua verde depois de a regra sumir do código não está provando
a regra. A técnica costuma ser vendida como caça a código errado; **no hivvo ela
tem pego, com mais frequência, TESTE QUE NÃO TESTA** — e é para isso que vale
ter a ferramenta no repo em vez de reinventá-la a cada batch:

  - Batch do estorno: um `getattr` no teste engolia o `AttributeError` e o
    assert nunca rodava.
  - Batch da auto-categoria de fatura: DUAS de cinco mutações sobreviveram.
    (a) o filtro de TIPO da camada 1 — `validar_nome_categoria` já barrava o
        caso do teste sozinho, então o teste passava sem o filtro;
    (b) o join por índice explícito — a fixture tinha as linhas não-materializáveis
        no FIM, então posição e índice coincidiam e a mutação era invisível.
    Nos dois casos o conserto foi no TESTE, não no harness.

Uso:
    python scripts/mutacao.py scripts/mutacoes/auto_categoria_fatura.json
    python scripts/mutacao.py <spec.json> --pytest venv/Scripts/python.exe

Formato do spec (lista de objetos):
    {
      "titulo": "camada 1 aprende de 'Outros'",
      "arquivo": "app/services/import_fatura/enriquecimento.py",
      "de":  "<trecho EXATO, com indentação>",
      "para": "<substituto; \"\" apaga>",
      "teste": "tests/routers/test_x.py::test_y"
    }

Garantias: só a PRIMEIRA ocorrência é trocada; o arquivo é restaurado sempre
(inclusive em Ctrl-C ou erro); trecho não encontrado é FALHA ruidosa, nunca
silenciosa (foi assim que um `não`/`nao` de acento apareceu em vez de virar um
"tudo verde" mentiroso). Sai 1 se qualquer mutação SOBREVIVER.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _rodar_teste(python: str, teste: str) -> tuple[int, list[str]]:
    proc = subprocess.run(
        [python, "-m", "pytest", teste, "-q", "--no-header", "-p", "no:warnings"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    interessantes = [
        linha
        for linha in proc.stdout.splitlines()
        if linha.startswith("E ") or linha.lstrip().startswith(("assert", ">"))
        or " passed" in linha or " failed" in linha or " error" in linha
    ]
    return proc.returncode, interessantes


def verificar(spec: list[dict], python: str) -> int:
    sobreviventes: list[str] = []

    for mutacao in spec:
        titulo = mutacao["titulo"]
        arquivo = RAIZ / mutacao["arquivo"]
        teste = mutacao["teste"]

        print(f"\n{'=' * 74}")
        print(f"MUTAÇÃO: {titulo}")
        print(f"  arquivo: {mutacao['arquivo']}")
        print(f"  alvo   : {teste}")
        print("=" * 74)

        original = arquivo.read_text(encoding="utf-8")
        if mutacao["de"] not in original:
            print("  *** SPEC QUEBRADO: trecho não encontrado no arquivo ***")
            print("  (o código mudou? a indentação/acento do spec confere?)")
            sobreviventes.append(titulo)
            continue

        rc_antes, _ = _rodar_teste(python, teste)
        if rc_antes != 0:
            print("  *** o teste JÁ ESTÁ VERMELHO antes da mutação — spec inútil ***")
            sobreviventes.append(titulo)
            continue

        arquivo.write_text(
            original.replace(mutacao["de"], mutacao["para"], 1), encoding="utf-8"
        )
        try:
            rc_depois, saida = _rodar_teste(python, teste)
        finally:
            arquivo.write_text(original, encoding="utf-8")

        if rc_depois == 0:
            print("  antes: PASSOU · com a mutação: PASSOU")
            print("  *** SOBREVIVEU — o teste não está provando esta regra ***")
            sobreviventes.append(titulo)
        else:
            print("  antes: PASSOU · com a mutação: FALHOU  → a mutação MATA o teste")
            for linha in saida:
                print(f"    | {linha}")

    print(f"\n{'=' * 74}")
    if sobreviventes:
        print(f"{len(sobreviventes)}/{len(spec)} SOBREVIVERAM:")
        for titulo in sobreviventes:
            print(f"  - {titulo}")
        return 1
    print(f"{len(spec)}/{len(spec)} mortas — toda regra do spec tem teste que a prova.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("spec", type=Path, help="JSON com a lista de mutações")
    parser.add_argument(
        "--python",
        default=str(RAIZ / "venv" / "Scripts" / "python.exe"),
        help="interpretador que roda o pytest (default: venv do projeto)",
    )
    args = parser.parse_args()

    if not Path(args.python).exists():
        args.python = sys.executable

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    return verificar(spec, args.python)


if __name__ == "__main__":
    raise SystemExit(main())
