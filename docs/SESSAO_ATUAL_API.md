# Hivvo — Sessão Atual

## Antes de começar
Leia `docs/Hivvo_Referencia.md`, `docs/SESSAO_ATUAL.md`, `docs/AUDITORIA_SEGURANCA.md`, `docs/AUDITORIA_TECNICA.md` e `docs/PLANO_EXECUCAO_API.md` para entender o produto, a arquitetura **real**, as decisões de stack e o plano de correção em andamento. Não proponha alternativas de tecnologia — já decididas. Uma tarefa/batch por vez, com aprovação antes do commit.

---

## Estado do Projeto

**Fase atual:** Fase 3 da projeção (as "lentes" — frontend), pós-deploy.
**Status:** App deployado e no ar (Railway + Vercel; Supabase de produção = `hivvo-prod`, ref `kufbqivycqjkydnfvgee`, us-west-2). Hardening pré-deploy (Batches 1–11) concluído e o backend da projeção Fase 1–2 completo: competência/fluxo, recorrência on-the-fly versionada por vigências, §1.3.1 (corte por dia: projeção/realizado/a-vir), §3.1.2 (operações de erro), Bugs 1/2. O backend da Fase 3 avançou: **3b-backend (visão CONSUMO no `/statistics/monthly`, commit `8ac6db5`)** e o **mês default do Dashboard (`GET /statistics/default-month`)** prontos. **342 testes verdes.** Próximo: **Fase 3 frontend** — toggle fluxo/consumo + consumir o default-month.
**Mês default do Dashboard — `GET /statistics/default-month` (07/07/2026):** endpoint leve que responde **em que mês o Dashboard ABRE** (não trava navegação): `{fluxo: {mes, ano}, consumo: {mes, ano}}`. FLUXO: tem histórico (competência < corrente) → **corrente**; senão → **1º mês com fluxo** no horizonte de 60 meses; senão → **mês seguinte**. CONSUMO: sempre o corrente. Regra no PLANO_PROJECAO §"Mês default do Dashboard". Suíte: **342 testes** (331 + 11), todos verdes. Ver seção "Mês default do Dashboard" abaixo.
**Fase 3b-backend — visão CONSUMO no `/statistics/monthly` (07/07/2026, commitado `8ac6db5`):** a `MensalResponse` ganhou `consumo: LeituraMes` (gasto por DATA da compra — pai parcelada pelo valor CHEIO, avulsa por data, à vista, receitas, recorrência) e `categorias_consumo` (donut) — 100% aditivo (FLUXO/realizado/a_vir/variação/yearly/IA intactos). Nova `_lancamentos_consumo_mes` em `estatisticas.py`. Opção A (valor cheio da pai): não reflete cancelamento por-parcela — limitação e gatilho registrados no PLANO §Fase 3b. Suíte: **331 testes** (319 + 12), todos verdes.
**Bug 2 (extensão) — piso por DATA da primeira ocorrência no POST /recorrencias (06/07/2026, commitado):** o piso do Bug 2 validava só o MÊS — override no **mês corrente com `dia_do_mes` já passado** (ex. hoje 5/jul, dia 4) passava (julho >= julho) e criava a primeira ocorrência no PASSADO. A validação do override agora compara a **DATA da primeira ocorrência** (`dt.date(ano_inicio, mes_inicio, clamp_dia_no_mes(dia_do_mes, ...))` — o MESMO clamp de `data_ocorrencia`) contra `hoje`: `< hoje` → **422** `"A primeira ocorrência da recorrência não pode ser no passado."`; `== hoje` passa (o próprio dia conta, coerente com o `<=` do §1.3.1). **SUBSTITUI** a comparação mensal (a de data é mais forte e a engloba — mensagem única). Default (regra do dia) **intacto** — seguro por construção (dia passado → mês seguinte). Suíte: **319 testes** (315 + 4), todos verdes; único teste existente alterado: a assertion da mensagem em `test_override_mes_passado_422`. Ver seção "Bug 2 (extensão)" abaixo.
**Bug 1 (E2E) — expor valor de recorrência com início futuro na gestão / campo `valor_exibicao` (05/07/2026, commitado):** recorrência cuja 1ª vigência começa no MÊS SEGUINTE tinha `valor_vigente=null` (`valor_no_mes(mês corrente)` não acha vigência cobrindo hoje) → lista mostrava "—" e o form de Editar carregava vazio, embora o valor esteja em `vigencias[]`. **Fix aditivo:** campo NOVO `valor_exibicao` na resposta (lista E detalhe, via `RecorrenciaResponse` — `RecorrenciaDetailResponse` herda), SEM tocar `valor_vigente` (que mantém o significado estrito "vige HOJE"; há consumidores que dependem do `null` — gating do corrigir, comparação de valor no front). Regra (helper puro `valor_exibicao` em [services/recorrencias.py](../app/services/recorrencias.py), reusa `valor_no_mes`): `= valor_vigente` se algo vige hoje; **senão** o valor da **vigência FUTURA mais próxima** (`min (ano_inicio, mes_inicio)` com início `>= (ano, mes)`). **Borda crítica (encerrada):** fallback restrito a início futuro → recorrência encerrada (só vigências passadas, nenhuma futura) → `valor_exibicao=null` (continua "—", correto — não pega valor de vigência passada). Início futuro → valor da vigência que vai começar; vigente hoje → `== valor_vigente`. **Complemento (mesmo dia):** adicionados `mes_exibicao`/`ano_exibicao` (início da MESMA vigência de exibição, para "a partir de ago/2026") — o helper virou `dados_exibicao`, que retorna `(valor, mes, ano)` num só cálculo (fonte única, coerência garantida); `null` quando vige hoje ou encerrada. Projeção intocada. Suíte: **315 testes**, todos verdes. **Falta o frontend** (ler `valor_exibicao` + `mes/ano_exibicao` na lista e no prefill do Editar — próximo batch). Ver seção "Bug 1 — valor_exibicao" abaixo.
**Bug 2 (E2E) — proibir início de recorrência no passado / piso no mês corrente (05/07/2026, commitado):** o POST `/recorrencias` passa a **barrar override explícito com início ANTERIOR ao mês corrente** (o passado é verdade histórica §3.1.2 — não se inventa recorrência retroativa; senão corrompe meses fechados e a variação vs. mês anterior). Achado na validação E2E: a UI deixava criar "Começa em" num mês já passado. Validação **no router** (`create_recorrencia`, branch de override), NÃO no schema — precisa comparar contra o MESMO `hoje` que o resto do endpoint usa (`app.routers.recorrencias.hoje`, que a suíte patcha; no schema seria um segundo relógio não-patchado → não-determinístico). Comparação por tupla `(ano_inicio, mes_inicio) < (hoje.year, hoje.month)` → **422** "O início da recorrência não pode ser anterior ao mês corrente." Corrente e futuro passam; o **default (regra do dia) fica intacto** (nunca resolve para o passado — só o override é validado). É a **fronteira REAL de integridade** (a UI ganha `min` no campo em outro batch, mas chamada direta a burla). **Migração de teste:** ~13 testes de editar/encerrar/corrigir que criavam recorrência com início jan/2026 **via POST** (agora barrado) passaram a montar esse estado — legítimo, é como fica uma recorrência criada meses atrás — **direto no banco** (helper `_semear_recorrencia_passada`); a cobertura de sucesso do POST não se perde (vive em `TestCriar` e na nova `TestPisoInicioNoPassado`). Suíte: **310 testes** (304 + 6), todos verdes. Ver seção "Bug 2 — piso no mês corrente" abaixo.
**Operações de erro na recorrência (§3.1.2) — hard delete + corrigir valor retroativo (04/07/2026, commitado):** duas rotas NOVAS e EXPLÍCITAS para "foi um erro", separadas das operações normais (que preservam o passado e ficaram **byte a byte intactas**): **`DELETE /recorrencias/{id}/permanente`** (apaga cabeçalho + TODAS as vigências do banco — some do histórico e da projeção, inclusive passada; aceita também ENCERRADA — cobre "encerrei por engano" e o apagar+recriar; deletes explícitos com CASCADE do Postgres como defesa em profundidade) e **`PATCH /recorrencias/{id}/corrigir-valor`** (reescreve o valor da vigência ÚNICA in place — erro fresco; com 2+ vigências → **409** "Correção retroativa indisponível..."; não versiona, não cria vigência). Rota separada > flag/`modo`: impossível de acionar por engano, autodocumentada no OpenAPI/logs. Isolamento T-36 em ambas. Suíte: **304 testes, todos verdes** (294 + 10). Ver seção "Operações de erro (§3.1.2)" abaixo.
**Correção §1.3.1 (projeção) — corte por dia no mês corrente: realizado / a-vir / projeção (03/07/2026, commitado):** no mês CORRENTE, o dia de hoje passa a dividir cada lançamento em **realizado** (dia/vencimento <= hoje) e **a-vir** (dia > hoje). Implementação por **MARCAÇÃO, não filtro**: `LancamentoFluxo` ganhou `realizado: bool = True`; Fonte 1 marca por `Parcela.data_vencimento <= hoje` (vencimento real) e Fonte 4 por `data_ocorrencia <= hoje` (clamp da 2a); Fontes 2/3 sempre realizadas (§1.3.2). **Topo do `/statistics/monthly` INALTERADO = projeção integral**; a resposta GANHOU `realizado: {receitas, despesas, saldo}` e `a_vir: {...}` (invariante: projeção = realizado + a_vir; mês não-corrente: realizado == projeção, a_vir = 0 — mês futuro é projeção integral, NÃO a-vir). Variação segue projeção×projeção; yearly (série = projeção) e IA (contexto integral) **sem mudança de números/shape**. `hoje()` agora é lido dentro de `_lancamentos_mes/_ano` (testes patcham `app.services.estatisticas.hoje`). Suíte: **294 testes, todos verdes** (282 antigos SEM ajuste + 12). **Falta a metade frontend (exibir realizado/a-vir no Dashboard).** Ver seção "Correção §1.3.1" abaixo.
**Fase 3a-backend (projeção) — regra do dia para o mês de início default da recorrência (03/07/2026, commitado):** o POST `/recorrencias` deixa de defaultar cegamente para o "mês corrente". Quando o cliente NÃO envia `mes_inicio`/`ano_inicio`, o mês de início default agora depende do **dia da ocorrência vs. hoje** (lógica de negócio, no backend): `dia_do_mes >= dia de hoje` → **mês corrente** (a ocorrência ainda acontece este mês; inclui a borda dia == hoje); `dia_do_mes < dia de hoje` → **mês seguinte** (o dia já passou), com virada de ano natural (dez → jan/ano+1). **Override explícito preservado:** se o cliente envia `mes_inicio`/`ano_inicio`, usa os enviados (o "ajustar" da UI). Mudança **isolada na resolução do default do POST** (novo helper `_default_mes_inicio` em `recorrencias.py`); NÃO toca `valor_no_mes` (2a), projeção (2b), PATCH/DELETE/vigência (2c) nem o modelo. Suíte: **282 testes** (276 + 6 da regra), todos verdes. Ver seção "Fase 3a-backend" abaixo.
**Fase 2c (projeção) — CRUD de recorrência (03/07/2026, commitado):** novo router `/api/v1/recorrencias` (POST/GET/GET{id}/PATCH/DELETE) + schemas próprios. **Mudança de semântica central: `ativa` SAIU do caminho da projeção** — `valor_no_mes` não checa mais `ativa` e a Fonte 4 não filtra mais; a projeção depende SÓ das vigências. PATCH de valor **versionado** (fecha vigência no mês anterior + abre nova no corrente; 2ª edição no mesmo mês SUBSTITUI in place — sem degeneradas); metadados retroativos no cabeçalho. DELETE **preserva o passado**: fecha a vigência no mês corrente + `ativa=False` (flag de listagem) — passado segue na projeção, futuro para. CORS ganhou `PATCH` no `allow_methods` (estava fora — o endpoint seria bloqueado no browser). Suíte: **276 testes, todos verdes** (254 intocados + 2 reescritos p/ a semântica nova → 3 + 19 novos). **FECHA A FASE 2 (recorrência) no backend.** Ver seção "Fase 2c" abaixo.
**Fase 2b (projeção) — recorrência integrada na projeção de fluxo (03/07/2026, commitado):** as ocorrências de recorrência ATIVAS entram como **QUARTA fonte** em `_lancamentos_mes` e `_lancamentos_ano` (`estatisticas.py`) — receita recorrente soma nas receitas, despesa nas despesas E no donut, por competência do MÊS (sem fatura/cartão, §3.4). `LancamentoFluxo` ganhou **`recorrente: bool = False`** (marcação para a Fase 3). **Sem N+1:** busca em 2 queries fixas (`_recorrencias_com_vigencias`) e o anual aplica `valor_no_mes` aos 12 meses em memória — **5 SELECTs fixos no anual, afirmado em teste por contagem de queries**. Fontes 1–3 intocadas; statistics e IA herdam automaticamente (consomem `_lancamentos_*`). Suíte: **256 testes, todos verdes** (248 + 8). **SEM CRUD (2c), SEM frontend (Fase 3).** Ver seção "Fase 2b" abaixo.
**Fase 2a (projeção) — fundação da recorrência (03/07/2026, commitado):** modelos `Recorrencia` (cabeçalho estável, UUID PK, soft delete `ativa`) + `RecorrenciaVigencia` (versões de valor por período de competência; fim NULL = aberta), migration `f2a7c9d1e8b3` (FKs ON DELETE CASCADE, 7 CHECKs, índice composto de período — **upgrade E downgrade testados de verdade no Postgres dev; aplicada ao fim**) e o algoritmo puro (`valor_no_mes`/`data_ocorrencia` em `app/services/recorrencias.py`, sem I/O de banco). Helpers novos: `agora()` (datetime SP em `dates.py`) e `clamp_dia_no_mes` extraído de `faturas.py` (4 call sites refatorados, comportamento idêntico). Suíte: **248 testes, todos verdes** (221 + 27). **SEM CRUD (2c), SEM integração na projeção (2b), SEM frontend (Fase 3).** Ver seção "Fase 2a" abaixo.
**Fase 1 (projeção) — estatísticas por competência de fatura (02/07/2026, commitado `de1f1eb`):** resolve o **T-39** (visão FLUXO). `getMonthlyStats` (`/statistics/monthly` + `/categories`), **`yearly_stats` (`/statistics/yearly`)** e o contexto da IA passam a agregar por **competência de fatura**, somando 3 fontes sem dupla contagem: parcelas por `fatura_mes/ano`, avulsas de cartão faturadas, e à vista/receitas por `data`. A transação-pai parcelada **deixa de somar** o valor cheio — mês da compra mostra a parcela daquele mês, meses futuros deixam de ser zero. O gráfico "Evolução mensal" (anual) fica **coerente com o card mensal** (adendo). Suíte: **221 testes, todos verdes** (213 + 8). **Shape das respostas inalterado — só os números mudam.** **Não** inclui recorrência (Fase 2), toggle consumo (Fase 3), otimização SUM/GROUP BY, nem remoção do campo `pago`. Ver seção "Fase 1 (projeção)" abaixo.
**Deploy — remetente do e-mail parametrizado (02/07/2026, commitado):** novo `EMAIL_FROM` em Settings (default sandbox `Hivvo <onboarding@resend.dev>`) usado no `forgot_password` no lugar do `from` hardcoded. Único ponto de envio de e-mail (confirmado por varredura de `resend.Emails.send`). Suíte com **213 testes, todos verdes** (212 + 1) — ver seção "Deploy — remetente do e-mail" abaixo. **⚠️ PRODUÇÃO (Railway): setar `EMAIL_FROM="Hivvo <noreply@hivvo.app>"`** (domínio verificado no Resend). **Não** toca F-24/F-18/Batch 16 nem outros batches.
**Batch 11b concluído — CÓDIGO (01/07/2026, commitado):** cookies same-site + token 30min (F-03, F-09), env-conditional (dev em localhost intacto). Cookies com `Domain=.hivvo.app`/`Secure`/`SameSite=Lax` em produção (sem Domain/Secure em dev), CORS com origem explícita + métodos/headers restritos, reforço CSRF por `Origin` nos endpoints mutáveis, access token 30min (refresh segue 7 dias). Suíte com **212 testes, todos verdes** (196 + 16) — ver seção "Batch 11b" abaixo. **⚠️ F-03/F-09 só se validam DE FATO no deploy** (domínio real). **Não** toca outros batches nem papel Postgres (ops).
**Fase 5 — resiliência de banco concluída (01/07/2026, commitado):** Batch 7 (parte CÓDIGO) — `pool_pre_ping`/`pool_recycle=1800`/`pool_size=5`/`max_overflow=10` no `database.py` (pool modesto p/ o pooler) — + **exception handler global**: falha de conexão (`OperationalError`/`InterfaceError`) → **503 limpo COM headers de CORS** (não mais falso-CORS). Suíte com **196 testes, todos verdes** (194 + 2) — ver seção "Fase 5 — resiliência de banco" abaixo. **Parte OPS do Batch 7 (papel Postgres restrito, sem superuser) fica para o passo de infra.** **Não** toca 11b, T-28 nem outros batches.
**Próximo passo imediato:** **Fase 3 (frontend)** — toggle fluxo/consumo no Dashboard (consome `consumo`/`categorias_consumo` do `/statistics/monthly`) + abrir a tela no mês do `GET /statistics/default-month`. O backend dos dois já está pronto (gate do `monthly_stats` resolvido: a visão CONSUMO foi implementada em `8ac6db5`). Deploy (Fase 5) e hardening pré-deploy **já feitos** — o app está no ar.
**T-28 CONCLUÍDO e VERIFICADO (01/07/2026, commitado `f46f17e`):** todos os routers de NEGÓCIO montados sob `/api/v1` (hard switch, sem dual-mount); `/health` permanece na RAIZ. **Cross-repo casado e testado ponta a ponta:** login + escrita + leitura funcionando sob `/api/v1` com os dois repos (API + Web) apontando para o mesmo prefixo. Suíte com **191 testes, todos verdes** (188 + 3 do hard switch) — ver seção "T-28 (lado API)" abaixo. **⚠️ Cross-repo: NÃO deployar API e Web separados** — produção precisa subir com `/api/v1` casado dos dois lados (`VITE_API_URL=https://api.hivvo.app/api/v1`).
**Batch 11a concluído (01/07/2026, commitado `1623dc8`):** LGPD — exclusão de conta (F-07). `DELETE /auth/me` (sob `/api/v1`), autenticado + reautenticação por senha, apaga TODOS os dados do usuário numa transação única. Suíte com **194 testes, todos verdes** (191 + 3) — ver seção "Batch 11a" abaixo. **⚠️ Política de Privacidade precisa ser atualizada** mencionando o direito de exclusão (conteúdo, fora do código). **F-03 (cookies same-site) e F-09 (token 30min) ficam para o deploy (11b)** — são deploy-coupled.
**Migração de conexão do banco (01/07/2026, ops — antecipa o núcleo do Batch 7):** `DATABASE_URL` local migrada da **conexão direta** do Supabase para o **SESSION POOLER** (host `pooler.supabase.com`, IPv4). Motivo: a conexão direta resolve para **IPv6** e a rede local é **IPv4-only** (`Test-NetConnection` deu `DestinationNetworkUnreachable` no IPv6). A **senha do banco de dev foi ROTACIONADA** nesta sessão. **⚠️ O mesmo problema de IPv6 reaparece no Railway** se usar a direct — ver checklist de deploy.
**Batch 10 concluído (30/06/2026, commitado):** observabilidade e deploy — T-25 (logging via dictConfig + Sentry opcional com scrub LGPD em 2 níveis + middleware de request-id), T-43 (lifespan + fail-fast de boot + engine.dispose), T-42 (Procfile: release `alembic upgrade head` + web uvicorn). Suíte com **188 testes, todos verdes** — ver seção "Batch 10" abaixo. **Não** toca pooler (Batch 7), T-28 nem Batch 11.
**Batch 9 concluído (29/06/2026, commitado):** resiliência da IA + rate limiting — T-21 (timeout no client, retry reduzido a 2 tentativas, client singleton) e F-04 (slowapi: limites por IP em login/register/forgot-password, e por IP + usuário + cota diária em /ai/chat). Suíte com **178 testes, todos verdes** — ver seção "Batch 9" abaixo.
**Batch 8 concluído (29/06/2026, commitado):** queries pesadas + teto de listagem — T-17 (invoices e cards agregam no banco, sem N+1/varredura) e T-12 (limit/offset no `GET /transactions`, clamp 500; novo `GET /transactions/export`). **Sem quebrar contrato** (array nu, sem envelope). Suíte com **173 testes, todos verdes** — ver seção "Batch 8" abaixo. **Feito fora de ordem** (antes do Batch 7, a pedido) — Batch 7 não bloqueia o 8.
**Batch 6 concluído (29/06/2026, commitado):** banco — índices compostos (T-09), sargabilidade (T-10), constraints (T-11), cascades (T-14). Uma migration Alembic (`e7c9a1b2d3f4`) + ajuste de 2 funções de query + guarda no `create_category`. Suíte com **166 testes, todos verdes**. **Migration NÃO rodada — comandos abaixo para o Lucas rodar em dev** — ver seção "Batch 6" abaixo.
**Batch 5 concluído (26/06/2026, commitado):** tokens e sessão — F-24, F-10, F-18/T-31. Suíte com **139 testes, todos verdes** — ver seção "Batch 5" abaixo.
**Batch 4b concluído (26/06/2026, commitado `6f5e359`):** hardening de entrada e hashing — F-16, F-22, F-23, F-06. Suíte com **128 testes, todos verdes** — ver seção "Batch 4b" abaixo. **F-06 validado em runtime e APROVADO** (nenhuma recusa de safety); observações de system prompt/contexto do Assistente surgidas na validação foram para "Itens diferidos / Backlog".
**Batch 4a concluído (26/06/2026, commitado `c7f84bf`):** robustez de config e higiene — F-01, T-07, F-13, F-14, F-11+T-08, T-06 e separação de dependências de dev. Suíte com **113 testes, todos verdes** — ver seção "Batch 4a" abaixo.
**Batch 1 concluído (11/06/2026, commitado):** lógica de fatura/parcela/estatísticas consolidada em `app/services/`.
**Batch 2 concluído (11/06/2026, commitado):** primeira suíte automatizada — 44 testes (42 pass + 2 xfail), 100% de cobertura em `services/faturas.py` e `services/parcelas.py` — ver seção "Batch 2" abaixo.
**Batch 3a concluído (12/06/2026, commitado `c315a3a`):** validação de entrada + fechamento dos 2 xfail (T-33, T-38, T-40, T-35 parte de schema) — ver seção "Batch 3a" abaixo.
**Batch 3b concluído (12/06/2026, commitado `124086f`):** comportamento de endpoint (T-36, T-34, T-35-endpoint, T-41, T-37, T-27 data de negócio) — ver seção "Batch 3b" abaixo. **Fecha o Batch 3 inteiro.**
**Fase 2 cross-repo concluída (12/06/2026, commitado `2fc837f`):** `POST /ai/suggest-category` — endpoint dedicado de sugestão de categoria, stateless (raiz do FE-08; o **Web-Batch 4** do hivvo-web vai consumi-lo) — suíte com **101 testes, todos verdes** — ver seção "Fase 2" abaixo.
**Teste de regressão round-trip parcelada→fatura concluído (26/06/2026, commitado `f3565c8`):** só testes — fecha o gap de cobertura do caminho de SUCESSO da criação parcelada (havia só atomicidade/FALHA do T-41). Suíte com **103 testes, todos verdes** — ver seção "Regressão round-trip" abaixo.
**T-29 ordenação estável de transações concluído (26/06/2026, commitado):** desempate determinístico `data DESC, id DESC` em `GET /transactions` e nas avulsas do detalhe de fatura. Suíte com **106 testes, todos verdes** — ver seção "T-29" abaixo.
**Última construção concluída:** Assistente IA com persistência e memória (`chat_messages`, sessões, histórico 24h, contexto de 50 mensagens, retry Gemini 5x). Validação de UX do histórico ainda pendente (bloqueada pelos 503 do Gemini).

