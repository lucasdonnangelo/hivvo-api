# Hivvo — Design da Importação de Fatura/Extrato

> Status: **DESENHO FECHADO (17/07/2026).**
> Decisões travadas em revisão com o Lucas. O que resta aberto está marcado "Ainda aberto".
>
> **SEQUÊNCIA DE ENTREGA:** fatura primeiro → validou → extrato em seguida. Fatura e extrato são
> entradas independentes que se reconciliam numa única costura: o pagamento da fatura.
>
> **VALIDAÇÃO CONCLUÍDA:** spike em 2 faturas reais (Nubank, Itaú) no Gemini free. Extração impecável.
> Rota LLM confirmada. Ver "VALIDAÇÃO DO SPIKE".
>
> **IMPORTAÇÃO DE FATURA — COMPLETA E VIVA EM PRODUÇÃO (validada E2E):**
> - ✅ **Batch 1** — `POST /import/fatura/preview` (extração stateless + reconciliação). Commit `d1f1073`.
> - ✅ **Batch 2** — `POST /import/fatura/commit` (materialização + idempotência atômica via
>   `import_fatura_lote`). Ver "MULTI-FATURA".
> - ✅ **Batch 3** — multi-fatura: dedup de parcela ENTRE importações (fork Y). Ver "MULTI-FATURA".
> - ✅ **Ajuste no preview** — `faturas_passadas` (competências passadas que o import cria, pra revisão).
> - ✅ **Frontend** — a tela de revisão (wizard cartão+upload → preview → revisão → faturas passadas → commit).
> - ✅ **Validado E2E em produção** (preview + commit em conta descartável).
>
> **DEPENDÊNCIAS / SINERGIAS (mesma leva):**
> - **#9 cobertura de pagamento:** `PagamentoFatura.valor_pago`; o import grava `valor_pago` = total
>   materializado ao confirmar faturas passadas pagas. Status `paga`/`paga_parcial` derivado por cobertura.
> - **Estorno:** o import materializa linha negativa como `tipo="estorno"` (não dropa); recibo
>   `estornos_importados`.
> - **Infra:** migrations agora aplicam no deploy via `railway.json` `preDeployCommand` (o `release:` do
>   Procfile era ignorado pelo Railway — causava drift silencioso).

---

## MULTI-FATURA — o fork que decide o miolo da materialização (FECHADO → Y, implementado no Batch 3)

**O problema (achado na review do Batch 2):** a decisão "histórico completo → materializar 1/N..N/N a
partir de uma fatura" funciona pra UMA fatura. Mas o onboarding é multi-mês, e cada fatura consecutiva
**relista a parcelada em andamento**:
- Importa julho: Blacktag 4/7 → cria a transação com 7 parcelas em abr..out.
- Importa agosto (competência diferente, passa pelo guard do lote): Blacktag 5/7 → cria OUTRA
  transação com 7 parcelas em mai..nov. **Duplicado**, cronogramas inconsistentes.

O guard do lote é por `(cartao, competência)` — não pega a mesma parcelada reaparecendo em faturas de
meses diferentes. Falta dedup de parcela ENTRE importações. E multi-fatura não é borda: é o uso central
(o Resumo só floresce com 6 meses → o usuário importa vários meses).

**As duas saídas:**
- **(X) Uma fatura por cartão** — a mais recente reconstrói o cronograma das parceladas; avulsas só do
  mês importado. Simples, sem duplicação. **MAS** entrega só 1 mês de consumo → o Resumo NÃO floresce.
  Falha na própria razão de existir da feature.
- **(Y) Várias faturas, incremental, com dedup de parcela** — cobre o histórico completo de consumo
  (Resumo floresce) sem duplicar as parceladas.

**RECOMENDAÇÃO: (Y).** É o que entrega o objetivo declarado (6 meses de consumo). E o dedup é tratável:

