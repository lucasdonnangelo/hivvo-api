# BeeFree — Sessão Atual

## Antes de começar
Leia os arquivos `docs/BeeFree_Referencia.md` e `docs/SESSAO_ATUAL.md` para entender o produto, a arquitetura e as decisões de stack. Não proponha alternativas de tecnologia — as escolhas já foram feitas.

---

## Estado do Projeto

**Fase atual:** Fase 4 — Monetização e Lançamento  
**Próxima tarefa:** Definir limites do plano gratuito + integrar Stripe/Pagar.me  
**Última tarefa concluída:** Fase 3 completa — todas as 17 tarefas implementadas

---

## Decisões Fixas (não discutir)

- **Backend:** FastAPI + SQLModel + PostgreSQL (Supabase)
- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **Estado:** Zustand (UI) + TanStack Query (servidor)
- **Roteamento:** React Router v6
- **Gráficos:** Recharts
- **PWA:** Vite PWA Plugin
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

### Fase 4 — Monetização e Lançamento

- [ ] Definir limites do plano gratuito (ex: até 3 cartões, 100 transações/mês)
- [ ] Integrar Stripe ou Pagar.me para plano Pro
- [ ] Gate de features por plano no backend
- [ ] Landing page do BeeFree
- [ ] Domínio próprio (beefree.app ou similar)
- [ ] Post LinkedIn + Product Hunt
- [ ] Analytics com Posthog (gratuito)

---

## Testes de Integração (Fase 4)

### Bloco 1 — Autenticação ✅ Concluído
- POST /auth/register
- POST /auth/login
- GET /auth/me
- PUT /auth/me
- PUT /auth/password
- POST /auth/logout

### Bloco 2 — Dashboard e Transações ✅ Concluído (com bugs corrigidos)
- GET /statistics/monthly
- GET /statistics/yearly
- GET /statistics/categories
- GET /transactions
- POST /transactions (simples e parcelada)
- PUT /transactions/{id}
- DELETE /transactions/{id}
- GET /categories
- POST /categories
- DELETE /categories/{id}

### Bloco 3 — Cartões, Faturas e Parcelas ⏳ Próximo
- GET /cards
- POST /cards
- PUT /cards/{id}
- DELETE /cards/{id}
- GET /cards/{id}/invoices
- GET /cards/{id}/invoices/{ano}/{mes}
- GET /installments
- PUT /installments/{id}
- DELETE /installments/{id}

### Bloco 4 — IA ⏳ Pendente
- POST /ai/chat

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

---

## Arquivos Criados/Modificados por Tarefa

### Tarefa #1 — Estrutura base
- `main.py` — FastAPI app, CORS, routers, GET /health
- `app/core/config.py` — Settings via pydantic-settings
- `app/core/database.py` — engine + get_session
- `requirements.txt` — dependências

### Tarefa #2 — Models + Alembic
- `app/models/user.py` — Usuario (email, username, senha_hash, rate limiting)
- `app/models/card.py` — Cartao (dia_vencimento, dia_fechamento, mes_offset_vencimento)
- `app/models/transaction.py` — Transacao (tipo receita/despesa, usuario_id FK)
- `app/models/category.py` — CategoriaCustomizada
- `app/models/installment.py` — Parcela (FK transacao + cartao + usuario)
- `alembic/env.py`, `alembic.ini`, `alembic/script.py.mako`
- Migration: `abdb546095c0_initial_schema.py` — aplicada no Supabase

### Tarefa #3 — Auth
- `app/core/auth.py` — hash_password, verify_password (bcrypt direto), create_access_token, get_current_user
- `app/schemas/auth.py` — RegisterRequest, LoginRequest, UserResponse
- `app/routers/auth.py` — POST /register, POST /login, POST /logout, GET /me

### Tarefa #3 Extra — Edição de perfil (commit 3789cb6)
- `app/schemas/auth.py` — UpdateMeRequest, ChangePasswordRequest
- `app/routers/auth.py` — PUT /auth/me (atualiza username), PUT /auth/password (troca senha)

### Tarefa #4 — Transações e Categorias
- `app/schemas/transaction.py` — TransacaoCreate, TransacaoUpdate, TransacaoResponse, TransacaoCreateResponse
- `app/schemas/category.py` — CategoriaCreate, CategoriaResponse
- `app/routers/transactions.py` — GET/POST/PUT/DELETE + lógica de parcelamento
- `app/routers/categories.py` — GET/POST/DELETE + 15 categorias padrão hardcoded

### Tarefa #5 — Cartões e Faturas
- `app/schemas/card.py` — CartaoCreate, CartaoUpdate, CartaoResponse, CartaoComFaturaResponse
- `app/schemas/invoice.py` — ParcelaFaturaResponse, TransacaoFaturaResponse, FaturaListItem, FaturaDetalhe
- `app/routers/cards.py` — GET/POST/PUT/DELETE + fatura aberta calculada em tempo real
- `app/routers/invoices.py` — GET /{card_id}/invoices (lista), GET /{card_id}/invoices/{ano}/{mes} (detalhe)

### Tarefa #6 — Parcelas
- `app/schemas/installment.py` — ParcelaUpdate, ParcelaResponse
- `app/routers/installments.py` — GET (filtros: cartao_id, pago, cancelado, mes, ano), PUT (marcar paga/cancelar), DELETE (individual)

### Tarefa #7 — Estatísticas
- `app/schemas/statistics.py` — CategoriaStats, MensalResponse, MesEvolucao, AnualResponse, CategoriasResponse
- `app/routers/statistics.py` — GET /statistics/monthly, GET /statistics/yearly, GET /statistics/categories

### Tarefa #8 — IA (proxy Gemini)
- `app/schemas/ai.py` — ChatRequest (mensagem, mes, ano), ChatResponse (resposta)
- `app/routers/ai.py` — POST /ai/chat: contexto financeiro injetado no prompt, chama Gemini via google-genai

### Tarefa #9 — Setup Frontend (beefree-web/)
- `vite.config.ts` — PWA plugin configurado com manifest BeeFree
- `tailwind.config.ts` — tokens de cor/tipografia do brand guide
- `index.html` — Inter font, lang=pt-BR, theme-color=#1A1714
- `src/main.tsx` — QueryClientProvider + BrowserRouter + StrictMode
- `src/App.tsx` — React Router v6: AppLayout escolhe Mobile vs Desktop via useBreakpoint
- `src/layouts/MobileLayout.tsx`, `DesktopLayout.tsx`, `AuthLayout.tsx`
- `src/hooks/useBreakpoint.ts`, `useAuth.ts`, `useTransactions.ts` (stub)
- `src/store/authStore.ts`, `uiStore.ts`
- `src/services/api.ts`, `auth.ts`, `transactions.ts`, `cards.ts`

### Tarefas #10–#17 — Frontend completo
- Todas as telas implementadas: Auth, Dashboard, Transações, AddTransaction, Cartões, Faturas, Assistente IA, Resumo Detalhado
- Features secundárias: importação CSV, backup JSON/CSV, gerenciar categorias, configurações de perfil

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

*Última atualização: 29 de Maio de 2026 — Testes Bloco 1 e Bloco 2 concluídos. Próximo: Bloco 3 (Cartões, Faturas e Parcelas)*  
*Projeto: BeeFree — gestão financeira pessoal com IA*  
*Repositório FinanceAI original: github.com/lucasdonnangelo/financeai*
