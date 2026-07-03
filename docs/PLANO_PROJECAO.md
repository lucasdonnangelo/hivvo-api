# PLANO_PROJECAO.md — Design da Projeção Financeira do Hivvo

> Documento de design que fixa o modelo de projeção financeira (fluxo futuro,
> visão de fatura, competência vs. consumo) antes da implementação. Guia as
> Fases 1–3. Deve ser revisado e aprovado por Lucas antes de qualquer código,
> e mantido como referência entre sessões (igual aos PLANO_EXECUCAO_*).
>
> Status: **APROVADO.** Fase 1 (estatísticas por competência / fluxo) CONCLUÍDA e deployada
> (commit `de1f1eb`). Fase 2 (recorrência) — design fechado (§3.4), pronta para implementar,
> fatiada em 2a (fundação: modelos + migration + algoritmo), 2b (integração na projeção), 2c (CRUD).

---

## 0. Motivação

Bug observado em produção: ao navegar para um mês futuro (agora possível após o fix
de navegação), o Dashboard/Transações/Resumo aparecem **zerados**, embora existam
parcelas materializadas para aquele mês. Ao mesmo tempo, o mês da compra aparece
**inflado** (a compra parcelada é contada 100% no mês da compra).

Causa-raiz (investigação Fase 0): a camada de estatísticas (`_buscar_mes`,
`estatisticas.py`) agrega **apenas** a tabela `transacoes` filtrando pela coluna
`data` (data de registro da compra). Ela **ignora** a tabela `parcelas` e as colunas
de competência `fatura_mes`/`fatura_ano`. Os dados das parcelas futuras **já existem**
no banco (materializados na criação); a stats só não os lê.

Oportunidade: corrigir isso destrava a visão de fluxo futuro — o core do Hivvo
(planejamento de parcelamento). E abre espaço para o pilar novo (recorrência) e para
a distinção competência-vs-consumo.

---

## 1. Conceitos centrais

### 1.1 Duas visões do dinheiro (ambas válidas, respondem perguntas diferentes)

| Visão | Pergunta que responde | Como conta uma compra de R$5.000 em 10x | Fonte de dados |
|---|---|---|---|
| **A pagar (FLUXO)** | "Quanto sai do meu bolso neste mês?" | R$500 no mês de cada parcela (competência de fatura) | tabela `parcelas` via `fatura_mes`/`fatura_ano` |
| **Gasto (CONSUMO)** | "Quanto eu comprometi/gastei?" | R$5.000 inteiro no mês da compra | `transacoes` (transação-pai) via `data` |

As duas convivem: em julho o usuário **pagou R$500** (fluxo) mas **gastou R$5.000**
(consumo). Ambos verdadeiros. Um extrato só mostra o primeiro; o Hivvo mostra os dois.

**A visão principal do produto é FLUXO** (decisão de produto — o Hivvo é um planejador,
"como estarei em dezembro"). Consumo é a lente complementar de comportamento.

### 1.2 Micro e macro

- **Micro (fatura por cartão):** "em dezembro, fatura do Itaú = R$A, fatura do Nubank = R$B".
- **Macro (consolidado do mês):** "dezembro = receitas R$X − despesas R$Y = saldo projetado R$Z".

Ambas derivam da **mesma** projeção. Fonte única no backend, múltiplas lentes no frontend
— nunca divergem.

### 1.3 Realizado vs. Projetado (derivado da data, sem estado manual)

Decisão de produto: **o tempo/ciclo de fatura é a fonte de verdade**. NÃO existe
"marcar parcela como paga" nem rastreamento de inadimplência.

- Fatura/mês **passado ou vencido** → **realizado**.
- Fatura/mês **futuro** → **projetado**.
- Não há campo `pago` manual governando isto; é derivado de `fatura_mes`/`fatura_ano`
  (ou data de vencimento) vs. o mês/hoje corrente.

Consequência aceita: se o usuário não pagar uma fatura de fato, o Hivvo ainda a
considera realizada (é um planejador, não um controle de contas a pagar).

