# Hivvo — Sessão Atual

## Antes de começar
Leia `docs/Hivvo_Referencia.md`, `docs/SESSAO_ATUAL.md`, `docs/AUDITORIA_SEGURANCA.md`, `docs/AUDITORIA_TECNICA.md` e `docs/PLANO_EXECUCAO_API.md` para entender o produto, a arquitetura **real**, as decisões de stack e o plano de correção em andamento. Não proponha alternativas de tecnologia — já decididas. Uma tarefa/batch por vez, com aprovação antes do commit.

---

## Estado do Projeto

**Fase atual:** Hardening pré-deploy (correções de segurança e técnicas)
**Status:** As fases de construção (backend + frontend + telas) estão concluídas e o app é funcional/instalável. Em 10/06/2026 o backend passou por **duas auditorias** (segurança e técnica) que revelaram **bloqueadores de lançamento**. O trabalho ativo agora é executar o plano de correção (`docs/PLANO_EXECUCAO_API.md`) **antes** do deploy.
**Próximo passo imediato:** Batch 3 do plano — correção dos bugs de domínio contra a rede de testes (T-36, T-34, T-35, T-40, T-33, T-38, T-41, T-37, T-27 parcial).
**Batch 1 concluído (11/06/2026, commitado):** lógica de fatura/parcela/estatísticas consolidada em `app/services/`.
**Batch 2 concluído (11/06/2026, aguardando commit):** primeira suíte automatizada — 44 testes (42 pass + 2 xfail), 100% de cobertura em `services/faturas.py` e `services/parcelas.py` — ver seção "Batch 2" abaixo.
**Última construção concluída:** Assistente IA com persistência e memória (`chat_messages`, sessões, histórico 24h, contexto de 50 mensagens, retry Gemini 5x). Validação de UX do histórico ainda pendente (bloqueada pelos 503 do Gemini).

---

## Auditorias e Plano de Correção (10/06/2026)

| Documento | Conteúdo |
|---|---|
| `docs/AUDITORIA_SEGURANCA.md` | 25 achados · **10 bloqueadores**. Forte: IDOR/BOLA sólido na leitura. Riscos: segredos, cookie/CORS cross-domain + CSRF, sem rate limiting, tokens em texto claro (F-24), RLS ausente, sem exclusão de conta (F-07). |
| `docs/AUDITORIA_TECNICA.md` | ~44 achados. Forte: ciclo de fatura correto, Decimal no dinheiro, API stateless, migrações limpas. Riscos: **zero testes**, Repository Pattern inexistente, conexão direta ao Supabase, sem paginação/índices, Gemini síncrono sem timeout, bugs de domínio (T-34/35/36/37/38/40). |
| `docs/PLANO_EXECUCAO_API.md` | **16 batches** ordenados (11 pré-deploy + deploy + 5 pós-deploy). Executar um por vez, com aprovação. |

**Gates:** Batches 1→2→3 são sequenciais (consolidar → testar → corrigir). Batch 7 tem passos manuais no Supabase. Batch 11 depende da decisão de topologia (`app.`/`api.hivvo.app`). Auditoria de **produto** será feita à parte (estratégia/mercado), não pelo Claude Code.

---

## Batch 2 — Rede de testes do domínio (11/06/2026)

Primeira suíte automatizada do projeto (T-23, subconjunto). Nenhuma mudança em `app/` — só `requirements.txt` (pytest, pytest-mock, pytest-cov) e `tests/`.

**Estrutura:** `tests/conftest.py` (fixture `session`: SQLite in-memory com `StaticPool`, `SQLModel.metadata.create_all`; dinheiro sempre comparado via `Decimal(str(x))` por causa da coerção float do SQLite) + `tests/services/test_faturas.py`, `test_parcelas.py`, `test_variacao.py`.

**Resultado:** `42 passed, 2 xfailed` · cobertura **100%** em `app/services/faturas.py` (44 stmts) e `app/services/parcelas.py` (18 stmts).

**Cobertura de casos:** fechamento em meses de 28/29/30/31 dias; compra no dia exato do fechamento (entra na fatura atual) vs. dia seguinte; virada dezembro→janeiro (pelo fechamento e pelo offset); offset 0/1/2; clamp do dia de vencimento (31 em fev normal/bissexto e mês de 30 dias); `_add_months` com salto de 25 meses; cartão sem `dia_vencimento`/`dia_fechamento`; arredondamento com dízima (última absorve para cima E para baixo); soma das parcelas == valor total (5 combinações); campos derivados (`fatura_mes/ano` da data de vencimento, descrição `(i/n)`).

**xfail documentando bugs (fechar no Batch 3, `strict=True`):**
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
- `app/services/parcelas.py` — `_criar_parcelas` (mantido o `session` como param e o `commit()` interno — purificação é Batch 12).
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
- Histórico completo ao reabrir (user + assistant). **Nota:** o Batch 3 corrige o bug que quebra o chat com resposta > 4000 chars (T-37); a validação fim-a-fim segue dependente da estabilização do Gemini (503).

---

## Testes — Estado Real

✅ **Suíte automatizada introduzida no Batch 2 (11/06/2026):** `tests/` com pytest — 44 testes (42 pass + 2 xfail documentando T-33/T-38), 100% de cobertura nas funções de fatura/parcela (`services/faturas.py`, `services/parcelas.py`). Rodar com `venv\Scripts\python.exe -m pytest tests`. Os "Blocos" abaixo foram **testes manuais end-to-end**, valiosos mas não regressivos.

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
| Arredondamento de parcelas | Última parcela absorve a diferença (`ROUND_HALF_UP`). Borda a corrigir: valores pequenos podem gerar parcela ≤ 0 (T-33). |
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

*Última atualização: 11 de junho de 2026 — Batches 1 e 2 concluídos (consolidação em `app/services/` + rede de testes com 100% de cobertura em fatura/parcela). Próximo: Batch 3 (correção dos bugs de domínio; os 2 xfail devem ficar verdes).*
*Projeto: Hivvo — gestão financeira pessoal com IA · Repositório FinanceAI original: github.com/lucasdonnangelo/financeai*
