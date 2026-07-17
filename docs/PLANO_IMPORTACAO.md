# Hivvo — Design da Importação de Fatura/Extrato

> Status: **DESENHO FECHADO (17/07/2026).** Substitui a versão "EM DESENHO".
> Decisões travadas em revisão com o Lucas. O que resta aberto está na seção "Ainda aberto" —
> e nada disso bloqueia a primeira fatia.
>
> **SEQUÊNCIA DE ENTREGA (decidida 17/07):** importar **fatura primeiro**. Se a fatura validar
> (extração vence a digitação manual), **o extrato entra em seguida** — é a próxima fatia, não um
> "talvez". A importação de extrato está DESENHADA aqui (seção própria), mas só se implementa depois
> de a fatura provar o valor. Fatura e extrato são entradas independentes que se reconciliam numa
> única costura: o pagamento da fatura.
> Filosofia: o Hivvo é planejador — o usuário traz o passado (fatos na mesa) para planejar o
> futuro. A importação é o que torna o "Cenário 1" (usuário com histórico) viável em escala, sem
> digitação manual de 7 extratos. Sem ela, quase todo usuário novo cai no Cenário 2 (sem histórico),
> e o Resumo — que só floresce com 6 meses — nunca entrega valor a quem não persistiu meio ano.

---

## A DECISÃO-PIVÔ: extração via LLM, não parser determinístico

O pedaço 🔴 do design nunca foi "ler o arquivo" — foi **interpretar** as linhas (isto é parcela?
isto é IOF? isto é pagamento da fatura?). Duas rotas para essa interpretação:

- **Parser determinístico (regex por banco):** dado nunca sai da infra, MAS é frágil, exige muitos
  exemplos por banco, e tem **cauda de manutenção infinita** para um dev solo — cada banco novo,
  cada mudança de layout, é o Lucas. **REJEITADO** por ser o maior risco de desperdício de recurso.
- **LLM (extração texto → JSON estruturado):** um schema serve todos os bancos, sem regex por banco.
  **ESCOLHIDO.** A imperfeição é aceitável porque a **tela de revisão obrigatória** é a rede — o
  usuário corrige antes de gravar. Extração não precisa ser perfeita; precisa ser melhor que digitar.

### Régua da feature (o alvo certo)
NÃO é acurácia de 100% (impossível, e é o alvo errado). É **"melhor que digitar à mão"**. Se a
importação traz 40 transações com 80% certas e o usuário corrige 8 em vez de digitar 40, venceu.
A tela de revisão não é o remendo de uma feature imperfeita — **ela é o produto.**

---

## EXTRATOR PLUGÁVEL (a decisão que tira a aposta única)

A extração é um **passo plugável** com contrato fixo: **texto da fatura entra → JSON estruturado sai.**
Isso torna a escolha do provedor de IA reversível sem tocar no resto do fluxo (revisão, modelagem,
commit não mudam uma linha).

Três implementações possíveis do mesmo contrato:
- **Gemini free** — só para VALIDAR qualidade (com fatura anonimizada). Não usar em produção: o free
  treina com o dado e revisores humanos podem ver.