> **DECIDIDO:** o campo `pago` das parcelas **deixa de ser fonte de verdade**. Realizado/projetado
> passa a ser derivado da competência (`fatura_mes`/`fatura_ano` de **vencimento** vs. mês corrente).
> Na Fase 1, a query da IA (`_total_parcelas_proximo_mes`, que hoje filtra `pago == False`) é
> ajustada para derivar de competência. O **campo** `pago` NÃO é removido na Fase 1 (para não
> misturar migration com a correção de stats) — vira código morto e é removido em cleanup posterior.

---

## 2. Regras de agregação (o coração da Fase 1)

**Competência = mês de VENCIMENTO da fatura** (decisão de produto: o Hivvo é um planejador de
fluxo de caixa; "a pagar em dezembro" = o que **vence** em dezembro, quando o dinheiro sai).
Bônus confirmado na Fase 0: as parcelas já materializam `fatura_mes`/`fatura_ano` **por
vencimento** — a Fase 1 apenas LÊ esse dado, não recalcula ciclo/fechamento (que já funciona).

A stats mensal passa a agregar **por competência**, unindo três fontes, **sem dupla
contagem**:

1. **Parcelas** (despesa de cartão parcelada): somar `valor_parcela` das parcelas com
   `fatura_mes`/`fatura_ano == (mes, ano)`, `cancelado == False`.
2. **Transações avulsas de cartão** (despesa não-parcelada no cartão): somar por
   `fatura_mes`/`fatura_ano == (mes, ano)`.
3. **Transações à vista e receitas** (sem cartão / não faturadas): somar por `data`
   dentro do mês.

### 2.1 Regra anti-dupla-contagem (CRÍTICA)

A **transação-pai de uma compra parcelada** (`parcelado == True`) tem o valor cheio
na data da compra. No modelo de **FLUXO**, ela **NÃO soma** nas stats — quem soma são
as **parcelas** (fonte 1). A transação-pai vira apenas o "registro da compra".

Consequência visível: o mês da compra **muda de valor** no Dashboard. Ex.: uma compra
de R$5.000 em 10x, feita em julho, hoje mostra R$5.000 em julho; passará a mostrar
R$500 em julho (a parcela 1), R$500 em agosto, etc. **Isto é intencional e correto**
para a visão de fluxo.

Na visão de **CONSUMO**, é o oposto: a transação-pai (R$5.000) **conta inteira** no mês
da compra, e as parcelas **não** contam. Cada visão usa a fonte que lhe corresponde.

### 2.2 Guarda de validação (evitar regressão de valores)

A rede de testes existente (round-trip, isolamento T-36, testes de invoices do Batch 8)
afirma valores de fatura. A Fase 1 NÃO pode quebrá-los. Além disso, adicionar teste
explícito: para uma compra parcelada conhecida, a soma das parcelas ao longo dos meses
(fluxo) deve igualar o valor cheio da compra (consumo). Fluxo e consumo somam o mesmo
total ao longo do tempo — só distribuem diferente.

---

## 3. Recorrência (pilar novo — Fase 2)

Não existe hoje. É a única entidade a construir do zero.

### 3.1 Modelo (proposta, a refinar na Fase 2)

Uma **receita/despesa recorrente**: descrição, valor, tipo (receita/despesa),
categoria, dia do mês (ex.: salário dia 5), data de início, data de fim (opcional /
"sem fim"), forma de pagamento, e **frequência**.

**Frequência: MENSAL apenas** (decisão de produto). O campo `frequencia` existe no modelo
e hoje só aceita `mensal` — desenhado para ser **extensível** a `semanal`/`quinzenal` no
futuro, SEM refazer o modelo, mas a implementação inicial faz só mensal. Razão: mensal cobre
~95% do planejamento pessoal (salário, aluguel, assinaturas, financiamento); semanal/quinzenal
explode a complexidade (4–5 ocorrências/mês, viradas de mês) por ganho pequeno. YAGNI — adiciona
depois se o uso real pedir.

