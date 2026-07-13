# PLANO_RESUMO.md — Design da tela de Resumo (análise + histórico)

> Documento de design. Fecha O QUE o Resumo é antes de qualquer código. Origem: o Resumo original
> ("ambas as visões + toggle + gráfico estendido pro futuro") foi CANIBALIZADO pelo Dashboard de
> dois blocos — o toggle morreu (as duas visões já aparecem juntas no Bloco 1) e a projeção futura
> migrou pro Bloco 2. Reformulado: o Resumo passa a ser a lente do PASSADO e da ANÁLISE, a metade
> que o Dashboard não cobre.

## CONCEITO
- **Dashboard** = "onde estou e pra onde vou" (Bloco 1 presente + Bloco 2 futuro).
- **Resumo** = "como cheguei aqui e quais meus padrões" (passado + análise).
- São as duas metades da história temporal do dinheiro. Por isso o Resumo vive DENTRO do Dashboard/
  Início, como uma ABA ao lado da visão geral (não um destino novo na barra, não enterrado em
  Transações). "Início" ganha sub-navegação: [Visão geral | Análise] (nomes a definir).

## PRINCÍPIO CENTRAL — A TELA FLORESCE (não bloqueia, não tem "dois modos")
Cada seção aparece quando há dado que a sustenta. O usuário novo vê valor imediato (o detalhe do
mês); as seções de análise temporal aparecem conforme o histórico cresce. NUNCA bloquear com aviso
"volte em 2 meses" (hostil ao novo, que é quem mais precisa de acolhimento). NÃO são dois modos
(novo vs maduro) com transição confusa — é UMA tela onde seções aparecem/somem por presença de dado
(mesmo padrão do EmptyState e do Bloco 2 "aparece quando tem projeção").