---

## Mês default do Dashboard — GET /statistics/default-month (07/07/2026)

Implementa a decisão de produto do **mês em que o Dashboard ABRE por padrão** (regra completa no
`docs/PLANO_PROJECAO.md` §"Mês default do Dashboard") — só a abertura; a navegação segue livre.
Suíte: **342 testes** (331 + 11), todos verdes; **nenhum teste existente alterado** (mudança
100% aditiva).

**A regra (visão FLUXO):**
1. **TEM HISTÓRICO** (lançamento com competência ANTERIOR ao mês corrente) → **mês corrente**.
2. Senão → **PRIMEIRO mês (corrente..corrente+60) que TEM FLUXO** — multi-cartão automático
   (cada compra já está na fatura certa por `fatura_mes`, sem calcular ciclo).
3. Sem fluxo em lugar nenhum → **mês seguinte** (fallback neutro, com virada dez → jan/ano+1).

**Visão CONSUMO:** sempre o mês corrente.

**Contrato — endpoint leve dedicado (não campo na `MensalResponse`):** `GET
/statistics/default-month` → `{fluxo: {mes, ano}, consumo: {mes, ano}}` (novos `MesAno` e
`MesDefaultResponse` em [schemas/statistics.py](../app/schemas/statistics.py)). Razões: o mês
default precisa ser conhecido ANTES do primeiro `/monthly` (campo na resposta mensal criaria
chicken-and-egg + refetch); e "tem fluxo" DEVE ser a definição da projeção (fonte única). O
`consumo` vem junto para o frontend não derivar "mês corrente" com o relógio/fuso do browser —
o backend usa **um único `hoje()`** (fuso do produto) para as duas visões.

**Implementação ([estatisticas.py](../app/services/estatisticas.py)):**
- **`_tem_historico(session, uid, mes, ano)`** — 4 consultas de existência (`LIMIT 1`,
  curto-circuito via `any`), uma por fonte, com a MESMA competência da projeção: Fonte 3 por
  `data <` 1º dia do corrente; Fontes 1/2 por tupla `(fatura_ano, fatura_mes) <` corrente
  (`or_/and_`; parcela respeita `cancelado=False`); Fonte 4 por vigência com
  `(ano_inicio, mes_inicio) <` corrente (vigência que começou no passado gerou ocorrência lá —
  cobre inclusive recorrência já encerrada). A transação-PAI parcelada NÃO conta (§2.1). Caminho
  comum (usuário com histórico): 4 queries e acabou.
- **`mes_default(session, uid)`** — devolve `((mes, ano) fluxo, (mes, ano) consumo)`. A varredura
  do "1º mês com fluxo" **reusa `_lancamentos_ano`** ano a ano (a MESMA projeção — zero drift de
  definição; "tem fluxo" == lista não-vazia, pois todo lançamento tem `valor > 0` por CHECK).
  Só usuários SEM histórico chegam à varredura (base pequena por definição) — custo máx. ~6×5
  queries triviais.
- **`HORIZONTE_MESES = 60`** — primeira materialização do §6.5 como constante no backend.
- Helper `_mes_seguinte` (virada dez → jan/ano+1).

**Testes (`TestDefaultMonth` em [test_statistics_router.py](../tests/routers/test_statistics_router.py), 11, hoje=15/07/2026):**
histórico (à vista em jun) vence fluxo futuro → corrente; parcela vencendo no corrente →
corrente (pai parcelada não é histórico); corrente vazio + parcela em 2 meses → pula para o mês
da parcela; sem nada → mês seguinte; **multi-cartão** (faturas em out e set) → o mais próximo
(set); consumo sempre corrente mesmo com fluxo futuro; recorrência com início futuro é o 1º
fluxo (e NÃO é histórico); **recorrência encerrada no passado conta como histórico** → corrente;
parcela cancelada não conta (nem histórico nem fluxo) → fallback; **borda do horizonte**
(+60 meses entra, +61 cai no fallback — 2 usuários, também exercita isolamento); fallback vira o
ano em dezembro (jan/2027). Helpers estendidos com defaults aditivos (`_add_recorrencia` ganhou
`mes_fim/ano_fim`; `_add_parcelada` ganhou `cartao_id/cancelado`; novo `_add_avista`).

**Não incluído:** frontend (toggle e consumo do default-month), importação, bugs de cartão.

---

## Bug 2 (extensão) — piso por DATA da primeira ocorrência no POST /recorrencias (06/07/2026)

Fecha o buraco achado em uso: o piso do Bug 2 validava só o **mês** (`(ano, mes) >= mês corrente`), então um override no **mês corrente** com `dia_do_mes` **já passado** (ex. hoje 5/jul, `dia_do_mes=4`) passava na validação e criava a primeira ocorrência no PASSADO (4/jul, ontem) — exatamente o histórico retroativo que o Bug 2 quis proibir. A regra correta é sobre a **DATA da primeira ocorrência** (mês+dia), não só o mês. Suíte: **319 testes** (315 + 4), todos verdes.

**A correção ([recorrencias.py](../app/routers/recorrencias.py) `create_recorrencia`, branch de override):**
- Primeira ocorrência = `dt.date(ano_inicio, mes_inicio, clamp_dia_no_mes(dia_do_mes, ano_inicio, mes_inicio))` — o **MESMO clamp** que `data_ocorrencia` usa (dia 31 em fev = último dia; não dá para chamar `data_ocorrencia` direto porque ela exige a instância `Recorrencia`, que ainda não existe nesse ponto — o cálculo é idêntico por construção, via o helper compartilhado de `faturas.py`).
- `primeira_ocorrencia < hoje` → **422** `"A primeira ocorrência da recorrência não pode ser no passado."`; `== hoje` → OK (o próprio dia conta — coerente com o `<=` do §1.3.1); futura → OK. Comparação por **`dt.date`**, não por tupla de mês.
- **SUBSTITUI a comparação mensal** do Bug 2 (não coexistem — a validação de data é mais forte e engloba a de mês: mês passado ⇒ data passada ⇒ 422). Mensagem única; a antiga `"anterior ao mês corrente"` sai.
- **Default (regra do dia) intocado e fora da validação** — seguro por construção: dia >= hoje → mês corrente (ocorrência hoje ou à frente); dia < hoje → mês seguinte (ocorrência futura). A primeira ocorrência default nunca é passada; os testes do default seguem afirmando isso.
- Mesmas razões do Bug 2 para viver **no router, não no schema**: compara contra o MESMO `hoje` que o resto do endpoint (a suíte patcha `app.routers.recorrencias.hoje`), e o backend é a fronteira REAL de integridade (a UI ganha o aviso/bloqueio no Add em outro batch — Batch 2 do frontend).

**Testes (`TestPisoInicioNoPassado`, hoje=15/07/2026):**
- **Único existente alterado:** `test_override_mes_passado_422` — só a assertion da mensagem (`"anterior ao mês corrente"` → `"no passado"`), porque a mensagem mudou de mês para data. Nenhum outro mudou: o `_payload()` usa `dia_do_mes=20` (> 15), então todos os overrides corrente/futuro existentes já tinham primeira ocorrência futura.
- **4 novos:** mês corrente + dia 10 (passado) → 422 (o buraco); mês corrente + dia 15 (== hoje) → 201 (borda); mês futuro (ago) + dia 1 → 201 (dia < 15 mas o MÊS é futuro → data futura); clamp em mês curto (hoje re-mockado 28/02/2027, `mes_inicio=2/2027`, `dia_do_mes=31` → clampa para 28/02 == hoje → 201, sem `ValueError`).

**Fora de escopo:** frontend (aviso/bloqueio no Add — Batch 2), projeção, regra do dia (default).

## Bug 1 — valor_exibicao: valor de recorrência com início futuro na gestão (05/07/2026)

Fecha o achado E2E: uma recorrência cuja 1ª vigência começa no **mês seguinte** (ex.: criada com dia já passado → a regra do dia joga o início pro próximo mês) tinha `valor_vigente=null` — pois `valor_no_mes(mês corrente)` não acha vigência cobrindo hoje. A lista mostrava "—" e o form de Editar carregava **vazio** um valor que **existe** em `vigencias[]`, forçando o usuário a redigitar às cegas ao editar metadados. Suíte: **315 testes** (310 + 5), todos verdes.

**Fix ADITIVO — campo novo, `valor_vigente` intocado:** um novo campo `valor_exibicao` na resposta, SEM sobrescrever `valor_vigente`. Motivo: `valor_vigente` tem o significado estrito "vige HOJE" e há consumidores que dependem do `null` (gating do "corrigir valor" e a comparação de valor no frontend). O campo novo é só para exibição/preenchimento.

**A regra (helper puro `valor_exibicao` em [services/recorrencias.py](../app/services/recorrencias.py)):**
- Reusa `valor_no_mes` (não duplica o "vige hoje"): `= valor_no_mes(mês corrente)` quando algo vige.
- **Senão**, o valor da **vigência FUTURA mais próxima**: `min` por `(ano_inicio, mes_inicio)` entre as vigências com início `>= (ano, mes)`. Comparação por tupla, via `hoje()`.
- **Borda crítica (encerrada):** o fallback é restrito a início **futuro**. Recorrência encerrada só tem vigências passadas (fechadas antes do mês corrente) e nenhuma futura → `valor_exibicao=null` → continua "—" na gestão (correto — não pega valor de vigência passada). Só o **início futuro** ganha valor; **vigente hoje** → `valor_exibicao == valor_vigente`.

**Complemento (05/07/2026) — `mes_exibicao`/`ano_exibicao` (início da vigência de exibição):** para a UI mostrar "R$1.500,00/mês · a partir de ago/2026", o front precisa também do mês/ano de início da vigência futura. Adicionados dois ints aditivos `mes_exibicao`/`ano_exibicao` (espelham `mes_inicio`/`ano_inicio`). **Coerência garantida por construção:** o helper `valor_exibicao` foi generalizado para **`dados_exibicao`** — retorna o trio `(valor, mes, ano)` da **MESMA** vigência de exibição num só cálculo (fonte única, impossível divergir). Regra do início: **vige hoje** → `(mes, ano)_exibicao = None` (já está valendo, sem "a partir de"); **início futuro** → o `(mes_inicio, ano_inicio)` da vigência futura mais próxima (a mesma que dá o `valor_exibicao`); **encerrada** → `None` (coerente com `valor_exibicao=null`). O standalone `valor_exibicao` foi removido (só o router o usava) — o router desempacota `dados_exibicao` na lista e no `_detail`.

**Onde entra ([recorrencias.py](../app/routers/recorrencias.py)):** `RecorrenciaResponse` ganhou `valor_exibicao: Optional[Decimal]` + `mes_exibicao`/`ano_exibicao: Optional[int]` (o `RecorrenciaDetailResponse` herda — cobre **lista e detalhe**). O router calcula com o mesmo `h = hoje()` na lista (`list_recorrencias`) e no `_detail`. **Projeção intocada** (campos de leitura da gestão, não entram em `_lancamentos_*`).

**Testes (`TestValorExibicao`):** início mês seguinte → `valor_vigente=null`, `valor_exibicao=valor` e `(mes,ano)_exibicao=(8,2026)` — lista **e** detalhe, com **coerência afirmada** (valor e início batem com a mesma `vigencias[0]`); vigente hoje → `valor_exibicao == valor_vigente` e `(mes,ano)_exibicao=None`; **encerrada só passado → tudo null** (a borda); início futuro distante (out/2026) → `(mes,ano)_exibicao=(10,2026)`; múltiplas vigências com uma vigente hoje → `valor_exibicao == valor_vigente` e início `None`.

**Fora de escopo:** frontend (ler `valor_exibicao` na lista e no prefill do Editar — próximo batch), mudar `valor_vigente`, tocar na projeção.

## Bug 2 — piso no mês corrente no POST /recorrencias (05/07/2026)

Fecha o buraco de integridade achado na validação E2E: a UI permitia criar recorrência com "Começa em" num mês **já passado** (ex.: hoje jul/2026, começar em jun/2026), criando histórico financeiro retroativo que nunca existiu — corrompe meses fechados e a variação vs. mês anterior. O passado é **verdade histórica** (`docs/PLANO_PROJECAO.md` §3.1.2), não se inventa recorrência retroativa. Suíte: **310 testes** (304 + 6), todos verdes.

**A correção — piso no override, no router ([recorrencias.py](../app/routers/recorrencias.py) `create_recorrencia`):**
- Só o **override explícito** (cliente envia `mes_inicio`/`ano_inicio`) precisa do piso. O **default (regra do dia, `_default_mes_inicio`)** nunca resolve para o passado (corrente-ou-seguinte por construção) → fica **intacto**, não é revalidado.
- Comparação por tupla: `(ano_inicio, mes_inicio) < (hoje.year, hoje.month)` → **422** `"O início da recorrência não pode ser anterior ao mês corrente."` Início no mês corrente = OK; futuro = OK (ajustar pra frente segue válido — "esse salário só começa em setembro"). Só o **passado** é barrado.

**Por que no router e não no schema (decisão registrada):** o piso precisa do MESMO `hoje` que o resto do endpoint usa. A suíte patcha `app.routers.recorrencias.hoje` (fixture autouse `clock`). Um validator no schema chamaria `app.schemas.recorrencia.hoje` — segundo ponto de relógio, não patchado → cairia no relógio real, quebrando o determinismo dos testes congelados. No router reusa o `h = hoje()` já computado, colado à resolução de `mes_inicio/ano_inicio`.

**Fronteira REAL de integridade:** o frontend vai ganhar um `min` no campo (outro batch), mas a UI é burlável por chamada direta — o backend DEVE validar. Este é o ponto que garante a invariante.

**Migração de teste (sem perda de cobertura do POST):** ~13 testes de editar/encerrar/corrigir/preservação usavam o POST com início jan/2026 (passado) só como **setup** para obter uma recorrência com história. Com o piso, esse POST devolve 422. A adaptação monta o **mesmo estado** — que é legítimo: é como fica uma recorrência criada meses atrás e ainda vigente — **direto no banco** via helper `_semear_recorrencia_passada(session, uid, valor)` (a session de teste e a do app são a mesma, dependency override). A cobertura de **sucesso do POST** não migrou pra lugar nenhum perigoso: continua em `TestCriar` (criar corrente, listagem, projeção, início futuro 2027), em `TestRegraDiaDefaultInicio` e na nova **`TestPisoInicioNoPassado`** (corrente/futuro → 201). A nova classe cobre: override mês passado → 422 (+ mensagem), override ano passado → 422, override corrente → 201, override futuro → 201, default dia futuro → mês corrente, default dia passado → mês seguinte (regra do dia intacta).

**Fora de escopo:** frontend (`min` no campo é outro batch), Bug 1 (valor vazio, próximo).

## Operações de erro na recorrência (§3.1.2) — hard delete + corrigir valor retroativo (04/07/2026)

Implementa as duas operações **"foi um erro"** do `docs/PLANO_PROJECAO.md` §3.1.2, distintas das operações normais **"a realidade mudou"** (alterar versionado + encerrar soft, da 2c — que permanecem intactas e como default). Suíte: **304 testes** (294 + 10), todos verdes.

