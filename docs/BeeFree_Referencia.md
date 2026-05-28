# BeeFree — Documento de Referência do Produto

**Brand Guide | Arquitetura | Telas | Plano de Migração**  
Maio 2026 | Lucas Donnangelo

---

## 1. Visão do Produto

BeeFree é um aplicativo web de gestão financeira pessoal com IA, voltado exclusivamente para pessoa física. O nome carrega duplo sentido: "bee" (abelha, símbolo de organização e construção) + "be free" (liberdade financeira).

### Pilares

- Controle financeiro completo: transações, cartões, faturas e parcelamentos
- Inteligência artificial (Gemini) como diferencial de insights
- Experiência premium: design escuro, paleta âmbar, identidade única
- PWA — funciona como app sem passar pela App Store
- Desktop e mobile com layouts distintos e otimizados

### Público-alvo

- Pessoa física com renda média-alta e múltiplos cartões de crédito
- Usuários que precisam de controle real de parcelamentos
- Perfil que valoriza design e não tolera interfaces genéricas

### Diferenciais Competitivos

- **Parcelamento completo** — gestão por fatura, indicador 2/12 por transação
- **IA com contexto financeiro real** — não é chatbot genérico
- **Layout responsivo genuíno** — não é apenas CSS adaptativo
- **Detecção automática de assinaturas recorrentes**

---

## 2. Brand Guide

### Identidade

