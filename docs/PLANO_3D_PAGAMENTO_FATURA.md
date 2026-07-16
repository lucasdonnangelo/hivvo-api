# Hivvo — Lente 3d (faturas por cartão) + Pagamento de Fatura

> Origem: investigação revelou que "fatura" NÃO é entidade no modelo — é uma agregação derivada
> (`cartao_id` + `fatura_mes` + `fatura_ano`). E `Parcela` tem `pago`, mas `Transacao` (avulsa de
> cartão) NÃO tem. Logo a decisão de produto ("o usuário marca a FATURA como paga") não é
> implementável sem mudança de modelo.

## SEPARAÇÃO EM DUAS LEVAS (decidido)
- **Leva 1 — 3d SIMPLES (agora):** a lente cross-cartão "1 mês × N cartões" (ex.: "dezembro: Itaú
  R$A, Nubank R$B). LEITURA PURA. Aditiva, sem decisão de modelo. 🟡.
- **Leva 2 — Pagamento de fatura (depois):** mudança de modelo (`PagamentoFatura`), revisita o
  `a_pagar`. 🔴, potente, design próprio.

---

## LEVA 1 — Lente 3d (faturas por cartão, num mês)

### O que JÁ existe (não reconstruir)
- `GET /cards/{id}/invoices` → lista de faturas do cartão (mes, ano, total, data_vencimento,
  total_parcelas_pagas, total_itens).
- `GET /cards/{id}/invoices/{ano}/{mes}` → detalhe (total, vencimento, parcelas[], avulsas[]).
- `GET /cards` → já traz `fatura_aberta_total/mes/ano/vencimento` por cartão.
- Frontend: `CardsPage` (1 cartão × N meses), `InvoiceMonthGrid` (grade de meses), `InvoiceDetail`
  (detalhe da fatura), `CardVisual`.

### O que FALTA (a lente 3d)
Hoje a tela é **1 cartão × N meses**. A lente 3d é **1 mês × N cartões**.
- **Backend:** endpoint por competência cruzando cartões, ex.
  `GET /invoices/{ano}/{mes}` → `[{cartao_id, nome, total, data_vencimento, ...}, ...]`.
  (Alternativa ruim: o front chamar `/cards/{id}/invoices` N vezes e cruzar no cliente.)
- **Frontend:** tela/seção que mostra, para um mês escolhido, a fatura de cada cartão + o total
  agregado. Navegação por mês.

### Contrato meio-implementado a formalizar (achado)
O frontend declara `InvoiceListItem.status: 'aberta'|'fechada'|'futura'` e o `InvoiceMonthGrid` usa
`inv.status === 'futura'` — **mas o backend nunca retorna `status`** (sempre `undefined`; "futura"
hoje = "mês sem dados" por acidente). Inversamente, o backend manda `total_parcelas_pagas`/
`total_itens` que o frontend ignora. A lente 3d deve formalizar (ou remover) esse contrato.

---

## LEVA 2 — Pagamento de fatura (design decidido, implementar depois)

> **✅ WEB ENTREGUE (10/07/2026).** Backend materializou `PagamentoFatura` e expôs `status`
> derivado (`paga`/`aberta`/`a_vencer`/`atrasada`) nos 3 endpoints de fatura + `PUT
> /invoices/{cartao_id}/{ano}/{mes}/pagamento {pago}`. Frontend: `status` reintroduzido nos 3 tipos,
> `InvoiceStatusBadge` (atrasada destacada), ação "Marcar/Desmarcar pagamento" (um clique, reversível)
> no `InvoiceDetail` — cobre os modos "Por cartão" e "Por mês" por reuso. Invalidação inclui
> `['statistics']` (o `a_pagar` do Dashboard muda ao confirmar). **NÃO feito:** aviso de fatura
> atrasada no Dashboard (item 4 — decisão adiada). Detalhes em `docs/SESSAO_ATUAL_WEB.md`.

