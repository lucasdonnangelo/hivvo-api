# Hivvo — Sessão Atual

## Antes de começar
Leia `docs/Hivvo_Referencia.md`, `docs/SESSAO_ATUAL.md`, `docs/AUDITORIA_SEGURANCA.md`, `docs/AUDITORIA_TECNICA.md` e `docs/PLANO_EXECUCAO_API.md` para entender o produto, a arquitetura **real**, as decisões de stack e o plano de correção em andamento. Não proponha alternativas de tecnologia — já decididas. Uma tarefa/batch por vez, com aprovação antes do commit.

---

## Estado do Projeto

**Fase atual:** Hardening pré-deploy (correções de segurança e técnicas)
**Status:** As fases de construção (backend + frontend + telas) estão concluídas e o app é funcional/instalável. Em 10/06/2026 o backend passou por **duas auditorias** (segurança e técnica) que revelaram **bloqueadores de lançamento**. O trabalho ativo agora é executar o plano de correção (`docs/PLANO_EXECUCAO_API.md`) **antes** do deploy.
**Batch 11b concluído — CÓDIGO (01/07/2026, aguardando commit):** cookies same-site + token 30min (F-03, F-09), env-conditional (dev em localhost intacto). Cookies com `Domain=.hivvo.app`/`Secure`/`SameSite=Lax` em produção (sem Domain/Secure em dev), CORS com origem explícita + métodos/headers restritos, reforço CSRF por `Origin` nos endpoints mutáveis, access token 30min (refresh segue 7 dias). Suíte com **212 testes, todos verdes** (196 + 16) — ver seção "Batch 11b" abaixo. **⚠️ F-03/F-09 só se validam DE FATO no deploy** (domínio real). **Não** toca outros batches nem papel Postgres (ops).
**Fase 5 — resiliência de banco concluída (01/07/2026, aguardando commit):** Batch 7 (parte CÓDIGO) — `pool_pre_ping`/`pool_recycle=1800`/`pool_size=5`/`max_overflow=10` no `database.py` (pool modesto p/ o pooler) — + **exception handler global**: falha de conexão (`OperationalError`/`InterfaceError`) → **503 limpo COM headers de CORS** (não mais falso-CORS). Suíte com **196 testes, todos verdes** (194 + 2) — ver seção "Fase 5 — resiliência de banco" abaixo. **Parte OPS do Batch 7 (papel Postgres restrito, sem superuser) fica para o passo de infra.** **Não** toca 11b, T-28 nem outros batches.
**Próximo passo imediato:** **Fase 5 — DEPLOY.** O hardening pré-deploy relevante está feito; o **T-28 (`/api/v1`) está CONCLUÍDO e verificado** (login + escrita + leitura testados sob `/api/v1`, os dois repos casados). O próximo passo **não** é mais o T-28 nem o Batch 7 formal (a troca para o pooler já foi antecipada nesta sessão — ver "Migração de conexão do banco" abaixo). Seguir a **seção "CHECKLIST DE DEPLOY (Fase 5)"** no fim deste doc. O que resta de código antes/durante o deploy: Batch 11b (F-03 cookies same-site + F-09 token 30min, deploy-coupled) e o Batch 7 formal (pool_pre_ping/recycle/size + papel Postgres restrito).
**T-28 CONCLUÍDO e VERIFICADO (01/07/2026, commitado `f46f17e`):** todos os routers de NEGÓCIO montados sob `/api/v1` (hard switch, sem dual-mount); `/health` permanece na RAIZ. **Cross-repo casado e testado ponta a ponta:** login + escrita + leitura funcionando sob `/api/v1` com os dois repos (API + Web) apontando para o mesmo prefixo. Suíte com **191 testes, todos verdes** (188 + 3 do hard switch) — ver seção "T-28 (lado API)" abaixo. **⚠️ Cross-repo: NÃO deployar API e Web separados** — produção precisa subir com `/api/v1` casado dos dois lados (`VITE_API_URL=https://api.hivvo.app/api/v1`).
**Batch 11a concluído (01/07/2026, commitado `1623dc8`):** LGPD — exclusão de conta (F-07). `DELETE /auth/me` (sob `/api/v1`), autenticado + reautenticação por senha, apaga TODOS os dados do usuário numa transação única. Suíte com **194 testes, todos verdes** (191 + 3) — ver seção "Batch 11a" abaixo. **⚠️ Política de Privacidade precisa ser atualizada** mencionando o direito de exclusão (conteúdo, fora do código). **F-03 (cookies same-site) e F-09 (token 30min) ficam para o deploy (11b)** — são deploy-coupled.
**Migração de conexão do banco (01/07/2026, ops — antecipa o núcleo do Batch 7):** `DATABASE_URL` local migrada da **conexão direta** do Supabase para o **SESSION POOLER** (host `pooler.supabase.com`, IPv4). Motivo: a conexão direta resolve para **IPv6** e a rede local é **IPv4-only** (`Test-NetConnection` deu `DestinationNetworkUnreachable` no IPv6). A **senha do banco de dev foi ROTACIONADA** nesta sessão. **⚠️ O mesmo problema de IPv6 reaparece no Railway** se usar a direct — ver checklist de deploy.
**Batch 10 concluído (30/06/2026, aguardando commit):** observabilidade e deploy — T-25 (logging via dictConfig + Sentry opcional com scrub LGPD em 2 níveis + middleware de request-id), T-43 (lifespan + fail-fast de boot + engine.dispose), T-42 (Procfile: release `alembic upgrade head` + web uvicorn). Suíte com **188 testes, todos verdes** — ver seção "Batch 10" abaixo. **Não** toca pooler (Batch 7), T-28 nem Batch 11.
**Batch 9 concluído (29/06/2026, aguardando commit):** resiliência da IA + rate limiting — T-21 (timeout no client, retry reduzido a 2 tentativas, client singleton) e F-04 (slowapi: limites por IP em login/register/forgot-password, e por IP + usuário + cota diária em /ai/chat). Suíte com **178 testes, todos verdes** — ver seção "Batch 9" abaixo.
**Batch 8 concluído (29/06/2026, aguardando commit):** queries pesadas + teto de listagem — T-17 (invoices e cards agregam no banco, sem N+1/varredura) e T-12 (limit/offset no `GET /transactions`, clamp 500; novo `GET /transactions/export`). **Sem quebrar contrato** (array nu, sem envelope). Suíte com **173 testes, todos verdes** — ver seção "Batch 8" abaixo. **Feito fora de ordem** (antes do Batch 7, a pedido) — Batch 7 não bloqueia o 8.
**Batch 6 concluído (29/06/2026, aguardando commit):** banco — índices compostos (T-09), sargabilidade (T-10), constraints (T-11), cascades (T-14). Uma migration Alembic (`e7c9a1b2d3f4`) + ajuste de 2 funções de query + guarda no `create_category`. Suíte com **166 testes, todos verdes**. **Migration NÃO rodada — comandos abaixo para o Lucas rodar em dev** — ver seção "Batch 6" abaixo.
**Batch 5 concluído (26/06/2026, aguardando commit):** tokens e sessão — F-24, F-10, F-18/T-31. Suíte com **139 testes, todos verdes** — ver seção "Batch 5" abaixo.
**Batch 4b concluído (26/06/2026, commitado `6f5e359`):** hardening de entrada e hashing — F-16, F-22, F-23, F-06. Suíte com **128 testes, todos verdes** — ver seção "Batch 4b" abaixo. **F-06 validado em runtime e APROVADO** (nenhuma recusa de safety); observações de system prompt/contexto do Assistente surgidas na validação foram para "Itens diferidos / Backlog".
**Batch 4a concluído (26/06/2026, commitado `c7f84bf`):** robustez de config e higiene — F-01, T-07, F-13, F-14, F-11+T-08, T-06 e separação de dependências de dev. Suíte com **113 testes, todos verdes** — ver seção "Batch 4a" abaixo.
**Batch 1 concluído (11/06/2026, commitado):** lógica de fatura/parcela/estatísticas consolidada em `app/services/`.
**Batch 2 concluído (11/06/2026, commitado):** primeira suíte automatizada — 44 testes (42 pass + 2 xfail), 100% de cobertura em `services/faturas.py` e `services/parcelas.py` — ver seção "Batch 2" abaixo.
**Batch 3a concluído (12/06/2026, commitado `c315a3a`):** validação de entrada + fechamento dos 2 xfail (T-33, T-38, T-40, T-35 parte de schema) — ver seção "Batch 3a" abaixo.
**Batch 3b concluído (12/06/2026, commitado `124086f`):** comportamento de endpoint (T-36, T-34, T-35-endpoint, T-41, T-37, T-27 data de negócio) — ver seção "Batch 3b" abaixo. **Fecha o Batch 3 inteiro.**
**Fase 2 cross-repo concluída (12/06/2026, commitado `2fc837f`):** `POST /ai/suggest-category` — endpoint dedicado de sugestão de categoria, stateless (raiz do FE-08; o **Web-Batch 4** do hivvo-web vai consumi-lo) — suíte com **101 testes, todos verdes** — ver seção "Fase 2" abaixo.
**Teste de regressão round-trip parcelada→fatura concluído (26/06/2026, commitado `f3565c8`):** só testes — fecha o gap de cobertura do caminho de SUCESSO da criação parcelada (havia só atomicidade/FALHA do T-41). Suíte com **103 testes, todos verdes** — ver seção "Regressão round-trip" abaixo.
**T-29 ordenação estável de transações concluído (26/06/2026, aguardando commit):** desempate determinístico `data DESC, id DESC` em `GET /transactions` e nas avulsas do detalhe de fatura. Suíte com **106 testes, todos verdes** — ver seção "T-29" abaixo.
**Última construção concluída:** Assistente IA com persistência e memória (`chat_messages`, sessões, histórico 24h, contexto de 50 mensagens, retry Gemini 5x). Validação de UX do histórico ainda pendente (bloqueada pelos 503 do Gemini).

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
