# Spike — validação da classificação de EXTRATO via LLM

**Standalone e descartável.** Valida se a extração de um EXTRATO DE CONTA (PDF →
texto → Gemini → JSON) **classifica** cada movimentação corretamente em um de
**três baldes**, ANTES de qualquer código de produção. Não toca `app/`, não
conecta em banco, não lê o `.env` do projeto.

Irmão do [spike_import/](../spike_import/) (aquele valida a fatura de cartão;
este, o extrato de conta). Mesma máquina, schema e prompt próprios.

## Os três baldes (o coração do spike)

| balde | o que é | saída de caixa? | mapeamento em produção |
|---|---|---|---|
| `receita` | entrada (salário, Pix recebido, depósito, rendimento) | não (entrada) | `Transacao(tipo="receita")` |
| `debito` | saída que É consumo (compra débito, Pix enviado, boleto, saque, tarifa) | sim | `Transacao(tipo="despesa")` |
| `pagamento_fatura` | pagamento de fatura de cartão — **não** é despesa | sim | `PagamentoFatura(cartao, competência)` |

`debito` e `pagamento_fatura` são **ambos** saída de caixa; a diferença é que
débito é consumo e pagamento de fatura não. O casamento do `pagamento_fatura`
com a fatura real **não** é aqui (é produção).

## Setup (venv próprio — não polui o venv do app)

```powershell
cd scripts\spike_extrato
python -m venv .venv          # requer Python >= 3.11
.venv\Scripts\pip install -r requirements.txt
```

## Rodar

```powershell
$env:GEMINI_SPIKE_API_KEY = "sua-chave-do-spike"   # NUNCA a GEMINI_API_KEY de produção
.venv\Scripts\python run_spike.py .\extratos\ --redact "Fulano de Tal"
```

Coloque os PDFs (anonimizados) em `extratos/` — a pasta é gitignored, PDFs reais
nunca commitam. Flags:

| Flag | Default | O que faz |
|---|---|---|
| `--model` | `gemini-2.5-flash` | modelo Gemini (troque para comparar com `-pro`) |
| `--tolerancia` | `0.02` | tolerância do balance walk em R$ |
| `--redact "Nome"` | — | nome a redigir antes do envio (repetível; cobre contraparte de Pix/TED) |
| `--out` | `out/` | pasta de saída |

Sem `GEMINI_SPIKE_API_KEY` o script falha imediatamente, antes de processar
qualquer PDF.

## O que sai

Por extrato: o JSON validado + relatório no console, e `out/<pdf>.json` /
`out/<pdf>.report.txt` para conferência manual contra o PDF. O relatório traz o
balance walk, os `pagamento_fatura` em destaque, os blocos `[!]` (ver abaixo) e
o dump completo `data | balde | valor | descrição`. Se o Pydantic rejeitar a
resposta do modelo, o cru vai para `out/<pdf>.raw.json`. PDF sem camada de texto
(escaneado) é reportado e pulado — OCR está fora de escopo.

## Convenção de sinal

`valor` é sempre **magnitude positiva**; a direção vem do `balde` — casa com o
CHECK `valor > 0` da `Transacao` em produção (direção via `tipo`). Só os
**saldos** carregam sinal (cheque especial existe).

## O balance walk (o guarda-costas)

```
saldo_final_calc = saldo_inicial + Σreceita − Σdebito − Σpagamento_fatura
bate = |saldo_final_calc − saldo_final_declarado| <= tolerância
```

`pagamento_fatura` não é consumo, mas É saída de caixa — entra no walk como
saída. O walk prova que os três baldes **particionam** o extrato: linha perdida,
duplicada ou com sinal trocado (`receita`↔`debito`) **não fecha**. Só roda
quando o extrato imprime `saldo_inicial` **e** `saldo_final`; senão, `N/A` e a
validação recai só na conferência manual.

## Sinais de design a observar (o spike existe para achar isto barato)

1. **Talvez falte um 4º balde.** Extrato de conta costuma ter movimentos que não
   são nenhum dos três: aplicação/resgate de investimento, transferência entre
   contas próprias, rendimento reinvestido. **Cuidado:** se essa linha for
   classificada na direção de caixa certa (aplicação → `debito`), o walk **fecha
   mesmo assim** — o walk só pega drop/duplicata/sinal trocado, não um balde
   errado na mesma direção. Por isso o relatório imprime um bloco `[!]` com as
   linhas cuja descrição cheira a investimento/transferência própria: olhe se
   elas mereciam um balde `transferencia`/`investimento` (não é bug — é achado
   de design).

2. **Reembolso não é renda.** O spike mapeia estorno/reembolso recebido para
   `receita` (no extrato é dinheiro que entra), mas conceitualmente um reembolso
   **abate consumo**, não deveria inflar receitas — como o `tipo="estorno"` da
   produção. O relatório destaca num bloco `[!]` as linhas de
   reembolso/estorno/devolução. Se aparecerem com frequência, reconsiderar o
   balde na produção. **Não bloqueia o spike** — só não deixa esse mapeamento
   virar verdade sem querer.

## Privacidade

- A chave é do spike (`GEMINI_SPIKE_API_KEY`), nunca a de produção.
- Redação best-effort antes do envio: CPF (regex) e nomes (`--redact`). O risco
  de PII próprio do extrato é o **nome da contraparte** em Pix/TED — cubra-o com
  `--redact "Nome"`. É rede, não garantia — anonimize o PDF antes.

## Régua de sucesso (impressa no fim do run)

1. Balance walk **bate em todos** os extratos com saldos (automático).
2. Na conferência **manual** (o coração): cada `balde` certo; cada
   `pagamento_fatura` com **cartão/valor/data** certos; menos campos a corrigir
   do que digitar à mão.

Não é gate automático — é o critério de decisão para seguir (Gemini pago) ou não.