- **Avulsas:** criadas por fatura, sem overlap entre meses (cada avulsa pertence a uma fatura). O guard
  do lote já impede re-importar a MESMA fatura. Nada novo.
- **Parceladas:** identidade estável = `(cartao_id, descrição normalizada, total_parcelas, origem
  implícita)`, onde `origem implícita = competência − (indice − 1)`. Na importação de cada linha
  parcelada: se já existe transação com essa identidade (de um import anterior) → **pula** (o
  cronograma já foi materializado); senão → materializa 1/N..N/N.
  - **Ordem-independente:** importar agosto (5/7, origem abr) primeiro e julho (4/7, origem abr) depois
    → mesma identidade → o segundo pula. Funciona em qualquer ordem.

**Impacto no código:** é ADIÇÃO ao `persistencia.py` do Batch 2 (uma checagem de dedup antes de
materializar parcelada), não reescrita. Endpoint, guard do lote, atomicidade e testes ficam.

### Sub-decisões do Y — FECHADAS (Batch 3)

**Fingerprint guardado vs recomputar → RECOMPUTAR (identidade em query, sem coluna nova).** Em cima do
modelo real: todos os campos da identidade já estão persistidos — `cartao_id`+`total_parcelas` na
`Transacao`; a **origem implícita = competência da `Parcela` nº 1** (a materialização grava
parcela j em âncora−(indice−j); j=1 ⇒ âncora−(indice−1) = origem — casa por construção com o Batch 2);
descrição **limpa** na `Transacao.descricao` (a extração separa lojista de "Parcela X/N" → o match é
limpa↔limpa, o sufixo `(i/N)` da `Parcela.descricao` nunca entra). Recompute evita coluna + migration +
backfill das parceladas do Batch 2 já importadas.

**Identidade + skip (contra SNAPSHOT de imports ANTERIORES):** no topo da materialização tira-se um
snapshot `{(desc_norm, total, origem_mes, origem_ano, valor_parcela_centavos)}` das parceladas já
importadas do cartão (`origem="importacao"`, via `Parcela` nº 1), **antes de qualquer insert**. Cada
linha parcelada nova computa a mesma chave; se está no snapshot → **PULA**; senão → materializa 1/N..N/N.
Decidir contra o snapshot (não contra a query viva) garante: duas linhas **idênticas na MESMA fatura**
são duas compras e **ambas materializam** (contar a mais é corrigível na revisão; a menos é invisível).
Cross-fatura (import anterior) funde. Skip visível no recibo (`parceladas_deduplicadas`).

**Desempate por valor:** o `valor_parcela` (em centavos) entra na CHAVE, não só na colisão. Duas
parceladas de mesma desc/total/origem mas valor distinto são compras DISTINTAS → ambas materializam;
um valor novo num import posterior nunca é engolido (viés anti-perda-de-dado).

**Confirmação de pagamento das passadas:** o gate aceita competência **estritamente antes da âncora**
que tenha **algum lançamento EXISTENTE deste cartão** (parcela ou avulsa — criado neste request OU por
import anterior). Com dedup, a parcelada passada pode ter sido PULADA neste import e ainda assim ser
marcável. Barra fatura arbitrária (sem lançamento → 422) e a própria/futura (≥ âncora).

### Bordas documentadas (Batch 3)
- **Drift de centavo da mesma parcelada** entre imports → valor difere → duplica. Aceito e visível.
- **Colisão com valores IGUAIS** (faturas diferentes) → fundidas como uma. Na MESMA fatura, ambas entram.
- **Descrição muda muito entre faturas** → quebra a identidade em QUALQUER método. `norm` cobre
  caixa/espaço (colapsa espaços + casefold), NÃO acento.
- **Manual vs import:** o dedup é escopo `origem="importacao"` — parcelada manual e importada coexistem.
- **Concorrência cross-competência:** dois commits simultâneos de competências distintas da MESMA
  parcelada têm janela TOCTOU no snapshot → possível duplicata. Mitigação (advisory lock) DEFERIDA; o
  rate-limit + fluxo humano (1 fatura por vez) cobrem por ora.

