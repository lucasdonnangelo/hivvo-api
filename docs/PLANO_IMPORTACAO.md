# Hivvo — Design da Importação de Fatura/Extrato

> Status: **DESENHO FECHADO (17/07/2026).** Substitui a versão "EM DESENHO".
> Decisões travadas em revisão com o Lucas. O que resta aberto está marcado "Ainda aberto".
>
> **SEQUÊNCIA DE ENTREGA (decidida 17/07):** importar **fatura primeiro**. Se a fatura validar
> (extração vence a digitação manual), **o extrato entra em seguida** — é a próxima fatia, não um
> "talvez". A importação de extrato está DESENHADA aqui (seção própria), mas só se implementa depois
> de a fatura provar o valor. Fatura e extrato são entradas independentes que se reconciliam numa
> única costura: o pagamento da fatura.
>
> **VALIDAÇÃO CONCLUÍDA (17/07):** spike rodado em 2 faturas reais (Nubank, Itaú) no Gemini free.
> Extração impecável nas duas. Rota LLM confirmada. Ver seção "VALIDAÇÃO DO SPIKE".
>
> **PROGRESSO DE PRODUÇÃO (17/07):**
> - ✅ **Batch 1** — `POST /import/fatura/preview` (extração stateless + reconciliação). Commit `d1f1073`.
> - ✅ **Batch 2** — `POST /import/fatura/commit` (materialização + idempotência atômica via
>   `import_fatura_lote`). Correto para UMA fatura. Commitado.
> - ✅ **Batch 3 (multi-fatura)** — dedup de parcela ENTRE importações. Fork (Y) fechado e
>   implementado: ver seção "MULTI-FATURA". Materialização vira multi-mês sem duplicar a parcelada
>   em andamento.

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
  - A identidade é **computável dos campos que já existem** (`cartao_id`, `descricao`, `total_parcelas`,
    e a competência derivada de `transacao.data`/1ª parcela) — avaliar se um fingerprint guardado é mais
    robusto que recomputar. Borda: duas parceladas de mesma descrição/total/origem no mesmo cartão
    (raro) — desempatar por valor.

**Impacto no código:** é ADIÇÃO ao `persistencia.py` do Batch 2 (uma checagem de dedup antes de
materializar parcelada), não reescrita. Endpoint, guard do lote, atomicidade e testes ficam.

### Sub-decisões do Y — FECHADAS (Batch 3)

**Fingerprint guardado vs recomputar → RECOMPUTAR (identidade em query, sem coluna nova).** Em cima do
modelo real: todos os campos da identidade já estão persistidos — `cartao_id`+`total_parcelas` na
`Transacao`; a **origem implícita = competência da `Parcela` nº 1** (a materialização grava
parcela j em âncora−(indice−j); j=1 ⇒ âncora−(indice−1) = origem — casa por construção com o Batch 2);
descrição **limpa** na `Transacao.descricao` (a extração separa lojista de "Parcela X/N" → o match é
limpa↔limpa, o sufixo `(i/N)` da `Parcela.descricao` nunca entra). Um fingerprint não seria mais
robusto: hasheia o **mesmo** `norm(descricao)` frágil, e a única vantagem (um `UNIQUE` atômico) não é
expressável nesta identidade (o valor precisa estar FORA para robustez e DENTRO para o desempate).
Recompute evita coluna + migration + backfill das parceladas do Batch 2 já importadas.

**Identidade + skip (contra SNAPSHOT de imports ANTERIORES):** no topo da materialização tira-se um
snapshot `{(desc_norm, total, origem_mes, origem_ano, valor_parcela_centavos)}` das parceladas já
importadas do cartão (`origem="importacao"`, via `Parcela` nº 1), **antes de qualquer insert**. Cada
linha parcelada nova computa a mesma chave; se está no snapshot → **PULA**; senão → materializa 1/N..N/N
(lógica do Batch 2 intacta). Decidir contra o snapshot (não contra a query viva) garante: duas linhas
**idênticas na MESMA fatura** são duas compras e **ambas materializam** (contar a mais é corrigível na
revisão; a menos é invisível). Cross-fatura (import anterior) funde. Ordem-independente (julho→agosto e
agosto→julho dão o mesmo resultado). Skip visível no recibo (`parceladas_deduplicadas`).

