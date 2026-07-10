# PLANO_3D_PAGAMENTO_FATURA.md — Leva 2: PagamentoFatura e o status de fatura

> Documento de design da **Leva 2 da lente 3d** (a Leva 1 — "1 mês × N cartões" — está no
> SESSAO_ATUAL_API de 10/07/2026). Registrado A POSTERIORI da aprovação (o design foi fechado
> em sessão de 10/07/2026 e implementado na mesma data) para valer como referência entre
> sessões, no padrão dos PLANO_*.
>
> Status: **IMPLEMENTADO no backend em 10/07/2026.** Migration `a3d9f4c2b7e1` aplicada ao dev.
> Falta o frontend (consumir `status` + o PUT de pagamento — batch web).

---

## 0. Motivação

A leva "A pagar e Saldo" (09/07) deixou dois furos estruturais:

1. **Fonte 1 (parcela)** dependia de `Parcela.pago` — gravável só via API (`PUT
   /installments/{id}`), sem UI. Na prática, parcela vencida ficava em "a pagar" para sempre.
2. **Fonte 2 (avulsa de cartão)** presumia **"venceu = saiu"** (a `Transacao` não tem `pago`) —
   uma fatura vencida e NÃO paga sumia do a_pagar sozinha, escondendo dívida.

Além disso, o frontend da Leva 1 removeu o campo `status` FANTASMA das faturas (declarado e
nunca retornado) esperando que ele voltasse REAL nesta leva.

## 1. A entidade — PagamentoFatura

**Fonte única de "essa fatura foi paga"**, por fatura = (cartão, competência):

- Tabela `pagamentos_fatura` ([models/pagamento_fatura.py](../app/models/pagamento_fatura.py)):
  `id` (int PK), `usuario_id` (FK, index), `cartao_id` (FK), `fatura_mes`, `fatura_ano`,
  `pago` (bool), `data_pagamento` (date, nullable), `criado_em`.
- **Chave natural**: UNIQUE `(cartao_id, fatura_ano, fatura_mes)`. Escopo por `usuario_id` em
  toda query (T-36).
- **Semântica dos estados**: AUSÊNCIA de registro = não confirmado; `pago=False` = o usuário
  disse "não paguei" (equivale à ausência no status; existe pela reversibilidade);
  `pago=True` = paga.
- Migration `a3d9f4c2b7e1`: tabela **VAZIA, SEM backfill** (não há base instalada). FKs ON
  DELETE CASCADE (usuarios, cartoes), índice `(usuario_id, fatura_ano, fatura_mes)`.
  Upgrade E downgrade testados no Postgres dev.

## 2. Regra "a fatura JÁ FECHOU" (derivada, sem estado)

Invertendo a materialização (`_fatura_cartao_avulso`/`_data_vencimento_parcela`): competência
= mês-base da compra + `mes_offset_vencimento`; compra com `dia > dia_fechamento` empurra o
mês-base em +1. Logo (`data_fechamento_fatura` em [services/faturas.py](../app/services/faturas.py)):

> **fechamento da competência (m, a)** = dia `clamp(dia_fechamento)` do mês-base =
> **(m, a) − mes_offset_vencimento**. Sem `dia_fechamento` → último dia do mês-base.
> **FECHADA ⇔ hoje > data_fechamento** (no próprio dia do fechamento a compra ainda entra —
> o `>` da materialização é estrito → a fatura ainda está ABERTA nesse dia).

Depois do fechamento, nenhuma compra NOVA (data = hoje) cai na competência. Exceções aceitas
e documentadas (decisão 3, §5): compra com **data retroativa** e o `PUT /installments`
editando `data_vencimento` (que já não rederivava `fatura_mes` — inconsistência pré-existente,
fora de escopo). Edge aceito: cartão sem `dia_vencimento` (parcelas `compra + i`, sem offset)
usa o mesmo cálculo com o offset do cartão — aproximação para config incompleta.

## 3. Endpoint de confirmação

**`PUT /invoices/{cartao_id}/{ano}/{mes}/pagamento`** body `{pago: bool}`
([routers/invoices.py](../app/routers/invoices.py), `router_competencia`; `ano/mes` por `Path`).

Validações: cartão de outro usuário/inexistente → **404**; fatura **não existe** (nenhuma
parcela não cancelada nem avulsa na competência — `fatura_existe`) → **422** "Não há fatura
nessa competência."; fatura **ainda aberta** (hoje <= fechamento) → **422** com a data.
**Pagamento ANTECIPADO** (fechada, vencimento futuro) é permitido.

Semântica: **upsert idempotente e reversível** pela chave natural. `pago=true` seta
`data_pagamento = hoje()` **só na transição** (re-PUT preserva a data); `pago=false` mantém o
registro com `data_pagamento=None`. Resposta:
`{cartao_id, ano, mes, pago, data_pagamento, status}`.

## 4. Status derivado (nunca materializado)

`status_fatura` em [services/faturas.py](../app/services/faturas.py):

