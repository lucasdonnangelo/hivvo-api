# Spike — validação da extração de fatura via LLM

**Standalone e descartável.** Valida se a extração de fatura de cartão (PDF → texto →
Gemini → JSON) vence a digitação manual, ANTES de qualquer código de produção.
Não toca `app/`, não conecta em banco, não lê o `.env` do projeto.

Contexto e decisões: [docs/PLANO_IMPORTACAO.md](../../docs/PLANO_IMPORTACAO.md).

## Setup (venv próprio — não polui o venv do app)

```powershell
cd scripts\spike_import
python -m venv .venv          # requer Python >= 3.11
.venv\Scripts\pip install -r requirements.txt
```

## Rodar

```powershell
$env:GEMINI_SPIKE_API_KEY = "sua-chave-do-spike"   # NUNCA a GEMINI_API_KEY de produção
.venv\Scripts\python run_spike.py .\faturas\
```

Coloque os PDFs (anonimizados) em `faturas/` — a pasta é gitignored, PDFs reais nunca
commitam. Flags:

| Flag | Default | O que faz |
|---|---|---|
| `--model` | `gemini-2.5-flash` | modelo Gemini (troque para comparar com `-pro`) |
| `--tolerancia` | `0.02` | tolerância da reconciliação em R$ |
| `--redact "Nome"` | — | nome a redigir antes do envio (repetível) |
| `--out` | `out/` | pasta de saída |

Sem `GEMINI_SPIKE_API_KEY` o script falha imediatamente, antes de processar qualquer PDF.

## O que sai

Por fatura: o JSON validado + relatório de reconciliação no console, e
`out/<pdf>.json` / `out/<pdf>.report.txt` para conferência manual contra o PDF.
Se o Pydantic rejeitar a resposta do modelo, o cru vai para `out/<pdf>.raw.json`.
PDF sem camada de texto (escaneado) é reportado e pulado — OCR está fora de escopo.

## Privacidade

- A chave é do spike (`GEMINI_SPIKE_API_KEY`), nunca a de produção.
- Redação best-effort antes do envio: CPF (regex), nomes (`--redact`), e finais de
  cartão **pseudonimizados com mapa reversível** (o Gemini vê `0001`; o script restaura
  o final real localmente na resposta). É rede, não garantia — anonimize o PDF antes.

## Régua de sucesso (impressa no fim do run)

1. Reconciliação **bate em todas** as faturas de teste (automático).
2. Na conferência manual, **menos campos a corrigir do que digitar à mão** (humano).

Não é gate automático — é o critério de decisão para seguir (Gemini pago) ou não.
