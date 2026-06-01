# Hivvo — Sessão Atual

## Antes de começar
Leia os arquivos `docs/Hivvo_Referencia.md` e `docs/SESSAO_ATUAL.md` para entender o produto, a arquitetura e as decisões de stack. Não proponha alternativas de tecnologia — as escolhas já foram feitas.

---

## Estado do Projeto

**Fase atual:** Pronto para deploy  
**Status:** Features de autenticação completas — recuperação de senha ✅, refresh token ✅, todos os bugs #1–#7 corrigidos ✅. Backend totalmente funcional e testado.  
**Próximo passo imediato:** Sessão de UI/UX (ajustes visuais e de experiência antes do deploy)  
**Próxima fase:** Deploy — backend no Railway/Render, frontend no Vercel  
**Última tarefa concluída:** Refresh token — tabela `refresh_tokens`, rotação obrigatória, cookies httpOnly, `access_token` 30 min

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
| `d9270ae` | `main.py` | Mojibake nas respostas JSON (`vocÃª`, `receberÃ¡`) — bytes UTF-8 lidos como latin-1 | `UTF8JSONResponse` com `charset=utf-8` como `default_response_class` |

---

## Próximos Passos

### Sessão de UI/UX (próxima etapa)
- Revisão visual das telas existentes
- Ajustes de espaçamento, tipografia e micro-interações
- Consistência de estados vazios, loading e erro em todas as telas
- Revisar fluxo mobile vs desktop

### Deploy
- **Backend — Railway ou Render (free tier):**
  - Criar serviço apontando para o repositório `hivvo-api`
  - Configurar variáveis de ambiente: `DATABASE_URL`, `SECRET_KEY`, `GEMINI_API_KEY`, `RESEND_API_KEY`, `FRONTEND_URL`
  - Rodar migration `alembic upgrade head` no ambiente de produção
  - Verificar health check em `GET /health`
  - Anotar a URL pública gerada (ex: `https://hivvo-api.railway.app`)
- **Frontend — Vercel:**
  - Criar projeto apontando para `hivvo-web`
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
- [x] Extra: `PUT /auth/me` + `PUT /auth/password` (commit `3789cb6`)

### Fase 2 — Frontend React PWA (base) ✅ Completa

- [x] 9. Setup React + Vite + Tailwind + PWA + layouts

### Fase 3 — Telas Restantes ✅ Completa

- [x] 10–17. Todas as telas frontend (Login, Dashboard, Transações, Cartões, IA, Resumo, CSV, Settings)

### Testes e Refinamentos ✅ Concluídos (Blocos 1–5)

- [x] 18. Testes end-to-end Blocos 1–5 + correção de todos os bugs críticos

### Features de autenticação ✅ Completa

- [x] 19. Recuperação de senha — `POST /auth/forgot-password` + `POST /auth/reset-password` + Resend
- [x] 20. UX frontend: confirmação de logout + toggle de visibilidade de senha
- [x] 21. Bug #6 — "Ver Resumo" mais visível (chip mobile + botão desktop)
- [x] 22. Bug #7 — encoding UTF-8 (`charset=utf-8` no Content-Type de todas as respostas JSON)
- [x] 23. Refresh token — `POST /auth/refresh` + cookie `refresh_token` (7 dias) + tabela `refresh_tokens` + rotação

### Sessão de UI/UX (próxima)

- [ ] 24. Revisão visual e ajustes de UX em todas as telas

### Fase 4 — Deploy

- [ ] Publicar backend no Railway ou Render
- [ ] Publicar frontend no Vercel
- [ ] Configurar variáveis de ambiente de produção
- [ ] Verificar fluxo completo em produção

### Fase 5 — Monetização e Lançamento (pós-deploy)

- [ ] Definir limites do plano gratuito (ex: até 3 cartões, 100 transações/mês)
- [ ] Integrar Stripe ou Pagar.me para plano Pro
- [ ] Gate de features por plano no backend
- [ ] Landing page do Hivvo
- [ ] Domínio próprio (hivvo.app ou similar)
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
| UTF-8 encoding | `UTF8JSONResponse` com `media_type = "application/json; charset=utf-8"` como `default_response_class` — elimina Mojibake em browsers que não assumem UTF-8 sem charset explícito no Content-Type. |
| Token de reset de senha | JWT separado com `sub=user_id` e `purpose=reset`, expiração de 15 min — não confundir com o `access_token`. |
| Refresh token | UUID v4 armazenado na tabela `refresh_tokens`; rotação obrigatória a cada uso (token antigo revogado, novo criado). `access_token` reduzido para 30 min. Cookie `refresh_token` httpOnly, 7 dias. |

---

## Estrutura de Pastas Atual (Backend)

```
hivvo-api/
├── main.py              ✓  (UTF8JSONResponse como default_response_class)
├── .env
├── requirements.txt
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── abdb546095c0_initial_schema.py
│       ├── 268b08c02e0a_add_password_reset_tokens.py
│       └── 207ebc9ef981_add_refresh_tokens.py
└── app/
    ├── models/
    │   ├── user.py                  ✓
    │   ├── card.py                  ✓
    │   ├── transaction.py           ✓
    │   ├── category.py              ✓
    │   ├── installment.py           ✓
    │   ├── password_reset_token.py  ✓
    │   └── refresh_token.py         ✓
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
    │   ├── auth.py          ✓  (register, login, refresh, logout, me, password, forgot/reset-password)
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
        ├── auth.py          ✓  (create_refresh_token, rotate_refresh_token)
        ├── database.py      ✓
        └── config.py        ✓  (ACCESS_TOKEN_EXPIRE_MINUTES=30, REFRESH_TOKEN_EXPIRE_DAYS=7)
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

*Última atualização: 01 de Junho de 2026 — Features de autenticação completas (recuperação de senha + refresh token). Todos os bugs #1–#7 corrigidos. Próximo: sessão de UI/UX → deploy.*  
*Projeto: Hivvo — gestão financeira pessoal com IA*  
*Repositório FinanceAI original: github.com/lucasdonnangelo/financeai*