### O problema
- "Marcar fatura paga" hoje = marcar N `Parcela.pago` (uma a uma, sem bulk) **e as avulsas, que não
  têm onde gravar** (`Transacao` não tem `pago`). Fatura com avulsa fica eternamente meio-paga.
- `a_pagar` (Bloco 1) hoje usa `Parcela.pago` para parcelas e **presume "avulsa vencida = paga"**.
  A presunção morreu para parcelas (furo 2, corrigido) mas continua viva para avulsas.

### A DECISÃO (Lucas concordou integralmente)
**1. `PagamentoFatura` como AGREGADO** — nova entidade:
```
PagamentoFatura(cartao_id, fatura_mes, fatura_ano) → {pago: bool, data_pagamento}
```
- A unidade de ação do usuário é a FATURA, não o componente. Ele paga "a fatura de dezembro do
  Itaú", não "a parcela 3/10 e a compra do mercado".
- Atômico: um clique = um registro. Evita o estado sem sentido de "fatura parcialmente paga".
- Reversível: alterna a qualquer momento (requisito de produto).

**2. `PagamentoFatura` SUBSTITUI `Parcela.pago` como fonte de "essa saída ocorreu".**
- Manter os dois criaria DUAS fontes de verdade — exatamente o que o projeto evita.
- `Parcela.pago` fica sem uso na projeção (ou é removido; decidir na implementação). Caso de uso
  residual a avaliar: pagamento antecipado de parcela específica (raro).
- **CONSEQUÊNCIA:** o `a_pagar` (feito na leva "eixo saiu/a-vencer") passa a consultar
  `PagamentoFatura` em vez de `Parcela.pago` + presunção por data das avulsas. Isso UNIFICA: mata a
  presunção para parcelas E avulsas de uma vez, porque o pagamento é da fatura (que contém ambos).
  Revisitar o `a_pagar` faz parte desta leva — não é retrabalho gratuito, é o modelo ficando correto.

**3. Status "atrasada" = DERIVADO, nunca materializado.**
- `atrasada = (sem registro OU pago=false) E data_vencimento < hoje`.
- Mesma disciplina da projeção: estado derivado de fato + data, não estado manual duplicado.
- O usuário nunca "marca como atrasada" — ele só não confirmou o pagamento, e o tempo passou.

### Estados da fatura (todos derivados de PagamentoFatura + vencimento)
| Estado | Condição | Conta em "A pagar"? |
|---|---|---|
| **Paga** | registro com `pago=true` | Não |
| **Em aberto** | sem registro, vencimento no futuro | Sim |
| **Atrasada** | sem registro (ou `pago=false`), vencimento < hoje | Sim, **destacada como atrasada** |

### UX da confirmação (decisão de Lucas)
- O sistema **NUNCA presume** pago pela data. Ele **pergunta**.
- Ação **extremamente simples**: um clique por fatura, no momento natural (quando vence).
- Se o usuário responde **"não paguei"** → a fatura continua visível em "A pagar", marcada
  **ATRASADA**, e ele pode alterar a qualquer momento.
- **Onde vive:** a tela de faturas por cartão (3d). Possivelmente um aviso discreto no Dashboard
  quando há fatura vencida não resolvida.
- **Cuidado de design:** nem intrusivo (modal bloqueando o Dashboard) nem escondido (ninguém
  responde e o "A pagar" acumula lixo). A definir no design da Leva 2.

### Escopo da Leva 2 (quando chegar)
- Migration: tabela `PagamentoFatura`.
- Endpoint: marcar/desmarcar fatura paga (por `cartao_id` + competência), atômico.
- Revisitar `a_pagar` (estatisticas.py) para consultar `PagamentoFatura` (fonte única).
- Expor status derivado (paga/aberta/atrasada) nos endpoints de fatura — fecha o contrato
  meio-implementado do `status` no frontend.
- UI: a ação de confirmar + o destaque de atrasada.
- Decidir o destino de `Parcela.pago`.
- 🔴 modelo potente; design detalhado antes do código.