**Decisão de contrato — rotas separadas, não flag/`modo` nas rotas existentes:** um booleano `?permanente=true` ou um campo `modo` deixa o caminho destrutivo a um typo do seguro (cliente que repassa um campo de form aciona destruição sem intenção). Rota dedicada é impossível de acionar por acidente, autodocumentada no OpenAPI e auditável nos logs de request sem parsear query string. Bônus: os endpoints da 2c não mudaram nem um byte.

**`DELETE /recorrencias/{id}/permanente` (204) — apagar permanentemente ([recorrencias.py](../app/routers/recorrencias.py)):**
- Remove a `Recorrencia` E todas as `RecorrenciaVigencia` (DELETE real). Como a projeção é calculada on-the-fly (§3.3 — nada materializado em transacoes/parcelas), apagar regra + vigências limpa histórico e projeção automaticamente.
- **Deletes explícitos num único commit** (vigências → cabeçalho): o `ON DELETE CASCADE` do Postgres existe (confirmado na verificação da migration 2a, `confdeltype='c'`), mas vive só na migration — o SQLite dos testes não o enforça. Convenção do Batch 11a: explícito como garantia DB-agnóstica, CASCADE como defesa em profundidade.
- **Aceita ativa E encerrada** (`exigir_ativa=False`, diferente do soft/PATCH): é a borracha — cobre "encerrei por engano" (senão a encerrada-lixo ficaria eterna em `incluir_encerradas`) e o caminho "apagar + recriar" do §3.1.2.
- Isolamento T-36 (404 alheia/inexistente).

**`PATCH /recorrencias/{id}/corrigir-valor` (200, detalhe) — corrigir valor retroativo:**
- Body: novo schema `RecorrenciaCorrigirValor {valor}` ([schemas/recorrencia.py](../app/schemas/recorrencia.py), validadores padrão: >0, vírgula normalizada).
- **Vigência ÚNICA (erro fresco):** reescreve `valor` **in place** — mesma linha, mesmo período, `len(vigencias)` continua 1. O passado reflete o valor corrigido (o erro é apagado da história, não versionado).
- **2+ vigências:** **409** `"Correção retroativa indisponível: a recorrência já teve o valor alterado. Use alterar (a partir deste mês) ou apague permanentemente e recrie."` — nada muda no banco (proteção do backend; o frontend nem oferece a opção nesse caso).
- Exige `ativa=True` (encerrada → 404, consistente com o PATCH normal). Isolamento T-36.

**Zero migration** (CASCADE já existia; nenhuma coluna nova). **Nenhuma mudança em estatisticas.py/projeção.**

**Testes ([test_recorrencias_router.py](../tests/routers/test_recorrencias_router.py), 10):**
- `TestHardDelete` (4): linhas somem do banco (cabeçalho E vigências) e a projeção de mês PASSADO zera (contraste com o soft); funciona em encerrada (soft → permanente → some); **soft delete segue sem apagar linhas** (contraste explícito); isolamento (B → 404, nada apagado).
- `TestCorrigirValor` (6): vigência única reescrita in place (mesmo id, mesmo período, passado corrigido em toda a projeção); múltiplas vigências → 409 com mensagem e vigências byte a byte intactas; encerrada → 404; alheia → 404; valor 0/negativo → 422 (2 parametrizados).
- Rede da 2c intacta: PATCH versionado e DELETE soft seguem com os testes originais verdes.

**Não incluído:** frontend (próximo batch — modal Editar com "Alterar × Corrigir" nomeados e "Apagar permanentemente" no rodapé, §3.1.2-UX), encerrar-em-data-futura, lixeira/undo.

---

## Correção §1.3.1 (projeção) — Corte por dia no mês corrente: realizado / a-vir / projeção (03/07/2026)

Implementa o **§1.3.1/§1.3.2** do `docs/PLANO_PROJECAO.md` (motivado por bug real: recorrência/parcela do mês corrente cujo dia ainda não chegou era somada como se já tivesse ocorrido). Suíte: **294 testes** (282 antigos **sem nenhum ajuste** + 12 novos), todos verdes.

**Desenho central — marcação, não filtro ([estatisticas.py](../app/services/estatisticas.py)):** a projeção integral continua sendo a lista COMPLETA de lançamentos (topo do shape, coerência mensal×anual, variação e IA intocados); o corte vira uma **flag por lançamento**:
- `LancamentoFluxo` ganhou **`realizado: bool = True`** (default True → construções existentes e Fontes 2/3 intocadas; mesmo padrão do `recorrente` da 2b). Invariante `projeção = realizado + a_vir` vale por construção.
- `_lancamentos_mes`: lê `h = hoje()` (novo import de dates.py) e `corrente = (ano, mes) == (h.year, h.month)`. **Fonte 1**: `realizado = (não corrente) or (p.data_vencimento <= h)` — vencimento REAL da parcela, não o fatura_mes (§1.3.2). **Fonte 4**: `_ocorrencias_recorrentes` ganhou `limite_realizado: Optional[date] = None` — quando setado (só no mês corrente), `realizado = data_ocorrencia(rec, mes, ano) <= limite` (reusa o clamp da 2a). **Fontes 2/3**: sempre realizadas (§1.3.2 — à vista já ocorreu por definição; avulsa de cartão não tem o dia de vencimento na Transacao, refinamento posterior).
- `_lancamentos_ano`: MESMA marcação para o mês corrente dentro do ano (Fonte 1 por data_vencimento; Fonte 4 com limite só no mês corrente) — as flags não divergem entre card e gráfico. A série anual segue sendo a projeção integral.
- Fronteira **`<=`** (dia == hoje conta como realizado). Meses não-correntes: tudo `realizado=True` (passado ocorreu; futuro é projeção integral — **mês futuro NÃO é a-vir**, `a_vir` só existe no mês corrente).