### 3.1.1 Edição versionada (por vigência) — para não mentir sobre o passado

Editar uma recorrência (ex.: aumento de salário R$10.000 → R$12.000) **preserva o passado e
aplica a mudança do mês corrente para frente**. Por baixo: a vigência antiga é **encerrada**
(R$10.000 até o mês anterior) e uma **nova vigência** é aberta (R$12.000 a partir do mês
corrente). O histórico fica fiel (meses passados mantêm o valor que valia à época); a projeção
futura usa o valor novo.

Para o usuário, a UX é simples ("editar minha receita"): ele não vê a mecânica de vigência.
Modelo interno: uma recorrência é uma **linha do tempo de vigências** (cada versão com seu
período de validade), não um único registro mutável. Detalhar estrutura exata na Fase 2.

### 3.4 Design detalhado da entidade (para a Fase 2)

> Esta seção fecha os detalhes de implementação da recorrência, para a Fase 2 ser executada
> com o modelo definido (não descoberto durante o código). Revisar antes de implementar.

**Estrutura — recorrência como cabeçalho + vigências:**

- **Recorrencia** (o "cabeçalho" estável): `id`, `usuario_id`, `tipo` (receita/despesa),
  `categoria`, `forma_pagamento`, `frequencia` (só `mensal` hoje), `dia_do_mes` (1–31),
  `descricao`, `ativa` (bool — soft delete), `data_criacao`. É a identidade da recorrência
  ("meu salário"). NÃO guarda o valor diretamente.
- **RecorrenciaVigencia** (as versões ao longo do tempo): `id`, `recorrencia_id`, `valor`,
  `mes_inicio`/`ano_inicio` (competência a partir da qual vale), `mes_fim`/`ano_fim` (opcional;
  NULL = "sem fim"). Uma recorrência tem 1+ vigências, sem sobreposição de períodos.

Exemplo: salário R$10.000 desde jan/2026, aumentado para R$12.000 em ago/2026 →
- Vigência 1: valor 10000, início jan/2026, fim jul/2026.
- Vigência 2: valor 12000, início ago/2026, fim NULL (sem fim).

**Por que separar cabeçalho e vigência:** permite editar o valor preservando o passado (§3.1.1)
sem duplicar a identidade. "Editar o salário" = fechar a vigência atual (pôr `mes_fim`/`ano_fim`
= mês anterior ao corrente) e criar nova vigência (início = mês corrente). O usuário vê só
"editei"; o modelo mantém a linha do tempo.

**Algoritmo — "esta recorrência gera ocorrência no mês (m, a)?":**
1. A recorrência está `ativa`? Se não, não gera.
2. Existe uma vigência cujo período [início, fim] contém (m, a)? (fim NULL = aberto). Se sim,
   usa o `valor` dessa vigência; senão, não gera.
3. O `dia_do_mes` é clampado ao último dia do mês (dia 31 em fevereiro → 28/29) — reusar a mesma
   lógica de clamp de `faturas.py` (`calendar.monthrange`), NÃO reimplementar.
4. A ocorrência é uma projeção — NÃO é materializada em `transacoes` nem `parcelas`. É calculada
   e retornada pela projeção do mês.

**Integração na projeção de fluxo (§2):** as ocorrências recorrentes de um mês entram como uma
QUARTA fonte na agregação de fluxo — receitas recorrentes somam nas receitas, despesas
recorrentes nas despesas, do mês de competência. Marcadas como `recorrente` (para o frontend
distinguir visualmente na Fase 3).

**CRUD (endpoints da Fase 2):**
- Criar recorrência (cria cabeçalho + primeira vigência).
- Editar VALOR (fecha vigência atual + abre nova — versionado). ✅ DECIDIDO: apenas o **valor** é
  versionado. Campos do cabeçalho (descrição, categoria, dia, forma de pagamento) aplicam
  **retroativo** a todas as vigências — são metadados, não afetam o histórico financeiro (ex.:
  renomear "Salário" → "Salário CLT" não versiona).
