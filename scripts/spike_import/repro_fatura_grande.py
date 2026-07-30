#!/usr/bin/env python
"""Repro OFFLINE do POST /import/fatura/preview — só a parte que pode falhar.

Reproduz o caminho de PRODUÇÃO até a resposta crua do Gemini:

    PDF -> extracao_pdf.extrair_texto -> redacao.redigir -> Gemini -> JSON

usando os MESMOS artefatos de produção:
  * prompt  = PROMPT_REGRAS lido do FONTE de app/services/import_fatura/gemini.py
              (via ast, SEM importar o módulo — ele puxa app.core.config, que
              carrega o .env do projeto, que aponta para o Supabase de PRODUÇÃO)
  * schema  = app.schemas.import_fatura.FaturaExtraida
  * safety  = app.core.gemini_safety.SAFETY_SETTINGS
  * extração/redação/reconciliação = os módulos reais de app/services/import_fatura/

ISOLAMENTO (garantido, não prometido):
  * NADA aqui abre conexão de banco. `_abortar_se_importou_banco()` checa
    sys.modules DEPOIS dos imports e aborta se app.core.config/database entrarem.
  * O .env do projeto NUNCA é lido. A única variável consumida é
    GEMINI_IMPORT_API_KEY, direto do ambiente do processo.
  * Nada é gravado em disco — o relatório sai só em stdout.

DIFERENÇA DELIBERADA vs. produção: por padrão a chamada roda SEM timeout, para
MEDIR quanto ela realmente leva (produção corta em GEMINI_IMPORT_TIMEOUT_MS=60000).
Use --timeout-ms 60000 para reproduzir o corte de produção.
Produção também NÃO seta max_output_tokens nem thinking_config; este script
espelha isso por padrão (--thinking-budget ausente = não setado, igual produção).
--thinking-budget é só INSTRUMENTAÇÃO DO HARNESS — nenhum código de produção
seta isso ainda; é para medir o efeito antes de decidir se entra em app/.

PII: o relatório imprime trechos da resposta (conteúdo de fatura) e roda em
terminal local, por design — é o que revela o truncamento. Não redirecione a
saída para arquivo versionado. --dump-json grava em scripts/spike_import/out/
(gitignored) por padrão — não aponte para pasta versionada.

Uso (a partir da raiz do hivvo-api):

    $env:GEMINI_IMPORT_API_KEY = "<a chave dedicada da importação>"
    venv\\Scripts\\python scripts\\spike_import\\repro_fatura_grande.py C:\\caminho\\fatura.pdf

Flags: --timeout-ms N | --model NOME | --max-paginas N | --redigir-nome "Fulano"
(repetível) | --thinking-budget N | --dump-json CAMINHO
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time
from pathlib import Path

# Raiz do repo no sys.path para importar `app.*` (o script vive em scripts/spike_import/).
_RAIZ = Path(__file__).resolve().parents[2]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

ENV_KEY = "GEMINI_IMPORT_API_KEY"
# Espelha o default de Settings.GEMINI_IMPORT_MODEL (app/core/config.py).
MODELO_DEFAULT = "gemini-2.5-flash"
# Espelha o default de Settings.IMPORT_MAX_PDF_PAGINAS.
MAX_PAGINAS_DEFAULT = 20
# Espelha Settings.GEMINI_IMPORT_TIMEOUT_MS — usado só se --timeout-ms for passado.
TIMEOUT_PROD_MS = 60000

_GEMINI_PROD = _RAIZ / "app" / "services" / "import_fatura" / "gemini.py"

# Módulos que abrem banco / carregam o .env de produção. Nenhum pode estar
# carregado depois dos imports deste script.
_PROIBIDOS = ("app.core.config", "app.core.database", "sqlmodel", "sqlalchemy")


def _abortar_se_importou_banco(fase: str) -> None:
    intrusos = sorted(m for m in _PROIBIDOS if m in sys.modules)
    if intrusos:
        sys.exit(
            f"ABORTADO ({fase}): módulos de banco/config foram importados: "
            f"{', '.join(intrusos)}.\n"
            "app.core.config carrega o .env do projeto, que aponta para o Supabase "
            "de PRODUÇÃO. Este script não pode tocar nisso — corrija o import."
        )


def carregar_prompt_de_producao() -> str:
    """Lê PROMPT_REGRAS do FONTE do módulo de produção, sem importá-lo.

    Importar app.services.import_fatura.gemini puxaria app.core.config (que lê o
    .env de produção). O ast dá o literal EXATO, e o script quebra alto se o nome
    sumir — assim o repro nunca roda com um prompt divergente do de produção.
    """
    arvore = ast.parse(_GEMINI_PROD.read_text(encoding="utf-8"))
    for no in arvore.body:
        if isinstance(no, ast.Assign):
            for alvo in no.targets:
                if isinstance(alvo, ast.Name) and alvo.id == "PROMPT_REGRAS":
                    return ast.literal_eval(no.value)
    sys.exit(
        f"ABORTADO: não achei PROMPT_REGRAS em {_GEMINI_PROD}.\n"
        "O módulo de produção mudou — ajuste este script antes de confiar no repro."
    )


def obter_api_key() -> str:
    key = os.environ.get(ENV_KEY)
    if not key:
        sys.exit(
            f"ERRO: a env var {ENV_KEY} não está definida.\n"
            "Este script NÃO lê o .env do projeto de propósito (ele aponta para o "
            "Supabase de PRODUÇÃO). Defina a chave só no ambiente do processo:\n"
            f'    $env:{ENV_KEY} = "sua-chave-da-importacao"'
        )
    return key


def _sec(t0: float) -> float:
    return time.perf_counter() - t0


def _titulo(txt: str) -> None:
    print(f"\n=== {txt} ===")


def _dump(rotulo: str, obj) -> None:
    """Imprime um objeto do SDK sem interpretar (model_dump quando pydantic)."""
    if obj is None:
        print(f"{rotulo}: None")
        return
    dados = obj.model_dump(exclude_none=True) if hasattr(obj, "model_dump") else obj
    print(f"{rotulo}: {json.dumps(dados, indent=2, ensure_ascii=False, default=str)}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pdf", type=Path, help="caminho do PDF da fatura")
    p.add_argument(
        "--timeout-ms", type=int, default=None,
        help=f"timeout do client HTTP em ms. Omitido = SEM timeout (mede a latência "
             f"real). Use {TIMEOUT_PROD_MS} para reproduzir o corte de produção.",
    )
    p.add_argument("--model", default=MODELO_DEFAULT, help=f"modelo Gemini (default: {MODELO_DEFAULT})")
    p.add_argument("--max-paginas", type=int, default=MAX_PAGINAS_DEFAULT)
    p.add_argument(
        "--redigir-nome", action="append", default=[], metavar="NOME",
        help="nome a redigir antes do envio (produção passa nome_completo/username "
             "do usuário). Repetível. Sem isso, só CPF e finais são tratados.",
    )
    p.add_argument(
        "--thinking-budget", type=int, default=None, metavar="N",
        help="INSTRUMENTAÇÃO DO HARNESS — produção não seta isso ainda. Ausente = "
             "thinking_config não setado (igual produção, orçamento default do "
             "modelo). Presente = ThinkingConfig(thinking_budget=N); aceita 0 "
             "(desliga o thinking).",
    )
    p.add_argument(
        "--dump-json", default=None, metavar="CAMINHO",
        help="grava o JSON extraído (indent=2, sort_keys=True, ensure_ascii=False, "
             "estável para diff entre execuções). CAMINHO relativo cai dentro de "
             "scripts/spike_import/out/ (gitignored) — passe um caminho absoluto "
             "só se quiser fugir disso de propósito.",
    )
    args = p.parse_args()

    if not args.pdf.is_file():
        sys.exit(f"ERRO: arquivo não encontrado: {args.pdf}")

    api_key = obter_api_key()

    # Acentos e trechos crus da fatura na saída — não deixar o console quebrar.
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    # --- Imports do caminho de produção (todos puros: pydantic/pdfplumber/genai) ---
    from google import genai
    from google.genai import types

    from app.core.gemini_safety import SAFETY_SETTINGS
    from app.schemas.import_fatura import FaturaExtraida
    from app.services.import_fatura import extracao_pdf, redacao
    from app.services.import_fatura.reconciliacao import TOLERANCIA, reconciliar

    _abortar_se_importou_banco("após os imports")

    prompt = carregar_prompt_de_producao()

    print("=" * 72)
    print("REPRO — /import/fatura/preview (offline, sem banco, sem .env)")
    print("=" * 72)
    print(f"pdf                 : {args.pdf}")
    print(f"bytes               : {args.pdf.stat().st_size}")
    print(f"modelo              : {args.model}")
    print(f"timeout do client   : {'SEM TIMEOUT (default do httpx desativado)' if args.timeout_ms is None else f'{args.timeout_ms} ms'}")
    print(f"max_output_tokens   : NÃO SETADO (igual produção)")
    if args.thinking_budget is None:
        print(f"thinking_config     : NÃO SETADO (igual produção — orçamento default do modelo)")
    else:
        print(f"thinking_config     : ThinkingConfig(thinking_budget={args.thinking_budget}) "
              f"[INSTRUMENTAÇÃO DO HARNESS — produção não seta isso]")
    print(f"prompt              : PROMPT_REGRAS de {_GEMINI_PROD.relative_to(_RAIZ)} ({len(prompt)} chars)")
    print(f"schema              : app.schemas.import_fatura.FaturaExtraida")
    print(f"safety              : app.core.gemini_safety.SAFETY_SETTINGS ({len(SAFETY_SETTINGS)} categorias)")

    # --- Etapa 1: leitura + extração de texto (pdfplumber, layout=True) ---
    _titulo("1. EXTRAÇÃO DO PDF")
    t0 = time.perf_counter()
    dados = args.pdf.read_bytes()
    dt_leitura = _sec(t0)
    if not dados.startswith(b"%PDF-"):
        sys.exit("ERRO: não começa com %PDF- (produção rejeita com 400 antes de tudo).")

    t0 = time.perf_counter()
    try:
        texto, paginas = extracao_pdf.extrair_texto(dados, args.max_paginas)
    except extracao_pdf.PaginasDemaisError as e:
        sys.exit(f"PDF com {e.paginas} páginas — produção devolve 422 (limite {args.max_paginas}).")
    dt_extracao = _sec(t0)

    print(f"leitura do arquivo  : {dt_leitura:.3f}s")
    print(f"extração pdfplumber : {dt_extracao:.3f}s")
    print(f"páginas             : {paginas}")
    print(f"chars do texto      : {len(texto)}")
    print(f"tem_camada_de_texto : {extracao_pdf.tem_camada_de_texto(texto)}")

    # --- Etapa 2: redação (mesma de produção) ---
    _titulo("2. REDAÇÃO (PII)")
    t0 = time.perf_counter()
    texto_redigido, mapa_reverso = redacao.redigir(texto, args.redigir_nome)
    dt_redacao = _sec(t0)
    print(f"duração             : {dt_redacao:.3f}s")
    print(f"chars após redação  : {len(texto_redigido)}")
    print(f"finais pseudonimiz. : {len(mapa_reverso)}")

    conteudo = prompt + texto_redigido
    print(f"chars enviados      : {len(conteudo)}  (prompt {len(prompt)} + fatura {len(texto_redigido)})")

    # --- Etapa 3: chamada ao Gemini (mesma config de produção) ---
    _titulo("3. CHAMADA AO GEMINI")
    kwargs_client = {"api_key": api_key}
    if args.timeout_ms is not None:
        # HttpOptions.timeout é em ms e o SDK ainda manda X-Server-Timeout (s)
        # a partir dele — ou seja, o valor corta dos DOIS lados.
        kwargs_client["http_options"] = types.HttpOptions(timeout=args.timeout_ms)
    client = genai.Client(**kwargs_client)

    config_kwargs = dict(
        temperature=0,
        response_mime_type="application/json",
        response_schema=FaturaExtraida,
        safety_settings=SAFETY_SETTINGS,
    )
    if args.thinking_budget is not None:
        # Só entra na config se a flag foi passada — ausência de flag preserva
        # o comportamento de produção (thinking_config não setado).
        config_kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=args.thinking_budget
        )

    t0 = time.perf_counter()
    try:
        resposta = client.models.generate_content(
            model=args.model,
            contents=conteudo,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except Exception as e:
        # Sem máscara: produção mapeia TUDO isso para o mesmo 503 e loga só a
        # classe. Aqui a classe E a mensagem, que é o que identifica a causa.
        dt = _sec(t0)
        _titulo("FALHA NA CHAMADA (é aqui que produção devolve 503)")
        print(f"duração até falhar  : {dt:.3f}s")
        print(f"classe              : {type(e).__module__}.{type(e).__name__}")
        print(f"mensagem            : {e}")
        for attr in ("code", "status", "message"):
            if hasattr(e, attr):
                print(f"{attr:<20}: {getattr(e, attr)!r}")
        causa = e.__cause__ or e.__context__
        if causa is not None:
            print(f"causa               : {type(causa).__name__}: {causa}")
        return 1
    dt_gemini = _sec(t0)
    print(f"duração             : {dt_gemini:.3f}s")

    # --- Etapa 4: anatomia da resposta ---
    _titulo("4. RESPOSTA — METADADOS")
    _dump("prompt_feedback", getattr(resposta, "prompt_feedback", None))
    candidatos = resposta.candidates or []
    print(f"candidates          : {len(candidatos)}")
    if candidatos:
        c = candidatos[0]
        print(f"finish_reason       : {c.finish_reason!r}")
        print(f"finish_message      : {getattr(c, 'finish_message', None)!r}")
        partes = (c.content.parts if c.content and c.content.parts else []) or []
        thought = sum(1 for x in partes if getattr(x, "thought", False))
        print(f"parts               : {len(partes)} (thought={thought}, texto={len(partes) - thought})")
        if c.safety_ratings:
            print("safety_ratings      :")
            for sr in c.safety_ratings:
                print(f"  - {sr.category} {sr.probability} blocked={sr.blocked}")

    _titulo("5. USAGE_METADATA (completo, sem interpretação)")
    _dump("usage_metadata", resposta.usage_metadata)

    # --- Etapa 5: texto cru (as pontas revelam o truncamento) ---
    raw = resposta.text or ""
    _titulo("6. RESPOSTA CRUA")
    print(f"resposta.text is None: {resposta.text is None}   (produção faz `or \"\"`)")
    print(f"resposta.parsed      : {'preenchido' if resposta.parsed is not None else 'None'}"
          "   (o SDK engole JSONDecodeError/ValidationError aqui — ver types.py)")
    print(f"len(raw)             : {len(raw)}")
    print("\n--- PRIMEIROS 500 chars ---")
    print(raw[:500])
    print("\n--- ÚLTIMOS 500 chars ---")
    print(raw[-500:])

    # --- Etapa 6: parse (json cru primeiro, para ter a POSIÇÃO do erro) ---
    _titulo("7. PARSE")
    t0 = time.perf_counter()
    try:
        json.loads(raw)
        print("json.loads          : OK")
    except json.JSONDecodeError as e:
        print(f"json.loads          : FALHOU — {type(e).__name__}: {e}")
        print(f"  pos={e.pos} lineno={e.lineno} colno={e.colno} len={len(raw)}")
        print(f"  restam {len(raw) - e.pos} chars após a posição do erro "
              "(0 = JSON cortado no fim → truncamento, não malformação)")
        print(f"  contexto: ...{raw[max(0, e.pos - 120):e.pos + 120]!r}...")
        print("\n(produção: ValidationError do Pydantic aqui → HTTP 502 "
              '"A extração retornou dados inválidos", NÃO o 503.)')
        return 1

    try:
        fatura = FaturaExtraida.model_validate_json(raw)
    except Exception as e:
        print(f"FaturaExtraida      : REJEITADO — {type(e).__name__}")
        print(f"{e}")
        print("\n(produção: HTTP 502 aqui.)")
        return 1
    print(f"FaturaExtraida      : OK ({_sec(t0):.3f}s)")

    # --- Etapa 7: reconciliação (mesma de produção) ---
    redacao.restaurar_finais(fatura, mapa_reverso)
    rec = reconciliar(fatura, TOLERANCIA)
    dt_parse = _sec(t0)  # parse + restauração + reconciliação
    _titulo("8. RESULTADO")
    print(f"banco               : {fatura.banco}")
    print(f"competência         : {fatura.competencia.mes:02d}/{fatura.competencia.ano}")
    print(f"transações          : {len(fatura.transacoes)}")
    print(f"ancora (declarada)  : {rec.ancora}")
    print(f"soma_gastos         : {rec.soma_gastos}")
    print(f"excluidos           : {rec.excluidos}")
    print(f"total_a_pagar       : {rec.total_a_pagar}")
    print(f"diferenca           : {rec.diferenca}   BATE={rec.bate} (tolerância {TOLERANCIA})")
    print(f"diferenca_secundaria: {rec.diferenca_secundaria}   bate_secundario={rec.bate_secundario}")

    _titulo("TEMPOS")
    print(f"pdfplumber          : {dt_extracao:.3f}s")
    print(f"redação             : {dt_redacao:.3f}s")
    print(f"gemini              : {dt_gemini:.3f}s")
    print(f"parse+reconciliação : {dt_parse:.3f}s")
    print(f"TOTAL (sem upload)  : {dt_leitura + dt_extracao + dt_redacao + dt_gemini + dt_parse:.3f}s")

    uso = resposta.usage_metadata
    thoughts = getattr(uso, "thoughts_token_count", None) or 0
    candidates_tok = getattr(uso, "candidates_token_count", None) or 0
    tokens_gerados = thoughts + candidates_tok
    if dt_gemini > 0 and tokens_gerados > 0:
        print(f"tokens/s (gemini)   : {tokens_gerados / dt_gemini:.1f}  "
              f"(={thoughts} thoughts + {candidates_tok} candidates ÷ {dt_gemini:.3f}s "
              "— comparável entre documentos de tamanhos diferentes)")
    else:
        print("tokens/s (gemini)   : n/d (usage_metadata sem thoughts/candidates)")

    print(f"\nProdução corta a chamada ao Gemini em {TIMEOUT_PROD_MS} ms "
          f"(GEMINI_IMPORT_TIMEOUT_MS).")

    # --- Etapa 8: dump estável do JSON extraído (comparável por diff) ---
    if args.dump_json is not None:
        destino = Path(args.dump_json)
        if not destino.is_absolute():
            destino = _RAIZ / "scripts" / "spike_import" / "out" / destino
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            # mode="json": FaturaExtraida hoje só tem str/int/enum (nunca Decimal/
            # date nativos — decisão de schema, ver import_fatura.py), então
            # json.dumps(model_dump()) já funcionaria; mode="json" blinda contra o
            # dia em que isso deixar de ser verdade, sem custo.
            json.dumps(fatura.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        _titulo("DUMP JSON")
        print(f"gravado em          : {destino}")

    return 0


if __name__ == "__main__":
    _abortar_se_importou_banco("no boot")
    sys.exit(main())
