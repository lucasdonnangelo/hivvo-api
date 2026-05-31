# BeeFree — Sessão Atual

## Antes de começar
Leia os arquivos `docs/BeeFree_Referencia.md` e `docs/SESSAO_ATUAL.md` para entender o produto, a arquitetura e as decisões de stack. Não proponha alternativas de tecnologia — as escolhas já foram feitas.

---

## Estado do Projeto

**Fase atual:** Novas features de autenticação  
**Status:** Recuperação de senha implementada e testada. Falta configurar RESEND_API_KEY no .env para testar envio real.  
**Próximo passo imediato:** (1) Configurar RESEND_API_KEY no .env e testar envio real; (2) Refresh token  
**Próxima fase:** Deploy — backend no Railway/Render, frontend no Vercel  
**Última tarefa concluída:** Recuperação de senha por e-mail — `POST /auth/forgot-password` + `POST /auth/reset-password` + tabela `password_reset_tokens`

---

## Testes de Integração — Estado Atual

| Bloco | Escopo | Status | Observações |
|---|---|---|---|
| Bloco 1 | Autenticação (register, login, me, update, password, logout) | ✅ Concluído | — |
| Bloco 2 | Dashboard e Transações (statistics, transactions CRUD, categories) | ✅ Concluído | 2 bugs corrigidos no frontend |
| Bloco 3 | Cartões, Faturas e Parcelas | ✅ Concluído | — |
| Bloco 4 | Assistente IA, Importar CSV, Backup, Configurações | ✅ Concluído | 1 bug corrigido em /settings |
| Bloco 5 | Build limpo, PWA instalável, qualidade de código | ✅ Concluído | 12 erros TS corrigidos, ícones PWA criados |

### Endpoints testados por bloco

**Bloco 1 — Autenticação**
- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`
- `PUT /auth/me`
- `PUT /auth/password`
- `POST /auth/logout`

**Bloco 2 — Dashboard e Transações**
- `GET /statistics/monthly`
- `GET /statistics/yearly`
- `GET /statistics/categories`
- `GET /transactions`, `POST /transactions` (simples e parcelada)
- `PUT /transactions/{id}`, `DELETE /transactions/{id}`
- `GET /categories`, `POST /categories`, `DELETE /categories/{id}`

**Bloco 3 — Cartões, Faturas e Parcelas**
- `GET /cards`, `POST /cards`, `PUT /cards/{id}`, `DELETE /cards/{id}`
- `GET /cards/{id}/invoices`
- `GET /cards/{id}/invoices/{ano}/{mes}`
- `GET /installments`, `PUT /installments/{id}`, `DELETE /installments/{id}`

**Bloco 4 — IA**
- `POST /ai/chat`

**Bloco 5 — Build e PWA (frontend)**
- Build TypeScript sem erros
- PWA instalável com ícones 192×192 e 512×512

### Bugs corrigidos durante testes

| Commit | Arquivo | Problema | Solução |
|---|---|---|---|
| `a66c92d` | `DonutChart.tsx:82` | `percentual.toFixed is not a function` — backend retorna string | `Number(item.percentual).toFixed(1)` |
| `a66c92d` | `AddTransactionPage.tsx:612` | Saldo estimado exibia `R$ NaN` — concatenação de string | `Number(stats.saldo)` na passagem para `ImpactPreview` |
| `fe3c8c9` | `SettingsPage.tsx:317` | Confirmação de remoção exibida para todas as categorias por padrão | `deletingId !== null &&` antes da comparação com `cat.id` |
| `07d476b` | `CardFormModal`, `EditTransactionModal`, `AddTransactionPage` | 12 erros TypeScript: Zod v4 + zodResolver + Recharts formatter | `.refine()`, cast `Resolver<z.infer<typeof schema>>`, `value: unknown` |
| `15798da` | `public/` | Ícones PWA `icon-192.png` e `icon-512.png` ausentes | Gerados via Pillow: fundo âmbar #EF9F27, letra B off-white centralizada |

---

## Próximos Passos

### Features de autenticação (etapa atual)

#### 1. Recuperação de senha por e-mail (Resend)
- **Dependência:** instalar SDK `resend` no Python; configurar `RESEND_API_KEY` no `.env`
- `POST /auth/forgot-password` — recebe `{ email }`, gera token JWT de curta duração (15 min), envia link `{FRONTEND_URL}/reset-password?token=...` via Resend
- `POST /auth/reset-password` — recebe `{ token, nova_senha }`, valida token, atualiza hash da senha no banco
- Token de reset: JWT separado com `sub=user_id` e `purpose=reset` (não é o access token)

#### 2. Refresh token
- **Login:** gerar dois tokens — `access_token` (15 min, httpOnly cookie) + `refresh_token` (30 dias, httpOnly cookie separado)
- `POST /auth/refresh` — lê cookie `refresh_token`, valida, retorna novo `access_token` (e renova `refresh_token` se < 7 dias para expirar)
- Revogar refresh token no logout

### Deploy (próxima etapa)
- **Backend — Railway ou Render (free tier):**
  - Criar serviço apontando para o repositório `beefree-api`
  - Configurar variáveis de ambiente: `DATABASE_URL`, `SECRET_KEY`, `GEMINI_API_KEY`
  - Apontar `DATABASE_URL` para o Supabase de produção
  - Verificar health check em `GET /health`
  - Anotar a URL pública gerada (ex: `https://beefree-api.railway.app`)