- Excluir. ✅ DECIDIDO (opção A — preservar o passado): a exclusão **fecha a última vigência
  aberta** no mês da exclusão (`mes_fim`/`ano_fim` = mês corrente, ou anterior — definir no 2c),
  em vez de apenas `ativa = False`. Assim as ocorrências de meses PASSADOS continuam na projeção
  histórica (o algoritmo do 2a as encontra, porque a vigência ainda cobre o passado), e as FUTURAS
  param (nenhuma vigência cobre o futuro). O campo `ativa` pode ser marcado `False` como flag
  adicional de "recorrência encerrada" (para a listagem não mostrá-la como ativa), MAS a
  preservação do passado vem do fechamento da vigência, NÃO do `ativa`. (Resolve a tensão
  registrada no 2a: `ativa=False → None sempre` continua válido no algoritmo; a exclusão não
  depende dele para preservar o passado.)
- Listar recorrências ativas do usuário.

**✅ DECIDIDO — recorrência NÃO passa por cartão/fatura:** recorrências são sempre à vista /
PIX / transferência (salário, aluguel), contam por competência do MÊS (por `data`/mês, não por
ciclo de fatura). Coerente com "receita nunca passa por cartão" (§6.4) e estendido às despesas
recorrentes. Despesa recorrente no cartão (ex.: Netflix no crédito) fica FORA do escopo inicial —
adicionar depois se o uso pedir (exigiria a ocorrência virar linha de fatura).

**Edge cases a cobrir em teste (Fase 2):**
- Dia 31 em mês de 30/28 dias (clamp).
- Vigência única sem fim (salário padrão) projeta corretamente até o horizonte (60 meses).
- Edição versionada: mês anterior mantém valor antigo, mês corrente em diante usa o novo, sem gap
  nem sobreposição.
- Recorrência que começa no meio do ano (não gera antes do início).
- Recorrência com fim: não gera após o fim.
- Soft delete: para de gerar futuro.

**Fora do escopo da Fase 2 (registrar):** frequência semanal/quinzenal; overrides de ocorrência
individual ("neste mês foi diferente"); despesa recorrente atrelada a cartão/fatura (ver decisão
acima — recorrências são sempre por competência do mês, não por ciclo de fatura no escopo inicial).

### 3.3 Materializar vs. calcular — DECIDIDO: **calcular** on-the-fly

A recorrência é armazenada como uma **regra** ("R$10.000 todo dia 5, sem fim"). As ocorrências
NÃO são materializadas em linhas — são **calculadas** on-the-fly para qualquer mês pedido
("esta regra gera uma ocorrência neste mês?"). Razão: recorrência "sem fim" (salário) geraria
linhas infinitas se materializada; calcular respeita qualquer horizonte (60 meses, §6.5) sem
gerar linhas além da própria regra.

Trade-off aceito: editar uma **ocorrência específica** ("neste mês o salário foi diferente") não
é trivial com cálculo puro. Porta aberta para o futuro: uma tabela de **exceções/overrides**
pontuais, adicionada depois se necessário — sem materializar tudo. Não no escopo inicial.

---

## 4. As lentes no frontend (Fase 3)

Todas consomem a mesma projeção do backend.

| Tela | Visão | Detalhe |
|---|---|---|
| **Dashboard** | FLUXO (padrão) **+ toggle** para CONSUMO | Saldo projetado do mês. Toggle in-line estilo "Mês/Tri/Ano" do Resumo. Rótulos claros: "A pagar este mês" / "Gasto do mês". |
| **Transações** | Lista os itens do mês (parcelas + avulsas + recorrências), marcados realizado/projetado | A lista do mês passa a incluir as parcelas que caem ali, não só transações registradas |
| **Resumo** | AMBAS (fluxo e consumo), exploradas | Tela de análise. Toggle/seções. Gráfico "Evolução mensal" estende para o futuro (linha projetada). |
| **Faturas por cartão** (lente micro) | Fatura futura de cada cartão | "Dezembro: Itaú R$A, Nubank R$B". Já há base (`/cards/{id}/invoices`) que aceita mês futuro. |