| Atributo | Valor |
|---|---|
| Nome | BeeFree |
| Conceito | Seja livre com seu dinheiro |
| Mascote | Abelha estilizada, minimalista, vista de frente (em pé) |
| Wordmark | "Bee" (off-white #F5F0E8) + "Free" (âmbar #EF9F27), peso 500, tracking -0.02em |
| Personalidade | Moderno, inteligente, acolhedor, confiável |

### Paleta de Cores

| Nome | Hex | Uso |
|---|---|---|
| Amber | `#EF9F27` | Cor primária — botões, destaques, wordmark "Free" |
| Amber Light | `#FAC775` | Hover, asas da abelha, elementos secundários |
| Amber Dark | `#BA7517` | Active, pressed, detalhes da abelha |
| Background | `#1A1714` | Fundo principal do app (tema escuro por padrão) |
| Surface | `#2A2520` | Cards, inputs, painéis |
| Border | `#3A3530` | Bordas, divisores |
| Text Primary | `#F5F0E8` | Texto principal |
| Text Muted | `#888580` | Labels, placeholders, textos secundários |
| Success | `#3DBF7F` | Receitas, valores positivos, status ok |
| Danger | `#E85D5D` | Despesas, erros, alertas |

### Tipografia

**Fonte: Inter (Google Fonts — gratuita)**

| Nível | Tamanho | Peso | Tracking | Uso |
|---|---|---|---|---|
| Display | 32px | 500 | -0.03em | Valor monetário principal |
| Heading 1 | 22px | 500 | -0.02em | Título de página |
| Heading 2 | 16px | 500 | -0.01em | Seção dentro da página |
| Body | 14px | 400 | 0 | Texto de transações, descrições |
| Caption | 12px | 400 | 0 | Datas, labels secundários |

### Tokens de Design

| Token | Valor | Uso |
|---|---|---|
| `--radius-sm` | 8px | Tags, badges, inputs |
| `--radius-md` | 12px | Botões, cards pequenos |
| `--radius-lg` | 20px | Cards principais, modais |
| `--radius-full` | 999px | Pills, avatares, FAB |
| `--space-xs` | 4px | Gap interno mínimo |
| `--space-sm` | 8px | Gap entre elementos |
| `--space-md` | 16px | Padding de cards |
| `--space-lg` | 24px | Padding de seções |

### Configuração Tailwind

```js
// tailwind.config.ts
colors: {
  amber: {
    DEFAULT: '#EF9F27',
    light: '#FAC775',
    dark: '#BA7517',
  },
  bg: {
    DEFAULT: '#1A1714',
    surface: '#2A2520',
    border: '#3A3530',
  },
  text: {
    primary: '#F5F0E8',
    muted: '#888580',
  },
  success: '#3DBF7F',
  danger: '#E85D5D',
}
```

---

## 3. Mapa de Telas

### Navegação Principal

| Tab | Tela | Sub-páginas | Notas |
|---|---|---|---|
| 1 | Dashboard | — | Visão geral mensal/anual com gráficos |
| 2 | Transações | Ver Resumo Detalhado | Lista com filtros + resumo como sub-rota |
| 3 | + Adicionar | — | Botão FAB central no mobile, ação direta |
| 4 | Cartões | Faturas, Gerenciar Parcelas | Lista de cartões + detalhe de fatura |
| 5 | Assistente IA | — | Chat Gemini + painel de insights |

**Menu secundário (ícone de perfil no header):**
- Importar CSV
- Backup (download JSON/CSV)
- Gerenciar categorias
- Configurações da conta

### Features por Tela

#### Dashboard
- Métricas: saldo do mês, receitas, despesas, comparativo vs mês anterior
- Navegação entre meses
- Últimas transações
- Gráfico de gastos por categoria
- Resumo de faturas abertas
- Empty state inteligente (diferencia usuário novo de mês sem dados)

#### Transações
- Busca por descrição, categoria ou valor
- Filtros: tipo, categoria (múltipla), forma de pagamento, valor min/max
- Navegação entre meses
- Lista agrupada por data com total filtrado
- Editar e deletar transação (com confirmação)
- Acesso a importação CSV

#### Adicionar Transação
- Campos: tipo, valor (formatação automática R$), descrição, categoria, data, forma de pagamento, cartão
- Grid de categorias com ícones + botão nova categoria customizada
- Parcelamento: número de parcelas, valor por parcela calculado automaticamente
- Validação em tempo real, botão desabilitado se inválido
- Sugestão de categoria por descrição via IA
- Preview de impacto no saldo (desktop apenas)

#### Cartões e Faturas
- Lista de cartões com fatura aberta de cada um
- Adicionar/editar cartão: nome, limite, dia de fechamento, dia de vencimento, offset de mês, tipo
- Grid de meses clicável por cartão
- Detalhe da fatura: total, data de vencimento, transações separadas em parcelas e avulsas
- Indicador de parcela por transação (2/12, 5/10 etc)
- Exportar fatura em PDF
- Gerenciar parcelas: cancelar, editar, ver todas as parcelas futuras

#### Assistente IA
- Chat conversacional com Gemini
- Histórico de mensagens na sessão
- Perguntas rápidas predefinidas
- Contexto financeiro automático (dados do mês injetados no prompt)
- Detecção de assinaturas recorrentes
- Alerta de gasto acima da média histórica
- Painel lateral com resumo do mês (desktop apenas)

#### Ver Resumo Detalhado (sub-página de Transações)
- Toggle: Mês / Trimestre / Ano
- Métricas: receitas, despesas, saldo líquido, parcelas do próximo mês
- Comparativo percentual vs período anterior
- Gráfico de pizza por categoria com legenda colorida
- Gráfico de barras de evolução mensal com média histórica
- Top categorias com percentual
- Exportar relatório

---

## 4. Arquitetura Frontend

### Stack

| Camada | Tecnologia | Motivo |
|---|---|---|
| Framework | React + Vite | Build rápido, HMR instantâneo, otimizado para PWA |
| Roteamento | React Router v6 | Rotas aninhadas para sub-páginas |
| Estilo | Tailwind CSS | Tokens do brand guide mapeados em classes, mobile-first |
| Estado global | Zustand | Simples, sem boilerplate, ideal para auth e UI state |
| Requisições | TanStack Query | Cache automático, retry, sync — sem useEffect para fetch |
| Gráficos | Recharts | SVG responsivo, API declarativa React |
| PWA | Vite PWA Plugin | Service Worker e manifest automáticos |
| Formulários | React Hook Form + Zod | Validação em tempo real sem re-renders |
| Deploy | Vercel | Gratuito, HTTPS, CDN global, deploy automático no push |

### Estrutura de Pastas (Frontend)

```
beefree-web/
├── index.html
├── vite.config.ts
├── tailwind.config.ts
├── public/
│   └── manifest.json
└── src/
    ├── layouts/
    │   ├── DesktopLayout.tsx     # sidebar + topbar + content
    │   ├── MobileLayout.tsx      # header + content + bottom bar
    │   └── AuthLayout.tsx        # login/cadastro centralizado
    ├── pages/
    │   ├── Dashboard/
    │   ├── Transactions/         # inclui Summary como sub-rota
    │   ├── AddTransaction/
    │   ├── Cards/                # inclui Invoices e Parcelas
    │   ├── Assistant/
    │   ├── Auth/                 # Login, Cadastro, Reset
    │   └── Settings/
    ├── components/
    │   ├── ui/                   # Button, Input, Card, Modal, Badge
    │   ├── charts/               # DonutChart, BarChart, LineChart
    │   ├── transaction/          # TransactionItem, TransactionList
    │   └── cards/                # CardVisual, InvoiceGrid, ParcelaItem
    ├── hooks/
    │   ├── useBreakpoint.ts      # detecta mobile vs desktop
    │   ├── useTransactions.ts    # fetch + cache via TanStack
    │   └── useAuth.ts            # estado de autenticação
    ├── store/
    │   ├── authStore.ts          # Zustand: token, usuário
    │   └── uiStore.ts            # Zustand: modais, toasts, loading
    ├── services/
    │   ├── api.ts                # instância Axios com interceptors JWT
    │   ├── transactions.ts
    │   ├── cards.ts
    │   └── auth.ts
    └── styles/
        └── tokens.css            # variáveis CSS do brand guide
```

### Lógica de Layout Responsivo

O hook `useBreakpoint` é o ponto central de toda a responsividade:

```tsx
const isMobile = useBreakpoint('md')
return isMobile ? <MobileLayout /> : <DesktopLayout />
```

**Mobile (< 768px):**
- Header fixo com logo e avatar
- Bottom tab bar com 5 tabs e FAB central elevado
- Modais em full screen
- Navegação por stack (push/pop)

**Desktop (≥ 768px):**
- Sidebar fixa à esquerda com 52px de largura (só ícones)
- Topbar contextual por página
- Painéis laterais side-by-side (filtros + lista, cartões + fatura)
- Modais centralizados com overlay
- Hover states em todos os itens interativos

### Fluxo de Dados

> **Regra fundamental:** dados de servidor ficam no TanStack Query. Estado de UI fica no Zustand. Nunca misturar os dois.

```
FastAPI → services/api.ts → TanStack Query → Componente
```

O componente nunca chama a API diretamente — sempre via hook do TanStack Query.

### Regras de Implementação Frontend

1. Nunca hardcodar cores — sempre usar tokens do Tailwind
2. Nunca usar CSS responsivo puro — sempre `MobileLayout` vs `DesktopLayout`
3. Dados de servidor: TanStack Query. Estado de UI: Zustand. Nunca misturar.
4. Componentes UI base ficam em `src/components/ui/` e são reutilizados em todo o projeto
5. Cada endpoint do FastAPI tem um arquivo correspondente em `src/services/`
6. Valores monetários: sempre `toFixed(2)` no JS

---

## 5. Arquitetura Backend

### Stack

| Camada | Tecnologia |
|---|---|
| Framework | FastAPI |
| ORM | SQLModel |
| Banco de dados | PostgreSQL (Supabase) |
| Migrations | Alembic |
| Autenticação | JWT (httpOnly cookie) + bcrypt |
| IA | Google Gemini API |
| Deploy | Railway ou Render (free tier) |

### Estrutura de Pastas (Backend)

```
beefree-api/
├── main.py
├── .env
├── requirements.txt
├── alembic/
│   └── versions/
└── app/
    ├── models/          # SQLModel models (migrados do FinanceAI)
    ├── repositories/    # Repository Pattern (migrado do FinanceAI)
    ├── services/        # Lógica de negócio (migrada do FinanceAI)
    ├── routers/         # Endpoints FastAPI por domínio
    │   ├── auth.py
    │   ├── transactions.py
    │   ├── categories.py
    │   ├── cards.py
    │   ├── invoices.py
    │   ├── installments.py
    │   ├── statistics.py
    │   └── ai.py
    ├── schemas/         # Pydantic schemas (request/response)
    └── core/
        ├── auth.py      # JWT + bcrypt
        ├── database.py  # conexão Supabase
        └── config.py    # variáveis de ambiente
```

### Endpoints por Domínio

| Domínio | Endpoints principais |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout` |
| Transações | `GET /transactions`, `POST /transactions`, `PUT /transactions/{id}`, `DELETE /transactions/{id}` |
| Categorias | `GET /categories`, `POST /categories`, `DELETE /categories/{id}` |
| Cartões | `GET /cards`, `POST /cards`, `PUT /cards/{id}`, `DELETE /cards/{id}` |
| Faturas | `GET /cards/{id}/invoices`, `GET /cards/{id}/invoices/{month}` |
| Parcelas | `GET /installments`, `PUT /installments/{id}`, `DELETE /installments/{id}` |
| Estatísticas | `GET /statistics/monthly`, `GET /statistics/yearly`, `GET /statistics/categories` |
| IA | `POST /ai/chat` |

---

## 6. Plano de Migração

### O que Reaproveitar do FinanceAI

| Arquivo | Status | Notas |
|---|---|---|
| `models.py` | ✅ 100% reaproveitado | SQLModel funciona com PostgreSQL sem alteração |
| `repositories.py` | ✅ 100% reaproveitado | Repository Pattern já desacoplado da UI |
| `logic.py` | ✅ 100% reaproveitado | Lógica de negócio pura, sem dependência de UI |
| `agent.py` | 🔄 Adaptado | Manter lógica Gemini, trocar interface para HTTP |
| `auth.py` | 🔄 Adaptado | Manter bcrypt, adicionar JWT |
| `pages/` + `components/` | ❌ Descartado | Streamlit substituído pelo React |

### Fases do Projeto

#### Fase 1 — Backend FastAPI + Supabase
**Objetivo:** API funcionando e testável via Swagger, sem frontend ainda.

- [ ] Criar projeto Supabase (PostgreSQL gratuito)
- [ ] Configurar projeto FastAPI com estrutura de pastas
- [ ] Configurar SQLModel com PostgreSQL
- [ ] Migrations com Alembic
- [ ] Deploy no Railway ou Render (free tier)
- [ ] Endpoints de auth (registro + login + JWT)
- [ ] Endpoints de transações e categorias
- [ ] Endpoints de cartões e faturas
- [ ] Endpoints de parcelas
- [ ] Endpoints de estatísticas
- [ ] Endpoint de IA (proxy Gemini)

#### Fase 2 — Frontend React PWA (base)
**Objetivo:** Design system, autenticação e Dashboard funcionando com dados reais.

- [ ] Criar projeto Vite + React + TypeScript
- [ ] Configurar Tailwind com tokens do brand guide
- [ ] Configurar Vite PWA Plugin + manifest.json
- [ ] Implementar MobileLayout e DesktopLayout
- [ ] Hook useBreakpoint
- [ ] Configurar React Router com rotas aninhadas
- [ ] Componentes UI base: Button, Input, Card, Modal, Badge
- [ ] Login e Cadastro
- [ ] Dashboard com dados reais do Supabase
- [ ] Zustand authStore + TanStack Query setup

**Critério de avanço:** login funcionando, dashboard com dados reais, PWA instalável no celular.

#### Fase 3 — Telas Restantes
**Objetivo:** Paridade funcional completa com o FinanceAI atual.

- [ ] Transações — lista, filtros, busca, editar, deletar
- [ ] Adicionar transação — form completo com parcelamento
- [ ] Ver resumo — gráficos mês/trimestre/ano
- [ ] Cartões — lista + detalhe de fatura + parcelas
- [ ] Assistente IA — chat + painel de insights
- [ ] Importar CSV
- [ ] Backup — export JSON/CSV
- [ ] Gerenciar categorias customizadas
- [ ] Configurações de perfil
- [ ] Export de fatura em PDF

#### Fase 4 — Monetização e Lançamento

- [ ] Definir limites do plano gratuito (ex: até 3 cartões, 100 transações/mês)
- [ ] Integrar Stripe ou Pagar.me para plano Pro
- [ ] Gate de features por plano no backend
- [ ] Landing page do BeeFree
- [ ] Domínio próprio (beefree.app ou similar)
- [ ] Post LinkedIn + Product Hunt
- [ ] Analytics com Posthog (gratuito)

### Ordem de Implementação com Claude Code

| # | Tarefa | Por que primeiro |
|---|---|---|
| 1 | Estrutura FastAPI + conexão Supabase | Fundação. Sem isso nada mais funciona. |
| 2 | Migrar models.py + migrations Alembic | Define o schema do banco. Tudo depende disso. |
| 3 | Endpoints de auth (registro + login + JWT) | Todas as outras rotas dependem do usuário autenticado. |
| 4 | Endpoints de transações e categorias | Core do produto. Frontend já tem o suficiente para o Dashboard. |
| 5 | Setup React + Tailwind + PWA + layouts | Base do frontend. Claude Code precisa dessas decisões antes de gerar telas. |
| 6 | Login + Dashboard | Primeiro marco visível. Valida o fluxo end-to-end completo. |
| 7 | Feature por feature (backend + frontend juntos) | Mais fácil de testar e validar. Não acumula bugs invisíveis. |

---

## 7. Como Usar com Claude Code

### Prompt de Abertura de Sessão

```
Leia os arquivos docs/BeeFree_Referencia.md e docs/SESSAO_ATUAL.md antes de começar.
Confirme que entendeu a arquitetura, as decisões de stack e a ordem de implementação.
Não proponha alternativas de tecnologia — as escolhas já foram feitas.
```

### Regras para Claude Code

1. Sempre usar os tokens de cor do brand guide — nunca hardcodar cores
2. Nunca usar CSS responsivo simples — sempre MobileLayout vs DesktopLayout
3. Dados de servidor: TanStack Query. Estado de UI: Zustand. Nunca misturar.
4. Componentes UI base ficam em `src/components/ui/` e são reutilizados em todo o projeto
5. Cada endpoint do FastAPI tem um arquivo correspondente em `src/services/`
6. Validar cada feature completa (endpoint + tela) antes de avançar para a próxima
7. JWT nunca em localStorage — apenas httpOnly cookie ou memória
8. Valores monetários: Decimal no Python, toFixed(2) no JS

### Critérios de Qualidade

- App instalável como PWA no celular (Add to Home Screen)
- Dashboard renderiza em menos de 2 segundos com dados reais
- Formulários com validação em tempo real em todos os campos
- Nenhum dado sensível no localStorage
- Todos os valores monetários com precisão correta

---

*BeeFree — Documento de Referência v1.0 — Maio 2026*  
*Repositório original: github.com/lucasdonnangelo/financeai*