- **Frontend — Vercel:**
  - Criar projeto apontando para `beefree-web`
  - Configurar `VITE_API_URL` com a URL do backend em produção
  - Verificar PWA instalável no celular após deploy

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

### Fase 1 — Backend FastAPI ✅ Completa

- [x] 1. Estrutura FastAPI + conexão Supabase + health check
- [x] 2. Migrar models.py + migrations Alembic
- [x] 3. Endpoints de auth (registro + login + JWT)
- [x] 4. Endpoints de transações e categorias
- [x] 5. Endpoints de cartões e faturas
- [x] 6. Endpoints de parcelas
- [x] 7. Endpoints de estatísticas
- [x] 8. Endpoint de IA (proxy Gemini)
- [x] Extra: PUT /auth/me + PUT /auth/password (commit 3789cb6)

### Fase 2 — Frontend React PWA (base) ✅ Completa

- [x] 9. Setup React + Vite + Tailwind + PWA + layouts

### Fase 3 — Telas Restantes ✅ Completa

- [x] 10. Login + Cadastro (frontend)
- [x] 11. Dashboard (frontend)
- [x] 12. Transações (frontend)
- [x] 13. Adicionar transação com parcelamento (frontend)
- [x] 14. Cartões e faturas (frontend)
- [x] 15. Assistente IA (frontend)
- [x] 16. Ver resumo detalhado (frontend)
- [x] 17. Features secundárias (CSV, backup, categorias, perfil)

### Testes e Refinamentos ✅ Concluídos (Blocos 1–5)

- [x] 18. Testes end-to-end Blocos 1–5 + correção de todos os bugs críticos
- [x] 19. Build TypeScript limpo (zero erros)
- [x] 20. PWA com ícones gerados e instalável
- [x] 21. Bugs #1–#5 frontend corrigidos (Settings, categorias, emoji, empty state, toast)

### Features de autenticação (etapa atual)

- [x] 22. Recuperação de senha por e-mail — endpoints `/auth/forgot-password` e `/auth/reset-password` + integração Resend
- [ ] 23. Refresh token — `POST /auth/refresh`, tokens de 15 min (access) + 30 dias (refresh)

### Fase 4 — Deploy

- [ ] Publicar backend no Railway ou Render
- [ ] Publicar frontend no Vercel
- [ ] Configurar variáveis de ambiente de produção
- [ ] Verificar fluxo completo em produção

### Fase 5 — Monetização e Lançamento (pós-deploy)

- [ ] Definir limites do plano gratuito (ex: até 3 cartões, 100 transações/mês)
- [ ] Integrar Stripe ou Pagar.me para plano Pro
- [ ] Gate de features por plano no backend
- [ ] Landing page do BeeFree
- [ ] Domínio próprio (beefree.app ou similar)
- [ ] Post LinkedIn + Product Hunt
- [ ] Analytics com Posthog (gratuito)

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

---

## Estrutura de Pastas Atual (Backend)

```
beefree-api/
├── main.py
├── .env
├── requirements.txt
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── abdb546095c0_initial_schema.py
└── app/
    ├── models/
    │   ├── user.py          ✓
    │   ├── card.py          ✓
    │   ├── transaction.py   ✓
    │   ├── category.py      ✓
    │   └── installment.py   ✓
    ├── schemas/
    │   ├── auth.py          ✓
    │   ├── transaction.py   ✓
    │   ├── category.py      ✓
    │   ├── card.py          ✓
    │   ├── invoice.py       ✓
    │   ├── installment.py   ✓
    │   ├── statistics.py    ✓
    │   └── ai.py            ✓
    ├── routers/
    │   ├── auth.py          ✓
    │   ├── transactions.py  ✓
    │   ├── categories.py    ✓
    │   ├── cards.py         ✓
    │   ├── invoices.py      ✓
    │   ├── installments.py  ✓
    │   ├── statistics.py    ✓
    │   └── ai.py            ✓
    ├── repositories/        — vazio
    ├── services/            — vazio
    └── core/
        ├── auth.py          ✓
        ├── database.py      ✓
        └── config.py        ✓
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

*Última atualização: 31 de Maio de 2026 — Bugs #1–#5 frontend corrigidos e commitados. Próximo: recuperação de senha via Resend + refresh token.*  
*Projeto: BeeFree — gestão financeira pessoal com IA*  
*Repositório FinanceAI original: github.com/lucasdonnangelo/financeai*
