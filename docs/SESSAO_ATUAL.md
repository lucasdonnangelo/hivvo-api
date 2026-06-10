# Hivvo — Sessão Atual

## Antes de começar
Leia os arquivos `docs/Hivvo_Referencia.md` e `docs/SESSAO_ATUAL.md` para entender o produto, a arquitetura e as decisões de stack. Não proponha alternativas de tecnologia — as escolhas já foram feitas.

---

## Estado do Projeto

**Fase atual:** Deploy  
**Status:** Assistente IA com persistência e memória implementado — tabela `chat_messages`, arquitetura de sessões, histórico com janela de 24h, contexto invisível das últimas 50 mensagens, retry Gemini 5x com backoff linear. Pendente validação de UX.  
**Próximo passo imediato:** Validar itens pendentes do Assistente quando o Gemini estabilizar + implementar melhorias de UX da Fase 3  
**Última tarefa concluída:** Retry Gemini 503 aumentado para 5 tentativas com backoff linear 2/4/6/8s (commit `de35c33`)

---

## Testes — Estado Atual

| Bloco | Escopo | Status | Observações |
|---|---|---|---|
| Bloco 1 | Autenticação (registro, login, logout, sessão persistida) | ✅ Concluído | — |
| Bloco 2 | Dashboard e Transações (CRUD, filtros, gráficos, resumo detalhado) | ✅ Concluído | 2 bugs corrigidos |
| Bloco 3 | Cartões, Faturas e Parcelas | ✅ Concluído | — |
| Bloco 4 | Assistente IA, Importar CSV, Backup, Configurações | ✅ Concluído | 1 bug corrigido em /settings |
| Bloco 5 | Build limpo, PWA instalável, qualidade de código | ✅ Concluído | 12 erros TS corrigidos, ícones PWA criados |

### Bugfixes pós-UI/UX — Sessão de 03/06/2026

| Commit | Arquivo | Problema | Solução |
|---|---|---|---|
| `f370bdb` | `app/schemas/transaction.py` | HTTP 422 ao enviar `valor` com vírgula decimal (`"150,00"`) | `field_validator("valor", mode="before")` normaliza `,` → `.` antes da coerção do Pydantic; aplicado em `TransacaoCreate` e `TransacaoUpdate` |
| `f7abfdd` | `app/schemas/auth.py`, `app/routers/auth.py` | Campo `username` obrigatório no cadastro mas nunca exibido no app | `username` removido do `RegisterRequest`; `_generate_username()` gera a partir do prefixo do email (caracteres não-alfanuméricos → `_`, sufixo `_2`/`_3` se já existir); sem migration |

### Bugs corrigidos durante testes