Horizonte de exibição futuro: **60 meses** (§6.5). A projeção calcula até lá; a navegação em si
permanece ilimitada.

Regras de UX (writing):
- Rótulos precisos: "A pagar este mês" ≠ "Gasto do mês". A clareza vem da linguagem,
  não de configuração.
- Itens projetados devem ser visualmente distintos dos realizados (tag/estilo).
- SEM sistema de configuração de visualização. O toggle in-line é um controle visível
  que ensina que há duas visões — não uma preferência enterrada.

---

## 5. Fases de execução

| Fase | Escopo | Repo | Complexidade | Depende de |
|---|---|---|---|---|
| **1** | Stats por competência + as duas visões (fluxo/consumo) + anti-dupla-contagem | hivvo-api | 🟡 médio | Fase 0 (feita) |
| **2** | Recorrência: modelo + CRUD + integração na projeção | hivvo-api | 🔴 complexo (modelo potente) | Fase 1 |
| **3** | Lentes no frontend (Dashboard toggle, Transações, Resumo, faturas por cartão) | hivvo-web | 🟡–🔴 (fatiável) | Fase 1 (e 2 p/ recorrência nas telas) |

Fatiamento sugerido da Fase 3: (3a) Dashboard fluxo+toggle; (3b) Transações lista com
parcelas; (3c) Resumo ambas + gráfico futuro; (3d) faturas por cartão (micro).

---

## 6. Decisões tomadas + questões residuais

**Decididas (trava do modelo):**
1. ✅ **Campo `pago`:** deixa de ser fonte de verdade (§1.3). Realizado/projetado deriva de
   competência de vencimento vs. mês corrente. IA ajustada na Fase 1. Campo removido em cleanup
   posterior (não na Fase 1).
2. ✅ **Recorrência:** **calculada** on-the-fly, não materializada (§3.3). Overrides como
   possibilidade futura.
3. ✅ **Competência:** por **vencimento** (§2). Já materializado assim no banco — Fase 1 só lê.
4. ✅ **Receitas:** nunca passam por cartão/fatura (são PIX/transferência) — contam sempre por
   `data` (fonte 3 do §2). Não há receita parcelada/faturada.
5. ✅ **Horizonte de exibição futuro:** **60 meses** (5 anos). Navegação ilimitada, mas a projeção
   (especialmente recorrência "sem fim") é exibida até 60 meses à frente.

**Residuais (resolver no início da fase correspondente):**
- **Dupla contagem entre visões (fluxo vs. consumo):** a despesa avulsa de cartão pertence a
  FLUXO por `fatura_mes` (vencimento) e a CONSUMO por `data` da compra. Confirmar na Fase 1 que
  cada visão usa só sua fonte, sem somar a mesma despesa duas vezes dentro da mesma visão.
- **Estrutura exata das vigências da recorrência** (§3.1.1): como modelar a linha do tempo de
  versões (uma tabela de recorrências com `data_inicio`/`data_fim` por vigência? um campo de
  versão?), o dia clampado a mês curto (dia 31 em fevereiro), e o encerrar-e-abrir na edição —
  detalhar na Fase 2 com o modelo potente.

---

## 7. Princípios (não violar)

- **Fonte única no backend, múltiplas lentes no frontend.** As telas nunca calculam
  projeção própria — consomem a do backend. Evita divergência de números.
- **Fluxo e consumo somam o mesmo total ao longo do tempo** — só distribuem diferente.
  Todo teste de valor deve honrar isto.
- **Realizado vs. projetado é derivado da data**, não de estado manual.
- **Correção antes de feature:** a Fase 1 (corrigir stats) conserta o bug com dados que
  já existem — vem antes da recorrência (feature nova).
- Regras arquiteturais gerais do Hivvo continuam valendo (Decimal no back, toFixed no
  front, tokens Tailwind, TanStack Query para server-state, etc.).