**Shape (Opção 1, aditiva) — [schemas/statistics.py](../app/schemas/statistics.py) + [statistics.py](../app/routers/statistics.py):** novo `LeituraMes {receitas, despesas, saldo}`; `MensalResponse` ganhou `realizado: LeituraMes` e `a_vir: LeituraMes`. **Topo inalterado = projeção integral** (a_vir computado por diferença — invariante exato). `categorias` (donut) segue projeção. **Variação: nenhuma mudança de código** — já era agregação integral × integral (projeção×projeção, §1.3.1); teste novo trava isso. `yearly_stats`/`categories_stats`/**IA: zero mudança** (consomem a agregação integral).

**Nota para testes futuros:** `_lancamentos_mes/_ano` agora leem o relógio — testes que afirmem as flags devem patchear **`app.services.estatisticas.hoje`**. Os 282 antigos não precisaram de ajuste porque afirmam totais (= projeção integral), que não mudaram.

**Testes (12):**
- `TestLeiturasDoDia` ([test_estatisticas.py](../tests/services/test_estatisticas.py), 9, hoje=15/07/2026): recorrência dia 20 → projeção conta, realizado não, a_vir conta; dia 10 → realizado; **fronteira dia 15 == hoje → realizado**; parcela vencendo 20/07 → projeção sim/realizado não/a_vir sim (e em junho, mês passado, integral); parcela vencida 10/07 → realizada; **invariante realizado + a_vir == projeção** com as 4 fontes juntas; mês passado E futuro integrais com a_vir = 0; **Fontes 2/3 integrais no corrente** (inclusive à vista com data futura — decisão §1.3.2; validação de cadastro é item separado); flags do anual == flags do mensal no mês corrente.
- [test_statistics_router.py](../tests/routers/test_statistics_router.py) (novo, 3): `GET /statistics/monthly` do mês corrente → topo = projeção + decomposição correta + invariante no shape; mês não-corrente → `realizado == topo`, `a_vir` zerado; **variação usa projeção** (mesma recorrência jun/jul, dia não chegou → 0.00%, não −100%).

**Não incluído:** frontend (exibir realizado/a-vir — próxima metade), corte nas Fontes 2/3, validação de data futura no cadastro de transação (item registrado no §1.3.2), donut por leitura.

---

## Fase 3a-backend (projeção) — Regra do dia para o mês de início default da recorrência (03/07/2026)

Refina o **default** de `mes_inicio`/`ano_inicio` na criação de recorrência. Antes, o POST `/recorrencias` defaultava para o **mês corrente** (`hoje().month`/`.year`) sempre que o cliente não especificava. Agora o default é **lógica de negócio** (fica no backend, não no frontend): depende do **dia da ocorrência vs. hoje**. Suíte: **282 testes** (276 + 6), todos verdes.

**A regra (só quando o cliente NÃO envia `mes_inicio`/`ano_inicio`):**
- `dia_do_mes >= dia de hoje` → **MÊS CORRENTE** (a ocorrência ainda vai acontecer este mês). Inclui a **borda** `dia_do_mes == dia de hoje` (a ocorrência ainda ocorre hoje).
- `dia_do_mes < dia de hoje` → **MÊS SEGUINTE** (o dia já passou; a primeira ocorrência é no próximo mês).
- **Virada de ano** natural: se hoje é dezembro e o dia já passou, o mês seguinte é **janeiro do ano seguinte** (`h.month == 12` → `(1, h.year + 1)`).

**Override explícito preservado (o "ajustar" da UI):** se o cliente ENVIA `mes_inicio`/`ano_inicio` (pareados no schema), usa os valores enviados — a regra do dia só governa o DEFAULT. Preserva "esse salário só começa em setembro".

**Implementação ([app/routers/recorrencias.py](../app/routers/recorrencias.py)):** novo helper puro `_default_mes_inicio(dia_do_mes, h)` (usa `hoje()` de `dates.py` para dia/mês/ano correntes — patchável nos testes, sem hardcode); `create_recorrencia` chama-o no ramo default e usa `body.mes_inicio`/`ano_inicio` no ramo de override. **Mudança isolada na resolução do default do POST** — NÃO toca `valor_no_mes`/algoritmo (2a), integração na projeção (2b), PATCH/DELETE/vigência (2c) nem o modelo. Recorrência **não passa por cartão** — a regra é sobre o dia da ocorrência vs. hoje, sem relação com ciclo de fatura.

**Testes ([tests/routers/test_recorrencias_router.py](../tests/routers/test_recorrencias_router.py), `hoje` congelado em 15/07/2026):**
- Nova classe `TestRegraDiaDefaultInicio` (6): dia futuro (20) → jul/2026; dia passado (10) → ago/2026; dia == hoje (15) → jul/2026; virada de ano (`hoje`→15/12/2026, dia 10) → jan/2027; override explícito (dia 10 + `mes_inicio=9`/`ano_inicio=2026`) → set/2026 (ignora a regra); reflexo na projeção (dia 10 → julho zero, agosto gera 10.000).
- **Ajuste no fixture `_payload`:** `dia_do_mes` `5` → `20`. Os 4 testes de CRUD que usavam o `_payload` sem `mes_inicio` (criar/listar/projeção/editar-no-mês-da-criação) assumiam "default = mês corrente"; com a regra nova, dia 5 < hoje 15 viraria mês seguinte e quebraria as assertions de valor/mês. Dia 20 (> 15) preserva a intenção "começa no mês corrente" **sem alterar nenhuma assertion**. Confirmado que nenhum teste depende do dia 5 em si (não há assert de `data_ocorrencia`/`dia_do_mes == 5`).

**Não incluído:** frontend (próximo batch), qualquer mudança no algoritmo/integração/vigência.

---

## Fase 2c (projeção) — CRUD de recorrência (endpoints + lógica de vigência) (03/07/2026)

Implementa a **Fase 2c** do `docs/PLANO_PROJECAO.md` (§3.1.1/§3.4) — o último batch da recorrência no backend. Suíte: **276 testes** (254 intocados + 3 da semântica nova + 19 do CRUD), todos verdes.

**⚠️ Mudança de semântica (resolução da tensão 2a, aprovada): `ativa` saiu do caminho da PROJEÇÃO.**
- [recorrencias.py (service)](../app/services/recorrencias.py): `valor_no_mes` **não checa mais `ativa`** — lê só as vigências. O parâmetro `recorrencia` fica na assinatura (extensão futura de `frequencia`).
- [estatisticas.py](../app/services/estatisticas.py): `_recorrencias_com_vigencias` **não filtra mais `ativa == True`**.
- Racional: com o DELETE preservando o passado via fechamento de vigência, `ativa` acumulava duas responsabilidades contraditórias. Agora: vigências = fonte de verdade financeira (projeção); `ativa` = flag de estado/listagem. Via API, "inativa com vigência aberta" é **inconstruível** (o DELETE sempre fecha a vigência junto). O §3.4 do PLANO_PROJECAO registra a resolução.
- **2 testes antigos reescritos para a semântica nova** (não removidos): `TestSoftDelete` (2a) → `TestRecorrenciaEncerrada` (encerrada com vigência fechada gera no passado, não no futuro; `ativa=False` sozinho não esconde) e `test_inativa_nao_aparece` (2b) → `test_encerrada_passado_aparece_futuro_some`.

**Schemas ([app/schemas/recorrencia.py](../app/schemas/recorrencia.py)):** `RecorrenciaCreate` (validadores padrão do projeto: tipo receita/despesa, valor>0 com vírgula normalizada, dia_do_mes 1–31, max_length F-22; `mes_inicio`/`ano_inicio` opcionais PAREADOS — default mês corrente; categoria é string livre, padrão do projeto; `frequencia` não é aceita — só 'mensal'), `RecorrenciaUpdate` (tudo opcional; `valor` versiona, resto é metadado), `RecorrenciaResponse` (+ **`valor_vigente`** — valor no mês corrente p/ a UI), `RecorrenciaDetailResponse` (+ `vigencias` ordenadas), `VigenciaResponse`.

**Router ([app/routers/recorrencias.py](../app/routers/recorrencias.py), registrado no [main.py](../main.py) sob `/api/v1` com `verify_origin`):** padrão dos demais (get_current_user/get_session; 404 idêntico p/ inexistente OU alheio — T-36; mês corrente via `hoje()` de dates.py, patchável nos testes).
- **POST** (201): cabeçalho + primeira vigência aberta num único commit; devolve o detalhe.
- **GET**: só ativas por padrão; `?incluir_encerradas=true` traz todas; `valor_vigente` computado com a busca da Fonte 4 reusada (2 queries, sem N+1); ordem estável por `data_criacao`.
- **GET /{id}**: detalhe com vigências; encerrada TAMBÉM aparece (histórico).
- **PATCH** (exige ativa; encerrada → 404): valor → acha a vigência aberta; se ela começou **neste mês ou no futuro** → **substitui in place** (2ª edição no mês não degenera; início futuro é preservado); senão → **fecha no mês anterior + abre nova no corrente** (sem gap/sobreposição por construção). Sem vigência aberta (anômalo) → 409. Metadados → cabeçalho direto, vigências intactas.
- **DELETE** (204; exige ativa; repetido → 404): fecha a vigência aberta em **mês corrente** + `ativa=False`. Nenhuma linha apagada. Edge: vigência de início FUTURO fechada no corrente vira intervalo `fim < início` = vazio → nunca gera (correto p/ "excluí antes de começar"; coberto por teste).

**[main.py](../main.py) — CORS:** `allow_methods` ganhou **`PATCH`** (estava fora; o preflight do browser bloquearia o PATCH novo em produção). `verify_origin` já cobria PATCH (`_MUTATING_METHODS`).

**Testes ([tests/routers/test_recorrencias_router.py](../tests/routers/test_recorrencias_router.py), 19, `hoje` congelado em 15/07/2026):** criar (cabeçalho+vigência aberta, listagem com valor_vigente, **reflexo na Fonte 4** em mês corrente/futuro, início informado, 6 validações 422); editar valor (vigências exatas jan–jun@10000 + jul–aberta@12000 sem gap, projeção passado/corrente/futuro; 2ª edição no mês → segue 2 vigências; edição no mês da criação → 1 substituída; início futuro preservado); metadados (cabeçalho muda, vigência e projeção de valor intactas); DELETE (fechada em jul, jun/jul geram, ago não, listagem padrão esconde/`incluir_encerradas` mostra, detalhe acessível; início futuro nunca gera; escrita em encerrada → 404); isolamento (B: lista vazia, 404 em GET/PATCH/DELETE do A, dados do A intactos).

**FECHA A FASE 2 (recorrência) no backend.** Próximo da projeção: **Fase 3 (frontend)** — lentes, toggle fluxo/consumo, tela de recorrências (consome estes endpoints). A flag `recorrente=True` já existe nos lançamentos internos da projeção; expor os lançamentos do mês (com a flag) num endpoint para a lista de Transações é decisão de contrato da Fase 3.

**Não incluído:** frontend (Fase 3), overrides de ocorrência, frequência não-mensal, recorrência em cartão, migration (nenhuma mudança de schema).

---

## Fase 2b (projeção) — Recorrência na projeção de fluxo (quarta fonte) (03/07/2026)

Implementa a **Fase 2b** do `docs/PLANO_PROJECAO.md` (§3.4, "Integração na projeção de fluxo"): as ocorrências de recorrência ATIVAS do usuário entram na agregação de fluxo da Fase 1 como **quarta fonte**. Tudo em [estatisticas.py](../app/services/estatisticas.py) + testes — **nenhum router mudou** (statistics e o contexto da IA consomem `_lancamentos_mes`/`_lancamentos_ano` e herdam a fonte automaticamente; o contexto da IA passa a enxergar recorrências — consequência natural e intencional). Suíte: **256 testes** (248 + 8), todos verdes.

**`LancamentoFluxo` — novo campo `recorrente: bool = False`:** ocorrências de recorrência nascem com `recorrente=True`; as 3 fontes existentes ficam com o default (nenhuma construção mudou — campo com default em dataclass frozen). `_agregar`/`_categorias` **não mudaram** (duck typing em tipo/valor/categoria) — a flag existe para a Fase 3 distinguir visualmente.

**Busca sem N+1 (2 queries fixas) — `_recorrencias_com_vigencias(session, uid)`:** (a) `Recorrencia` com `ativa == True` do usuário; (b) `RecorrenciaVigencia` com `recorrencia_id IN (ids)` (guarda de lista vazia → retorna cedo, padrão Batch 8), agrupadas por recorrência em Python. Retorna `list[tuple[Recorrencia, list[RecorrenciaVigencia]]]`. O filtro `ativa` na query evita carregar soft-deletadas; `valor_no_mes` segue como dupla guarda.

**Fonte 4 pura — `_ocorrencias_recorrentes(recs_com_vigs, mes, ano)`:** aplica `valor_no_mes` (Fase 2a) a cada recorrência; não-None vira `LancamentoFluxo(rec.tipo, valor, rec.categoria, recorrente=True)`. Receita recorrente soma nas receitas, despesa nas despesas e no donut — automático via tipo/categoria. Recorrência **não passa por fatura** (§3.4): competência do MÊS direto, como a Fonte 3. Sem tratamento de horizonte (60 meses é limite de EXIBIÇÃO — Fase 3; o backend calcula o mês pedido).

**Integração:**
- `_lancamentos_mes`: após as 3 fontes (intocadas), `extend` com a Fonte 4 (2 queries + cálculo).
- `_lancamentos_ano`: `_recorrencias_com_vigencias` chamada **UMA vez**; `for m in 1..12` aplica `_ocorrencias_recorrentes` **em memória** — zero query por mês. Total do anual: **5 SELECTs fixos** (3 fontes + 2 recorrência).

**Testes (`TestRecorrenciaNaProjecao` em [test_estatisticas.py](../tests/services/test_estatisticas.py), 8):**
- Salário R$10.000 vigência aberta → receitas de jan/2026, jul/2026, dez/2027 e jan/2031 == 10.000; antes do início == 0.
- Marcação: lançamento de recorrência com `recorrente=True`, transação comum com `False`.
- Despesa recorrente soma nas despesas **e** aparece no donut (`_categorias`) com a categoria certa.
- Edição versionada na agregação real: 10.000 jan–jul + 12.000 ago–aberto → julho=10.000, agosto=12.000.
- `ativa=False` → lista vazia (nem donut).
- Isolamento por usuário (recorrência do uid=2 não vaza para uid=1).
- **Coerência mensal×anual COM recorrência** no cenário completo das 4 fontes (parcelas 12x + avulsa faturada + à vista + receita versionada + despesa recorrente com fim): `_agregar(_lancamentos_ano[m]) == _agregar(_lancamentos_mes(m))` para os 12 meses.
- **Eficiência afirmada em teste:** listener `before_cursor_execute` conta SELECTs durante `_lancamentos_ano` → **exatamente 5** (trava N+1 de recorrência E regressão nas fontes 1–3).
- Rede da Fase 1 intacta: invariante 12x, coerência sem recorrência e os 248 anteriores seguem verdes.

**Não incluído:** endpoints CRUD (2c), frontend (Fase 3), overrides, recorrência em cartão. Shape das respostas inalterado — só os números passam a incluir recorrência.

---

## Fase 2a (projeção) — Fundação da recorrência: modelos + migration + algoritmo (03/07/2026)

Implementa a **Fase 2a** do `docs/PLANO_PROJECAO.md` (§3.4) — o batch que prova que o **modelo** e o **algoritmo** da recorrência estão corretos, ANTES da integração na projeção (2b) e do CRUD (2c). Suíte: **248 testes** (221 + 27), todos verdes.

**Modelos ([app/models/recorrencia.py](../app/models/recorrencia.py), exportados em `__init__.py`):**
- **`Recorrencia`** (tabela `recorrencias`) — o cabeçalho estável ("meu salário"): `id` **UUID PK** (convenção de `chat_messages`), `usuario_id` **int** FK `usuarios.id` (o PK de usuários é int), `tipo` (receita/despesa), `categoria`, `forma_pagamento`, `frequencia` (só `'mensal'` hoje — campo existe para extensão futura), `dia_do_mes` (1–31), `descricao`, `ativa` (soft delete), `data_criacao` (datetime SP via `agora()`). **NÃO guarda valor** — o valor vive nas vigências.
- **`RecorrenciaVigencia`** (tabela `recorrencia_vigencias`) — as versões de valor: `id` UUID PK, `recorrencia_id` UUID FK, `valor` `Numeric(15,2)`, `mes_inicio`/`ano_inicio`, `mes_fim`/`ano_fim` **nullable** (NULL = vigência aberta "sem fim"). 1+ vigências por recorrência, **sem sobreposição** (invariante a garantir na escrita — 2c).
- **CHECKs declarados também em `__table_args__`** (paridade metadata↔DB do Batch 6; SQLite dos testes enforça): `tipo IN (...)`, `dia_do_mes BETWEEN 1 AND 31`, `frequencia = 'mensal'`, `mes_inicio BETWEEN 1 AND 12`, `mes_fim NULL OR BETWEEN 1 AND 12`, `(mes_fim IS NULL) = (ano_fim IS NULL)` (os dois nulos juntos ou ambos preenchidos), `valor > 0`.
- FKs **sem** `ondelete` nos models — CASCADE vive na migration (convenção registrada no Batch 11a).

**Migration `f2a7c9d1e8b3` (down_revision `e7c9a1b2d3f4`):** cria as 2 tabelas com FKs **ON DELETE CASCADE** (`usuarios`→`recorrencias`, `recorrencias`→`recorrencia_vigencias`), os 7 CHECKs com os mesmos nomes dos models, índices `ix_recorrencias_usuario_id`, `ix_recorrencia_vigencias_recorrencia_id` e o composto `ix_rec_vigencias_rec_periodo (recorrencia_id, ano_inicio, mes_inicio)` (busca de vigência por período). `downgrade()` completo. **Testada DE VERDADE no Postgres dev (Supabase):** `upgrade` → verificação por SQL (tabelas, 7 CHECKs, FKs com `confdeltype='c'`, índices, colunas UUID/nullable corretas) → `downgrade -1` → verificação (tabelas somem) → `upgrade head` de novo. **Estado final do dev: migration APLICADA** (`f2a7c9d1e8b3 (head)`).

**Algoritmo puro ([app/services/recorrencias.py](../app/services/recorrencias.py), sem I/O de banco — recebe os dados e computa; reusável na projeção 2b):**
- `valor_no_mes(recorrencia, vigencias, mes, ano) -> Optional[Decimal]`: (1) `ativa=False` → None; (2) acha a vigência cujo período contém `(mes, ano)` — **comparação por tupla `(ano, mes)`** (cobre virada de ano), fim NULL = aberto; (3) retorna o `valor` dela; nenhuma contém → None. Não pressupõe lista ordenada (pela invariante, no máximo uma casa).
- `data_ocorrencia(recorrencia, mes, ano) -> date`: `dia_do_mes` clampado ao último dia do mês. O `dia_do_mes` **não** afeta SE gera — só a DATA.

**Helpers de suporte (aprovados no plano):**
- [dates.py](../app/core/dates.py): novo **`agora()`** — datetime `now(TZ_PRODUTO)` (São Paulo); não existia helper de datetime, só `hoje()` (date).
- [faturas.py](../app/services/faturas.py): o clamp `min(dia, calendar.monthrange(...)[1])`, repetido inline em 4 pontos, foi extraído para **`clamp_dia_no_mes(dia, ano, mes)`** e os 4 call sites refatorados (comportamento idêntico — a cobertura de 100% do Batch 2 segue verde). A recorrência importa ESTE helper (não reimplementa o clamp, PLANO §3.4).

**Testes (27 novos):**
- [tests/services/test_recorrencias.py](../tests/services/test_recorrencias.py) (15, algoritmo puro, sem banco): clamp dia 31→30 (abril), 31→28 (fev/2026 não bissexto), 31→29 (fev/2028 bissexto), dia normal intocado; vigência aberta gera nos **60 meses** do horizonte e não gera antes do início; vigência com fim gera **até o fim inclusive** e para depois (inclusive mesmo mês do ano seguinte); início no meio do ano; **edição versionada na fronteira exata** (10000 jan–jul, 12000 ago–aberto → jul=10000, ago=12000; independe da ordem da lista); `ativa=False` → None em passado/corrente/futuro; **virada de ano** dez/2026–fev/2027 (prova a comparação por tupla, não por mês).
- [tests/services/test_constraints.py](../tests/services/test_constraints.py) (12, `TestFase2aRecorrencias`/`TestFase2aVigencias`): tipo inválido, `dia_do_mes` 0/32, `frequencia='semanal'`, `mes_inicio=13`, `mes_fim=13`, fim inconsistente (mes sem ano e vice-versa) → `IntegrityError`; linhas válidas (aberta e fechada) passam.

**⚠️ Tensão de design registrada (resolver na 2b/2c, NÃO nesta fase):** o §3.4 diz no CRUD que o soft delete "para de gerar ocorrências FUTURAS, mas meses PASSADOS continuam aparecendo"; o algoritmo (passo 1, como especificado para 2a) retorna None em **qualquer** mês quando `ativa=False`. A conciliação (ex.: delete = fechar a vigência aberta no mês anterior, em vez de/além de `ativa=False`) é decisão da 2b/2c.

**Não incluído (fases seguintes):** endpoints CRUD (2c), integração na projeção de fluxo/estatísticas (2b), frontend (Fase 3), overrides de ocorrência, frequência não-mensal.

---

## Fase 1 (projeção) — Estatísticas por competência de fatura (T-39) (02/07/2026)

Implementa a **Fase 1** do `docs/PLANO_PROJECAO.md` (visão FLUXO). Antes, `_buscar_mes` somava **só** `transacoes` pela `data` da compra, ignorando `parcelas` e as colunas `fatura_mes/fatura_ano` — por isso mês futuro = zero e mês da compra parcelada = inflado (valor cheio). Agora as estatísticas mensais, **o anual** e o contexto da IA agregam por **competência de fatura**. Suíte: **221 testes** (213 + 8), todos verdes. **Shape das respostas inalterado — só os números mudam.**

**[estatisticas.py](../app/services/estatisticas.py) — novo núcleo de fluxo:**
- Novo dataclass `LancamentoFluxo(tipo, valor, categoria)` — normaliza as 3 fontes num objeto que `_agregar`/`_categorias` já somam por duck typing. Type hint de `_agregar`/`_categorias` relaxado para `Union[Transacao, LancamentoFluxo]` (yearly ainda passa `Transacao`).
- `_buscar_mes` **intacto** (segue retornando `Transacao` por `data`, sargável — T-10 verde) e reusado como **Fonte 3**.
- `_parcelas_competencia(session, uid, mes, ano)`: parcelas com `fatura_mes/ano==(mes,ano)`, `cancelado==False` — **NÃO olha `pago`** (PLANO §1.3).
- `_avulsas_cartao_competencia(...)`: `Transacao` `parcelado==False`, `tipo=='despesa'`, faturadas em `(mes,ano)` — espelha o filtro de avulsas de `invoices.py`.
- `_lancamentos_mes(...)`: une **Fonte 3** (`_buscar_mes` filtrando só `not parcelado and fatura_mes is None`) + **Fonte 1** (parcelas) + **Fonte 2** (avulsas faturadas). **Anti-dupla-contagem (§2.1):** a pai parcelada (`parcelado=True`, `fatura_mes=None`) e a avulsa já faturada são puladas na Fonte 3 — quem soma são as parcelas/avulsa na sua competência.

**Consumidores trocados de `_buscar_mes` → `_lancamentos_mes`:**
- **[statistics.py](../app/routers/statistics.py):** `monthly_stats` (mês atual + anterior) e `categories_stats`. `MensalResponse`/`CategoriasResponse` inalterados.
- **[ai.py](../app/routers/ai.py):** `chat` (contexto + `num_transacoes` agora conta lançamentos de fluxo), `_variacao_saldo_pct`, `_build_historico_anual`. `_total_parcelas_proximo_mes` passou a usar `_parcelas_competencia` (deriva de competência, **removido o filtro `pago==False`**; campo `pago` **não** removido — vira código morto, cleanup posterior). Import de `Parcela` (agora sem uso) removido de ai.py.

**Testes ([tests/services/test_estatisticas.py](../tests/services/test_estatisticas.py), classe `TestFluxoPorCompetencia`, 6 novos):**
- **Invariante (§7):** R$1200 em 12x → soma das despesas de fluxo nos 12 meses de competência == R$1200 (fluxo distribui, não perde/cria dinheiro).
- Mês da compra parcelada → parcela daquele mês (R$100), **não** o valor cheio.
- Mês futuro com parcela agendada → valor da parcela (não zero).
- Avulsa de crédito (compra jan, fatura fev) → conta em **fev** (competência), zero em jan (data).
- À vista + receita (sem cartão) → contam por `data`.
- `_total_parcelas_proximo_mes` conta parcela `pago=True` que vence no próximo mês e **ignora** `cancelado` (prova o desacoplamento de `pago`).
- **Rede preservada:** as 4 classes T-10 de `_buscar_mes` e os testes de fatura/round-trip/invoices/isolamento (Batch 8) seguem verdes — só os NÚMEROS das estatísticas mudaram, valores de fatura não.

**Adendo — `yearly_stats` estendido para FLUXO (mesmo commit):** o gráfico "Evolução mensal" (`/statistics/yearly`) agregava por `data.month` (consumo), fazendo o card "Saldo do mês" (fluxo) discordar do gráfico na MESMA tela. Agora agrega por **competência**, coerente com o mensal.
- **Novo `_lancamentos_ano(session, uid, ano) → dict[int, list[LancamentoFluxo]]`** em estatisticas.py: mesma semântica das 3 fontes / anti-dupla-contagem, escopada ao ano e resolvida em **3 queries** (uma por fonte) agrupadas por mês em Python — **preserva a ausência de N+1** do yearly (não virou 12× `_lancamentos_mes`). Fonte 1/2 filtram por `fatura_ano==ano` (bucket por `fatura_mes`); Fonte 3 por `data` no ano (bucket por `data.month`). Compra que atravessa anos distribui as parcelas por competência entre os anos.
- **[statistics.py](../app/routers/statistics.py) `yearly_stats`** monta `meses` a partir de `_lancamentos_ano`. `AnualResponse`/`MesEvolucao` **inalterados**. Imports órfãos removidos (`extract`, `select`, `Transacao`).
- **Testes (`TestFluxoAnual`, 2):** coerência card×gráfico — para cada mês do ano, `_agregar(_lancamentos_ano[m]) == _agregar(_lancamentos_mes(m))` (prova que não discordam mais); compra R$1200/12x começando ago/2026 distribui R$500 em 2026 + R$700 em 2027 == valor cheio (invariante atravessando anos).

---

## Deploy — remetente do e-mail parametrizado (EMAIL_FROM) (02/07/2026)

O domínio `hivvo.app` foi verificado no Resend. O `forgot_password` enviava de `Hivvo <onboarding@resend.dev>` (remetente de **sandbox**), que o Resend recusa para destinatários que não sejam o dono da conta. Agora o remetente é parametrizável. Suíte: **213 testes** (212 + 1 novo), todos verdes.

- **[config.py](../app/core/config.py):** novo `EMAIL_FROM: str = "Hivvo <onboarding@resend.dev>"`. O default mantém o sandbox → **dev e testes seguem funcionando sem env**.
- **[auth.py](../app/routers/auth.py) `forgot_password`:** o `"from"` hardcoded do `resend.Emails.send` virou `settings.EMAIL_FROM`. **Nada mais tocado** neste arquivo: `hash_token` (F-24), commit-antes-do-envio + try/except (F-18) e `dt.datetime.utcnow()` (Batch 16) **intactos**.
- **Único ponto de envio:** varredura por `resend.Emails.send` / `"from"` confirmou que **só existe este** ponto de e-mail no código.
- **Teste (`tests/routers/test_auth_tokens.py`, `TestEnvioRobustoDeEmail`):** mocka `resend.Emails.send`, dispara `forgot-password` e afirma `payload["from"] == settings.EMAIL_FROM`. Os testes de forgot-password existentes (F-18) não mudaram (o default é o mesmo valor de antes).

**⚠️ PRODUÇÃO (Railway):** setar como env var **`EMAIL_FROM="Hivvo <noreply@hivvo.app>"`** (o domínio `hivvo.app` está verificado no Resend). Sem essa env, o app usa o sandbox e o Resend recusa destinatários que não sejam o dono da conta.

---

## Batch 11b — Cookies same-site + token 30min (F-03, F-09) (01/07/2026)

F-03 + F-09, **env-conditional** — regra central: **dev (localhost) não quebra** (login segue funcionando em `http://localhost:5173`). Suíte: **212 testes** (196 + 16 novos), todos verdes. App sobe. **Não** inclui papel Postgres (ops) nem outros batches.

**F-03 — cookies centralizados ([auth.py](../app/routers/auth.py)):** novo helper `_cookie_kwargs()` (constante `_COOKIE_DOMAIN=".hivvo.app"`) condiciona por `ENVIRONMENT`:
- **Produção:** `Domain=.hivvo.app` (same-site vale entre `app.` e `api.`), `Secure=True`, `SameSite=Lax`, `HttpOnly=True`.
- **Dev:** **sem** `Domain`, `Secure=False` (localhost é http), `SameSite=Lax`, `HttpOnly=True`.
- Aplicado em TODOS os pontos: `_set_auth_cookie`/`_set_refresh_cookie` (login/register/refresh) e o novo `_clear_auth_cookies` (logout e delete-me) — set e clear usam os **mesmos** atributos, senão o browser não casa o cookie na limpeza.

**F-03 — CORS ([main.py](../main.py)):** `allow_origins=[settings.FRONTEND_URL]` (origem explícita, nunca `"*"` — incompatível com credentials), `allow_credentials=True`, e **restringidos** `allow_methods=["GET","POST","PUT","DELETE","OPTIONS"]` + `allow_headers=["Content-Type"]` (eram `"*"`). JWT vai no cookie, não em header — por isso Content-Type basta. **Se o frontend passar a mandar header customizado, adicionar aqui** (validar no deploy).

**F-03 — reforço CSRF por Origin (novo [app/core/csrf.py](../app/core/csrf.py)):** `verify_origin` — só métodos mutáveis (POST/PUT/PATCH/DELETE); `Origin` **presente e ≠ `settings.FRONTEND_URL`** → **403**; `Origin` **ausente** (clientes não-browser) → passa (cai na defesa SameSite; Origin é reforço). Env-conditional automático via `FRONTEND_URL` (dev=localhost:5173, prod=app.hivvo.app). Ligado como `dependencies=[Depends(verify_origin)]` nos 8 includes de router de negócio. Preflight OPTIONS é tratado pelo CORSMiddleware antes — não é bloqueado. **Os testes existentes mandam POST/PUT/DELETE sem `Origin` → seguem verdes.**

**F-09 — access token 30min:** `ACCESS_TOKEN_EXPIRE_MINUTES` efetivo **30** (default do `config.py` já era 30; `.env` e `.env.example` corrigidos de 1440→30 — o `.env` é local/gitignored, o `.env.example` é versionado). **Refresh INTACTO em `REFRESH_TOKEN_EXPIRE_DAYS=7`** (longo — é o que mantém a sessão; o access é curto e renovável via `/auth/refresh`). Não confundir os dois.

**Testes novos (16):**
- `tests/test_session_hardening.py` (unidade): cookie prod (Domain/Secure/SameSite/HttpOnly) × dev (sem Domain/Secure, com SameSite/HttpOnly); `_clear_auth_cookies` prod leva `Domain` nos dois cookies; `verify_origin` (GET não checado; mutável+Origin inválido→403; Origin dev e prod→passa; sem Origin→passa); F-09 (default 30 + refresh 7 dias; access decodificado expira ~30min; refresh persistido ~7 dias).
- `tests/routers/test_csrf_cors.py` (integração): POST com Origin inválido→**403**; Origin correto→passa a checagem (401 credencial); sem Origin→passa (401); preflight OPTIONS → `access-control-allow-origin == FRONTEND_URL` (não `"*"`) + `access-control-allow-credentials: true`.

**⚠️ Validação real fica para o DEPLOY (domínio real):** o cookie same-site atravessando `app.hivvo.app`↔`api.hivvo.app` e o ciclo de refresh ("não desloga sozinho após 30min") só se comprovam em produção com `ENVIRONMENT=production` + `FRONTEND_URL=https://app.hivvo.app`. Em teste/dev, a lógica env-conditional está coberta, mas o comportamento cross-subdomínio do browser não.

---

## Fase 5 — Resiliência de banco (Batch 7 código + handler DB→503) (01/07/2026)

Parte de **código** do Batch 7 + exception handler de banco fora. Suíte: **196 testes** (194 + 2 novos), todos verdes. App sobe (QueuePool). **Não** inclui papel Postgres restrito (OPS no Supabase), 11b (F-03/F-09), T-28 nem outros batches.

**Batch 7 (código) — [database.py](../app/core/database.py):** o `create_engine` ganhou `pool_pre_ping=True` (detecta conexão morta e reconecta no checkout), `pool_recycle=1800` (descarta conexões velhas após 30min), `pool_size=5` e `max_overflow=10` — **pool modesto de propósito**: o Session pooler do Supabase tem limite próprio de conexões, então nada de pool grande. O pooler já estava em uso via `DATABASE_URL` (migração desta sessão).

**Exception handler global — [main.py](../main.py):** `db_unavailable_handler` registrado para `OperationalError` **e** `InterfaceError` (classes de falha de conexão do SQLAlchemy) → **503** `{"detail": "Serviço temporariamente indisponível"}`.
- **Por que sai COM CORS (o ponto crítico):** o handler é tratado pelo `ExceptionMiddleware`, que no stack do Starlette fica **dentro** do `CORSMiddleware` — a resposta 503 volta decorada com `Access-Control-Allow-Origin`. Um 500 cru sobe pelo `ServerErrorMiddleware` (**fora** do CORS) e chega ao browser sem headers de CORS, que então reporta um **falso erro de CORS** (mascarou o diagnóstico de banco-fora duas vezes). Agora não mais.
- **Complementaridade:** `pool_pre_ping` cobre queda transitória/conexão reciclada; o handler cobre o banco **totalmente fora** (pausado, IPv6 inalcançável).
- **Log sem PII:** `logger.error("Falha de conexão com o banco: %s", exc.__class__.__name__)` — **não** loga `str(exc)` (pode conter host/string de conexão). Corpo ao cliente é genérico.

**Testes (`tests/routers/test_db_unavailable.py`, 2):** `get_session` mockado para levantar `OperationalError` + `get_current_user` dummy (não toca o banco); `GET /api/v1/transactions` com header `Origin` → **503**, corpo genérico, **e `access-control-allow-origin` presente** (prova que banco-fora não vira mais falso-CORS; o próprio 503 — em vez de exceção propagada — prova que foi tratado dentro do stack). Guarda: o detalhe do erro (`could not connect`) **não** vaza no corpo.

**⚠️ Parte OPS do Batch 7 (fora do código):** criar **papel Postgres restrito** (sem superuser / sem BYPASSRLS, só SELECT/INSERT/UPDATE/DELETE nas tabelas da app — F-02) e apontar o `DATABASE_URL` de produção para ele. Passo de infra no Supabase — no checklist de deploy.

---

## Batch 11a — LGPD: exclusão de conta (F-07) (01/07/2026)

Só **F-07**. **Não** inclui F-03 (cookies same-site) nem F-09 (token 30min) — esses são **deploy-coupled** e ficam para o **passo de deploy (11b)**. Suíte: **194 testes** (191 + 3 novos), todos verdes. App sobe.

**Endpoint `DELETE /auth/me` ([auth.py](../app/routers/auth.py), sob `/api/v1` pelo mount do T-28), autenticado:**
- **Reautenticação obrigatória:** recebe a senha atual no corpo (`DeleteMeRequest{password}`) e valida com `verify_password` **antes** de apagar. Senha errada → **401**, não apaga nada. Um cookie sozinho não deleta a conta.
- **Só o próprio usuário:** opera sobre `current_user.id` — nunca aceita id de outro usuário no path/corpo.
- **Transação única (tudo ou nada):** deletes explícitos por `usuario_id` em cada tabela filha + o usuário, num único `commit`; erro → rollback.
- **Ordem dos deletes respeita as FKs inter-tabelas** (não só filha→`usuarios`): `parcelas` (aponta p/ `transacoes` e `cartoes`) → `transacoes` (aponta p/ `cartoes`) → `cartoes` → `categorias`/`refresh_tokens`/`password_reset_tokens`/`chat_messages` (independentes) → `usuarios`. Correto no **Postgres real** (FKs do T-14), não só no SQLite que não força FK. `categoria` em transações/parcelas é **string desnormalizada**, não FK — por isso `categorias` é independente.
- **Decisão — deletes explícitos, não `DELETE FROM usuarios` puro:** os models declaram `foreign_key="usuarios.id"` **sem `ondelete="CASCADE"`** — o cascade do T-14 vive só no Postgres (migration), não no metadata do SQLModel; o SQLite dos testes não força FK. Deletes explícitos tornam a garantia **DB-agnóstica e provável** no teste, sem tocar nos 8 models/conftest (fora do escopo de 11a). Em produção os cascades do T-14 seguem como **defesa em profundidade**.
- **Log de auditoria SEM PII:** `logger.info("conta_excluida usuario_id=%s", uid)` — só id + evento; o timestamp vem do formatter (Batch 10). Nunca email/nome.
- **Limpa os cookies** (`access_token`/`refresh_token`) na resposta; o refresh do próprio usuário já cai nos deletes. Retorna **204**.

**Testes (`tests/routers/test_account_deletion.py`, TestClient + SQLite, `get_current_user` trocado, base_url `/api/v1`):**
- Usuário com senha real + 1 linha em **cada** tabela ligada (cartão, transação, parcela, categoria, refresh token, reset token, chat message); `DELETE /auth/me` com senha correta → **204** e **zero linhas** do usuário em cada uma das 7 tabelas + o próprio usuário some (varredura `_rows_do_usuario`).
- Senha errada → **401**, nada apagado (todas as tabelas seguem com ≥1 linha).
- Sem autenticação (sem override de `get_current_user`, sem cookie) → **401**.

**⚠️ Tarefa de conteúdo (fora do código):** a **Política de Privacidade** precisa ser atualizada mencionando o direito de exclusão (LGPD art. 18).

---

## T-28 (lado API) — Routers de negócio sob /api/v1, hard switch (01/07/2026)

Lado **API** do T-28 (cross-repo). Suíte: **191 testes** (188 + 3 novos), todos verdes. App sobe. **Não** inclui pooler (Batch 7), cookies/topologia (Batch 11) nem outros batches.

**Mount ([main.py](../main.py)):** os 8 `app.include_router(x.router)` passaram a `app.include_router(x.router, prefix="/api/v1")` — auth, transactions, categories, cards, invoices, installments, statistics, ai. Cada router mantém seu prefixo interno → `/api/v1/auth/...`, `/api/v1/transactions/...`, etc. **Hard switch:** sem dual-mount (não se serve em `/` e `/api/v1` ao mesmo tempo).

**Exceção obrigatória — `/health` na RAIZ:** `@app.get("/health")` **intocado**. O health check do Railway/load balancer bate em `/health` na raiz; movê-lo quebraria o deploy em crash-loop.

**CORS — sem mudança:** `allow_origins=[settings.FRONTEND_URL]` é por **origem**, não por path. Confirmado — nada a alterar. Nenhuma referência interna a path de API (o link do e-mail de reset aponta para o **frontend**, `FRONTEND_URL`, não para a API).

**Testes — prefixo via `base_url` do TestClient:** em vez de reescrever ~50 strings, o prefixo entrou no `base_url` dos 3 pontos que criam TestClient para rotas de negócio — [tests/routers/conftest.py](../tests/routers/conftest.py) (fixture `as_user`, cobre transactions/cards/invoices/ai/categories/installments), [tests/routers/test_auth_tokens.py](../tests/routers/test_auth_tokens.py) (fluxos de auth) e [tests/routers/test_rate_limit.py](../tests/routers/test_rate_limit.py) (forgot-password): `TestClient(app, base_url="http://testserver/api/v1")`. O httpx concatena o path do `base_url` (com barra final imposta) ao path relativo → `client.get("/transactions")` resolve para `/api/v1/transactions`. Os paths dentro dos testes ficam legíveis e todos batem em `/api/v1`. `test_request_log.py` **não muda** — bate em `/rota-inexistente-batch10` (não é rota de negócio; testa o middleware, que roda na raiz).

**Teste novo do hard switch ([tests/routers/test_api_v1_prefix.py](../tests/routers/test_api_v1_prefix.py), 3):** toda rota de negócio em `app.routes` começa com `/api/v1`; `/health` está na raiz e **não** sob `/api/v1`; `TestClient(app)` (sem prefixo) em `GET /auth/me` → **404** (raiz antiga não montada), e `GET /api/v1/auth/me` → **401** (rota existe, sem token — não 404). Utilitárias do FastAPI (`/docs`, `/docs/oauth2-redirect`, `/redoc`, `/openapi.json`) e `/health` são exceções conhecidas na varredura.

**⚠️ Coordenação cross-repo (obrigatória):** o frontend muda `VITE_API_URL` para incluir `/api/v1` em seguida (passo coordenado). **Backend e frontend de produção DEVEM subir com `/api/v1` casado — não deployar um sem o outro.**

---

## Auditorias e Plano de Correção (10/06/2026)

| Documento | Conteúdo |
|---|---|
| `docs/AUDITORIA_SEGURANCA.md` | 25 achados · **10 bloqueadores**. Forte: IDOR/BOLA sólido na leitura. Riscos: segredos, cookie/CORS cross-domain + CSRF, sem rate limiting, tokens em texto claro (F-24), RLS ausente, sem exclusão de conta (F-07). |
| `docs/AUDITORIA_TECNICA.md` | ~44 achados. Forte: ciclo de fatura correto, Decimal no dinheiro, API stateless, migrações limpas. Riscos: **zero testes**, Repository Pattern inexistente, conexão direta ao Supabase, sem paginação/índices, Gemini síncrono sem timeout, bugs de domínio (T-34/35/36/37/38/40). |
| `docs/PLANO_EXECUCAO_API.md` | **16 batches** ordenados (11 pré-deploy + deploy + 5 pós-deploy). Executar um por vez, com aprovação. |

**Gates:** Batches 1→2→3 são sequenciais (consolidar → testar → corrigir). Batch 7 tem passos manuais no Supabase. Batch 11 depende da decisão de topologia (`app.`/`api.hivvo.app`). Auditoria de **produto** será feita à parte (estratégia/mercado), não pelo Claude Code.

---

## Fase 2 (cross-repo) — Endpoint dedicado de sugestão de categoria (12/06/2026)

Resolve a **raiz do FE-08** no servidor: a sugestão de categoria por IA reusava `POST /ai/chat`, persistindo em `chat_messages` e entrando na janela de 50 mensagens — poluía a memória do Assistente e aparecia como "sessão recente". **Aditivo: o comportamento de persistência do `/ai/chat` não mudou** (guardado por teste novo).

**`POST /ai/suggest-category`** (autenticado): entrada `{descricao (1..200), valor?, tipo? ('receita'|'despesa')}` → saída `{categoria}`. One-shot e stateless por contrato: **não** escreve em `chat_messages`, **não** cria/toca `sessao_id`, **não** carrega a janela de 50 mensagens. Única leitura de banco: categorias customizadas ativas do usuário.

**Como funciona:** lista de categorias válidas (padrão + customizadas do usuário, filtradas por `tipo` quando informado) entra na system instruction; o Gemini responde com um nome; `_match_categoria` normaliza (match exato case-insensitive → substring → fallback `"Outros"`) — a sugestão é sempre uma categoria que o picker do frontend conhece.

**Refactors de suporte (zero mudança de comportamento):**
- O loop de retry do Gemini saiu do corpo do `chat` para `_gemini_generate(contents, system_instruction)` — mesmos 5 retries/sleeps/mensagens; `chat` o chama e aplica `_post_process` como antes. Sem timeout/singleton/rate-limit (Batch 9/T-21/F-04 cobrirão os dois endpoints juntos).
- `_CATEGORIAS_PADRAO` movida de `routers/categories.py` para `app/services/categorias.py` (`CATEGORIAS_PADRAO`) — evita import router→router (anti-padrão do T-02).

**Testes (`tests/routers/test_ai_router.py`, Gemini mockado, sem rede):** chamada ao suggest-category deixa `chat_messages` com **zero linhas** (logo nenhum `sessao_id` criado) e retorna a sugestão; categoria customizada aceita; resposta fora da lista → `"Outros"`; resposta com decoração normalizada; **guarda do refactor:** `/ai/chat` segue persistindo user+assistant com o `sessao_id` enviado (primeiro teste do chat — não existia).

**Cross-repo:** o **Web-Batch 4** (hivvo-web) troca a chamada de sugestão de `/ai/chat` para este endpoint.

---

## Regressão round-trip — criação parcelada → fatura (26/06/2026)

**Só testes — nenhuma mudança em código de app.** Fecha o gap de cobertura confirmado na investigação cross-repo de fatura/parcela: o backend cria e agrega parcelas corretamente, mas só existia teste de **atomicidade/FALHA** do T-41 (falha na geração não persiste nada) e da absorção da última parcela — **nenhum** provava o caminho de **SUCESSO** ponta a ponta até a fatura. (A investigação descartou regressão de T-41/T-35/T-36: as 10 parcelas do caso real tinham `usuario_id`/`cartao_id`/`fatura_mes/ano` corretos; o sintoma de "não reflete" era de cache/refetch no frontend.)

**Onde:** `tests/routers/test_transactions_router.py` — nova classe `TestCriacaoParceladaRoundTripAteFatura`, reusando os helpers existentes (`make_card`, `post_parcelada`) e a fixture de TestClient + SQLite + override de `get_session`/`get_current_user`.

**Cenário determinístico:** cartão fech. 3 / venc. 10 / offset 1; `hoje` fixado em 26/06/2026 via `mocker.patch("app.routers.cards.hoje", ...)` (única dependência de relógio é a fatura aberta de `GET /cards`; a derivação das parcelas vem de `data`+cartão). Compra de crédito R$ 4.500 em 10x em 26/06 → 1ª parcela na fatura **(8, 2026)** (que também é a fatura aberta), demais avançando mês a mês até **(5, 2027)**.

**Asserts:**
- **Criação:** 201; `parcelas_criadas == 10`; transação-pai com `fatura_mes/ano = None` e `parcelado=True`.
- **10 parcelas:** `numero_parcela == 1..10`; toda parcela com `usuario_id`/`cartao_id` corretos; soma == R$ 4.500,00; `fatura_mes/ano` na sequência `(8,2026)…(5,2027)`.
- **Agregação:** `GET /cards` → fatura aberta `(8, 2026)`, `fatura_aberta_total == 450.00` (só a parcela 1 cai na aberta); `GET /cards/{id}/invoices` → 10 faturas, uma por mês, R$ 450 cada; `GET /cards/{id}/invoices/{ano}/{mes}` da aberta → total 450,00, 1 parcela, 0 avulsas.
- **Caso extra** (`test_transacao_pai_parcelada_fatura_none_e_ignorada_nas_avulsas`): a linha-pai parcelada tem `fatura_mes/ano = None` e a agregação de avulsas (`parcelado=False`) a ignora — sem dupla contagem.

**Resultado:** `103 passed` (101 anteriores + 2 novos). A absorção da última parcela com resto segue coberta em `TestT41.../test_sucesso_persiste_transacao_e_parcelas` (100/3 → 33,33/33,33/33,34).

---

## T-29 — Ordenação estável de transações (26/06/2026)

**Confirmado por investigação:** `GET /transactions` ordenava por `data DESC` **sem desempate**, e `Transacao` **não tem coluna de criação** (só `data`, granularidade de dia). Para transações do mesmo dia a ordem era heap do Postgres (não-determinística) — a criada por último não vinha no topo. O Dashboard "últimas transações" consome o mesmo endpoint, então herdava o problema.

**Correção (mínima, sem migration, sem coluna nova):** desempate por `id DESC` (`id` é PK autoincremento → id maior = criada depois = topo dentro do mesmo dia). Aplicado nos **dois** pontos que listam `Transacao` ordenado por `data DESC` (varredura completa de `order_by`):
- `routers/transactions.py` (`GET /transactions`) → `order_by(data.desc(), id.desc())`.
- `routers/invoices.py` (avulsas do detalhe de fatura, `GET /cards/{id}/invoices/{ano}/{mes}`) → mesmo desempate, por consistência.

Outros `order_by` não foram tocados por não listarem `Transacao`: `installments.py`/`invoices.py:108` ordenam `Parcela.data_vencimento`; `ai.py` ordena `ChatMessage`; `statistics.py` não ordena. **Não** se mexeu em paginação (T-12).

**Testes (`tests/routers/test_transactions_router.py`, classe `TestOrdenacaoEstavel`, reusa `as_user`/`post_transacao`):** 3 transações no mesmo dia criadas em sequência → `GET /transactions` retorna maior id primeiro; caso com datas distintas intercaladas → entre dias manda `data DESC`, dentro do dia `id DESC` (ordem esperada explícita `[b2, b1, a2, a1]`); e 3 avulsas de crédito no mesmo dia → o detalhe de fatura (`GET /cards/{id}/invoices/{ano}/{mes}`) também devolve maior id primeiro (rede do segundo ponto tocado; direção inalterada — já era `data DESC`).

**Resultado:** `106 passed` (103 + 3 novos). App importa OK.

---

## Batch 10 — Observabilidade e deploy (30/06/2026)

T-25 + T-43 + T-42. Suíte: **188 testes** (178 + 10 novos), todos verdes. App sobe. **Não** inclui pooler (Batch 7), T-28 nem Batch 11.

**Novo módulo [app/core/observability.py](../app/core/observability.py)** concentra a observabilidade. Regra dura: NUNCA logar nem enviar ao Sentry corpo, tokens, senhas, cookies ou conteúdo de mensagem — só metadados.

**T-25 (logging + Sentry + middleware):**
- **Logging via `dictConfig`** (`configure_logging()`): nível por `ENVIRONMENT` — `DEBUG` em dev, `INFO` em produção. Handler de console + formato com timestamp/level/logger. Chamado no startup (lifespan).
- **Sentry OPCIONAL** (`init_sentry()`): inicializa **só se `SENTRY_DSN`** estiver setado; sem DSN é **no-op** (não crasha dev). SDK importado **lazy** (dentro da função). Novo `SENTRY_DSN: str | None = None` em Settings. `sentry-sdk[fastapi]>=2.0.0` no `requirements.txt` (inativo sem DSN).
- **LGPD — scrub em 2 níveis (o conteúdo de mensagem NÃO viaja só no corpo):**
  - **Na origem, no `init`:** `send_default_pii=False` + **`include_local_variables=False`** (Sentry não anexa as variáveis locais do traceback — é por elas que a mensagem do `/ai/chat` vazaria mesmo com o corpo removido) + **`max_request_body_size="never"`** (não captura o corpo do request).
  - **Defesa adicional no `before_send`** (`_before_send`): filtra `Authorization`/`Cookie`/`Set-Cookie`/`X-CSRF-Token` dos headers (→ `[Filtered]`); descarta `cookies` e o corpo (`data`); **e varre os locals de TODOS os frames** de `exception.values[].stacktrace` **e** `threads.values[].stacktrace` (remove `vars` de cada frame). Auto-suficiente — protege mesmo se a captura de locals/corpo for reativada no futuro. ⚠️ **Correção sobre a 1ª versão deste batch:** o `_before_send` inicial só limpava `request` (headers/cookies/data) e **deixava os locals passarem** — a mensagem de chat vazaria pelos `vars` do stacktrace. Fechado.
- **Middleware de request log** (`request_log_middleware`, registrado em `main.py` via `app.middleware("http")`): gera `request-id` (UUID) por request, devolve em **`X-Request-ID`**, e loga **só metadados** — `método path status duração_ms request_id`. Usa `request.url.path` (sem query string → não vaza segredo em URL). `/health` logado em **DEBUG** (silenciado em produção, que roda em INFO).

**T-43 (lifespan + fail-fast de boot):**
- `main.py` migrado de criação direta para **`lifespan`** (asynccontextmanager, não `on_event`). Startup: `configure_logging()` → `init_sentry()` → `validate_startup_config()`. Shutdown: **`engine.dispose()`**.
- **Fail-fast** (`validate_startup_config()`): estende o F-01 — em **produção**, `RuntimeError` com mensagem clara se `GEMINI_API_KEY` ou `RESEND_API_KEY` ausentes (aborta o boot). Em **dev**, apenas `WARNING` (são feature-specific; o app sobe sem elas).
- **Nota:** o `lifespan` só roda quando o `TestClient` é usado como context manager — os testes de router existentes usam `TestClient(app)` direto (sem `with`), então a validação/dispose não disparam neles; o middleware, porém, roda por request (inócuo: só adiciona header e loga metadados).

**T-42 (Procfile, config-only, sem código):** novo [Procfile](../Procfile) — `release: alembic upgrade head` (migration no release bloqueia o deploy se falhar — desejado) e `web: uvicorn main:app --host 0.0.0.0 --port $PORT`. `alembic.ini` na raiz, então o `release` roda da raiz.

**`SENTRY_DSN` é setado no deploy (ops).** Sem ele o Sentry fica inativo — em dev e em qualquer ambiente sem a env.

**Testes novos (10):**
- `tests/routers/test_request_log.py` (T-25, 2): resposta inclui `X-Request-ID` (UUID válido, via 404 sem depender de DB/auth); **teste NEGATIVO de vazamento** — POST com `senha`/`token` no corpo **não** aparece no `caplog`, mas a linha de metadados (`POST` + path) sai.
- `tests/test_observability.py` (T-25 + T-43, 8): scrub do Sentry provado com **evento realista** — request (`Authorization`/`Cookie`/`cookies`/`data`) **e locals do stacktrace** (mensagem de chat + token nos `vars` de um frame); afirma que headers sensíveis viram `[Filtered]`, header inócuo é preservado, `cookies`/`data`/`vars` somem, e uma **varredura de texto no evento inteiro** confirma que nenhum dos 6 segredos (mensagem do corpo, mensagem dos locals, senha, token do cookie, token do local, token do Authorization) sobra; `init_sentry` passa `send_default_pii=False`/`include_local_variables=False`/`max_request_body_size="never"`/`before_send` (via fake module injetado em `sys.modules`); no-op sem DSN (não chama `init`); fail-fast produção sem chaves → `RuntimeError` citando `GEMINI_API_KEY`/`RESEND_API_KEY`; produção com chaves → OK; dev sem chaves → só `WARNING`.

---

## Batch 9 — Resiliência da IA + rate limiting (29/06/2026)

T-21 + F-04. Suíte: **178 testes** (173 + 5 novos), todos verdes. App sobe. **Não** inclui logging/Sentry (Batch 10), pooler (Batch 7), T-28.

**T-21 ([ai.py](../app/routers/ai.py)):**
- **Timeout explícito:** `genai.Client(..., http_options=types.HttpOptions(timeout=settings.GEMINI_TIMEOUT_MS))` — novo `GEMINI_TIMEOUT_MS=30000` (~30s) em Settings.
- **Orçamento de retry reduzido:** `_gemini_generate` deriva `max_attempts = len(settings.GEMINI_RETRY_WAITS) + 1` (era `range(1,6)` fixo). Default `GEMINI_RETRY_WAITS` mudou de `[2,4,6,8,10]` → `[2]` (**2 tentativas**, 1 espera) — o usuário está esperando; retry longo é para job assíncrono. Vale para **chat e suggest-category** (ambos via `_gemini_generate`).
- **Client singleton:** `_get_client()` cria a instância **uma vez** (módulo), reusada entre requests, em vez de `genai.Client(...)` por chamada. Se `GEMINI_API_KEY` faltar → `HTTPException(503)` com mensagem clara (não AttributeError). **Não** é o fail-fast de boot (isso é T-43/Batch 10).
- Log do retry mudou de `[chat]` para `[gemini]` (cobre os dois endpoints).

**F-04 (rate limiting, slowapi):**
- Novo [app/core/rate_limit.py](../app/core/rate_limit.py): `limiter = Limiter(key_func=get_remote_address, enabled=settings.RATE_LIMIT_ENABLED, storage_uri="memory://")` + `_user_or_ip_key` (decodifica o JWT do cookie p/ chave por usuário; fallback IP). [main.py](../main.py) registra `app.state.limiter` + handler de `RateLimitExceeded` (429).
- Limites: `/auth/login` **10/min por IP**, `/auth/register` **5/min por IP**, `/auth/forgot-password` **5/min por IP**; `/ai/chat` **30/min por IP + 15/min por usuário + 200/dia por usuário**. Endpoints ganharam `request: Request`.
- **Lockout por conta MANTIDO** (`tentativas_login`/`bloqueado_ate` em auth.py) — o rate limit por IP é camada **complementar**, não substituição.
- Novo `RATE_LIMIT_ENABLED: bool = True` em Settings. **Desligado na suíte** via `os.environ.setdefault("RATE_LIMIT_ENABLED","false")` no topo do `tests/conftest.py` raiz (antes de qualquer import de `main`) — sem isso os testes que repetem login/chat tomariam 429.
- `slowapi>=0.1.9` adicionado ao `requirements.txt` (dep de produção).
- **⚠️ LIMITAÇÃO CONHECIDA (registrada):** o store do slowapi é em **memória do processo** — NÃO sobrevive a múltiplas instâncias. Ao escalar horizontalmente em produção, **migrar para Redis** (`storage_uri="redis://..."`) para o limite ser global entre réplicas.
- **Refinamento futuro (registrado):** `/ai/suggest-category` dispara no blur (sensível a latência) e hoje **herda** o timeout de 30s do chat; um timeout próprio menor para suggest-category é melhoria futura — não implementado agora.

**Testes novos (5):**
- `tests/routers/test_ai_resiliencia.py` (T-21): `_get_client()` reusa a mesma instância (singleton); chave ausente → 503 com mensagem clara; retry usa `len(GEMINI_RETRY_WAITS)+1` tentativas (mock de `ServerError`, `sleep` neutralizado, sem rede).
- `tests/routers/test_rate_limit.py` (F-04): com o limiter religado no teste, `/auth/forgot-password` dá 200 nas 5 primeiras e **429** na 6ª; e guarda confirmando que o limiter está **off por padrão** na suíte.

---

## Batch 8 — Queries pesadas + teto de listagem (29/06/2026)

T-17 + T-12. **Sem quebrar contrato:** todas as listagens continuam **array nu** (sem envelope `{items,total}` — passo coordenado futuro). Suíte: **173 testes** (166 + 7 novos), todos verdes. App sobe. Feito **fora de ordem** (antes do Batch 7, a pedido); não há dependência entre eles. **Não** inclui pooler (Batch 7), Gemini (Batch 9), T-28.

**T-17 invoices ([invoices.py](../app/routers/invoices.py) `GET /cards/{id}/invoices`):** a varredura que carregava todas as parcelas/avulsas do cartão e somava em Python virou **2 queries com `GROUP BY fatura_mes, fatura_ano`** no banco — `SUM(valor)`, `COUNT(id)` e, nas parcelas, `SUM(CASE WHEN pago THEN 1 ELSE 0)` para `total_parcelas_pagas`. Mesma fusão por `(mes,ano)`, mesma ordenação `(ano,mes)` desc, mesmos filtros (parcela `cancelado=False`; avulsa `parcelado=False` + `tipo='despesa'`). **Valores idênticos** — provados pelo teste novo e pelos de round-trip/isolamento que já afirmam totais de fatura.

**T-17 cards ([cards.py](../app/routers/cards.py) `GET /cards`):** eliminado o N+1 (era 2 queries por cartão). Agora: fatura aberta de cada cartão computada em Python (como antes), depois **2 queries `GROUP BY cartao_id, fatura_mes, fatura_ano`** cobrindo todos os cartões via `.in_(card_ids)`; o total de cada cartão é lido no map pela tupla da sua fatura aberta — mesmo filtro/valor de antes. Guarda: retorna `[]` cedo se não há cartões (evita `IN ()`).

**T-12 ([transactions.py](../app/routers/transactions.py)):**
- `GET /transactions`: novos params `limit` (default 100, `ge=1`, **clampado a 500 no código** — não usa `le`, então `limit>500` não dá 422, é reduzido a 500) e `offset` (default 0, `ge=0`). `.offset().limit()` aplicado **após** o `order_by(data DESC, id DESC)` (T-29) — paginação estável. **Continua array nu.** Sem bypass `all=true`/`limit=0`: o teto de 500 é inviolável na listagem.
- `GET /transactions/export` (novo, autenticado): **todas** as transações do usuário, sem teto, mesma ordenação estável. É o caminho do backup do frontend (`getAllTransactions()`), separado da listagem paginada. Rota `/export` não colide com nenhum `GET /{id}` (não existe).

**Testes novos (7):**
- `tests/routers/test_invoices_router.py` (novo, T-17): fatura com parcela paga + parcela não-paga + avulsa na MESMA fatura → `total`/`total_itens`/`total_parcelas_pagas` conferem; parcela cancelada e avulsa-receita excluídas; ordenação `(ano,mes)` desc; cartão sem movimento → `[]`.
- `tests/routers/test_transactions_router.py` (`TestT12Paginacao`): seed de 501 transações via sessão → default retorna 100; `limit=1000` clampa a 500 (sem 422); `offset` pagina sem overlap e estável (`min(page1) > max(page2)`, desc por id); offset além do fim → `[]`; `/transactions/export` retorna 501 (> teto), mesma ordenação.
- T-17 cards: cobertura de equivalência herdada de `TestCriacaoParceladaRoundTripAteFatura` e `TestT36...` (afirmam `fatura_aberta_total` e detalhe de fatura) — seguem verdes.

---

## Batch 6 — Banco: índices, sargabilidade, constraints, cascades (29/06/2026)

T-09, T-10, T-11, T-14. Uma migration Alembic + 2 funções de query + guarda no `create_category`. Suíte: **166 testes** (139 + 27 novos), todos verdes. App sobe. **Não** inclui T-28, pooler (Batch 7), paginação (Batch 8) nem Gemini (Batch 9).

**PASSO 0 — pré-checagem read-only (antes de escrever a migration):** rodada contra o Supabase de dev via MCP. Tudo limpo (0 violações) **exceto** 1 grupo duplicado em `categorias(usuario_id, nome)`: 3 linhas "Uber Eats" do usuário 1 (1 ativa + 2 inativas, 0 transações referenciando) — subproduto esperado do **soft delete**, não dado corrompido. PASSO 0b confirmou **0 duplicatas entre ATIVAS** normalizadas por `lower(trim(nome))`. Decisão do Lucas: **índice parcial** em vez de UNIQUE puro (ver T-11 abaixo); **não limpar** as 3 linhas (não violam o índice parcial).

**T-09 (índices compostos, na migration):** `ix_transacoes_usuario_data(usuario_id, data)`, `ix_transacoes_cartao_fatura(cartao_id, fatura_ano, fatura_mes)`, `ix_parcelas_cartao_fatura(cartao_id, fatura_ano, fatura_mes)`, `ix_parcelas_usuario_fatura(usuario_id, fatura_ano, fatura_mes)`, `ix_chat_messages_sessao_id(sessao_id)`.

**T-10 (sargabilidade, código — comportamento idêntico):**
- [`_buscar_mes`](../app/services/estatisticas.py): `extract(month/year)` → range `data >= date(ano,mes,1) AND data < primeiro_dia_do_próximo_mês`. Borda dez→jan: `mes==12 → date(ano+1,1,1)`. Import `extract` removido (sem uso).
- [`list_transactions`](../app/routers/transactions.py) (`GET /transactions`): `mes`/`ano` são opcionais e independentes — reescrito preservando as mesmas linhas em todos os combos: `mes`+`ano` → range sargável; só `ano` → `[date(ano,1,1), date(ano+1,1,1))`; **só `mes`** (sem ano) → **mantém `extract("month")`** (não há range sargável para "mês em qualquer ano"); nenhum → sem filtro.
- **Fora de escopo (não tocado):** [`yearly_stats`](../app/routers/statistics.py) também usa `extract("year")`, mas o T-10/prompt nomeia só essas 2 funções. **Observação de backlog:** poderia virar range `[date(ano,1,1), date(ano+1,1,1))` num passo futuro.

**T-14 (cascades, na migration):** as 8 FKs de `usuario_id` (`cartoes`, `categorias`, `transacoes`, `parcelas`, `chat_messages`, `refresh_tokens`, `password_reset_tokens`) e `parcelas.transacao_id` recriadas (drop + add) com `ON DELETE CASCADE`. Nomes confirmados em `pg_constraint`. As FKs de `cartao_id` ficam fora (soft delete de cartão, não cascade). O delete explícito de parcelas do T-34 em `transactions.py` foi **mantido** (defesa em profundidade).

**T-11 (constraints, na migration + models):**
- **NOT NULL** em `transacoes.valor`, `parcelas.valor_parcela/taxa_juros/valor_juros` (+ `nullable=False` nos models).
- **CHECK:** `ck_transacoes_valor_positivo (valor>0)`, `ck_transacoes_tipo_valido (tipo IN ('receita','despesa'))`, `ck_transacoes_fatura_mes_valido`, `ck_parcelas_valor_positivo`, `ck_parcelas_fatura_mes_valido`, `ck_parcelas_numero_parcela_valido (numero_parcela<=total_parcelas)`. Os CHECKs de `fatura_mes` aceitam NULL (avulsa sem cartão).
- **UNIQUE puro:** `uq_parcelas_transacao_numero (transacao_id, numero_parcela)`.
- **Índice parcial UNIQUE:** `uq_categorias_usuario_nome_ativa` em `(usuario_id, lower(trim(nome))) WHERE ativa=true` — a regra real dado o soft delete é "não duas categorias **ATIVAS** com o mesmo nome". Render: `CREATE UNIQUE INDEX ... ON categorias (usuario_id, lower(trim(nome))) WHERE ativa = true`.
- **Paridade metadata↔DB:** todos os CHECKs, o UNIQUE de parcelas e o índice parcial de categorias foram declarados também em `__table_args__` nos models (mesmos nomes) — sem drift e o SQLite de teste passa a enforçá-los (viabiliza os testes T-11). WHERE do índice parcial é por dialeto (`ativa = true` Postgres / `ativa = 1` SQLite).

**Guarda no [`create_category`](../app/routers/categories.py) (acompanha o índice parcial):** antes do INSERT, busca por `lower(trim(nome))` do usuário — se existe **ativa** → `409` "Já existe uma categoria ativa com esse nome"; se existe só **inativa** → **reativa a MESMA linha** (`ativa=True`, atualiza `icone`/`tipo` com os do request), não insere 2ª; senão → INSERT. `commit` envolto em `try/except IntegrityError` → `rollback` + `409` (cobre corrida concorrente; nunca 500).

**Migration `e7c9a1b2d3f4` (down_revision `1046109fa1a2`):** `downgrade()` completo e reversível (exato inverso do `upgrade()` — FKs voltam a NO ACTION, índice parcial/UNIQUE/CHECKs dropados, colunas voltam a nullable, índices dropados). Validada **offline** (`--sql`, sem tocar no banco); upgrade e downgrade rendem SQL válido.

**⚠️ Comandos para o Lucas rodar em DEV (não rodei a migration — nem dev nem prod):**
```
venv\Scripts\python.exe -m alembic upgrade head
# para reverter:
venv\Scripts\python.exe -m alembic downgrade -1
```

**Testes novos (27):**
- `tests/routers/test_categories_router.py` (novo): nome novo insere; nome já ativo → 409 (não insere 2ª); recriar nome inativo → reativa a MESMA linha (id igual, 1 linha no banco); reativação atualiza icone/tipo; case/espaço tratados (`Uber Eats` == `  uber eats `) → 409; mesmo nome entre usuários distintos coexiste.
- `tests/services/test_estatisticas.py` (novo, T-10): `_buscar_mes` retorna só o mês pedido (limites inclusivo/exclusivo); borda dez→jan não vaza; fevereiro bissexto; isolamento por usuário.
- `tests/routers/test_transactions_router.py` (`TestT10FiltroSargavel`): 4 combos de `mes`/`ano` (+ borda dez) retornam as mesmas linhas.
- `tests/services/test_constraints.py` (novo, T-11): via ORM no SQLite — `valor<=0`/NULL, `tipo` inválido, `fatura_mes` fora de 1..12 (transacoes e parcelas), `numero_parcela>total_parcelas`, parcela duplicada `(transacao_id,numero_parcela)` → `IntegrityError`; casos válidos passam.

---

## Batch 5 — Tokens e sessão (26/06/2026)

F-24, F-10, F-18/T-31. **Não** inclui F-09 (Batch 11), índices/constraints (Batch 6) nem T-28 (cross-repo). Suíte: **139 testes** (128 + 11 novos), todos verdes. App sobe.

**F-24 (hashear tokens persistidos):** novo helper `hash_token(token)` em [core/auth.py](../app/core/auth.py) — `sha256` hexdigest (uuid4 é alta entropia, ~122 bits → sem salt, preserva busca por índice). A coluna `token` continua `str` e guarda o **hash**; o valor **cru** vai ao cliente (refresh → cookie; reset → e-mail). Pontos de criação **e** lookup atualizados para casar:
- **Refresh:** criação em `create_refresh_token` persiste `hash_token(token_str)`; lookup em `rotate_refresh_token` compara `hash_token(old_token_str)`.
- **Reset:** criação em `forgot_password` persiste `hash_token(token_str)`; lookup em `reset_password` compara `hash_token(body.token)`.
- **5º ponto (além dos 4 do prompt):** o `logout` também faz **lookup de refresh** — hasheado também, senão o logout deixaria de revogar (assimetria quebraria o fluxo).
- Tokens em texto claro já existentes deixam de validar (aceitável pré-lançamento — desloga sessões atuais). **Sem migration, sem rehash dos antigos.**

**F-10 (revogar sessões na troca de senha):** novo helper `revoke_all_refresh_tokens(user_id, session)` em [core/auth.py](../app/core/auth.py) marca todos os `RefreshToken` não revogados do usuário como `revogado=True` (o chamador commita). Chamado **na mesma transação** em `change_password` E `reset_password`, antes do `commit`. Refresh com token antigo após qualquer um dos dois → 401.

**F-18 + T-31 (envio robusto do e-mail de reset):** em [routers/auth.py](../app/routers/auth.py):
- `resend.api_key = settings.RESEND_API_KEY` movido para **inicialização do módulo** (não setado a cada request).
- Token **commitado ANTES** do envio — a falha de e-mail não impede o reset de ficar disponível.
- Envio em `try/except`: falha → `logger.error` server-side (sem token/PII no log — só a exceção), **nunca** 500.
- Resposta ao cliente permanece **genérica** (mesma mensagem exista ou não o e-mail — anti-enumeração). `logger` novo no módulo.

**Testes novos (`tests/routers/test_auth_tokens.py`, TestClient + SQLite, Resend mockado):**
- **F-24 refresh:** após login, o banco guarda o hash (≠ cookie cru) e casa via `hash_token`; `/auth/refresh` com o cru valida; token errado → 401.
- **F-24 reset:** `forgot-password` grava o hash (≠ token extraído do link do e-mail mockado); `reset-password` com o cru valida (e a nova senha loga); token errado → 404.
- **F-10:** após `reset-password` e após `change_password`, o refresh anterior → 401.
- **F-18:** `resend.Emails.send` levantando → request **não** 500, resposta genérica, token **já commitado** (1 linha); caminho feliz commita e chama o send uma vez; e-mail inexistente → resposta genérica, **sem** token e sem chamar o send (anti-enumeração).

---

## Batch 4b — Hardening de entrada e hashing (26/06/2026)

F-16, F-22, F-23, F-06. **Não** inclui T-28 (cross-repo separado) nem F-09 (adiado para o Batch 11). Suíte: **128 testes** (113 + 15 novos), todos verdes. App sobe.

**F-16 (sessao_id tipado):** `ChatRequest.sessao_id` passou de `str(min/max=36)` para `uuid.UUID` ([schemas/ai.py](../app/schemas/ai.py)) — entrada malformada vira **422** automático (antes era 500 no `uuid.UUID(...)` do router). Em `routers/ai.py`, `sessao_uuid = uuid.UUID(body.sessao_id)` → `sessao_uuid = body.sessao_id` (já é UUID). O resto do fluxo já operava em `uuid.UUID` (a coluna `ChatMessage.sessao_id` já era `uuid.UUID`).

**F-22 (max_length só em schemas de ENTRADA):** limites generosos e por campo, nunca um número único apertado:
- `TransacaoCreate`/`TransacaoUpdate`: `descricao`/`categoria`=200; `forma_pagamento`/`tipo_gasto`/`origem`=50; `tipo`=20.
- `CategoriaCreate`: `nome`=200, `icone`=50, `tipo`=20.
- `CartaoCreate`/`CartaoUpdate`: `nome`=200, `tipo`=20.
- `SuggestCategoryRequest.descricao`: 200 → **500**.
- **`ChatRequest.mensagem`:** já tinha `max_length=2000` — **deixado como está**. Não existe constante de char-length em Settings (só `CHAT_CONTEXT_MESSAGES=50`, que é nº de mensagens); para não criar um segundo número conflitante, não foi promovido nem alterado. **Decisão registrada:** se quiser o 2000 em Settings, é um passo à parte.
- **Regra dura respeitada:** `max_length` **nunca** em schema de releitura. Confirmado que nenhum schema é bidirecional (`TransacaoResponse`, `CategoriaResponse`, `CartaoResponse`, `HistoricoResponseItem`, `ChatResponse`, `SuggestCategoryResponse` são todos separados dos `*Create`/`*Update`/`*Request`) — a regra de "parar e reportar" não disparou.

**F-23 (bcrypt rounds):** `bcrypt.gensalt()` → `bcrypt.gensalt(rounds=12)` em [core/auth.py](../app/core/auth.py) (`hash_password`). Afeta só hashes **novos**; `verify_password` lê o custo do próprio hash, então senhas antigas (qualquer custo) seguem validando.

**F-06 (Gemini safety):** `_SAFETY` em `routers/ai.py` passou de `BLOCK_NONE` para `BLOCK_ONLY_HIGH` nas 4 categorias — cobre **chat e suggest-category** (ambos usam `_SAFETY` via `_gemini_generate`). Objetivo: não recusar consulta financeira legítima sem desligar a moderação por completo. **✅ VALIDADO EM RUNTIME E APROVADO:** prompts financeiros reais foram respondidos, nenhuma recusa de safety. As limitações observadas na validação são de system prompt/contexto do Assistente (não do filtro) — registradas em "Itens diferidos / Backlog".

**Testes novos:** `tests/routers/test_ai_router.py` (`TestChatSessaoIdValidacao`: sessao_id inválido → 422 sem chamar o Gemini; uuid válido → 200); `tests/schemas/test_transacao_schemas.py` (`TestF22MaxLengthEntrada`: descrição/categoria no limite passam, acima → 422); `tests/schemas/test_ai_schemas.py` (novo: sessao_id uuid; suggest descricao 500/501; **não-regressão T-37** — `HistoricoResponseItem` com texto de 10k chars passa e não tem `max_length` no campo `text`); `tests/test_auth_hash.py` (novo: hash novo com custo `12`; login de hash custo `10` simulado ainda valida).

**F-06 — fechado:** validado em runtime e aprovado (ver acima). Observações de system prompt/contexto que surgiram na validação estão em "Itens diferidos / Backlog".

---

## Batch 4a — Robustez de config e higiene (26/06/2026)

Subconjunto do Batch 4 (T-28 e os itens de comportamento ficam para 4b/cross-repo). Suíte: **113 testes** (106 + 7 novos), todos verdes. App sobe com `.env` válido.

**F-01 (SECRET_KEY obrigatória):** removido o default `"change-me-in-production"` de `config.py` — `SECRET_KEY: str` sem default, então o boot **falha** (ValidationError do Pydantic) se ausente, em dev e prod. `model_validator(mode="after")` adicionado: quando `ENVIRONMENT == "production"`, rejeita valores de exemplo (`change-me-in-production`, `your-secret-key-here`) e `len < 32` com mensagem clara apontando `openssl rand -hex 32`. **Não** foi inventado default — o `.env` local já tem `SECRET_KEY`.

**T-07 (CORS e constantes via Settings):**
- `main.py`: CORS `allow_origins=[settings.FRONTEND_URL]` (default `http://localhost:5173`) no lugar do hardcode. `allow_credentials`/métodos/headers **intactos** (a config same-site completa, `Domain=.hivvo.app`, é o Batch 11).
- Promovidos para `Settings` (só movidos — valores e comportamento idênticos): `GEMINI_MODEL`, `CHAT_SESSION_WINDOW_HOURS=24`, `CHAT_CONTEXT_MESSAGES=50`, `GEMINI_RETRY_WAITS=[2,4,6,8,10]`. Em `ai.py`: `_MODEL`→`settings.GEMINI_MODEL`; `timedelta(hours=24)`→`settings.CHAT_SESSION_WINDOW_HOURS`; `.limit(50)`→`settings.CHAT_CONTEXT_MESSAGES`; `_RETRY_WAITS`→`settings.GEMINI_RETRY_WAITS` (loop `range(1,6)`/`attempt<5` inalterados).

**F-13:** `docs_url`/`redoc_url`/`openapi_url = None` quando `ENVIRONMENT == "production"` (em `main.py`, via `_IS_PRODUCTION`).

**F-14:** `/health` é **público** (sem auth) — o corpo não nomeia subsistemas nem o ambiente. Saudável: `200 {"status":"ok"}` (antes vazava `database`/`environment`); DB fora: `503 {"status":"unhealthy"}` (via `UTF8JSONResponse`, não mais `raise HTTPException`), com o erro real só no log (`logger.error`). `HTTPException` saiu do import de `main.py` (sem outros usos).

**F-11 + T-08 (higiene):**
- Arquivos `*.log`/`*.err`/`cookies.xml`: **nenhum presente** no diretório (já limpos) e os três padrões **já constavam** no `.gitignore` — nada a remover, **nenhum segredo a reportar/rotacionar** por esta via.
- Removidos os 6 `logger.info` de `GET /ai/historico` (instrumentação dos 503 do Gemini), incluindo o loop que despejava `text` de cada mensagem do chat (privacidade). `logger` segue em uso no retry do Gemini.

**T-06 (populate_db):** movido via `git mv` para `scripts/populate_db.py`. Guarda no topo: `ENVIRONMENT == "production"` → `sys.exit` (não roda seed em produção). Paths corrigidos para a nova profundidade (`PROJECT_ROOT = Path(__file__).resolve().parent.parent` para `.env` e `sys.path`). Cópias locais de `_data_vencimento_parcela` e `_fatura_cartao_avulso` **removidas** — agora importadas de `app/services/faturas.py`. `_criar_parcelas` **mantido local** de propósito (diverge: marca parcela passada como paga via `pago = data_venc < TODAY`).

**Higiene de dependências:** criado `requirements-dev.txt` (`-r requirements.txt` + pytest, pytest-mock, pytest-cov); essas três **removidas** de `requirements.txt`. `tzdata` **mantido** em `requirements.txt` (dependência de PRODUÇÃO do T-27/ZoneInfo).

**Testes novos (`tests/test_config.py`):** SECRET_KEY ausente → `ValidationError` no boot; chave curta/valor de exemplo rejeitados em produção; chave forte aceita em produção; chave curta aceita em dev (só obrigatoriedade); `FRONTEND_URL` default e lido de settings. Usa `_env_file=None` + `monkeypatch.delenv` para isolar do `.env` local.

**Fora do escopo (não tocados):** Batch 4b (backend-local) — F-09 (`ACCESS_TOKEN_EXPIRE_MINUTES`), F-16 (`sessao_id: uuid.UUID`), F-22 (`max_length`), F-23 (`gensalt(rounds=12)`), F-06 (safety do Gemini). T-28 (`/api/v1`) **não é 4b** — é passo cross-repo próprio (API + Web juntos). Índices (Batch 6) e demais batches intocados.

---

## Batch 3b — Comportamento de endpoint (12/06/2026)

Fecha T-36, T-34, T-35 (endpoint), T-41, T-37 e a parte de data de negócio do T-27 — **conclui o Batch 3**. Suíte: **96 testes** (83 + 13 novos), todos verdes.

**T-36 (SEGURANÇA — poluição de fatura entre usuários):**
- `update_transaction` valida propriedade do `cartao_id` (mesmo check/404 da criação).
- As duas agregações de `GET /cards` ganharam `usuario_id == current_user.id` (defesa em profundidade — dados legados alheios apontando para o cartão deixam de inflar o total).
- **Teste de isolamento obrigatório:** `tests/routers/test_cards_router.py` — dados do usuário B na fatura do cartão de A (inseridos direto na sessão, simulando legado) não entram no total de A; + PUT apontando cartão alheio → 404.

**T-34:** `deletar_parcelas` removido de `DELETE /transactions/{id}` (era um caminho impossível → 500 por FK). Parcelas sempre saem junto, no mesmo commit. Query param enviado por cliente antigo é ignorado pelo FastAPI (sem quebra de contrato).

**T-35 (endpoint):** parcelada **bloqueia** edição de `valor`/`data` (400, orienta excluir/recriar ou Gerenciar Parcelas; sem recálculo de parcelas); não-parcelada rederiva `fatura_mes/ano` quando `data` ou `cartao_id` mudam (espelha a criação: `_fatura_cartao_avulso` se cartão com `dia_vencimento`; senão limpa para `None` — ex. cliente removeu o cartão).

**T-41:** criação parcelada atômica — `add` → `flush()` (id) → `_criar_parcelas` → **um** commit no endpoint. `_criar_parcelas` perdeu o `commit()` interno (agora add+`flush()`; o boundary commita). Teste: falha na geração de parcelas → nada persiste (antes ficava transação `parcelado=True` órfã). `populate_db.py` não foi tocado (usa cópia local própria — registro do Batch 1).

**T-37:** `_build_contents` recebe pares `(role, text)` construídos direto das rows; `HistoricoItem` (schema de **entrada**, `max_length=4000`) saiu do caminho de releitura — resposta longa do Gemini persistida não quebra mais o chat. A classe ficou sem nenhum uso e foi **removida** de `schemas/ai.py`.

**T-27 (data de negócio):** novo `app/core/dates.py` — `TZ_PRODUTO = America/Sao_Paulo` + `hoje()` (mockável; testes fixam via `mocker.patch` no nome importado pelo módulo sob teste). Substituiu `date.today()` em `cards.py` (fatura aberta), `installments.py` (`data_pagamento`) e nos `default_factory` de `criado_em` (models `card`/`category`/`installment`). `utcnow()` **não** foi tocado (Batch 16). **Dependência nova:** `tzdata` no `requirements.txt` (Windows e imagens slim não têm a base IANA do sistema — verificado: sem ele o `ZoneInfo` falha).

**Infra de teste nova:** `tests/routers/` — TestClient sobre o `app` real com override de `get_session`/`get_current_user` e fixture de dois usuários (`users` + `as_user`); base para os futuros testes de isolamento (F-02/Batch 15).

---

## Batch 3a — Validação de entrada + fechamento dos xfail (12/06/2026)

Fecha T-33, T-38, T-40 e a parte de **schema** do T-35. Suíte: **82 testes, todos verdes, zero xfail/xpass**; cobertura 100% mantida em `services/faturas.py` e `services/parcelas.py` (a nova `_variacao` em `services/estatisticas.py` também 100% coberta).

**T-33 (parcela ≤ 0):**
- `TransacaoCreate.valida_parcelamento` rejeita `valor < total_parcelas × 0.01` (422, "cada parcela deve ser de pelo menos R$ 0,01").
- `services/parcelas.py` (`_criar_parcelas`) defensivo: `ValueError` antes de criar qualquer parcela — invariante garantido na matemática, não só na borda da API.
- Caso T-33 em `test_parcelas.py` perdeu o xfail: afirma o raise + nenhuma parcela persistida + caso-limite R$ 0,12 em 12× (mínimo válido).

**T-38 (variação % com saldo anterior negativo):**
- `_variacao` canônica (com `abs()` no denominador) agora vive em `app/services/estatisticas.py`. `statistics.py` importa de lá (cópia local sem `abs()` removida); em `ai.py`, `_variacao_saldo_pct` virou wrapper fino que busca o mês anterior e delega a fórmula à canônica (cópia da matemática removida). **Nota de comportamento:** o percentual da IA agora sai quantizado em 2 casas (antes era float pleno) — irrelevante, é exibido com `:.1f`.
- `test_variacao.py` importa de `app.services.estatisticas`, sem xfail, com casos extras (−100→+100 = +200%, base positiva, base zero → None).

**T-40 (validators do CartaoUpdate):** replicados de `CartaoCreate`, todos None-safe (update parcial): `tipo ∈ {Crédito, Débito, Ambos}`, `dia_vencimento`/`dia_fechamento` 1..31, e `mes_offset_vencimento >= 0`. O validator de offset foi adicionado **também ao `CartaoCreate`** (não existia lá — sem ele nasceria cartão com offset negativo que o update rejeita, quebrando a matemática de fatura).

**T-35 (somente schema; endpoint/derivação é o 3b):** `TransacaoUpdate` perdeu `fatura_mes`/`fatura_ano` (derivados — cliente que enviar tem o campo silenciosamente ignorado pelo Pydantic) e ganhou `valor > 0` + `tipo` válido (None-safe; normalização de vírgula decimal mantida).

**Testes novos:** `tests/schemas/` (pydantic puro, sem banco) — `test_card_schemas.py` e `test_transacao_schemas.py` cobrindo rejeições (tipo inválido, dias fora de 1..31, offset negativo, valor ≤ 0, T-33 na borda) e aceites nos limites.

---

## Batch 2 — Rede de testes do domínio (11/06/2026)

Primeira suíte automatizada do projeto (T-23, subconjunto). Nenhuma mudança em `app/` — só `requirements.txt` (pytest, pytest-mock, pytest-cov) e `tests/`.

**Estrutura:** `tests/conftest.py` (fixture `session`: SQLite in-memory com `StaticPool`, `SQLModel.metadata.create_all`; dinheiro sempre comparado via `Decimal(str(x))` por causa da coerção float do SQLite) + `tests/services/test_faturas.py`, `test_parcelas.py`, `test_variacao.py`.

**Resultado:** `42 passed, 2 xfailed` · cobertura **100%** em `app/services/faturas.py` (44 stmts) e `app/services/parcelas.py` (18 stmts).

**Cobertura de casos:** fechamento em meses de 28/29/30/31 dias; compra no dia exato do fechamento (entra na fatura atual) vs. dia seguinte; virada dezembro→janeiro (pelo fechamento e pelo offset); offset 0/1/2; clamp do dia de vencimento (31 em fev normal/bissexto e mês de 30 dias); `_add_months` com salto de 25 meses; cartão sem `dia_vencimento`/`dia_fechamento`; arredondamento com dízima (última absorve para cima E para baixo); soma das parcelas == valor total (5 combinações); campos derivados (`fatura_mes/ano` da data de vencimento, descrição `(i/n)`).

**xfail documentando bugs (fechados no Batch 3a — hoje são testes verdes normais):**
- T-33 (`test_parcelas.py`): R$ 0,10 em 12× não pode gerar parcela ≤ 0 (hoje gera −0,01).
- T-38 (`test_variacao.py`): `_variacao` com saldo anterior negativo deve usar `abs()` no denominador (hoje inverte o sinal). Importa de `app.routers.statistics` — sem efeito colateral real (engine criado mas sem conexão).

---

## Batch 1 — Consolidação da lógica de fatura/parcela (11/06/2026)

Refactor sem mudança de comportamento (T-04 + extração alvo do T-01 + T-02). Só movimentação de código + imports; nenhuma regra de cálculo, assinatura ou resposta de endpoint alterada. Verificado: `py_compile` em todos os arquivos tocados + import da app OK.

**PASSO 0 (diff das cópias antes de consolidar):**
- `_add_months`: 4 cópias (`transactions.py`, `cards.py`, `invoices.py`, `populate_db.py`) — **byte-idênticas**.
- `_fatura_vencimento`: 2 cópias (`cards.py`, `invoices.py`) — **byte-idênticas**. A de `invoices.py` tinha também um `_add_months` morto (nunca chamado).
- `_agregar`/`_categorias`/`_buscar_mes`: existiam **só** em `statistics.py`; `ai.py` importava de lá (T-02). Sem cópias.

**Módulos criados:**
- `app/services/faturas.py` — `_add_months`, `_data_vencimento_parcela`, `_fatura_cartao_avulso`, `_fatura_vencimento`, `_current_open_fatura`.
- `app/services/parcelas.py` — `_criar_parcelas` (mantido o `session` como param; o `commit()` interno foi removido no Batch 3b/T-41 — purificação completa é Batch 12).
- `app/services/estatisticas.py` — `_agregar`, `_categorias`, `_buscar_mes`. `statistics.py` e `ai.py` importam daqui (T-02 resolvido).
- Routers e `populate_db.py` passaram a importar dos services; imports órfãos (`calendar`, `dt`, `Optional`, `ROUND_HALF_UP`) removidos onde ficaram sem uso.

**Fora do escopo, registrado para decisão futura:** `populate_db.py` mantém cópias locais de `_data_vencimento_parcela` e `_fatura_cartao_avulso` (idênticas em lógica às canônicas) e de `_criar_parcelas` (**divergente de propósito**: o seed marca parcelas passadas como pagas via `pago = data_venc < TODAY`). O plano mandava substituir ali apenas `_add_months`. `_variacao` (statistics) vs `_variacao_saldo_pct` (ai) seguem divergentes — é o T-38/Batch 3.

---

## Próximos Passos

### 1. Hardening pré-deploy (workstream ativo)
Executar os batches do `PLANO_EXECUCAO_API.md` na ordem. Não fazer itens pós-deploy "de carona".

### 2. Deploy (gated pelos batches pré-deploy + decisão de topologia)
- **Backend:** `hivvo-api` no Railway/Render — env vars no painel (segredos **rotacionados**, F-05), `DATABASE_URL` apontando para o **pooler** do Supabase com papel de privilégio mínimo, release com `alembic upgrade head`, health check em `/health`.
- **Frontend:** `hivvo-web` no Vercel — `VITE_API_URL` para o backend (com `/api/v1`), PWA instalável.
- **Domínio:** registrar `hivvo.app`; apontar `app.`/`api.` conforme a topologia decidida.

### 3. Melhorias de UX — Fase 3 (pode interlevar pós-deploy, conforme princípio "UX depois de bugs")
- Unificação dos formulários de criação/edição de transação (modal único)
- Destacar toggle "Parcelar compra" no formulário
- Reorganizar Configurações
- Value proposition no login

### 4. Lançamento
Landing page · Product Hunt + LinkedIn · Posthog · limites do plano gratuito (ver roadmap §8 da Referência).

### Validação pendente — Assistente IA
- Histórico completo ao reabrir (user + assistant). **Nota:** o bug que quebrava o chat com resposta > 4000 chars (T-37) foi corrigido no Batch 3b; a validação fim-a-fim segue dependente da estabilização do Gemini (503).

---

## Itens diferidos / Backlog de observações

> Observações para passos **FUTUROS**, fora do escopo dos batches atuais. **Não agir agora** — registradas para não se perderem.

### Observado na validação runtime do F-06 (Batch 4b) — system prompt/contexto do Assistente

**Contexto de fechamento do F-06:** o F-06 (`BLOCK_NONE` → `BLOCK_ONLY_HIGH`) foi **validado em runtime e está APROVADO**. Nenhuma das observações abaixo foi recusa de safety do Gemini — **todas as mensagens foram respondidas**. As limitações são do **system prompt/contexto do Assistente** (`routers/ai.py`), **não** do filtro de safety.

1. **[PRODUTO / pós-launch] Escopo e tom do system prompt do Assistente.** Hoje o assistente recusa orientação financeira legítima ("como quito uma dívida?", "vale a pena pegar empréstimo pra quitar o rotativo?") devolvendo "só analiso seus dados". Para o público-alvo (alto volume parcelado, que busca orientação), é UX ruim. **Decisão de produto:** definir quão "consultor" o assistente deve ser e com quais ressalvas (não é consultor financeiro certificado). Entra na **auditoria de produto pós-launch**.

2. **[BUG — investigar em batch futuro] Assistente expõe lista de categorias interna e INCOMPLETA.** Ao responder sobre gastos, a IA listou "as categorias disponíveis são Outros, Alimentação, Roupas, Saúde e Transporte" — mostrando só as categorias **com gasto no mês** e vazando estrutura interna, além de incompleta (faltam Moradia, Lazer, etc.). **Provável causa:** o contexto/prompt montado para o Gemini confunde "categorias com gasto no período" com "categorias disponíveis". Candidato a **batch de correção**; investigar a montagem do contexto em `routers/ai.py`.

3. **[PRODUTO] Reconciliação "no vermelho" vs. dados.** Ao prompt "estou no vermelho e não consigo pagar as contas", a IA respondeu que o saldo está **positivo** (R$ 21.327,50) e que não dá conselho — contradizendo o usuário secamente, sem reconciliar a percepção com os dados nem acolher o conteúdo emocional. **Decisão de produto/prompt:** como lidar com descasamento entre o que o usuário relata e o que os dados mostram.

---

## Testes — Estado Real

✅ **Suíte automatizada (Batches 2, 3a, 3b, Fase 2, regressão round-trip, T-29, Batch 4a, 4b, 5, 6, 8 e 9):** `tests/` com pytest — **178 testes, todos verdes, zero xfail** (`tests/services/` domínio com SQLite in-memory; `tests/schemas/` validação pydantic pura — incl. F-22 e a não-regressão T-37; `tests/routers/` endpoints via TestClient com override de auth/sessão, incluindo isolamento entre usuários, o round-trip de criação parcelada→fatura, a ordenação estável, a validação de sessao_id e os fluxos de token/sessão — `test_auth_tokens.py`: hashing de refresh/reset, revogação de sessões e envio robusto do e-mail; `tests/test_config.py` carregamento de Settings — F-01/T-07; `tests/test_auth_hash.py` custo bcrypt — F-23), 100% de cobertura nas funções de fatura/parcela (`services/faturas.py`, `services/parcelas.py`). Datas de negócio nos testes: sempre fixadas via patch em `app.core.dates.hoje` — nenhum teste depende do relógio real. Rodar com `venv\Scripts\python.exe -m pytest tests`. Os "Blocos" abaixo foram **testes manuais end-to-end**, valiosos mas não regressivos.

| Bloco (manual E2E) | Escopo | Status |
|---|---|---|
| Bloco 1 | Autenticação (registro, login, logout, sessão) | ✅ |
| Bloco 2 | Dashboard e Transações (CRUD, filtros, gráficos, resumo) | ✅ (2 bugs corrigidos) |
| Bloco 3 | Cartões, Faturas e Parcelas | ✅ |
| Bloco 4 | Assistente IA, Importar CSV, Backup, Configurações | ✅ (1 bug em /settings) |
| Bloco 5 | Build limpo, PWA instalável, qualidade de código | ✅ |

---

## Decisões Fixas (não discutir)

- **Backend:** FastAPI + SQLModel + PostgreSQL (Supabase) + Alembic
- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **Estado:** Zustand (UI) + TanStack Query (servidor)
- **Roteamento:** React Router v6 · **Gráficos:** Recharts · **PWA:** Vite PWA Plugin
- **Deploy:** backend Railway/Render · frontend Vercel
- **Autenticação:** JWT (httpOnly cookie) + bcrypt + refresh token rotativo
- **Tema:** escuro (#1A1714) · **Cor primária:** âmbar (#EF9F27)

---

## Decisões Técnicas Tomadas

| Decisão | Detalhes |
|---|---|
| **Arquitetura em camadas (estado real)** | Repository Pattern **não implementado** — lógica nos routers; `repositories/`/`services/` vazias. Extração planejada (Batch 1 inicia; refactor completo no Batch 12). Corrige o que a Referência afirmava antes. |
| `passlib` removido | Incompatível com `bcrypt >= 4.0`. Usando `bcrypt` direto. |
| `fatura_mes`/`fatura_ano` | Derivados da `data_vencimento` da parcela, não da data da compra. |
| Routers sem trailing slash | Endpoints raiz usam `""` em vez de `"/"` (evita redirect 307). |
| Soft delete em categorias | `ativa=False` em vez de DELETE para preservar histórico. |
| Arredondamento de parcelas | Última parcela absorve a diferença (`ROUND_HALF_UP`). Borda T-33 fechada no Batch 3a: `valor < total_parcelas × 0.01` é rejeitado no schema (422) e por `ValueError` defensivo no service. |
| Vírgula decimal em `valor` | `field_validator(mode="before")` normaliza `"150,00"` → `"150.00"` em `TransacaoCreate` e `TransacaoUpdate`. |
| `username` auto-gerado | Removido do `RegisterRequest`; `_generate_username(email)` — prefixo do e-mail, não-alfanuméricos viram `_`, sufixo numérico garante unicidade. |
| UTF-8 encoding backend | `UTF8JSONResponse` (`charset=utf-8`) como `default_response_class` — elimina Mojibake. |
| Refresh token — interceptor | `isRefreshing` + `failedQueue` serializam 401s paralelos; falha faz `clearAuth()` + redirect `/login`. |
| Zod v4 coerce + RHF | `z.coerce.number()` com `.refine()` + cast `as Resolver<z.infer<typeof schema>>`. |
| Recharts Tooltip formatter | Parâmetros como `unknown` com cast interno. |

---

## Implementado — Assistente IA com Persistência e Memória

### Comportamento final
- Primeira vez no chat → IA se apresenta como Assistente Hivvo
- < 24h desde a última mensagem → UI mostra histórico da sessão, IA com contexto completo
- > 24h → UI limpa (nova sessão automática), IA com contexto invisível das últimas 50 mensagens
- "Nova conversa" → novo `sessao_id` no frontend, UI limpa

### Backend
- Tabela `chat_messages` (id UUID, usuario_id FK, role, text, created_at, `sessao_id` UUID nullable; índices em usuario_id e created_at).
- `GET /ai/historico` retorna apenas a sessão mais recente (vazio se > 24h). `DELETE /ai/historico` para uso administrativo.
- `POST /ai/chat`: salva mensagem do user, busca últimas 50 (todas as sessões) como contexto, detecta primeira vez (COUNT==1), monta system instruction + contents (com sanitização de turnos), envia ao Gemini com retry 5x backoff linear, salva user+assistant **atomicamente** após sucesso, recebe e persiste `sessao_id`.

### Cenários de teste pendentes (aguardando Gemini estabilizar)
Primeiro acesso (apresentação) · segundo acesso (sem apresentação) · volta < 24h (histórico) · simular > 24h (UI limpa, contexto) · referência a conversa anterior com UI limpa · "Nova conversa" · primeiro acesso após nova conversa.

---

## Histórico de Construção (resumo)

Ordem concluída: estrutura FastAPI + Supabase → models + Alembic → auth (JWT) → transações/categorias → cartões/faturas → parcelas → estatísticas → IA → setup React/Tailwind/PWA/layouts → login/cadastro → Dashboard → Transações → Adicionar (parcelamento) → Cartões/faturas → Assistente IA → Ver resumo → features secundárias (CSV, backup, categorias, perfil) → testes E2E Blocos 1–5 → recuperação de senha → renomeação BeeFree→Hivvo → Termos/Privacidade → melhorias UI/UX #1–#10 → Assistente IA com persistência.

**Pendente:** item 27 — Deploy (agora **gated** pelo hardening pré-deploy).

### Melhorias UI/UX #1–#10 (01/06/2026) — commitadas
Labels na sidebar desktop · skeleton loading · Importar CSV na navegação · widget de compromissos futuros · badge de parcela inline (`6d582fa`) · gear badge em Configurações mobile (`96809d3`) · total R$ 0,00 em vermelho (`56b334e`) · Termos/Privacidade no app (`035dc5f`) · barra de limite no card (`36b117a`) · onboarding progressivo (`1994d61`).

### Bugfixes relevantes (referência)
`f370bdb` vírgula decimal em `valor` (422) · `f7abfdd` `username` removido do cadastro · `a66c92d` `toFixed`/`R$ NaN` (string do backend) · `07d476b` Zod v4 + zodResolver cast · `15798da` ícones PWA · `f55c4df` error handling em Settings + emoji em categorias · `41522d5` Toast global · `c592196` "Ver Resumo" visível · `d9270ae` UTF-8 backend.

> **Changelog detalhado de arquivos por tarefa:** consolidado no histórico do git. (As listas exaustivas de paths por tarefa foram removidas deste doc para mantê-lo acionável; nada de decisão foi perdido — está acima e no git.)

---

## Estrutura de Pastas Atual (Frontend)

```
hivvo-web/src/
├── layouts/    DesktopLayout, MobileLayout, AuthLayout
├── pages/      Dashboard, Transactions/Summary, AddTransaction, Cards,
│               Assistant, Auth (Login, Register, ForgotPassword,
│               ResetPassword), Settings, Import, Legal (Terms, Privacy)
├── components/ ui/ (Button, Input, Modal, Spinner, Toast, OnboardingBanner),
│               charts/, transaction/, cards/
├── hooks/      useBreakpoint, useTransactions, useCategories, useStatistics,
│               useCards, useAuth, useInstallments
├── store/      authStore, uiStore
├── services/   api, auth, transactions, categories, cards, ai, statistics,
│               installments
└── styles/     tokens.css
```

---

## CHECKLIST DE DEPLOY (Fase 5)

Itens acumulados ao longo dos batches. Percorrer antes/durante o deploy de produção (Railway = API, Vercel = Web, domínio `hivvo.app`).

- [ ] **DATABASE_URL de PRODUÇÃO usa o Session pooler (IPv4), NÃO a conexão direta (IPv6).** O mesmo problema de IPv6 que quebrou a conexão local (`DestinationNetworkUnreachable`) reaparece no Railway se usar a direct. Usar o host `pooler.supabase.com`.
- [ ] **F-05 — rotacionar TODOS os segredos** (DB, Gemini, Resend, SECRET_KEY) e inseri-los **só como env vars no Railway** — nunca em arquivo. (A senha do banco de **dev** já foi rotacionada nesta sessão; produção é à parte.)
- [ ] **VITE_API_URL na Vercel = `https://api.hivvo.app/api/v1`** (COM `/api/v1`). O frontend **não tem `.env` local** e depende do fallback; em produção a env é **obrigatória**. Backend e frontend devem subir com `/api/v1` casado — não deployar um sem o outro.
- [ ] **SENTRY_DSN setado no Railway.** Sem ele o Sentry fica **no-op** (não captura nada). Ver Batch 10.
- [x] **Batch 11b — cookies same-site + token curto — CÓDIGO FEITO (01/07/2026):** `Domain=.hivvo.app` + `Secure` + `SameSite=Lax` em produção / sem Domain+Secure em dev (F-03), CORS com origem explícita + métodos/headers restritos, reforço CSRF por Origin nos endpoints mutáveis, e `ACCESS_TOKEN_EXPIRE_MINUTES` 30 (F-09, refresh segue 7 dias). **Falta VALIDAR no domínio real:** cookie same-site atravessando `app.`↔`api.hivvo.app` e o ciclo de refresh (a sessão não pode deslogar sozinha após 30min). Definir `ENVIRONMENT=production` e `FRONTEND_URL=https://app.hivvo.app` no Railway.
- [ ] **⚠️ INVARIANTE CSRF — confirmar topologia same-site (`app.`/`api.hivvo.app`, mesmo site `hivvo.app`).** É o que faz o `SameSite=Lax` proteger contra CSRF: request mutável cross-site não carrega os cookies → 401. O `verify_origin` deixa passar `Origin` ausente (clientes não-browser) apoiado NESTE invariante. **NÃO migrar os cookies para `SameSite=None`** (nem hospedar front/API em sites diferentes, ex.: `*.vercel.app`↔`*.railway.app`) **sem antes endurecer o `verify_origin` para rejeitar `Origin` ausente (ou adotar CSRF token double-submit)** — caso contrário abre um buraco de CSRF silencioso. Ver o guard-note em `app/core/csrf.py`.
- [x] **Batch 7 formal (código) — FEITO (01/07/2026):** `pool_pre_ping=True`, `pool_recycle=1800`, `pool_size=5`, `max_overflow=10` em `app/core/database.py` (pool modesto — o pooler do Supabase tem limite próprio). **Falta a parte OPS:** **papel Postgres restrito** (sem superuser / sem BYPASSRLS, só SELECT/INSERT/UPDATE/DELETE nas tabelas da app — F-02) — passo de infra no Supabase.
- [x] **Exception handler global — FEITO (01/07/2026):** erro de conexão de banco (`OperationalError`/`InterfaceError`) vira **503 limpo COM headers de CORS**, não 500 cru. Handler dentro do `ExceptionMiddleware` (dentro do CORS); corpo genérico; erro real só no log sem string de conexão. Provado por teste.
- [ ] **Higiene da imagem:** `requirements-dev.txt` fora da imagem de produção; garantir que o `.env` **não** vai para a imagem; **fixar versões** das dependências (`==`/lockfile).
- [ ] **CSP (`vercel.json`):** o `connect-src` deve casar com o domínio real da API (`api.hivvo.app`).
- [ ] **Política de Privacidade — mencionar o direito de exclusão de conta (F-07).** Tarefa de conteúdo, fora do código.

---

## Regras de Trabalho

1. **Uma tarefa/batch por vez** — não avançar sem confirmação
2. **Sempre rodar testes** antes de marcar como concluído (a partir do Batch 2 há suíte automatizada)
3. **Nunca hardcodar cores** — tokens do brand guide
4. **Nunca misturar** TanStack Query com Zustand
5. **Layouts distintos** — MobileLayout/DesktopLayout, nunca CSS responsivo puro
6. **Valores monetários** — `Decimal` no Python, `toFixed(2)` no JS
7. **JWT** — nunca em localStorage, apenas httpOnly cookie ou memória
8. **Atualizar este `SESSAO_ATUAL.md`** ao fim de cada batch

---

*Última atualização: 1 de julho de 2026 — Batch 11b (cookies same-site + token 30min, F-03/F-09, env-conditional): cookies com `Domain=.hivvo.app`/`Secure`/`SameSite=Lax` em produção (sem Domain/Secure em dev), centralizados em `_cookie_kwargs()` e usados em set E clear (logout/delete-me); CORS com origem explícita + métodos/headers restritos; reforço CSRF por `Origin` (`app/core/csrf.py`) nos routers de negócio (só métodos mutáveis; Origin ausente passa); access token 30min, refresh intacto em 7 dias. 212 testes verdes. Dev em localhost intacto. F-03/F-09 validam-se DE FATO só no deploy (domínio real). Próximo: deploy (ver CHECKLIST DE DEPLOY) + parte OPS do Batch 7 (papel Postgres).*
*Penúltima: 1 de julho de 2026 — Fase 5 (resiliência de banco): Batch 7 código (`pool_pre_ping`/`pool_recycle=1800`/`pool_size=5`/`max_overflow=10` no `database.py`, pool modesto p/ o pooler) + exception handler global de banco fora (`OperationalError`/`InterfaceError` → 503 limpo COM headers de CORS, tratado dentro do ExceptionMiddleware/CORS — não mais falso-CORS; log sem string de conexão). 196 testes verdes. Parte OPS do Batch 7 (papel Postgres restrito) fica para o infra. Próximo: deploy (ver CHECKLIST DE DEPLOY) e Batch 11b (F-03/F-09).*
*Penúltima: 1 de julho de 2026 — Fim de sessão: T-28 `/api/v1` CONCLUÍDO e verificado (login+escrita+leitura sob `/api/v1`, dois repos casados, commit `f46f17e`); Batch 11a LGPD `DELETE /auth/me` (F-07) commitado `1623dc8`; migração de conexão do banco local para o **Session pooler** do Supabase (IPv4 — a direct resolve IPv6 e a rede local é IPv4-only) antecipando o núcleo do Batch 7, senha de dev rotacionada. 194 testes verdes. Próximo: **Fase 5 — DEPLOY** (ver seção "CHECKLIST DE DEPLOY (Fase 5)"); resta em código Batch 11b (F-03/F-09) e Batch 7 formal. F-03 (cookies same-site) + F-09 (token 30min) ficam para o deploy (11b).*
*Penúltima: 30 de junho de 2026 — Batch 10: observabilidade e deploy (T-25 logging via dictConfig + Sentry opcional com scrub LGPD em 2 níveis — `send_default_pii=False`/`include_local_variables=False`/`max_request_body_size="never"` no init E `before_send` que limpa headers/cookies/corpo **e os locals do stacktrace** onde a mensagem de chat realmente viaja + middleware de request-id em `X-Request-ID` logando só metadados, /health em DEBUG; T-43 lifespan com fail-fast de boot — produção sem GEMINI/RESEND aborta, dev só warning — + engine.dispose no shutdown; T-42 Procfile release `alembic upgrade head` + web uvicorn). `SENTRY_DSN` setado no deploy (ops); sem ele Sentry inativo. 188 testes verdes. Próximo: Batch 7 (pooler + papel Postgres, passos manuais no Supabase) e T-28 /api/v1 (cross-repo).*
*Penúltima: 29 de junho de 2026 — Batch 9: resiliência da IA + rate limiting (T-21 timeout no genai.Client + retry reduzido a 2 tentativas + client singleton; F-04 slowapi com limites por IP em login/register/forgot-password e por IP+usuário+cota diária em /ai/chat, lockout por conta mantido). Rate limit OFF na suíte; store em memória → migrar p/ Redis ao escalar. 178 testes verdes. Próximo: Batch 7 (pooler + papel Postgres, passos manuais no Supabase) e T-28 /api/v1 (cross-repo).*
*Penúltima: 29 de junho de 2026 — Batch 8: queries pesadas + teto de listagem (T-17 invoices/cards agregam no banco com GROUP BY, sem N+1/varredura, valores idênticos; T-12 limit/offset no GET /transactions com clamp 500 + novo GET /transactions/export, mantendo array nu). 173 testes verdes. Feito fora de ordem (antes do Batch 7). Próximo: Batch 7 (pooler + papel Postgres, passos manuais no Supabase) e T-28 /api/v1 (cross-repo).*
*Penúltima: 29 de junho de 2026 — Batch 6: banco (T-09 índices compostos; T-10 sargabilidade em `_buscar_mes` e `GET /transactions`; T-11 NOT NULL monetário + CHECKs + UNIQUE puro de parcelas + índice parcial UNIQUE de categorias `WHERE ativa` + guarda de reativação no create_category; T-14 cascades nas FKs de usuario_id e parcelas.transacao_id). Migration `e7c9a1b2d3f4`, downgrade reversível, validada offline — NÃO rodada (Lucas roda `alembic upgrade head` em dev). 166 testes verdes. Próximo: T-28 /api/v1 (passo cross-repo, API + Web juntos); Batch 7 (pooler + papel Postgres, tem passos manuais no Supabase).*
*Projeto: Hivvo — gestão financeira pessoal com IA · Repositório FinanceAI original: github.com/lucasdonnangelo/financeai*