- **Gemini pago** — produção contratualmente privada: **não treina** com o prompt, retenção limitada
  (dias, só abuso/legal), ZDR disponível por adendo. Continua subprocessador (→ exige #4). Custo de
  setup quase nulo.
- **Modelo local self-hosted** (Ollama/llama.cpp, modelo pequeno) — dado **nunca sai** da infra.
  Qualidade menor que o Gemini (a revisão fecha parte do gap). Custo: infra + setup, NÃO manutenção
  por banco. Import é evento raro (onboarding) → CPU serve, sem GPU sempre ligada.

### Sequência de validação (embutida, descartável)
1. **Fatura ANONIMIZADA** (tira nome/CPF/final do cartão — deixa data/descrição/valor/`X/Y`) →
   **Gemini free** → mede se a extração vence a digitação manual. Sinal de qualidade com quase zero
   exposição. O que se testa (detecta parcela? separa IOF? ignora pagamentos?) não precisa da
   identidade.
2. Se prestar → **Gemini pago** é decisão direta (mesma qualidade, sem treinar, sem reter).
3. Se inclinar pro **local** → NÃO decidir pelo resultado do free (free ≈ pago em qualidade; local é
   mais fraco). Rodar a mesma fatura no modelo local real e comparar. Só aí decidir.

⚠️ **O free valida o caminho Gemini, não o local.** Concluir "funcionou no free → vou de local" é
armadilha: mediu-se a qualidade do Gemini, não a do modelo local.

---

## DECISÕES DE PRODUTO — TRAVADAS

| # | Decisão | Resolvido |
|---|---|---|
| 1 | **Formato de entrada** | **PDF** (faturas de banco são PDF digital, com camada de texto extraível deterministicamente — 🟡 mecânico). A interpretação das linhas é o passo LLM. ⚠️ Se algum banco exportar PDF **escaneado/imagem**, precisa OCR (🔴) — **fora do escopo inicial**. |
| 2 | **Fatura vs extrato** | **Fatura por ciclo** (não extrato). Casa com o modelo (competência de fatura), já traz o recorte de fechamento pronto. |
| 3 | **Cartão obrigatório** | O cartão DEVE existir antes. Fluxo: **cadastra cartão → importa a fatura dele**. A fatura é "para" um cartão com ciclo de fechamento conhecido. |
| 4 | **Escopo do passado** | **Histórico completo** (o usuário quer "fatos na mesa"). Ver a armadilha do pagamento abaixo — é consequência direta desta decisão. |
| 5 | **Parcelamento `X/Y`** | Cria as parcelas **futuras** (competência += 1 mês cada, valor = o mostrado, assumindo parcelas iguais). Como o escopo é histórico completo, **também materializa as passadas** — que entram como fatos já pagos após a confirmação em bloco. |
| 6 | **Revisão** | **Obrigatória.** Tela onde o usuário vê as N transações detectadas, corrige (categoria, valor, parcelamento) e confirma antes de gravar. |
| 7 | **Múltiplos finais na mesma fatura** | **Mesma fatura = mesmo cartão no Hivvo.** O final (6042, 9493) é só o portador físico. |
| 8 | **Seção "Pagamentos e Financiamentos"** | **Excluir** da importação de transações (é abatimento da fatura, não gasto — inverteria o sinal e poluiria). |
| 9 | **IOF** | **Importar como despesa própria**, categoria "Taxas/IOF". Razão: a soma das linhas importadas tem que bater com o total da fatura (ver reconciliação) — ignorar o IOF quebraria o fechamento. |
| 10 | **Conversão de moeda (internacional)** | Usar o **valor em R$** (o que importa pra fatura). A conversão (USD, taxa) é metadado — guardar opcional ou ignorar. |

### ⚠️ Armadilha do histórico: importar passado quebra o "A pagar"
O modelo **deriva status e nunca presume pago pela data**. Se o histórico entra cru, **toda fatura
passada nasce não-paga** → o Bloco 1 "A pagar" explode com dívida já quitada, e cada fatura antiga
aparece "atrasada". Não se pode auto-marcar como paga (viola a regra do modelo).

**Solução obrigatória:** passo de **confirmar em bloco o pagamento das faturas fechadas** na revisão.
O usuário vê "estas N faturas passadas — marcar como pagas?" e confirma. Fatos na mesa sem mentir
sobre o status. Sem esse passo, importar histórico quebra o dashboard.

### Reconciliação — o guarda-costas determinístico da extração por LLM
Depois que o LLM devolve o JSON, o **backend valida que a soma bate**:
`soma(transações) + IOF + ajustes == total da fatura`. Se não bater, sinaliza na revisão ("faltam
R$X pra fechar a fatura — confira"). Este é o cheque determinístico que torna a extração por LLM
confiável: o modelo pode errar uma linha, mas o total denuncia. É a diferença entre "confio no LLM"
e "verifico o LLM".

---

## ARQUITETURA

- **Fronteira (regra não-negociável):** extração + modelagem no **backend** (lógica de negócio nunca
  no front). A tela de revisão é só **display + edição**. O commit final **re-valida no backend**.
- **Stateless — SEM tabela nova.** Fluxo: `POST` do PDF → backend extrai (texto → LLM → JSON) →
  valida (reconciliação) → **devolve o JSON** → frontend segura em memória → usuário revisa/edita →
  `POST` final grava em `transacoes`/`parcelas`. Evita superfície de RLS e é mais simples.
  - ⚠️ **Se um dia** precisar persistir o batch (retomar revisão depois de fechar a aba), aí sim
    tabela nova — e **COM `ENABLE ROW LEVEL SECURITY` no `upgrade()`** (regra permanente: o Alembic
    não sabe de RLS → tabela nova nasce exposta). Começar SEM.
- **Reuso:** a modelagem (distribuir parcelas nas faturas certas por cartão/competência) **reusa o
  modelo de parcela/fatura que já existe** — não reinventa.

---

## IMPORTAÇÃO DE EXTRATO (fatia seguinte — implementa DEPOIS da fatura validar)

Fatura e extrato descrevem o **mesmo dinheiro por dois lados** — e por isso importá-los ingênuo
**conta em dobro**:
- **Fatura** (cartão de crédito) = as compras individuais → consumo, parcelas, "a pagar".
- **Extrato** (conta corrente) = o fluxo de caixa → receitas, gastos que já saíram (débito, PIX,
  boleto), **e o pagamento da fatura**.

A linha "Pagamento fatura Nubank -R$500" no extrato **não é gasto novo** — é a quitação das compras
que a fatura já capturou. Mesma lógica da seção "Pagamentos e Financiamentos" (item #8), agora no
nível do extrato.

### A regra: extrato e fatura se RECONCILIAM, não se somam
Toda linha do extrato cai em um de três baldes:
1. **Receita** → nova entrada (alimenta Receitas).
2. **Débito / PIX / boleto direto** → despesa que já saiu (consumo + caixa).
3. **Pagamento de fatura de cartão** → **NÃO é despesa.** Vira um `PagamentoFatura`, casado com a
   fatura daquele cartão/competência.

### O extrato resolve DE GRAÇA a armadilha do histórico
A armadilha (item "Armadilha do histórico"): importar histórico faz toda fatura passada nascer
não-paga → o Bloco 1 "A pagar" explode. O extrato **prova** quais faturas foram pagas e quando — a
linha de pagamento cria o `PagamentoFatura` automaticamente. Em vez de o usuário marcar N faturas na
mão, o extrato marca por ele.

### Reforço de modelo: nenhuma mudança estrutural
Como o `PagamentoFatura` **já é a fonte única** de "fatura paga", o extrato é apenas um novo
*produtor* de `PagamentoFatura` (+ receitas + despesas de débito). A costura que a feature precisa já
existe — não se pinta num canto ao adiar.

### "Associadas ou não" — os três casos
- **Os dois, mesmo cartão/período** → *associados*: o pagamento do extrato confirma a fatura
  importada. Reconcilia, não duplica.
- **Só o extrato** → tem-se a verdade de caixa (saiu R$500), mas não as compras itemizadas nem as
  parcelas. Preferência do planejador: sinalizar "você pagou uma fatura que não temos — importe ela
  pra ver o detalhe", em vez de gravar um gasto opaco "fatura Nubank" (que degrada o consumo).
- **Só a fatura** → o fluxo já desenhado: compras conhecidas, pagamento confirmado pelo usuário.

O casamento pagamento↔fatura é por (cartão, valor, data ≈ vencimento), **proposto na revisão** —
nunca associado em silêncio.

### Escopo
O extrato **dobra a superfície** (tipos de linha novos: receita, débito, boleto, PIX, TED, casamento
de pagamento). Por isso é fatia **seguinte**, não a primeira — mas é entrega firme assim que a fatura
validar, não um "talvez". Sub-decisões a fechar quando chegar a vez: categorização automática das
linhas de débito, e o que fazer com receitas que colidem com recorrências já cadastradas (evitar
duplicar salário). **Ainda aberto** — não bloqueia a fatura.

---

## FATIA VERTICAL (a primeira entrega)

**Um banco (Nubank), uma fatura real, um cartão já cadastrado, revisão obrigatória, ponta-a-ponta.**
Ataca o pedaço mais difícil (o `X/Y` + reconciliação) primeiro, mas atrás da revisão, onde errar é
barato. O Lucas é o `usuario_id=2`, multi-cartão, o público-alvo exato — se a fatia não poupar tempo
*a ele*, aprendeu-se barato e para. **O segundo banco só depois do primeiro fechar ponta-a-ponta.**
Não construir "importação" como plataforma geral antes de um caminho funcionar — esse é o desperdício
real.

### Fatiamento (esforço)
1. **Extração PDF → texto** (determinístico, camada de texto): 🟡 mecânico.
2. **Interpretação texto → JSON** (o passo LLM, schema único): 🟡 com LLM (era 🔴 com regex).
3. **Reconciliação** (soma bate com o total): 🟢.
4. **Filtro de não-compras** (seção Pagamentos, saldos): dobra no schema do LLM + cheque — 🟢-🟡.
5. **Modelagem → transações/parcelas** (distribuir por fatura/cartão, reusa o existente): 🟡.
6. **Confirmação de pagamento em bloco das faturas passadas:** 🟡 (backend + revisão).
7. **Tela de revisão/edição:** 🟡 frontend.

**É feature de várias sessões (GG).** Não cabe num único batch. Uma fatia por vez, aprovação
explícita antes de cada commit.

---

## PRÉ-REQUISITOS (antes de mandar a 1ª fatura REAL pro modelo em produção)
- **#4 Termos/Privacidade** deixa de ser "próximo por prioridade" e vira **pré-requisito técnico**:
  precisa declarar **Google/Gemini como subprocessador** dos dados financeiros antes de a importação
  mandar a primeira fatura real pro Gemini pago em produção. Atacar #4 nesse embalo.
- **F-06** — confirmar se os filtros do Gemini ainda estão em `BLOCK_NONE`. Fatura é dado ainda mais
  sensível que o chat.
- **Confirmar o tier do assistente hoje (free vs pago).** Se o assistente roda no Gemini **free**, os
  dados do chat **já** estão sendo usados pra treinar (revisores humanos inclusive) — exposição que
  existe independente da importação.

*(A validação com fatura ANONIMIZADA no Gemini free — passo 1 da sequência — não depende de #4,
porque não é dado real identificável nem é produção.)*

---

## PRÓXIMO PASSO IMEDIATO (não é código ainda)
1. **Coletar 3-4 faturas reais** de bancos diferentes, com parcelamentos variados (insumo essencial —
   um exemplo só não valida a extração nem a revisão contra a realidade).
2. **Rodar a validação:** fatura anonimizada → Gemini free → medir se a extração vence a digitação.
3. **Só então** o primeiro batch pro Claude Code (extração PDF→texto + schema do LLM, na fatia Nubank).

O primeiro prompt fechado pro Claude Code nasce DEPOIS de a validação confirmar que a extração presta.
Fechar design ≠ acionar executor — o próximo passo aqui é o teste de validação, não um batch.

**E DEPOIS da fatura entregar:** implementar o **extrato** (seção acima) — próxima fatia firme, não
opcional. A ordem é: fatura → valida → fatura implementada → extrato implementado.

---

## Anexo — o que a fatura do Nubank revelou (formato real, 07/07/2026)
- Cabeçalho: titular, "FATURA 13 JUL 2026", "EMISSÃO 06 JUL 2026", período "DE 06 JUN A 06 JUL".
- Agrupamento por portador/cartão (finais 6042, 9493 — múltiplos finais na mesma fatura).
- Linhas: `DATA | (ícone) final | descrição | valor`.
- Parcelamento na descrição: "Blacktag - Parcela 4/7 · R$105,26" (mostra a parcela do mês + o índice,
  não o total nem o início).
- IOF: "IOF de Anthropic R$0,72".
- Internacional: "Anthropic BRL 20.00 = USD 3.86"; "Cloudflare USD 14.20 · Conversão USD 1 = R$5,40".
- Seção "Pagamentos e Financiamentos": "Pagamento em 12 JUN -R$58,95" (abatimento), "Saldo restante
  da fatura anterior R$0,00".