**Desempate por valor:** o `valor_parcela` (em centavos) entra na CHAVE, não só na colisão. Duas
parceladas de mesma desc/total/origem mas valor distinto (105,26 vs 200,00) são compras DISTINTAS →
ambas materializam; um valor novo num import posterior nunca é engolido por uma existente (viés
anti-perda-de-dado — perder lançamento real seria pior que duplicar).

**Confirmação de pagamento das passadas:** o gate deixa de exigir "competência ∈ o que ESTE import
criou" e passa a aceitar competência **estritamente antes da âncora** que tenha **algum lançamento
EXISTENTE deste cartão** (parcela ou avulsa — criado neste request OU por import anterior). Com dedup, a
parcelada passada pode ter sido PULADA neste import e ainda assim ser marcável (ela existe de outro).
Continua barrando fatura arbitrária (sem lançamento → 422) e a própria/futura (≥ âncora).

### Bordas documentadas (Batch 3)
- **Drift de centavo da mesma parcelada** (última parcela arredondada: 105,26 vs 105,20) entre imports →
  valor difere → **duplica**. Aceito e **visível** (duas transações); preço de seguir "desempate por
  valor" à risca e nunca perder lançamento. O Batch 2 já não modela parcelas desiguais.
- **Colisão com valores IGUAIS** (duas compras idênticas em desc/total/origem/valor, faturas diferentes)
  → fundidas como uma (conservador; fundir idêntico > duplicar). Na MESMA fatura, ambas entram (snapshot).
- **Descrição muda muito entre faturas** ("Blacktag" vs "BLACKTAG\*PARCELA") → quebra a identidade em
  QUALQUER método (fingerprint idem) → duplicaria. Risco inerente à identidade, não ao recompute.
  `norm` cobre caixa/espaço (colapsa espaços + casefold), NÃO acento.
- **Manual vs import:** o dedup é escopo `origem="importacao"` — parcelada manual e importada coexistem
  (o import não engole a manual). Fora de escopo aqui.
- **Concorrência cross-competência:** dois commits simultâneos de competências distintas da MESMA
  parcelada (fora do fluxo humano de revisão, 1 fatura por vez) têm janela TOCTOU no snapshot → possível
  duplicata. Mitigação (advisory lock por cartão no Postgres) DEFERIDA; o rate-limit + fluxo humano
  cobrem por ora.

---

## A DECISÃO-PIVÔ: extração via LLM, não parser determinístico

O pedaço 🔴 do design nunca foi "ler o arquivo" — foi **interpretar** as linhas (isto é parcela?
isto é IOF? isto é pagamento da fatura?). Duas rotas:

- **Parser determinístico (regex por banco):** dado nunca sai da infra, MAS é frágil, exige muitos
  exemplos por banco, e tem **cauda de manutenção infinita** para um dev solo. **REJEITADO** por ser
  o maior risco de desperdício de recurso.
- **LLM (extração texto → JSON estruturado):** um schema serve todos os bancos, sem regex por banco.
  **ESCOLHIDO.** A imperfeição é aceitável porque a **tela de revisão obrigatória** é a rede.

### Régua da feature (o alvo certo)
NÃO é acurácia de 100% (impossível, e é o alvo errado). É **"melhor que digitar à mão"**. A tela de
revisão não é o remendo de uma feature imperfeita — **ela é o produto.**

---

## EXTRATOR PLUGÁVEL

A extração é um **passo plugável** com contrato fixo: **texto da fatura entra → JSON estruturado sai.**
Escolha do provedor de IA reversível sem tocar no resto (revisão, modelagem, commit não mudam).

- **Gemini free** — só para VALIDAR qualidade (com fatura anonimizada). Nunca em produção: o free
  treina com o dado e revisores humanos podem ver.