| Commit | Arquivo | Problema | Solução |
|---|---|---|---|
| `a66c92d` | `DonutChart.tsx:82` | `percentual.toFixed is not a function` — backend retorna string | `Number(item.percentual).toFixed(1)` |
| `a66c92d` | `AddTransactionPage.tsx:612` | Saldo estimado exibia `R$ NaN` — concatenação de string | `Number(stats.saldo)` na passagem para `ImpactPreview` |
| `fe3c8c9` | `SettingsPage.tsx:317` | Confirmação de remoção exibida para todas as categorias por padrão | `deletingId !== null &&` antes da comparação com `cat.id` |
| `07d476b` | `CardFormModal`, `EditTransactionModal`, `AddTransactionPage` | `invalid_type_error` e `error` inexistentes em `z.coerce.number()` no Zod v4 | `.refine(v => !isNaN(v))` + `.refine(v => v > 0)` |
| `07d476b` | `CardFormModal`, `EditTransactionModal`, `AddTransactionPage` | `zodResolver` infere tipo INPUT (`unknown`) incompatível com `useForm<OutputType>` | Import `Resolver` + cast `zodResolver(schema) as Resolver<z.infer<typeof schema>>` |
| `07d476b` | `BarChart.tsx`, `DonutChart.tsx` | Formatter do Recharts espera `ValueType/NameType`, não `number/string` | `(value: unknown, name: unknown)` com cast interno |
| `15798da` | `public/` | Ícones PWA `icon-192.png` e `icon-512.png` ausentes | Gerados via Pillow: fundo âmbar #EF9F27, letra B off-white centralizada |
| `f55c4df` | `SettingsPage.tsx` | Error handling genérico ao salvar nome — não exibia mensagem do backend | `extractDetail` extrai `error.response.data.detail` (string/array/objeto) |
| `f55c4df` | `SettingsPage.tsx` | Botão X aparecia para categorias padrão (`usuario_id === null`) | Loop usa `categories.map()` com condição `{cat.usuario_id !== null && <X>}` |
| `f55c4df` | `SettingsPage.tsx`, `services/categories.ts`, `hooks/useCategories.ts` | Emoji em categorias: sem suporte a emoji no nome | Campo aceita emoji; `extractEmojiAndName` via `Intl.Segmenter`; fallback `📦`; sugestões desktop |
| `f55c4df` | `DashboardPage.tsx` | Empty state do Dashboard não diferenciava mobile/desktop | Texto contextual via `useBreakpoint`: 'botão + abaixo' vs 'ícone + na barra lateral' |
| `41522d5` | `Toast.tsx`, `App.tsx`, hooks | Toast de sucesso ausente em toda a aplicação | `ToastContainer` com auto-dismiss 3s, animação suave, posição adaptativa mobile/desktop |
| `c592196` | `TransactionsPage.tsx` | "Ver Resumo" discreto e difícil de encontrar em mobile e desktop | Chip âmbar na barra de filtros (mobile) + botão com borda âmbar no topbar (desktop) |
| `d9270ae` | `hivvo-api/main.py` | Mensagens com Mojibake (`vocÃª`, `receberÃ¡`) — bytes UTF-8 lidos como latin-1 | `UTF8JSONResponse` com `charset=utf-8` como `default_response_class` |

---

## Próximos Passos

### Validação pendente — Assistente IA (aguardando Gemini estabilizar)
- Histórico completo ao reabrir (user + assistant visíveis)
- Fluxo de 5+ mensagens consecutivas sem erro 503

### Melhorias de UX — Fase 3 (próxima implementação)
- Unificação dos formulários de criação/edição de transação (modal único reutilizável)
- Widget de parcelas ativas no Dashboard (resumo visual das parcelas em aberto)
- Destacar toggle "Parcelar compra" no formulário de transação
- Reorganizar Configurações (hierarquia e agrupamento mais claro)
- Value proposition no login (frase de impacto + benefícios visíveis antes de autenticar)

### Deploy (etapa em paralelo)
- **Backend:** publicar `hivvo-api` no Railway ou Render (free tier)
  - Configurar variáveis de ambiente (.env) no painel do serviço
  - Apontar `DATABASE_URL` para o Supabase de produção
  - Verificar health check em `/health`
- **Frontend:** publicar `hivvo-web` no Vercel
  - Configurar `VITE_API_URL` apontando para o backend em produção
  - Verificar PWA instalável no celular após deploy
- **Domínio:** registrar `hivvo.app` e apontar para o Vercel

### Fase seguinte — Lançamento
- Landing page do Hivvo
- Post LinkedIn + Product Hunt
- Analytics com Posthog (gratuito)
- Definir limites do plano gratuito

---

## ✅ Implementado — Assistente IA com Persistência e Memória

### Visão geral do comportamento final
- Primeira vez no chat → IA se apresenta como Assistente Hivvo
- Menos de 24h desde a última mensagem → UI mostra histórico, IA tem contexto completo
- Mais de 24h → UI limpa, IA tem contexto invisível das últimas 50 mensagens
- Botão "Nova conversa" → limpa UI e banco, IA começa do zero

### FASE 1 — Backend (hivvo-api)

**1.1 — Nova tabela `chat_messages`**
- id: UUID, primary key, default uuid4
- usuario_id: FK para usuarios, not null
- role: string ("user" ou "assistant"), not null
- text: text, not null
- created_at: datetime, default utcnow, not null
- Índices: ix_chat_messages_usuario_id, ix_chat_messages_created_at

**1.2 — Migration Alembic**
Gerar e aplicar migration para criar a tabela chat_messages.

