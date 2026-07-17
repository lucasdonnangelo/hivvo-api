"""Spike de validação: fatura PDF -> texto -> Gemini -> JSON -> reconciliação.

Standalone e descartável. NÃO importa nada de app/, não conecta em banco,
não lê o .env do projeto. Ver README.md para setup e uso.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from extract_pdf import extrair_texto, tem_camada_de_texto
from llm import MODELO_DEFAULT, extrair_fatura, obter_api_key
from reconcile import Reconciliacao, reconciliar
from redact import redigir, restaurar_finais
from schema import FaturaExtraida, TipoTransacao


def brl(v: Decimal) -> str:
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass
class Resultado:
    pdf: str
    status: str  # "BATE" | "NAO BATE" | "SEM TEXTO" | "SCHEMA INVALIDO" | "ERRO API"
    detalhe: str = ""


def montar_relatorio(nome: str, fatura: FaturaExtraida, rec: Reconciliacao) -> str:
    contagem = {t: 0 for t in TipoTransacao}
    for tr in fatura.transacoes:
        contagem[tr.tipo] += 1
    partes_contagem = ", ".join(
        f"{n} {tipo.value}" for tipo, n in contagem.items() if n
    )

    linhas = [
        f"=== {nome} ===",
        f"Banco: {fatura.banco} | Competência: "
        f"{fatura.competencia.mes:02d}/{fatura.competencia.ano}"
        + (f" | Vencimento: {fatura.vencimento}" if fatura.vencimento else ""),
        f"{len(fatura.transacoes)} transações ({partes_contagem})",
        f"ancora (compras+IOF declarados): {brl(rec.ancora)}",
        f"soma_gastos (linhas compra+iof): {brl(rec.soma_gastos)}",
        f"diferenca:                       {brl(rec.diferenca)}  ->  "
        + ("BATE" if rec.bate else "NAO BATE"),
        f"secundário (gastos {brl(rec.soma_gastos)} + excluidos {brl(rec.excluidos)} "
        f"vs a pagar {brl(rec.total_a_pagar)}): diferenca "
        f"{brl(rec.diferenca_secundaria)}  ->  "
        + ("BATE" if rec.bate_secundario else "NAO BATE"),
    ]
    return "\n".join(linhas)


def processar_pdf(
    pdf: Path, args: argparse.Namespace, api_key: str, out_dir: Path
) -> Resultado:
    texto = extrair_texto(pdf)
    if not tem_camada_de_texto(texto):
        print(
            f"\n=== {pdf.name} ===\n"
            f"SEM camada de texto extraível ({len(texto)} chars) — "
            f"provável PDF escaneado. OCR está fora de escopo; pulando."
        )
        return Resultado(pdf.name, "SEM TEXTO")

    texto_redigido, mapa_reverso = redigir(texto, args.redact)

    try:
        raw = extrair_fatura(texto_redigido, args.model, api_key)
    except Exception as e:  # erro de API não derruba o run das outras faturas
        print(f"\n=== {pdf.name} ===\nERRO na chamada ao Gemini: {e}")
        return Resultado(pdf.name, "ERRO API", str(e))

    try:
        fatura = FaturaExtraida.model_validate_json(raw)
    except ValidationError as e:
        # salva o cru ANTES de reportar — o caso que falhou é dado de debug
        raw_path = out_dir / f"{pdf.stem}.raw.json"
        raw_path.write_text(raw, encoding="utf-8")
        print(
            f"\n=== {pdf.name} ===\n"
            f"Resposta REJEITADA pelo schema Pydantic. "
            f"Resposta crua salva em {raw_path}\n{e}"
        )
        return Resultado(pdf.name, "SCHEMA INVALIDO", f"cru em {raw_path.name}")

    restaurar_finais(fatura, mapa_reverso)
    rec = reconciliar(fatura, Decimal(args.tolerancia))

    saida = {
        "fatura": fatura.model_dump(),
        "reconciliacao": {
            "ancora_compras_mais_iof_declarados": str(rec.ancora),
            "soma_gastos": str(rec.soma_gastos),
            "excluidos": str(rec.excluidos),
            "total_a_pagar_declarado": str(rec.total_a_pagar),
            "diferenca": str(rec.diferenca),
            "bate": rec.bate,
            "diferenca_secundaria": str(rec.diferenca_secundaria),
            "bate_secundario": rec.bate_secundario,
        },
    }
    json_legivel = json.dumps(saida, ensure_ascii=False, indent=2)
    relatorio = montar_relatorio(pdf.name, fatura, rec)

    (out_dir / f"{pdf.stem}.json").write_text(json_legivel, encoding="utf-8")
    (out_dir / f"{pdf.stem}.report.txt").write_text(relatorio, encoding="utf-8")

    print(f"\n{json_legivel}\n\n{relatorio}")
    return Resultado(
        pdf.name,
        "BATE" if rec.bate else "NAO BATE",
        f"dif {brl(rec.diferenca)}",
    )


def imprimir_agregado(resultados: list[Resultado]) -> None:
    print(f"\n{'=' * 60}\nRESULTADO AGREGADO ({len(resultados)} PDFs)\n")
    largura = max(len(r.pdf) for r in resultados)
    for r in resultados:
        detalhe = f" ({r.detalhe})" if r.detalhe else ""
        print(f"  {r.pdf.ljust(largura)}  {r.status}{detalhe}")

    reconciliadas = [r for r in resultados if r.status in ("BATE", "NAO BATE")]
    todas_batem = bool(reconciliadas) and all(r.status == "BATE" for r in reconciliadas)
    print(
        "\nRégua de sucesso do spike:\n"
        f"  1. Reconciliação bate em TODAS as faturas de teste: "
        + ("SIM" if todas_batem else "NAO")
        + "\n"
        "  2. Menos campos a corrigir do que digitar à mão: conferência MANUAL —\n"
        "     compare cada out/<pdf>.json com o PDF aberto do lado.\n"
        "Não é gate automático: é o critério de decisão (extração vence a digitação?)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Spike: extração de fatura de cartão (PDF) via Gemini + reconciliação."
    )
    parser.add_argument("pasta", type=Path, help="pasta com os PDFs de fatura")
    parser.add_argument("--model", default=MODELO_DEFAULT, help=f"modelo Gemini (default: {MODELO_DEFAULT})")
    parser.add_argument("--tolerancia", default="0.02", help="tolerância da reconciliação em R$ (default: 0.02)")
    parser.add_argument(
        "--redact",
        action="append",
        default=[],
        metavar="NOME",
        help="nome a redigir do texto antes do envio (repetível)",
    )
    parser.add_argument("--out", type=Path, default=None, help="pasta de saída (default: out/ ao lado do script)")
    args = parser.parse_args()

    # Console Windows pode estar em cp1252; força UTF-8 pra não quebrar em acento
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    api_key = obter_api_key()  # fail-fast ANTES de processar qualquer PDF

    if not args.pasta.is_dir():
        sys.exit(f"ERRO: {args.pasta} não é uma pasta.")
    pdfs = sorted(args.pasta.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"ERRO: nenhum .pdf em {args.pasta}.")

    out_dir = args.out or (Path(__file__).parent / "out")
    out_dir.mkdir(parents=True, exist_ok=True)

    resultados = [processar_pdf(pdf, args, api_key, out_dir) for pdf in pdfs]
    imprimir_agregado(resultados)


if __name__ == "__main__":
    main()