- **Gemini pago** — produção contratualmente privada: **não treina**, retenção limitada, ZDR
  disponível. Continua subprocessador (→ exige #4). Setup quase nulo.
- **Modelo local self-hosted** — dado **nunca sai** da infra. Qualidade menor (a revisão fecha o gap).
  Custo: infra + setup, NÃO manutenção por banco.

---

## VALIDAÇÃO DO SPIKE (17/07/2026)

Spike isolado em `scripts/spike_import/` (fora do app), rodado em **2 faturas reais** no **Gemini
free**: `fatura_nubank_platinum.pdf` e `fatura_itau_platinum.pdf`.

### Resultado: extração impecável nas duas
Conferido campo a campo contra os PDFs. **Zero erro de conteúdo.**
- **Nubank (8 linhas):** Blacktag Parcela 4/7, os dois IOF, Anthropic e Cloudflare com internacional
  (USD, taxa, portador), pagamento como `pagamento`. A linha "Saldo restante" **duplicada é real no
  PDF** — o modelo reproduziu fielmente, não alucinou.
- **Itaú (2 linhas):** capturou tudo que a fatura tem (1 compra + 1 pagamento). Nada perdido.
- Campos a corrigir na mão: **praticamente zero.** A régua "vence a digitação" está batida no free.

### O achado: reconciliar pelo TOTAL DE COMPRAS DO CICLO, não pelo "total a pagar"
O Itaú deu "NÃO BATE" — **não por erro de extração**, mas porque o modelo pegou "Total desta fatura =
R$0,00" (o *líquido a pagar*, já quitado por débito automático) em vez do consumo bruto. O Nubank
"bateu" por **coincidência do mês** (a fatura anterior foi 100% paga, então "Total a pagar" calhou de
igualar o bruto; com saldo anterior sobrando, não bateria).

**Correção travada:** a reconciliação ancora no **total de compras/lançamentos do ciclo**, que os dois
bancos expõem explicitamente:
- Itaú: "Total dos lançamentos atuais → R$93,95"
- Nubank: "Total de compras 06 JUN a 06 JUL → R$202,65" + "IOF R$3,41" = R$206,06

Com esse âncora, **as duas batem**. É fix de schema/código, não de LLM. O **cheque secundário**
(gastos + excluídos vs total) fez o trabalho pra que foi desenhado: apontou "o total deste banco
inclui pagamentos". Ganhou o lugar.

### Privacidade: redação best-effort NÃO é blindagem
No run de validação, o `--redact "Lucas Donnangelo"` **não pegou** o nome completo
(`LUCAS JANNUZZI REIS DONNANGELO`, e a forma sem espaços do `layout=True`) nem o endereço do Itaú —
foram pro Gemini free. Lição: **produção = Gemini pago + #4 declarado, não free-com-redação.** A
redação é rede para o teste, não garantia.

### Achados menores pro modelo de produção (anotar)
- O pagamento do Nubank (-R$58,95) é da fatura **anterior** ("Fatura anterior / Pagamento recebido"),
  não desta competência → na produção NÃO deve virar `PagamentoFatura` deste ciclo.
- O `portador_final` (ex.: 4189) é a âncora confiável do portador — **não o nome** (o Itaú traz
  variantes: `LUCASJRDONNANGELO` vs completo).

---

## DECISÕES DE PRODUTO — TRAVADAS

| # | Decisão | Resolvido |
|---|---|---|
| 1 | **Formato de entrada** | **PDF** (faturas de banco são PDF digital, texto extraível determinístico — 🟡). Interpretação das linhas = passo LLM. PDF escaneado/imagem → OCR (🔴), fora do escopo inicial. |
| 2 | **Fatura vs extrato** | **Fatura por ciclo** (não extrato). Casa com competência de fatura. |
| 3 | **Cartão obrigatório** | O cartão DEVE existir antes. Fluxo: **cadastra cartão → importa a fatura dele**. |
| 4 | **Escopo do passado** | **Histórico completo.** Ver a armadilha do pagamento abaixo. |
| 5 | **Parcelamento `X/Y`** | Cria as **futuras** (competência += 1 mês, valor = o mostrado). Com histórico completo, materializa também as passadas (como fatos já pagos após confirmação em bloco). |
| 6 | **Revisão** | **Obrigatória.** Tela onde o usuário vê, corrige (categoria, valor, parcelamento) e confirma antes de gravar. |
| 7 | **Múltiplos finais na mesma fatura** | **Mesma fatura = mesmo cartão no Hivvo.** O final é o portador físico (`portador_final` por linha). |
| 8 | **Seção "Pagamentos e Financiamentos"** | **Excluir** da importação de transações (abatimento, não gasto). |
| 9 | **IOF** | **Importar como despesa própria**, categoria "Taxas/IOF" (entra em `soma_gastos`, senão a fatura não fecha). |
| 10 | **Conversão de moeda** | Usar o **valor em R$**. Conversão (moeda, valor orig, taxa) = metadado. |

### ⚠️ Armadilha do histórico: importar passado quebra o "A pagar"
O modelo **deriva status e nunca presume pago pela data**. Histórico cru → toda fatura passada nasce
não-paga → o Bloco 1 "A pagar" explode. **Solução obrigatória:** passo de **confirmar em bloco o
pagamento das faturas fechadas** na revisão.

### Reconciliação — o guarda-costas determinístico da extração por LLM
Depois que o LLM devolve o JSON, o **backend valida que a soma bate**, tudo em `Decimal`:
- **Âncora = total de compras/lançamentos do ciclo** (o consumo bruto), NÃO "total a pagar"/"total
  desta fatura" (que embutem saldo anterior/pagamentos e variam de banco pra banco). Ver
  "VALIDAÇÃO DO SPIKE" — foi o achado das faturas reais.
- `soma_gastos` = Σ das linhas `{compra, iof}` (parcelas do mês são linhas de compra; estornos são
  compra negativa).
- **Cheque secundário** (`soma_gastos + excluídos` vs total a pagar): quando o primário não bate,
  distingue "semântica do total do banco" de "erro do LLM". Provou-se útil na fatura do Itaú.
- Se não bater, sinaliza na revisão — nunca grava no escuro.

---

## ARQUITETURA
- **Fronteira:** extração + modelagem no **backend** (lógica de negócio nunca no front). Revisão é
  display + edição. Commit re-valida no backend.
- **Stateless — SEM tabela nova.** `POST` do PDF → backend extrai → valida (reconciliação) → devolve
  JSON → frontend segura em memória → usuário revisa → `POST` final grava em `transacoes`/`parcelas`.
  - ⚠️ **Se um dia** persistir o batch → tabela nova **COM `ENABLE ROW LEVEL SECURITY` no
    `upgrade()`** (o Alembic não sabe de RLS → tabela nova nasce exposta). Começar SEM.
- **Reuso:** a modelagem reusa o modelo de parcela/fatura que já existe.

---

## IMPORTAÇÃO DE EXTRATO (fatia seguinte — implementa DEPOIS da fatura validar)

Fatura e extrato descrevem o **mesmo dinheiro por dois lados** — importá-los ingênuo **conta em
dobro**. A linha "Pagamento fatura Nubank -R$500" no extrato **não é gasto novo** — é a quitação das
compras que a fatura já capturou.

### A regra: extrato e fatura se RECONCILIAM, não se somam
Toda linha do extrato cai em um de três baldes:
1. **Receita** → nova entrada (alimenta Receitas).
2. **Débito / PIX / boleto direto** → despesa que já saiu (consumo + caixa).
3. **Pagamento de fatura de cartão** → **NÃO é despesa.** Vira `PagamentoFatura`, casado com a fatura
   daquele cartão/competência.

### O extrato resolve DE GRAÇA a armadilha do histórico
O extrato **prova** quais faturas foram pagas e quando → cria o `PagamentoFatura` automaticamente. Em
vez de o usuário marcar N faturas na mão, o extrato marca por ele.

### Reforço de modelo: nenhuma mudança estrutural
`PagamentoFatura` já é a fonte única de "fatura paga" → o extrato é só um novo *produtor* dele (+
receitas + despesas de débito). A costura já existe.

### "Associadas ou não" — três casos
- **Os dois, mesmo cartão/período** → *associados*: o pagamento do extrato confirma a fatura. Não
  duplica.
- **Só o extrato** → tem-se a verdade de caixa, não as compras itemizadas → sinalizar "importe a
  fatura pra ver o detalhe".
- **Só a fatura** → fluxo já desenhado: pagamento confirmado pelo usuário.

Casamento pagamento↔fatura por (cartão, valor, data ≈ vencimento), **proposto na revisão**, nunca em
silêncio.

### Escopo
Dobra a superfície (receita, débito, boleto, PIX, TED, casamento de pagamento). Fatia **seguinte**,
não primeira — mas entrega firme assim que a fatura validar. Sub-decisões (categorização de débito;
receita colidindo com recorrência já cadastrada, pra não duplicar salário): **Ainda aberto**, não
bloqueia a fatura.

---

## FATIA VERTICAL (a primeira entrega de produção)

**Um banco (Nubank), fatura real, cartão já cadastrado, revisão obrigatória, ponta-a-ponta.** O
segundo banco só depois do primeiro fechar. Não construir "importação" como plataforma antes de um
caminho funcionar.

### Fatiamento (esforço)
1. Extração PDF → texto (determinístico): 🟡 — **validado no spike.**
2. Interpretação texto → JSON (LLM, schema único): 🟡 — **validado no spike.**
3. Reconciliação (âncora = total de compras): 🟢 — **corrigir âncora (ver achado).**
4. Filtro de não-compras: 🟢-🟡.
5. Modelagem → transações/parcelas (reusa o existente): 🟡.
6. Confirmação de pagamento em bloco das faturas passadas: 🟡.
7. Tela de revisão/edição: 🟡 frontend.

**GG — várias sessões.** Uma fatia por vez, aprovação explícita antes de cada commit.

---

## PRÉ-REQUISITOS (antes da 1ª fatura REAL em produção)
- **#4 Termos/Privacidade** — vira **pré-requisito técnico**: declarar **Google/Gemini como
  subprocessador** antes de a importação mandar fatura real pro Gemini pago em produção.
- **F-06** — confirmar se os filtros do Gemini ainda estão em `BLOCK_NONE`.
- **Confirmar o tier do assistente hoje (free vs pago).** Se free, a exposição do chat já existe.

*(A validação com fatura ANONIMIZADA no Gemini free — já concluída — não dependeu de #4.)*

---

## PRÓXIMO PASSO
Importação de fatura CODE-COMPLETE ponta a ponta (backend + frontend). Falta validar e declarar.
1. ✅ Ajuste no preview (faturas_passadas) — entregue.
2. ✅ Tela de revisão (hivvo-web) — implementada (build/tsc/lint limpos). ⚠️ E2E isolado PENDENTE:
   preview é read-only (E2E livre); o COMMIT escreve → só contra banco descartável, nunca o .env de prod.
3. **E2E ponta a ponta** (upload → preview → revisão → commit) em conta descartável — onde os bugs
   reais aparecem. Confirmar que "A pagar"/projeção se mexem após importar.
4. **#4 Termos/Privacidade** — pré-requisito ANTES de abrir pra usuários reais (edições já redigidas).
5. **Ir ao ar** com a fatura (fatia Nubank), tier pago + #4 no ar.
6. **Extrato** — a fatia seguinte.

---

## Anexo — o que a fatura do Nubank revelou (formato real)
- Cabeçalho: "FATURA 13 JUL 2026", "EMISSÃO 06 JUL 2026", período "06 JUN a 06 JUL".
- RESUMO: "Total de compras ... R$202,65" + "IOF R$3,41" = "Total a pagar R$206,06". Fatura anterior
  R$58,95 / Pagamento recebido -R$58,95.
- Linhas: `DATA •••• final descrição R$ valor`. Parcelamento "Blacktag - Parcela 4/7".
- Internacional: "Anthropic BRL 20.00 = USD 3.86 · Conversão BRL 5.35 = USD 1".
- Seção "Pagamentos e Financiamentos": "Pagamento em 12 JUN -R$58,95"; "Saldo restante da fatura
  anterior R$0,00" (aparece DUAS vezes — é real).

## Anexo — o que a fatura do Itaú revelou (formato real)
- "Resumo da fatura em R$": Total da fatura anterior 0,00 · Pagamento efetuado 16/06 -93,95 · Saldo
  financiado -93,95 · Lançamentos atuais 93,95 · **Total desta fatura 0,00** (líquido a pagar, já
  quitado por débito automático).
- Âncora de consumo: "Total dos lançamentos atuais R$93,95".
- Cartão `4705.XXXX.XXXX.4189` → portador 4189. Linha: "15/06 JIM.COMANALUIZAPEREZ 93,95".
- **Lição:** "Total desta fatura" ≠ consumo do ciclo. Reconciliar por "Lançamentos atuais".
