# BeeFree — Sessão Atual

## Antes de começar
Leia o arquivo `docs/BeeFree_Referencia.docx` para entender o produto, a arquitetura e as decisões de stack. Não proponha alternativas de tecnologia — as escolhas já foram feitas.

---

## Estado do Projeto

**Fase atual:** Fase 1 — Backend FastAPI + Supabase  
**Próxima tarefa:** #1 — Estrutura FastAPI + conexão Supabase  
**Última tarefa concluída:** Nenhuma (início do projeto)

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

## O que Reaproveitar do FinanceAI

| Arquivo | Ação |
|---|---|
| `models.py` | Copiar integralmente — SQLModel funciona com PostgreSQL |
| `repositories.py` | Copiar integralmente — já desacoplado da UI |
| `logic.py` | Copiar integralmente — lógica de negócio pura |
| `agent.py` | Adaptar — manter lógica Gemini, trocar interface para HTTP |
| `auth.py` | Adaptar — manter bcrypt, adicionar JWT |
| `pages/` + `components/` | Ignorar — Streamlit será descartado |

---

## Ordem de Implementação

- [ ] 1. Estrutura FastAPI + conexão Supabase + health check
- [ ] 2. Migrar models.py + migrations Alembic
- [ ] 3. Endpoints de auth (registro + login + JWT)
- [ ] 4. Endpoints de transações e categorias
- [ ] 5. Endpoints de cartões e faturas
- [ ] 6. Endpoints de parcelas
- [ ] 7. Endpoints de estatísticas
- [ ] 8. Endpoint de IA (proxy Gemini)
- [ ] 9. Setup React + Vite + Tailwind + PWA + layouts
- [ ] 10. Login + Cadastro (frontend)
- [ ] 11. Dashboard (frontend)
- [ ] 12. Transações (frontend)
- [ ] 13. Adicionar transação com parcelamento (frontend)
- [ ] 14. Cartões e faturas (frontend)
- [ ] 15. Assistente IA (frontend)
- [ ] 16. Ver resumo detalhado (frontend)
- [ ] 17. Features secundárias (CSV, backup, categorias, perfil)

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

## Estrutura de Pastas Esperada (Backend)

```
beefree-api/
├── main.py
├── .env
├── requirements.txt
├── alembic/
├── app/
│   ├── models/
│   ├── repositories/
│   ├── services/
│   ├── routers/
│   ├── schemas/
│   └── core/
│       ├── auth.py
│       ├── database.py
│       └── config.py
```

---

## Estrutura de Pastas Esperada (Frontend)

```
beefree-web/
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── public/
│   └── manifest.json
└── src/
    ├── layouts/
    │   ├── DesktopLayout.tsx
    │   ├── MobileLayout.tsx
    │   └── AuthLayout.tsx
    ├── pages/
    ├── components/
    │   └── ui/
    ├── hooks/
    │   └── useBreakpoint.ts
    ├── store/
    │   ├── authStore.ts
    │   └── uiStore.ts
    ├── services/
    │   └── api.ts
    └── styles/
        └── tokens.css
```

---

## Notas da Sessão Atual

_(atualizar conforme o trabalho avança)_

---

*Documento criado em: Maio 2026*  
*Projeto: BeeFree — gestão financeira pessoal com IA*  
*Repositório FinanceAI original: github.com/lucasdonnangelo/financeai*