---

## A DECISÃO-PIVÔ: extração via LLM, não parser determinístico

O pedaço 🔴 nunca foi "ler o arquivo" — foi **interpretar** as linhas. Duas rotas:
- **Parser determinístico (regex por banco):** dado não sai da infra, MAS frágil, muitos exemplos por
  banco, **cauda de manutenção infinita** para dev solo. **REJEITADO.**
- **LLM (texto → JSON):** um schema serve todos os bancos. **ESCOLHIDO.** A imperfeição é aceitável
  porque a **tela de revisão obrigatória** é a rede.

### Régua da feature
NÃO é 100% de acurácia (impossível, alvo errado). É **"melhor que digitar à mão"**. A tela de revisão
não é o remendo de uma feature imperfeita — **ela é o produto.**

---

## EXTRATOR PLUGÁVEL

Contrato fixo: **texto entra → JSON estruturado sai.** Provedor reversível sem tocar no resto.
- **Gemini free** — só VALIDAÇÃO (fatura anonimizada). Nunca produção: treina + revisores humanos.
- **Gemini pago** — produção: **não treina**, retenção limitada, ZDR. Subprocessador (→ #4). **EM USO.**
- **Modelo local self-hosted** — dado nunca sai; qualidade menor; custo de infra. Alternativa futura.

---

## VALIDAÇÃO DO SPIKE (17/07/2026)

Spike isolado em `scripts/spike_import/`, em 2 faturas reais no Gemini free.

### Resultado: extração impecável nas duas
Zero erro de conteúdo. Nubank (8 linhas, com a linha "Saldo restante" duplicada que é REAL no PDF),
Itaú (2 linhas). Campos a corrigir na mão: praticamente zero. A régua "vence a digitação" batida.

### O achado: reconciliar pelo TOTAL DE COMPRAS DO CICLO, não pelo "total a pagar"
O Itaú deu "NÃO BATE" — não por erro de extração, mas porque o modelo pegou "Total desta fatura = 0,00"
(líquido a pagar, quitado por débito automático). A reconciliação ancora no **total de
compras/lançamentos do ciclo** (Itaú "Total dos lançamentos atuais R$93,95"; Nubank "Total de compras
R$202,65" + "IOF R$3,41"). O cheque secundário (`gastos + excluídos` vs total) diagnostica a semântica
do total do banco.

### Privacidade: redação best-effort NÃO é blindagem
O `--redact` não pegou o nome completo nem o endereço → foram pro Gemini free. Lição: **produção =
Gemini pago + #4 declarado, não free-com-redação.**

---

## DECISÕES DE PRODUTO — TRAVADAS

| # | Decisão | Resolvido |
|---|---|---|
| 1 | **Formato de entrada** | **PDF** digital, texto extraível. Interpretação = LLM. PDF escaneado → OCR (🔴), fora do escopo. |
| 2 | **Fatura vs extrato** | **Fatura por ciclo.** Casa com competência. |
| 3 | **Cartão obrigatório** | O cartão DEVE existir antes. Cadastra cartão → importa a fatura dele. |
| 4 | **Escopo do passado** | **Histórico completo.** Ver armadilha do pagamento. |
| 5 | **Parcelamento `X/Y`** | Materializa 1/N..N/N (multi-fatura com dedup — ver "MULTI-FATURA"). |
| 6 | **Revisão** | **Obrigatória.** Categoria + apagar linha (edição de valor/parcela = follow-up). |
| 7 | **Múltiplos finais na mesma fatura** | Mesma fatura = mesmo cartão. `portador_final` por linha. |
| 8 | **Seção "Pagamentos e Financiamentos"** | **Excluir** (abatimento, não gasto). |
| 9 | **IOF** | Despesa própria, categoria "Taxas/IOF" (entra em `soma_gastos`). |
| 10 | **Conversão de moeda** | Valor em R$. Conversão = metadado. |

### ⚠️ Armadilha do histórico
O modelo **deriva status e nunca presume pago pela data**. Histórico cru → toda fatura passada nasce
não-paga → "A pagar" explode. **Solução:** confirmar em bloco o pagamento das passadas na revisão (o
import grava `valor_pago` = total materializado — sinergia #9).

### Reconciliação — o guarda-costas determinístico
Backend valida a soma em `Decimal`: **âncora = total de compras/lançamentos do ciclo** (não "total a
pagar"). `soma_gastos` = Σ `{compra, iof}` (estorno = compra negativa). Cheque secundário distingue
semântica do banco de erro do LLM. Não bate → sinaliza na revisão, nunca grava no escuro.

---

## ARQUITETURA
- **Fronteira:** extração + modelagem no **backend**. Revisão = display + edição. Commit re-valida.
- **Stateless.** POST PDF → extrai → valida → devolve JSON → front segura → POST final grava. (Tabela
  nova de idempotência `import_fatura_lote` COM RLS no `upgrade()` — a única persistência.)
- **Reuso:** a modelagem reusa parcela/fatura/PagamentoFatura existentes.

---

## IMPORTAÇÃO DE EXTRATO (fatia ATUAL — fatura já validada e viva; extrato é o próximo)

Fatura e extrato descrevem o **mesmo dinheiro por dois lados** — importá-los ingênuo **conta em dobro**.
A linha "Pagamento fatura Nubank -R$500" no extrato **não é gasto novo** — é a quitação das compras que
a fatura já capturou.

### Achados do spike de extrato (Nubank conta real) — dobrados no design
Classificação impecável (7 receita + 1 pagamento_fatura). O pagamento_fatura de R$206,06 casou com a
fatura Nubank importada — sinergia #9 validada ao vivo. O balance-walk pegou dois achados:

- **RENDIMENTO — um `receita` que a extração só-movimentações perdia.** A conta Nubank rende juros
  ("Rendimento líquido +0,45"), que aparece SÓ no resumo, não nas movimentações. Decisão: o schema
  captura o rendimento do resumo e ele vira **receita** (categoria própria "Rendimentos"), e entra no
  walk: `saldo_inicial + rendimento + Σreceita − Σdebito − Σpagamento_fatura = saldo_final`. Com ele,
  o walk fecha.
- **PII DE TERCEIROS — o extrato é muito mais pesado que a fatura.** Linhas de PIX/TED trazem nome,
  CPF, agência e conta de CONTRAPARTES (que não consentiram). Decisão de produção: **redigir o
  regex-confiável (CPF, agência, conta) ANTES de enviar ao Gemini** — nada disso é necessário pra
  classificar. Nome de contraparte é best-effort. E o **#4 ganha uma linha** reconhecendo que o extrato
  envia dado de terceiro ao subprocessador (ângulo distinto do dado do titular).

### A regra: extrato e fatura se RECONCILIAM, não se somam
Toda linha do extrato cai em um de três baldes:
1. **Receita** → nova entrada (Receitas).
2. **Débito / PIX / boleto direto** → despesa que já saiu (consumo + caixa).
3. **Pagamento de fatura de cartão** → **NÃO é despesa.** Vira `PagamentoFatura`.

### O extrato resolve DE GRAÇA a armadilha do histórico (+ sinergia #9)
O extrato **prova** quais faturas foram pagas, com **valor e data reais**. Cria o `PagamentoFatura`
automaticamente com `valor_pago` = o valor real do extrato (cobertura EXATA do #9, não "assume total") e
`data_pagamento` = a data real (não `None`). Em vez de o usuário marcar N faturas na mão, o extrato
marca por ele — e melhor do que o import de fatura conseguia.

### Reforço de modelo: nenhuma mudança estrutural
`PagamentoFatura` (agora com `valor_pago` do #9) já é a costura → o extrato é um novo *produtor* dele
(+ receitas + despesas de débito). A costura já existe.

### "Associadas ou não" — três casos
- **Os dois, mesmo cartão/período** → *associados*: o pagamento do extrato confirma a fatura. Não duplica.
- **Só o extrato** → verdade de caixa, sem as compras itemizadas → sinalizar "importe a fatura pra ver
  o detalhe".
- **Só a fatura** → fluxo já desenhado: pagamento confirmado pelo usuário.

### Sub-decisões — FECHADAS
- **Receita × recorrência (armadilha do salário duplicado):** na revisão, receitas que casam com uma
  recorrência existente (≈valor + ≈data) entram com default **"não importar — já é recorrência"**; o
  usuário pode sobrepor. Evita duplicar o salário (a recorrência já o conta como realizado).
- **Categorização do débito:** **auto-categoria via a sugestão do agente** (reusa `/ai/suggest-category`),
  não default "Outros". (Follow-up: retrofitar a mesma auto-categoria na importação de FATURA, hoje
  default "Outros" — consistência.)
- **Casamento pagamento↔fatura:** proposto na REVISÃO (cartão + competência + valor), o usuário
  confirma — nunca em silêncio. Usa a data real do extrato como `data_pagamento` e o valor real como
  `valor_pago`.
- **Primeiro banco:** Nubank conta.

### Escopo / fatiamento
Dobra a superfície (receita, débito, boleto, PIX, TED, casamento de pagamento). **GG — várias sessões.**
1. ✅ **SPIKE** — extração + classificação em três baldes, isolado, num extrato real Nubank anonimizado.
   Valida a peça mais nova (a classificação) antes de wirar produção — como o spike da fatura.
2. **Produção:** ✅ Batch 1 (preview stateless) → ✅ Batch 2 (enriquecimento: categoria sugerida,
   casamento de fatura, flag de recorrência) → ✅ **Batch 3 (commit)** → tela de revisão (três baldes).

### Batch 3 — o COMMIT (feito): decisões travadas
- **Materialização:** `receita` → `Transacao(tipo="receita")`; `debito` → `Transacao(tipo="despesa",
  forma_pagamento="Débito")` **sem cartao_id e sem fatura_mes/ano** (é caixa que JÁ SAIU: cai na
  Fonte 3 da projeção, realizada, nunca `a_pagar` — travado por teste E2E no `/statistics/monthly`);
  `pagamento_fatura` → `PagamentoFatura`, nunca lançamento; `rendimento` → receita `"Rendimentos"`
  (categoria PADRÃO nova) na data final do período, só se > 0.
- **Prevalência (#9) — real vence assumido, nas DUAS ordens:** o commit de extrato SEMPRE escreve
  `valor_pago` = valor REAL da linha e `data_pagamento` = data REAL; e o commit de FATURA passou a
  PRESERVAR competência que já tem `pago=True` (antes sobrescrevia com o total assumido e zerava a
  data) — reportado no recibo em `faturas_ja_confirmadas`. Resíduo (proveniência) → PENDÊNCIA 32.
- **Idempotência:** tabela `import_extrato_lote` com `UNIQUE(usuario_id, banco, periodo_de,
  periodo_ate)`, inserida PRIMEIRO na transação (409 atômico). Banco normalizado → PENDÊNCIA 33.
  Período ausente = 422 (sem ele não há chave). O `/auth/reset-data` passou a apagar os DOIS lotes de
  importação — senão zerar os dados travaria o reimport em 409 para sempre.
- **Revisão manda, servidor confere:** cada linha traz `importar` TRI-ESTADO — ausente significa
  "não decidido" e o servidor aplica o default seguro, recomputando o casamento receita×recorrência
  (a armadilha do salário mora no BACKEND, não na flag do front). Categoria revalidada contra a lista
  do usuário; cartão contra a propriedade (404); competência contra `fatura_existe` (422 "importe a
  fatura" — `PagamentoFatura` em competência vazia é fantasma invisível na UI).

---

## PRÉ-REQUISITOS DE LANÇAMENTO — TODOS FECHADOS
- ✅ **#4 Termos/Privacidade** — Gemini pago/subprocessador + fluxo de importação declarados.
- ✅ **F-06** — o caminho de importação ganhou `BLOCK_ONLY_HIGH` explícito (não mais default do provedor).
- ✅ **#7 fantasma "services vazio"** — corrigido em docs + brief + memória.
- ✅ **Gemini pago** (billing) + `GEMINI_IMPORT_API_KEY` dedicada no Railway.
- ✅ **`preDeployCommand`** — migrations aplicam no deploy (o `release:` do Procfile era ignorado).

---

## PRÓXIMO PASSO
Importação de FATURA: **completa, validada E2E, VIVA em produção.** #9 e estorno entregues na mesma leva.

**EXTRATO — backend COMPLETO:** spike ✅ → preview ✅ (Batch 1) → enriquecimento ✅ (Batch 2) →
commit ✅ (Batch 3, a primeira escrita: três baldes + rendimento, atômico e idempotente).

1. **Próximo: a TELA DE REVISÃO dos três baldes** (`hivvo-web`) — é o que falta para o fluxo do
   extrato existir para o usuário. O backend já entrega tudo que ela precisa: o preview traz a
   proposta por linha (categoria sugerida, fatura candidata, flag de recorrência) e o commit recebe
   as decisões (`importar` por linha, categoria, cartão+competência confirmados) e devolve o recibo.
2. **Validar E2E em produção** com extrato real (como foi com a fatura), incluindo o caso que junta
   as duas pontas: importar a fatura e o extrato do mesmo mês e ver a fatura virar `paga_parcial`
   com o valor REAL.
3. **Depois do extrato:** retenção — notificações (#6).

**Follow-ups menores registrados:** "faltam R$X" nas lentes de lista/competência (expor `valor_pago`);
retrofitar auto-categoria na FATURA (hoje default "Outros"); netting de estorno contra a compra-mãe;
TOCTOU cross-competência (raro); dívida dos `datetime.utcnow()`.

**Áreas novas a discutir (antes da próxima sessão):** guia de onboarding pra usuário novo; área de
feedback (anônimo ou não).

---

## Anexo — fatura Nubank (formato real)
- Cabeçalho: "FATURA 13 JUL 2026", "EMISSÃO 06 JUL 2026", período "06 JUN a 06 JUL".
- RESUMO: "Total de compras R$202,65" + "IOF R$3,41" = "Total a pagar R$206,06". Fatura anterior R$58,95
  / Pagamento recebido -R$58,95.
- Linhas: `DATA •••• final descrição R$ valor`. Parcelamento "Blacktag - Parcela 4/7".
- Internacional: "Anthropic BRL 20.00 = USD 3.86 · Conversão BRL 5.35 = USD 1".
- Seção "Pagamentos e Financiamentos": "Pagamento em 12 JUN -R$58,95"; "Saldo restante da fatura
  anterior R$0,00" (aparece DUAS vezes — é real).

## Anexo — fatura Itaú (formato real)
- "Resumo da fatura em R$": Total da fatura anterior 0,00 · Pagamento efetuado 16/06 -93,95 · Saldo
  financiado -93,95 · Lançamentos atuais 93,95 · **Total desta fatura 0,00** (líquido, quitado por
  débito automático).
- Âncora de consumo: "Total dos lançamentos atuais R$93,95".
- Cartão `4705.XXXX.XXXX.4189` → portador 4189. Linha: "15/06 JIM.COMANALUIZAPEREZ 93,95".
- **Lição:** "Total desta fatura" ≠ consumo do ciclo. Reconciliar por "Lançamentos atuais".
