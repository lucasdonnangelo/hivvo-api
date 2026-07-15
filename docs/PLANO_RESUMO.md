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
  estar pronto — fast-follow explícito, leva dedicada.
  DECISÕES DO FAST-FOLLOW (fechadas): (a) base CONSUMO — "quanto GASTEI/PASSEI em cada cartão este
  mês" (valor cheio pela data da compra; parcelada conta cheia no mês da compra, não a parcela). (b)
  QUALQUER CARTÃO agrupado cru por `cartao_id` — crédito, débito e "ambos" juntos no MESMO cartão
  (a pergunta é "quanto gastei NESTE cartão físico", independente da modalidade; separar débito
  fragmentaria um cartão "ambos" em dois baldes — errado). "SEM CARTÃO" = só PIX/à vista (cartao_id
  NULL) + recorrências. Invariante: soma(por cartão + sem cartão) == consumo.despesas do mês. (c)
  DESPESA-ONLY (receita não entra — não se recebe salário em cartão). (d) DISTINÇÃO CRÍTICA na UI:
  isto é "gastei/passei neste cartão" (consumo), a lente 3d é "vou pagar desta fatura" (fluxo). Com
  débito no meio, num cartão "ambos" parte já saiu (débito) e parte vira fatura (crédito) — o rótulo
  DEVE dizer "gastei", não "vou pagar", senão confunde com a fatura da 3d. (e) Padrão técnico:
  `cartao_id: Optional[int]=None` no LancamentoFluxo, preenchido só na fonte C1 (Transacao) da trilha
  de consumo MENSAL, MESMO padrão aditivo de data/descricao; o endpoint agrupa cru por cartao_id (NÃO
  consulta Cartao.tipo — qualquer cartão conta). Teste-guarda: trilha de fluxo não vaza; paridade
  Resumo/Dashboard intacta.
- **Receitas vs despesas**: a composição do mês (já existe no /monthly).
- **Destaques**: a maior despesa, o dia de maior gasto, o número de transações (endpoint novo).

### Seção 2 — "Comparação" (aparece com ≥2 meses de dados)
- **Variação total**: gastei mais/menos que o mês anterior.
- **Variação por categoria**: "Alimentação +30%, Transporte −15%".
- **Receitas também** (não só despesas).
- Base: vs mês anterior E vs média (as duas leituras — mês anterior é intuitivo, média é robusta a
  meses atípicos).

### Seção 3 — "Evolução" (aparece com ≥6 meses de dados — coverage >= 6)
FLORESCE COM 6 MESES (não 3, decisão revista): a série temporal precisa de base consistente. Um
evento inicial atípico sobre poucos meses distorce; com 6+ ele é diluído. (Ver "Princípios de
indicadores financeiros" abaixo — a lição da XP.)
- **Gráfico principal**: LINHA, despesas vs receitas (duas linhas — a MARGEM entre elas é a leitura:
  "gasto dentro do que ganho ao longo do tempo?"). Valores em R$ (não %). Base CONSUMO.
- **Gráfico de categoria** (SEPARADO do principal, não integrado — eixos e semânticas diferentes):
  um SELETOR de categoria (chips/dropdown) que mostra UMA categoria por vez ao longo do tempo. Várias
  linhas sobrepostas = espaguete ilegível. Uma linha limpa responde "como essa categoria evoluiu?".
- **Filtro de horizonte** (3/6/12/tudo), default 6. O backend já é parametrizado (?meses=N). O FILTRO
  TAMBÉM FLORESCE — as opções se limitam ao histórico: coverage>=6 → [3·6·Tudo] (Tudo=6); coverage>=12
  → [3·6·12·Tudo]. NUNCA oferecer horizonte maior que o histórico (plotaria meses vazios que enganam
  — a lição XP aplicada ao filtro). "Tudo" = todo o histórico (teto 60 do backend).
- **MÊS CORRENTE = PARCIAL**: o mês corrente está acontecendo → o último ponto é sempre "baixo" e
  parece uma QUEDA falsa. Marcar visualmente como parcial (linha tracejada / cor / rótulo "em
  andamento") OU excluir da série. Nunca deixar o parcial parecer tendência de queda. (Mesma
  disciplina da média da Seção 2, que exclui o corrente.)
- Gatilho é DADOS (coverage = competências distintas com lançamento), não tempo de conta. Quem
  importar 6 meses de histórico destrava na hora; quem tem conta há 6 meses mas nunca lançou, não.

## PRINCÍPIOS DE INDICADORES FINANCEIROS (a lição da XP — vale para TODO gráfico/métrica do Hivvo)
Origem: Lucas relatou que a XP Investimentos mostrou "-78% de rendimento" por ~1 ano por causa de um
evento inicial atípico (compra de ~R$13 numa base minúscula durante a fase de aprendizado) que
contaminou uma métrica PERCENTUAL COMPOSTA sobre base pequena — só "corrigiu" quando o evento saiu
da janela móvel. Para o Hivvo NUNCA repetir isso:
1. **Prefira valores ABSOLUTOS (R$) a percentuais** em gráficos/indicadores. % sobre base pequena
   mente (+200% de R$10 é irrelevante). [Já aplicado: curadoria da Seção 2 por R$.]
2. **Trate base zero/pequena explicitamente** — "nova", "sem base", NUNCA "+∞"/"+400%" cru. [Já
   aplicado: Seção 2 categoria nova/zerada.]
3. **O mês corrente (parcial) NUNCA contamina série ou média** — marque como parcial ou exclua. [Já
   aplicado: média da Seção 2; a aplicar: gráfico da Seção 3.]
4. **Não mostre análise temporal até haver base suficiente** — o florescimento tardio protege contra
   eventos iniciais atípicos. [Já aplicado: Seção 3 em 6 meses; o filtro limitado ao histórico.]
5. **EVITE métricas compostas/acumuladas ancoradas num ponto inicial.** O Hivvo hoje mede fluxo/
   consumo POR PERÍODO (absoluto), não crescimento composto sobre uma base — por isso é imune ao bug
   da XP. SE um dia introduzir "evolução patrimonial" ou "% de progresso desde o início" (o 50/30/20
   pode pedir), ancore com cuidado: base = capital/estado real, janela móvel, EXCLUA a fase de setup.
Quatro dos cinco já eram seguidos por instinto na sessão — a história da XP CONFIRMOU os princípios,
não revelou buraco. O #5 é preventivo (só importa se surgir métrica composta).

### Seção 4 — Insights da IA
FORA do escopo inicial (decidido). Possível no futuro (Gemini comentando padrões). Registrado, não
construído agora.

## LIMIARES DE FLORESCIMENTO
- Seção 1: há qualquer transação no mês → aparece (independe de coverage — reflete o mês corrente).
- Seção 2: coverage >= 2 → aparece (há mês anterior). A comparação vs MÉDIA só com coverage >= 3.
- Seção 3: coverage >= 6 → aparece (base consistente p/ série temporal — lição XP). O filtro de
  horizonte também floresce: coverage>=6 → [3·6·Tudo]; coverage>=12 → [3·6·12·Tudo].
("Mês com dados" = competência distinta com lançamento de CONSUMO. É o que /coverage conta.)

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