Seção ausente → mostrar um CONVITE discreto ("Sua comparação mensal aparecerá com mais um mês de
uso"), não poluição. Ensina que existe, cria expectativa.

## AS SEÇÕES

### Seção 1 — "Este mês em detalhe" (SEMPRE, se há qualquer transação no mês)
Serve o usuário novo — valor no dia 1. Aprofunda o que o Dashboard só resume.
- **Gasto por categoria**: donut/barra MAIOR e mais detalhado que o mini-donut do Dashboard — todas
  as categorias, valores e percentuais. **BASE = CONSUMO** (decidido) — coerente com o donut do
  Dashboard (que é consumo); o Resumo é o aprofundamento do MESMO donut, tem que bater. O dado já
  existe (`categorias_consumo` no /monthly); falta expor de forma dedicada ou o Resumo lê do /monthly.
- **Gasto por cartão**: ADIADO para FAST-FOLLOW (decidido). Não entra na v1 do Resumo. Motivo:
  consumo-por-cartão exige carregar `cartao_id` na trilha de CONSUMO (`LancamentoFluxo` de consumo
  não tem hoje) — mexe no núcleo do cálculo; e a fatura-por-cartão (fluxo) JÁ existe na lente 3d
  (/invoices/{ano}/{mes}), então não há lacuna urgente. Lucas quer adicionar LOGO APÓS o Resumo
  estar pronto — fast-follow explícito, leva dedicada (adicionar cartao_id à trilha de consumo +
  endpoint consumo-por-cartão + a UI na Seção 1).
- **Receitas vs despesas**: a composição do mês (já existe no /monthly).
- **Destaques**: a maior despesa, o dia de maior gasto, o número de transações (endpoint novo).

### Seção 2 — "Comparação" (aparece com ≥2 meses de dados)
- **Variação total**: gastei mais/menos que o mês anterior.
- **Variação por categoria**: "Alimentação +30%, Transporte −15%".
- **Receitas também** (não só despesas).
- Base: vs mês anterior E vs média (as duas leituras — mês anterior é intuitivo, média é robusta a
  meses atípicos).

### Seção 3 — "Evolução" (aparece com ≥3 meses de dados)
- **Gráfico de linha/barra dos últimos N meses**: gasto mensal, ou receita vs despesa por mês.
  É onde vive o gráfico "evolução mensal" do Resumo antigo — mas olhando PRA TRÁS (o futuro é do
  Bloco 2 do Dashboard).
- **Evolução de uma categoria específica** ao longo do tempo (abrir uma categoria e ver sua série).
- **Horizonte: padrão 3 meses** quando aparece. FILTRO de período (3/6/12/tudo) é FUTURO — não no
  escopo inicial do frontend, MAS o backend nasce PARAMETRIZADO (?meses=N) para não exigir
  retrabalho depois. Frontend começa fixo em 3 (sem os botões de filtro), consumindo um endpoint
  que já aceita qualquer horizonte.

### Seção 4 — Insights da IA
FORA do escopo inicial (decidido). Possível no futuro (Gemini comentando padrões). Registrado, não
construído agora.

## LIMIARES DE FLORESCIMENTO
- Seção 1: há qualquer transação no mês → aparece.
- Seção 2: ≥2 meses com dados → aparece.
- Seção 3: ≥3 meses com dados → aparece.
("Mês com dados" = mês com ao menos uma transação/lançamento. Definir a contagem exata na
investigação — provável: meses distintos com lançamento no histórico do usuário.)

## LOCALIZAÇÃO
Aba "Análise" dentro de "Início" (ao lado de "Visão geral" = o Dashboard atual). Não incha a barra
de navegação (segue com 5 itens), não esconde o Resumo em Transações, conecta as duas telas irmãs.
O usuário novo abre no Dashboard e VÊ a aba ao lado (descoberta natural); ao clicar cedo, a tela
floresce e acolhe.

## ESCOPO / FASES (dimensionado pela investigação)
Mini-fase, múltiplos batches.

**Backend (🔴 potente) — helper único + 5 endpoints:**
- **`_lancamentos_horizonte(session, uid, meses)`** — o ESPELHO PRA TRÁS do /projection: percorre
  os últimos N meses reusando `_lancamentos_ano` com cache por ano (carrega ceil(N/12)+1 anos).
  TODOS os endpoints de análise consomem esse helper → zero drift de competência entre eles e vs o
  Dashboard. Fonte única, olhando pra trás.
- Convenção de horizonte: âncora = mês corrente (incluído); `meses=N` = corrente + (N−1) pra trás;
  `Query(3, ge=1, le=60)`, default 3 (o front usa 3).
- **GET /statistics/evolution?meses=N** — série mensal pra trás (S3). Base CONSUMO (o "gasto" do
  Resumo é consumo).
- **GET /statistics/evolution/categories?meses=N** — série por categoria (S3) + base da comparação.
- **GET /statistics/comparison?meses=N** — totais + por-categoria: mês atual, anterior, e média dos
  N (S2 — mês anterior E média, as duas leituras). Retornar valores ABSOLUTOS (não só %).
- **GET /statistics/highlights?mes=&ano=** — destaques do mês (S1: maior despesa, dia de maior
  gasto, nº de transações). Único não-temporal.
- **GET /statistics/coverage** — nº de meses distintos com dados (florescimento: ≥2 → Seção 2;
  ≥3 → Seção 3). Sem parâmetros.
- Verificar se /statistics/yearly (ano-calendário fixo) pode ser aposentado pelo /evolution, ou se
  algo ainda o usa (reportar, não remover cegamente).

**Frontend:** aba "Análise" dentro do Início, as 3 seções, o florescimento por presença de dado
(coverage decide), horizonte fixo em 3.

**Categorias e "gasto" no Resumo = CONSUMO** (bate com o Dashboard). Fluxo é do Dashboard/faturas.

## PRINCÍPIOS HERDADOS
- Fonte única no backend; o Resumo é lente, nunca recalcula. As mesmas visões (fluxo/consumo) do
  modelo: "gasto" no Resumo é CONSUMO (o que se gastou), coerente com o donut do Dashboard.
- Tokens Tailwind, MobileLayout/DesktopLayout, TanStack Query.
- Florescimento reusa o molde EmptyState e a lógica de "seção some quando vazia" do Bloco 2.
