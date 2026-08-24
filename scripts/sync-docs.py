#!/usr/bin/env python3
"""
sync-docs.py — Copia os docs COMPARTILHADOS de hivvo-api/docs → hivvo-web/docs.

O hivvo-api é a FONTE ÚNICA dos docs compartilhados. Edite sempre aqui e rode
este script; nunca copie à mão (foi a cópia manual que fez os docs divergirem).
Docs específicos de repo NÃO são tocados — ver docs/README.md.

Uso:
    python scripts/sync-docs.py            # sincroniza
    python scripts/sync-docs.py --check    # não escreve; sai 1 se algo divergir
    python scripts/sync-docs.py --dest ../outro-web/docs

Destino: --dest > $HIVVO_WEB_DOCS > ../hivvo-web/docs (repos irmãos).
"""

import argparse
import filecmp
import os
import shutil
import sys
from pathlib import Path

# O console do Windows abre em cp1252, que não encoda nem "→" nem acento: sem
# isto, o script morre de UnicodeEncodeError ao imprimir o resumo.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Script vive em scripts/ — a pasta docs/ canônica está um nível acima
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "docs"

# Os docs compartilhados: existem nos dois repos e devem ser idênticos.
# Canônicos aqui (hivvo-api). Para adicionar/remover um, edite ESTA lista —
# ela é a definição do que é compartilhado.
SHARED = [
    "DECISAO_A_PAGAR_SALDO.md",
    "ENGINEERING.md",
    "Hivvo_Referencia.md",
    "PLANO_3D_PAGAMENTO_FATURA.md",
    "PLANO_DASHBOARD_DOIS_BLOCOS.md",
    "PLANO_IMPORTACAO.md",
    "PLANO_PERFIL_CONFIG.md",
    "PLANO_PROJECAO.md",
    "PLANO_RESUMO.md",
]

# Saíram desta lista em 24/08/2026: ESTADO_HIVVO_HANDOFF.md e
# PENDENCIAS_PRIORIZADAS.md. Não viraram específicos de repo — saíram dos DOIS
# repos de código e passaram a viver só no repo privado de documentação, junto
# com as auditorias, os diários de sessão e os planos de execução. São docs
# operacionais: descrevem um sistema em produção, e por isso não acompanham o
# código quando ele vai a público.
#
# O .gitignore dos dois repos lista os mesmos caminhos. As duas coisas são o
# MESMO passo, e a ordem importa: se esta lista voltar a citar um doc que o
# .gitignore bloqueia, o sync recria o arquivo no destino e o Git o esconde do
# `git status` — divergência que não aparece em lugar nenhum.


def resolve_dest(cli_dest: str | None) -> Path:
    if cli_dest:
        return Path(cli_dest).expanduser().resolve()
    env_dest = os.environ.get("HIVVO_WEB_DOCS")
    if env_dest:
        return Path(env_dest).expanduser().resolve()
    return (PROJECT_ROOT.parent / "hivvo-web" / "docs").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--check",
        action="store_true",
        help="não escreve nada; sai com 1 se algum compartilhado divergir",
    )
    parser.add_argument("--dest", help="pasta docs/ do hivvo-web")
    args = parser.parse_args()

    dest_dir = resolve_dest(args.dest)
    if not dest_dir.is_dir():
        print(f"ERRO: destino não existe: {dest_dir}", file=sys.stderr)
        print("Passe --dest ou defina HIVVO_WEB_DOCS.", file=sys.stderr)
        return 2

    # Fonte incompleta é erro de configuração, não algo a sincronizar por cima.
    faltando = [nome for nome in SHARED if not (SOURCE_DIR / nome).is_file()]
    if faltando:
        print(f"ERRO: não existe(m) em {SOURCE_DIR}: {', '.join(faltando)}", file=sys.stderr)
        return 2

    divergentes: list[str] = []
    iguais = 0

    for nome in SHARED:
        origem = SOURCE_DIR / nome
        destino = dest_dir / nome

        # shallow=False compara conteúdo, não (tamanho, mtime): o mtime mente
        # quando uma cópia manual sobrescreve um arquivo com a versão velha.
        if destino.is_file() and filecmp.cmp(origem, destino, shallow=False):
            iguais += 1
            continue

        divergentes.append(nome)
        if not args.check:
            # copyfile = cópia binária exata. Não traduzir fim-de-linha: os dois
            # repos usam core.autocrlf=true (CRLF em disco, LF no blob do git).
            shutil.copyfile(origem, destino)

    if args.check:
        if divergentes:
            print(f"DIVERGEM ({len(divergentes)}):")
            for nome in divergentes:
                print(f"  - {nome}")
            print("\nRode: python scripts/sync-docs.py")
            return 1
        print(f"OK: os {len(SHARED)} docs compartilhados estão sincronizados.")
        return 0

    for nome in divergentes:
        print(f"  copiado: {nome}")
    print(f"\n{len(divergentes)} copiado(s), {iguais} ja igual(is) -> {dest_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
