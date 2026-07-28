"""Spike de validação: extrato de conta PDF -> texto -> Gemini -> JSON -> balance walk.

Standalone e descartável. NÃO importa nada de app/, não conecta em banco,
não lê o .env do projeto. Ver README.md para setup e uso.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from extract_pdf import extrair_texto, tem_camada_de_texto
from llm import MODELO_DEFAULT, extrair_extrato, obter_api_key
from reconcile import Reconciliacao, reconciliar
from redact import redigir
from schema import Balde, ExtratoExtraido


def brl(v: Decimal) -> str:
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


# Heurísticas SÓ de conferência (nunca classificam): puxam o olho do revisor
# para os dois sinais de design do extrato.
# 1) Linhas que talvez não caibam nos 3 baldes (candidatas a um 4º balde):
PADRAO_NAO_CONSUMO = re.compile(
    r"aplica\w*|resgate|reinvest\w*|\brdb\b|\bcdb\b|tesouro|"
    r"transfer\w+\s+entre\s+contas|conta[ -]?investimento|caixinha",
    re.IGNORECASE,
)
# 2) Reembolso/estorno recebido: mapeado a receita no spike, mas conceitualmente
#    abate consumo — decisão de produção a revisitar (ver README).
PADRAO_REEMBOLSO = re.compile(
    r"reembols\w*|estorn\w*|devolu\w*|cashback", re.IGNORECASE
)


@dataclass
class Resultado:
    pdf: str
    # "BATE" | "NAO BATE" | "SEM SALDOS" | "SEM TEXTO" | "SCHEMA INVALIDO" | "ERRO API"
    status: str
    detalhe: str = ""


def montar_relatorio(nome: str, extrato: ExtratoExtraido, rec: Reconciliacao) -> str:
    contagem = {b: 0 for b in Balde}
    for linha in extrato.linhas:
        contagem[linha.balde] += 1
    partes = ", ".join(f"{n} {b.value}" for b, n in contagem.items() if n)

    out = [
        f"=== {nome} ===",
        f"Banco: {extrato.banco}"
        + (
            f" | Período: {extrato.periodo.de} a {extrato.periodo.ate}"
            if extrato.periodo
            else ""
        ),
        f"{len(extrato.linhas)} linhas ({partes})",
    ]

    if rec.aplicavel:
        out += [
            "",
            "Balance walk:",
            f"  saldo_inicial:        {brl(rec.saldo_inicial)}",
            f"  + receitas:           {brl(rec.soma_receitas)}",
            f"  - debitos:            {brl(rec.soma_debitos)}",
            f"  - pagamentos_fatura:  {brl(rec.soma_pagamentos)}",
            f"  = saldo_final_calc:   {brl(rec.saldo_final_calc)}",
            f"    saldo_final_decl.:  {brl(rec.saldo_final_declarado)}",
            f"    diferenca:          {brl(rec.diferenca)}  ->  "
            + ("BATE" if rec.bate else "NAO BATE"),
        ]
    else:
        out += [
            "",
            "Balance walk: N/A (extrato sem saldo_inicial/saldo_final impressos)",
        ]

    pagamentos = [l for l in extrato.linhas if l.balde is Balde.pagamento_fatura]
    if pagamentos:
        out += ["", "Pagamentos de fatura (conferir cartão / valor / data):"]
        for l in pagamentos:
            cartao = l.cartao_citado or "(cartão não citado)"
            out.append(f"  {l.data}  {cartao.ljust(24)}  {brl(Decimal(l.valor))}")

    suspeitas = [l for l in extrato.linhas if PADRAO_NAO_CONSUMO.search(l.descricao)]
    if suspeitas:
        out += [
            "",
            "[!] Talvez NAO caibam nos 3 baldes (investimento / transferência própria "
            "-> precisa de 4o balde?):",
        ]
        for l in suspeitas:
            out.append(
                f"  {l.data}  [{l.balde.value}]  {brl(Decimal(l.valor))}  {l.descricao.strip()}"
            )

    reembolsos = [l for l in extrato.linhas if PADRAO_REEMBOLSO.search(l.descricao)]
    if reembolsos:
        out += [
            "",
            "[!] Reembolso/estorno recebido (mapeado a receita no spike -> decisão de "
            "produção a revisitar):",
        ]
        for l in reembolsos:
            out.append(
                f"  {l.data}  [{l.balde.value}]  {brl(Decimal(l.valor))}  {l.descricao.strip()}"
            )

    out += ["", "Todas as linhas (data | balde | valor | descrição):"]
    for l in extrato.linhas:
        out.append(
            f"  {l.data}  {l.balde.value.ljust(16)}  "
            f"{brl(Decimal(l.valor)).rjust(14)}  {l.descricao.strip()}"
        )

    return "\n".join(out)


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

    texto_redigido = redigir(texto, args.redact)

    try:
        raw = extrair_extrato(texto_redigido, args.model, api_key)
    except Exception as e:  # erro de API não derruba o run dos outros extratos
        print(f"\n=== {pdf.name} ===\nERRO na chamada ao Gemini: {e}")
        return Resultado(pdf.name, "ERRO API", str(e))

    try:
        extrato = ExtratoExtraido.model_validate_json(raw)
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

    rec = reconciliar(extrato, Decimal(args.tolerancia))

    saida = {
        "extrato": extrato.model_dump(),
        "reconciliacao": {
            "aplicavel": rec.aplicavel,
            "saldo_inicial": str(rec.saldo_inicial),
            "soma_receitas": str(rec.soma_receitas),
            "soma_debitos": str(rec.soma_debitos),
            "soma_pagamentos_fatura": str(rec.soma_pagamentos),
            "saldo_final_calc": str(rec.saldo_final_calc),
            "saldo_final_declarado": str(rec.saldo_final_declarado),
            "diferenca": str(rec.diferenca),
            "bate": rec.bate,
        },
    }
    json_legivel = json.dumps(saida, ensure_ascii=False, indent=2)
    relatorio = montar_relatorio(pdf.name, extrato, rec)

    (out_dir / f"{pdf.stem}.json").write_text(json_legivel, encoding="utf-8")
    (out_dir / f"{pdf.stem}.report.txt").write_text(relatorio, encoding="utf-8")

    print(f"\n{json_legivel}\n\n{relatorio}")

    if not rec.aplicavel:
        return Resultado(pdf.name, "SEM SALDOS", "walk N/A")
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
    todas_batem = bool(reconciliadas) and all(
        r.status == "BATE" for r in reconciliadas
    )
    print(
        "\nRégua de sucesso do spike:\n"
        "  1. Balance walk bate em TODOS os extratos com saldos: "
        + ("SIM" if todas_batem else "NAO")
        + "\n"
        "  2. Classificação certa (conferência MANUAL, o coração) — para cada\n"
        "     out/<pdf>.report.txt com o PDF aberto do lado: cada balde certo;\n"
        "     cada pagamento_fatura com cartão/valor/data certos.\n"
        "  Olhe os blocos [!] do relatório: linhas fora dos 3 baldes (4o balde?)\n"
        "  e reembolsos mapeados a receita (decisões de produção a revisitar).\n"
        "Não é gate automático: é o critério de decisão (extração vence a digitação?)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Spike: classificação de extrato de conta (PDF) via Gemini + balance walk."
    )
    parser.add_argument("pasta", type=Path, help="pasta com os PDFs de extrato")
    parser.add_argument(
        "--model", default=MODELO_DEFAULT, help=f"modelo Gemini (default: {MODELO_DEFAULT})"
    )
    parser.add_argument(
        "--tolerancia", default="0.02", help="tolerância do balance walk em R$ (default: 0.02)"
    )
    parser.add_argument(
        "--redact",
        action="append",
        default=[],
        metavar="NOME",
        help="nome a redigir do texto antes do envio (repetível; cobre contraparte de Pix/TED)",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="pasta de saída (default: out/ ao lado do script)"
    )
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