**1.3 — Novos endpoints**

GET /ai/historico
- Autentica usuário via JWT
- Busca mensagens das últimas 24h, ordenadas por created_at ASC
- Retorna lista de {role, text, created_at}

DELETE /ai/historico
- Autentica usuário via JWT
- Deleta todas as mensagens do usuário no banco

**1.4 — Modificar POST /ai/chat**
1. Receber mensagem do usuário
2. Salvar mensagem do usuário no banco (role: "user")
3. Buscar últimas 50 mensagens do usuário no banco (sem filtro de 24h)
4. Verificar se é primeira vez — COUNT(*) == 1
5. Montar _build_contents() com as 50 mensagens
6. Montar _build_system_instruction() com flag primeira_vez
7. Enviar ao Gemini
8. Salvar resposta da IA no banco (role: "assistant")
9. Retornar resposta ao frontend

**1.5 — Modificar _build_system_instruction()**
Adicionar parâmetro primeira_vez: bool

Se primeira_vez=True:
"É a primeira vez que este usuário usa o Assistente. Apresente-se como Assistente Hivvo, explique brevemente o que você pode fazer (análise de gastos, parcelas, comparações, planejamento) e convide o usuário a fazer sua primeira pergunta. Seja caloroso mas conciso."

Se primeira_vez=False:
"Este usuário já usou o Assistente anteriormente. Não se apresente. Cumprimente brevemente apenas se o usuário cumprimentar. Vá direto ao ponto."

### FASE 2 — Frontend (hivvo-web)

**2.1 — Modificar serviço ai.ts**
- Adicionar getHistorico() → GET /ai/historico
- Adicionar clearHistorico() → DELETE /ai/historico
- Modificar sendMessage() → remover parâmetro historico do payload

**2.2 — Modificar AssistantPage.tsx**

Ao montar o componente:
1. Chamar getHistorico()
2. Se retornar mensagens → popular estado messages com histórico
3. Se retornar vazio → UI limpa

Ao enviar mensagem:
1. Adicionar mensagem ao estado local imediatamente
2. Chamar sendMessage() sem passar histórico
3. Adicionar resposta ao estado local

Botão "Nova conversa":
1. Modal de confirmação: "Deseja iniciar uma nova conversa? O histórico será apagado."
2. Confirmar → clearHistorico() + reset do estado messages para []

**2.3 — Botão "Nova conversa"**
- Posição: canto superior direito da área de chat
- Estilo: discreto, ícone de lápis ou texto pequeno

### FASE 3 — Testes (7 cenários obrigatórios)
1. Primeiro acesso — enviar "Oi" → IA se apresenta
2. Segundo acesso — enviar "Boa tarde" → IA cumprimenta sem apresentação
3. Navegar para outra tela e voltar em menos de 24h → histórico visível
4. Simular 24h (alterar created_at no banco) → UI limpa, IA com contexto
5. Perguntar algo referenciando conversa anterior com UI limpa → IA responde com contexto
6. Clicar "Nova conversa" e confirmar → UI limpa, IA sem contexto anterior
7. Primeiro acesso após "Nova conversa" → IA se apresenta novamente

### Ordem de execução
1. hivvo-api — Fase 1 completa
2. Validar endpoints manualmente
3. hivvo-web — Fase 2 completa
4. Fase 3 — testes dos 7 cenários

---

## Revisão da arquitetura — Sessões de chat

A implementação original usava filtro de 24h direto na query. A arquitetura foi revisada para usar o conceito de sessão.

### Mudança no banco
- Adicionar coluna `sessao_id` (UUID, nullable) na tabela `chat_messages`
- Gerar nova migration Alembic

### Comportamento de sessão
- Cada "Nova conversa" gera um novo `sessao_id` no frontend e o envia nas próximas mensagens
- `GET /ai/historico` retorna apenas mensagens da sessão mais recente do usuário
  - Se a última mensagem da sessão mais recente tiver **mais de 24h** → retorna vazio (UI limpa, nova sessão automática)
  - Se tiver **menos de 24h** → retorna mensagens da sessão (UI mostra conversa)