| Status | Condição |
|---|---|
| `paga` | registro com `pago=true` (registro manda — vale mesmo se a composição mudou depois) |
| `aberta` | hoje <= fechamento (ainda aceita compras) |
| `a_vencer` | fechada, não confirmada, vencimento >= hoje |
| `atrasada` | fechada, não confirmada, vencimento < hoje |

Vencimento via `vencimento_avulsa` (nunca None — fallback fim do mês). O usuário NUNCA marca
"atrasada" — é consequência de não confirmar + tempo. **Exposto (aditivo) nos 3 contratos**:
`FaturaListItem` (`GET /cards/{id}/invoices`, +1 query fixa de pagamentos do cartão),
`FaturaDetalhe` (detalhe, 1 lookup) e `FaturaCartaoItem` (`GET /invoices/{ano}/{mes}`, +1
query da competência). Fecha o contrato `status` que o front declarou e o backend nunca
cumpria.

## 5. Decisões fechadas (com o Lucas, 10/07/2026)

1. **Parcela SEM cartão** (carnê — `cartao_id=None`, legal via API): não tem fatura
   confirmável → **presunção por vencimento** (`a_pagar = data_vencimento > hoje`, a regra da
   antiga Fonte 2). A presunção por data morre SÓ para lançamentos COM cartão.
2. **Superfícies de LEITURA do `pago` legado** (`ParcelaResponse.pago/data_pagamento`, filtro
   `GET /installments?pago=`, `total_parcelas_pagas` do list_invoices): **mantidas intocadas**
   — só o WRITE morreu. Remoção fica para batch cross-repo (SummaryPage do web lê `!p.pago`).
3. **Compra retroativa em fatura já confirmada paga**: **aceitar e documentar** — o status
   continua `paga` (registro manda); o usuário desmarca/remarca se quiser. Nenhuma validação
   nova na criação de transações.

## 6. Revisão do a_pagar ([services/estatisticas.py](../app/services/estatisticas.py))

**Regra unificada**: lançamento de crédito COM cartão está PAGO ⇔ a fatura dele tem
`PagamentoFatura.pago=true`. Senão → `a_pagar=True`, **a vencer OU atrasada**. Unifica
parcelas e avulsas e MATA a presunção por data.

- Helpers `_faturas_pagas_mes`/`_faturas_pagas_ano` (+1 query fixa, só quando há lançamento
  de cartão) e `_parcela_a_pagar` (regra da Fonte 1, com o ramo sem-cartão).
- **`realizado`/projeção integral: intactos** — o corte §1.3.1 segue por data/competência.
- **FRONTEIRA (invariante, com testes-guarda em serviço E router)**: a marcação `a_pagar` é o
  ÚNICO consumidor de `PagamentoFatura` na camada de estatísticas; alternar o pagamento não
  move projeção/realizado/a_vir/anual/consumo. E **`Parcela.pago` está MORTO** na camada:
  alternar a coluna obsoleta não move NADA (nem o a_pagar).
- **Pontos que liam `pago` (reporte)**: `estatisticas.py` Fontes 1 mensal/anual →
  **substituídos**; `invoices.py` `total_parcelas_pagas` → mantido (legado);
  `installments.py` filtro `?pago=` → mantido (read-only); `installments.py` PUT (write) →
  **REMOVIDO**; `ParcelaResponse`/`ParcelaFaturaResponse` → mantidos; `ai.py` → só comentário.
- Colunas `Parcela.pago`/`data_pagamento` **NÃO dropadas** — marcadas OBSOLETAS no modelo.

## 7. PUT /installments/{id} — o que saiu e o que ficou

`ParcelaUpdate` perdeu `pago`/`data_pagamento` e ganhou `extra="forbid"` → mandar `pago` vira
**422 explícito** (não um no-op silencioso). **Ficaram**: `cancelado` (rota viva, gatilho do
§Fase 3b) e `data_vencimento`. O router perdeu o bloco de auto-preenchimento de
`data_pagamento`.

## 8. Helper único de composição de fatura

`_cond_parcelas_fatura`/`_cond_avulsas_fatura` em [services/faturas.py](../app/services/faturas.py)
— as MESMAS condições de "o que compõe uma fatura" usadas por `get_invoice`,
`totais_fatura_por_cartao` e o novo `fatura_existe`. A consistência entre as lentes passa a
ser **por construção** (o teste de consistência cruzada vira guarda do refactor).

## 9. Riscos aceitos / consequências de produto

- **Números do Dashboard mudam**: `a_pagar` de meses passados/corrente SOBE — avulsa vencida
  não confirmada deixa de sumir por presunção. Intencional: pendência até o usuário confirmar.
- **Zerar o a_pagar agora exige ação do usuário** (a pendência "marcar fatura paga" da leva
  de 09/07 nasce aqui; o frontend é outro batch).
- `delete_me` ganhou o delete explícito de `PagamentoFatura` (antes de `Cartao`). Gap
  pré-existente observado, fora de escopo: Recorrencia/Vigencia não estão nos deletes
  explícitos do delete_me (cobertas pelo CASCADE do Postgres).