- `POST /ai/chat` recebe `sessao_id` no body e salva em cada mensagem
- A IA sempre recebe as últimas 50 mensagens do banco (todas as sessões) como contexto invisível

### Comportamento na prática
- Volta em menos de 24h → UI mostra sessão mais recente
- Volta após mais de 24h → UI limpa, nova sessão automática
- Clica "Nova conversa" → UI limpa, novo `sessao_id` gerado no frontend

### Impacto nas Fases
- **Fase 1 (backend):** migration para adicionar `sessao_id`; ajustar `GET /ai/historico` (busca por sessão mais recente + cheque de 24h); ajustar `POST /ai/chat` (recebe e persiste `sessao_id`)
- **Fase 2 (frontend):** `sendMessage()` passa `sessao_id`; geração de novo UUID em "Nova conversa" em vez de chamar `DELETE /ai/historico`
- `DELETE /ai/historico` pode ser mantido para uso administrativo/futuro

---

## Melhorias de UI/UX — Sessão de 01/06/2026 ✅

| # | Melhoria | Commit | Arquivos |
|---|---|---|---|
| #1 | Labels na sidebar desktop | (histórico) | `DesktopLayout.tsx` |
| #2 | Skeleton loading em Transações e Cartões | (histórico) | `TransactionsPage.tsx`, `CardsPage.tsx` |
| #3 | Importar CSV acessível pela navegação | (histórico) | `SettingsPage.tsx`, layouts |
| #4 | Widget de compromissos futuros no Dashboard | (histórico) | `DashboardPage.tsx`, `useInstallments.ts` |
| #5 | Badge de parcela inline nas transações | `6d582fa` | `TransactionItem.tsx`, `services/transactions.ts` |
| #6 | Acesso a Configurações via avatar — gear badge mobile | `96809d3` | `MobileLayout.tsx` |
| #7 | Total R$ 0,00 em vermelho nos cartões | `56b334e` | `InvoiceDetail.tsx` |
| #8 | Termos e Privacidade acessíveis dentro do app | `035dc5f` | `SettingsPage.tsx` |
| #9 | Barra de limite usado/disponível no card | `36b117a` | `CardVisual.tsx`, `services/cards.ts` |
| #10 | Onboarding progressivo pós-cadastro | `1994d61` | `OnboardingBanner.tsx`, `DashboardPage.tsx` |

### Detalhes das melhorias #5–#10

**#5 — Badge de parcela inline:**
- `total_parcelas: number | null` adicionado ao tipo `Transaction` (backend já retornava)
- `TransactionItem` substituiu `· Parcelado` por badge pill âmbar `{total_parcelas}x`
- `InvoiceDetail` já tinha badge X/Y correto — sem alteração

**#6 — Acesso a Configurações:**
- Desktop: já tinha `title="Configurações"` e label "Config." — sem alteração
- Mobile: badge `⚙` sobreposto no canto inferior-direito do avatar (absolute, 14×14px)

**#7 — Cor do total de fatura:**
- `total > 0 → text-danger`, `total === 0 → text-text-muted`
- `parseFloat(detail.total) > 0` como condição

**#8 — Legal em Configurações:**
- Seção "LEGAL" no final de `SettingsPage` com links para `/terms` e `/privacy`
- Rotas já estavam fora do `ProtectedRoute` em `App.tsx`

**#9 — Barra de limite:**
- `fatura_aberta_total: string | null` adicionado ao tipo `Card`
- Barra `h-1`, track `bg-bg/20`, fill `bg-bg/60`, texto `R$ X usado · R$ Y disponível`
- `GET /cards` já retornava `fatura_aberta_total` via `CartaoComFaturaResponse`

**#10 — Onboarding:**
- `OnboardingBanner` auto-contido: 3 steps com botões de ação, dismissal em `localStorage`
- Condição: `!isLoading && transactions.length === 0 && cards.length === 0`
- Renderizado acima do `EmptyState` em mobile e desktop

---

## Decisões Fixas (não discutir)

- **Backend:** FastAPI + SQLModel + PostgreSQL (Supabase)
- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **Estado:** Zustand (UI) + TanStack Query (servidor)
- **Roteamento:** React Router v6
- **Gráficos:** Recharts
- **PWA:** Vite PWA Plugin — instalável, ícones gerados (192×192 e 512×512)
- **Deploy backend:** Railway ou Render (free tier)
- **Deploy frontend:** Vercel
- **Autenticação:** JWT (httpOnly cookie)
- **Tema:** Escuro por padrão (#1A1714)
- **Cor primária:** Âmbar (#EF9F27)

---

## Ordem de Implementação

- [x] 1. Estrutura FastAPI + conexão Supabase + health check
- [x] 2. Migrar models.py + migrations Alembic
- [x] 3. Endpoints de auth (registro + login + JWT)
- [x] 4. Endpoints de transações e categorias
- [x] 5. Endpoints de cartões e faturas
- [x] 6. Endpoints de parcelas
- [x] 7. Endpoints de estatísticas
- [x] 8. Endpoint de IA (proxy Gemini)
- [x] 9. Setup React + Vite + Tailwind + PWA + layouts
- [x] 10. Login + Cadastro (frontend)
- [x] 11. Dashboard (frontend)
- [x] 12. Transações (frontend)
- [x] 13. Adicionar transação com parcelamento (frontend)
- [x] 14. Cartões e faturas (frontend)
- [x] 15. Assistente IA (frontend)
- [x] 16. Ver resumo detalhado (frontend)
- [x] 17. Features secundárias (CSV, backup, categorias, perfil)
- [x] 18. Testes end-to-end Blocos 1–5 + correção de bugs críticos
- [x] 19. Recuperação de senha — frontend (`/forgot-password`, `/reset-password`) + backend (`/auth/forgot-password`, `/auth/reset-password`)
- [x] 20. UX: confirmação de logout (modal) + toggle de visibilidade de senha em todos os campos
- [x] 21. Bug #6 — "Ver Resumo" mais visível (chip mobile + botão desktop)
- [x] 22. Bug #7 — encoding UTF-8 no backend (`charset=utf-8` no Content-Type)
- [x] 23. Refresh token — interceptor Axios com retry automático + `refreshToken()` em `auth.ts`
- [x] 24. Renomeação BeeFree → Hivvo (brand, layouts, títulos, manifest, PWA)
- [x] 25. Termos de Uso (`/terms`) e Política de Privacidade (`/privacy`) — páginas estáticas em `AuthLayout`
- [x] 26. Sessão de UI/UX — melhorias #1 a #10 implementadas e commitadas
- [ ] 27. Deploy — backend Railway/Render + frontend Vercel + domínio hivvo.app
- [x] 28. Assistente IA com persistência e memória — tabela chat_messages + endpoints GET/DELETE /ai/historico + modificar POST /ai/chat + frontend (getHistorico, clearHistorico, botão "Nova conversa")

---

## Decisões Técnicas Tomadas

| Decisão | Detalhes |
|---|---|
| `passlib` removido | Incompatível com `bcrypt >= 4.0`. Usando `bcrypt` diretamente. |
| `fatura_mes`/`fatura_ano` | Derivados da `data_vencimento` da parcela, não da data da compra. |
| Routers sem trailing slash | Endpoints raiz usam `""` em vez de `"/"` para evitar redirect 307. |
| Soft delete em categorias | `ativa=False` em vez de DELETE para preservar histórico de transações. |
| Parcelamento sem cartão | Usa intervalos mensais simples a partir da data da compra. |
| Arredondamento de parcelas | Última parcela absorve diferença de arredondamento (`ROUND_HALF_UP`). |
| Zod v4 coerce + RHF | `z.coerce.number()` com `.refine()` requer cast `as Resolver<z.infer<typeof schema>>` no zodResolver. |
| Recharts Tooltip formatter | Parâmetros tipados como `unknown` com cast interno — `ValueType`/`NameType` são uniões que incluem `undefined`. |
| Input.showToggle | Estado local `visible` encapsulado no componente — não vaza para o formulário. `tabIndex={-1}` no botão do olho para não interferir no tab order. |
| Button.variant danger | `border border-danger text-danger hover:bg-danger/5` — usado no modal de confirmação de logout. |
| UTF-8 encoding backend | `UTF8JSONResponse` subclasse com `media_type = "application/json; charset=utf-8"` como `default_response_class` — elimina Mojibake em browsers que não assumem UTF-8 sem charset explícito. |
| Refresh token — interceptor | `isRefreshing` + `failedQueue` serializam 401s paralelos; falha no refresh faz `clearAuth()` + `window.location.href = '/login'`; dependência circular evitada chamando `api.post('/auth/refresh')` inline. |
| import type Axios | `AxiosRequestConfig` importado com `import type` — `InternalAxiosRequestConfig` não disponível na versão instalada (Axios 1.16.1). |
| OnboardingBanner dismiss | Estado lazy `() => localStorage.getItem(STORAGE_KEY) === '1'` — sem flash de re-render. Chave: `hivvo_onboarding_dismissed`. |
| Vírgula decimal em `valor` | `field_validator(mode="before")` em `TransacaoCreate` e `TransacaoUpdate` normaliza `"150,00"` → `"150.00"` antes da coerção do Pydantic para `Decimal`. |
| `username` auto-gerado | Removido do `RegisterRequest`; gerado via `_generate_username(email, session)` — prefixo do email, não-alfanuméricos viram `_`, sufixo `_2`/`_3` garante unicidade. Banco e `UpdateMeRequest` inalterados — usuário pode ajustar em Configurações. |
| Badge parcela inline | `total_parcelas` já era retornado pelo backend mas não declarado no tipo TS — sem backend change. `numero_parcela` ausente em `transacoes`; badge mostra `Nx` em vez de `X/Y` (X seria sempre 1 no filtro por data de compra). |
| Barra de limite CardVisual | `fatura_aberta_total` de `CartaoComFaturaResponse` já disponível — só faltava declarar no tipo `Card` do frontend. Guard `limite > 0` evita divisão por zero. |

---

## Arquivos Criados/Modificados por Tarefa

### Melhorias UI/UX #5–#10 (01/06/2026)
- `src/services/transactions.ts` — `total_parcelas: number | null` no tipo `Transaction`
- `src/components/transaction/TransactionItem.tsx` — badge pill âmbar `{total_parcelas}x`
- `src/layouts/MobileLayout.tsx` — badge `⚙` sobreposto ao avatar de Configurações
- `src/components/cards/InvoiceDetail.tsx` — cor condicional do total (`text-danger` / `text-text-muted`)
- `src/pages/Settings/SettingsPage.tsx` — seção "LEGAL" com links para `/terms` e `/privacy`
- `src/services/cards.ts` — `fatura_aberta_total: string | null` no tipo `Card`
- `src/components/cards/CardVisual.tsx` — barra de progresso uso/disponível do limite
- `src/components/ui/OnboardingBanner.tsx` — novo componente (3 passos, dismissal localStorage)
- `src/pages/Dashboard/DashboardPage.tsx` — `useCards()` + `showOnboarding` + `OnboardingBanner`

### Tarefas #23 — Refresh token (interceptor Axios)
- `src/services/auth.ts` — `refreshToken()` exportado chamando `POST /auth/refresh`
- `src/services/api.ts` — interceptor 401 reescrito: `isRefreshing` + `failedQueue` + retry da request original; redirect `/login` em caso de falha no refresh

### Tarefas #24–#25 — Renomeação + páginas legais
- Renomeação BeeFree → Hivvo em todos os layouts, títulos, manifest e PWA
- `src/pages/Legal/TermsPage.tsx` — Termos de Uso (rota `/terms`)
- `src/pages/Legal/PrivacyPage.tsx` — Política de Privacidade (rota `/privacy`)
- `src/App.tsx` — rotas `/terms` e `/privacy` dentro do `AuthLayout`, fora do `ProtectedRoute`

### Tarefas #21–#22 — Bugs #6 e #7 (UX + encoding)
- `src/pages/Transactions/TransactionsPage.tsx` — chip "Resumo" âmbar na barra de filtros mobile; botão com borda âmbar no topbar desktop; `ChartBarIcon` SVG inline (Bug #6)
- `hivvo-api/main.py` — `UTF8JSONResponse` como `default_response_class` (Bug #7)

### Tarefa #20 — Confirmação de logout + toggle de visibilidade de senha
- `src/components/ui/Button.tsx` — variante `danger` adicionada
- `src/components/ui/Input.tsx` — prop `showToggle` com estado local `visible`, botão com ícones SVG `EyeIcon`/`EyeOffIcon`, `pr-10` no input, `tabIndex={-1}` no botão
- `src/pages/Auth/LoginPage.tsx` — `showToggle` no campo `password`
- `src/pages/Auth/RegisterPage.tsx` — `showToggle` nos campos `password` e `confirmPassword`
- `src/pages/Auth/ResetPasswordPage.tsx` — `showToggle` nos campos `nova_senha` e `confirmar_senha`
- `src/pages/Settings/SettingsPage.tsx` — modal de confirmação de logout (`logoutModalOpen`, `Button variant="danger"`); `showToggle` nos campos `senha_atual`, `nova_senha`, `confirmar`

### Tarefa #19 — Recuperação de senha (frontend)
- `src/services/auth.ts` — `forgotPassword(email)`, `resetPassword(token, nova_senha)`
- `src/pages/Auth/ForgotPasswordPage.tsx` — nova página; estado `submitted` — mensagem genérica independente do resultado da API
- `src/pages/Auth/ResetPasswordPage.tsx` — nova página; lê `token` via `useSearchParams`; redireciona para `/login` se ausente; `status: 'idle' | 'success' | 'error'`
- `src/pages/Auth/LoginPage.tsx` — link "Esqueceu a senha?" abaixo do botão Entrar
- `src/App.tsx` — rotas `/forgot-password` e `/reset-password` dentro do `AuthLayout`, fora do `ProtectedRoute`

### Tarefa #18 — Testes e correções de bugs (Blocos 1–5)
- `src/pages/Settings/SettingsPage.tsx` — guarda `deletingId !== null` na confirmação de remoção de categorias
- `src/components/cards/CardFormModal.tsx` — Zod v4: `.refine()` substituindo `invalid_type_error`; cast do zodResolver; import `Resolver`
- `src/components/transaction/EditTransactionModal.tsx` — idem
- `src/pages/AddTransaction/AddTransactionPage.tsx` — idem
- `src/components/charts/BarChart.tsx` — formatter `(value: unknown, name: unknown)` com cast interno
- `src/components/charts/DonutChart.tsx` — idem
- `public/icon-192.png` — ícone PWA 192×192 (fundo âmbar, letra B off-white)
- `public/icon-512.png` — ícone PWA 512×512 (fundo âmbar, letra B off-white)

### Tarefa #17 — Features Secundárias (frontend)
- `src/pages/Import/ImportPage.tsx` — upload CSV com drag-and-drop, parse client-side, preview com validação, importação sequencial
- `src/pages/Settings/SettingsPage.tsx` — /settings com Perfil, Categorias customizadas e Exportar dados
- `src/services/auth.ts` — `updateMe(username)`, `changePassword(senha_atual, nova_senha)`
- `src/services/categories.ts` — `createCategory(nome)`, `deleteCategory(id)`; `usuario_id: number | null`
- `src/services/transactions.ts` — `getAllTransactions()` sem filtro de mês para backup
- `src/hooks/useCategories.ts` — `useCreateCategory`, `useDeleteCategory`
- `src/layouts/MobileLayout.tsx`, `DesktopLayout.tsx` — botão de perfil navega para /settings
- `src/App.tsx` — rotas `/import` e `/settings` adicionadas

### Tarefa #16 — Ver Resumo Detalhado (frontend)
- `src/services/statistics.ts` — `getYearlyStats(ano)`, `getCategoryStats({ mes?, ano })`
- `src/services/installments.ts` — novo
- `src/hooks/useStatistics.ts` — `useYearlyStats`, `useCategoryStats`, `useQuarterlyStats`
- `src/hooks/useInstallments.ts` — novo
- `src/components/charts/BarChart.tsx` — novo
- `src/pages/Transactions/SummaryPage.tsx` — página completa com toggle Mês/Trimestre/Ano

### Tarefa #15 — Assistente IA (frontend)
- `src/services/ai.ts` — `sendMessage(mensagem, mes, ano)` como base; `suggestCategory` reutiliza
- `src/pages/Assistant/AssistantPage.tsx` — chat completo com TypingIndicator, MessageBubble, StatsPanel (desktop)

### Tarefa #14 — Cartões e faturas (frontend)
- `src/services/cards.ts` — tipos e funções de cartões/faturas
- `src/hooks/useCards.ts` — mutations e queries de cartões/faturas
- `src/components/cards/` — CardVisual, CardFormModal, InvoiceMonthGrid, InvoiceDetail
- `src/pages/Cards/CardsPage.tsx` — página completa mobile/desktop

### Tarefa #13 — Adicionar transação com parcelamento (frontend)
- `src/pages/AddTransaction/AddTransactionPage.tsx` — form completo com parcelamento, sugestão IA, ImpactPreview

### Tarefa #12 — Transações (frontend)
- `src/components/transaction/` — TransactionItem, TransactionGroup, EditTransactionModal, DeleteConfirmModal
- `src/pages/Transactions/TransactionsPage.tsx` — filtros, busca, agrupamento por data

### Tarefa #11 — Dashboard (frontend)
- `src/components/charts/DonutChart.tsx` — novo
- `src/pages/Dashboard/DashboardPage.tsx` — métricas, DonutChart, últimas transações, empty state

### Tarefa #10 — Login + Cadastro (frontend)
- `src/components/ui/Button.tsx`, `Input.tsx`, `Spinner.tsx`
- `src/pages/Auth/LoginPage.tsx`, `RegisterPage.tsx`

### Tarefas #1–#9 — Backend completo + Setup Frontend
- Backend FastAPI: auth, transações, categorias, cartões, faturas, parcelas, estatísticas, IA
- Frontend setup: Vite + Tailwind + PWA + layouts + Zustand + TanStack Query

---

## Estrutura de Pastas Atual (Frontend)

```
hivvo-web/
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── public/
│   ├── manifest.json        ✓
│   ├── icon-192.png         ✓  (gerado — fundo âmbar, letra B)
│   └── icon-512.png         ✓  (gerado — fundo âmbar, letra B)
└── src/
    ├── layouts/             DesktopLayout, MobileLayout, AuthLayout  ✓
    ├── pages/               Dashboard, Transactions/Summary, AddTransaction, Cards, Assistant, Auth (Login, Register, ForgotPassword, ResetPassword), Settings, Import, Legal (Terms, Privacy)  ✓
    ├── components/          ui/ (Button, Input, Modal, Spinner, Toast, OnboardingBanner), charts/, transaction/, cards/  ✓
    ├── hooks/               useBreakpoint, useTransactions, useCategories, useStatistics, useCards, useAuth, useInstallments  ✓
    ├── store/               authStore, uiStore  ✓
    ├── services/            api, auth, transactions, categories, cards, ai, statistics, installments  ✓
    └── styles/              tokens.css  ✓
```

---

## Regras de Trabalho

1. **Uma tarefa por vez** — não avançar sem confirmação
2. **Sempre rodar testes** antes de marcar tarefa como concluída
3. **Nunca hardcodar cores** — usar sempre os tokens do brand guide
4. **Nunca misturar** TanStack Query com Zustand
5. **Layouts distintos** — MobileLayout e DesktopLayout, nunca CSS responsivo puro
6. **Valores monetários** — sempre Decimal no Python, toFixed(2) no JS
7. **JWT** — nunca em localStorage, apenas httpOnly cookie ou memória

---

*Última atualização: 09 de Junho de 2026 — Assistente IA com persistência e memória concluído: `chat_messages`, sessões, histórico 24h, salvar user+assistant atomicamente, retry Gemini 5x backoff linear. Pendente validação de UX. Próximo: melhorias UX Fase 3.*  
*Projeto: Hivvo — gestão financeira pessoal com IA*  
*Repositório FinanceAI original: github.com/lucasdonnangelo/financeai*
