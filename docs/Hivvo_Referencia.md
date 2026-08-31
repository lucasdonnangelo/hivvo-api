# Hivvo — Documento de Referência do Produto

**Brand Guide | Arquitetura | Telas | Estado de Qualidade | Roadmap**
Atualizado em 29 de julho de 2026 | Lucas Donnangelo

> **Nota de versão (29/07/2026):** documentadas as features da leva de importação, todas verificadas no
> código antes de escritas: importação de **fatura** e de **extrato** por PDF (§3 telas, §5 endpoints,
> **§5.1** o fluxo inteiro), **cobertura de pagamento** (`paga_parcial`, #9), **estorno** como terceiro
> tipo de transação, a **validação fechamento×vencimento** do cartão e o **`preDeployCommand`** que
> aplica migrations no deploy (§8). A estrutura de pastas dos dois repos foi reconferida contra o disco.

> **Nota de versão (10/06/2026):** documento sincronizado com o estado real do código após as auditorias internas de segurança e de arquitetura. Correções relevantes: a arquitetura em camadas (Repository Pattern) **descrita anteriormente como pronta não existe no código** — está planejada para o pós-deploy. Ver §5 e §8.

---

## 1. Visão do Produto

Hivvo é um aplicativo web (PWA) de gestão financeira pessoal com IA, voltado exclusivamente para pessoa física. O nome carrega duplo sentido: "bee" (abelha, organização e construção) + "be free" (liberdade financeira).

### Pilares

- Controle financeiro completo: transações, cartões, faturas e parcelamentos
- Inteligência artificial (Gemini) como diferencial de insights, com contexto financeiro real do usuário
- Experiência premium: design escuro, paleta âmbar, identidade única
- PWA instalável — funciona como app pelo navegador (distribuição nas lojas é meta futura; ver §8)
- Desktop e mobile com layouts distintos e otimizados

### Público-alvo

- Pessoa física com renda média-alta e múltiplos cartões de crédito
- Usuários que precisam de controle real de parcelamentos
- Perfil que valoriza design e não tolera interfaces genéricas

### Diferenciais Competitivos

- **Parcelamento completo** — gestão por fatura, indicador 2/12 por transação, controle **manual** (posicionamento contra concorrentes que dependem de Open Finance/conexão automática)
- **IA com contexto financeiro real** — não é chatbot genérico
- **Layout responsivo genuíno** — não é apenas CSS adaptativo

> Itens como "detecção automática de assinaturas recorrentes" e "alerta de gasto acima da média" são **roadmap**, não estão implementados (ver §8).

---

## 2. Brand Guide

### Identidade

| Atributo | Valor |
|---|---|
| Nome | Hivvo |
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
  amber: { DEFAULT: '#EF9F27', light: '#FAC775', dark: '#BA7517' },
  bg:    { DEFAULT: '#1A1714', surface: '#2A2520', border: '#3A3530' },
  text:  { primary: '#F5F0E8', muted: '#888580' },
  success: '#3DBF7F',
  danger:  '#E85D5D',
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

**Menu do ícone de perfil (header mobile / sidebar desktop):** **Perfil** · **Configurações** · **Sair**

- **Perfil** (`/profile`) — nome (editável), e-mail (read-only), trocar senha, sair, Termos e Privacidade.
- **Configurações** (`/settings`) — Categorias (despesa/receita) · Recorrências · Assistente IA
  (Resetar Assistente) · Meus dados (Importar CSV · **Importar fatura (PDF)** → `/import/fatura` ·
  **Importar extrato (PDF)** → `/import/extrato` · Exportar transações JSON · Excluir minha conta).

> Histórico: até 14/07/2026 esta linha afirmava que o menu tinha 5 itens (Importar CSV · Backup ·
> Gerenciar categorias · Configurações da conta · Termos e Privacidade). **Era falso e nunca existiu**
> — o ícone chamava `navigate('/settings')` direto, sem dropdown algum; aqueles 5 itens eram, na
> verdade, as SEÇÕES DE DENTRO do SettingsPage. A descrição de "Backup (download JSON/CSV)" também
> era falsa em dois pontos: o export só traz transações (não é backup da conta) e só gera JSON, nunca
> CSV. O menu acima existe de fato desde a separação Perfil/Configurações (BATCH 1).

### Features por Tela (implementadas)

**Dashboard** — métricas (saldo do mês, receitas, despesas, comparativo vs. mês anterior), navegação entre meses, últimas transações, gráfico de gastos por categoria, resumo de faturas abertas, empty state inteligente, onboarding progressivo pós-cadastro, widget de compromissos futuros (parcelas).

**Transações** — busca por descrição/categoria/valor, filtros (tipo, categoria múltipla, forma de pagamento, valor min/max), navegação entre meses, lista agrupada por data com total filtrado, editar/deletar com confirmação, acesso à importação CSV, badge de parcela inline.

**Adicionar Transação** — tipo, valor (formatação automática R$, aceita vírgula decimal), descrição, categoria, data, forma de pagamento, cartão; grid de categorias com ícones/emoji + categoria customizada; parcelamento com valor por parcela calculado; validação em tempo real; sugestão de categoria via IA; preview de impacto no saldo (desktop).

**Cartões e Faturas** — lista com fatura aberta por cartão e barra de limite usado/disponível; adicionar/editar cartão (nome, limite, dia de fechamento, dia de vencimento, offset de mês, tipo); grid de meses por cartão; detalhe da fatura (total, vencimento, parcelas e avulsas separadas); indicador de parcela por transação; exportar fatura em PDF; gerenciar parcelas (cancelar, editar, ver futuras).

**Assistente IA** — chat com Gemini; persistência e memória (tabela `chat_messages`, sessões com `sessao_id`, janela de 24h na UI, contexto invisível das últimas 50 mensagens); perguntas rápidas; contexto financeiro injetado no prompt; botão "Nova conversa"; painel lateral com resumo do mês (desktop).

**Ver Resumo Detalhado** — toggle Mês/Trimestre/Ano; métricas (receitas, despesas, saldo líquido, parcelas do próximo mês); comparativo percentual vs. período anterior; pizza por categoria; barras de evolução mensal com média; top categorias; exportar relatório.

**Auth / Conta** — login, cadastro (username auto-gerado a partir do e-mail), recuperação de senha (forgot/reset), troca de senha, toggle de visibilidade de senha, refresh token automático, Termos de Uso e Política de Privacidade (base LGPD).

**Importação por PDF (29/07/2026)** — dois wizards independentes, alcançados por Configurações → Meus dados. **Fatura** (`/import/fatura`, 4 passos): escolher cartão + upload → revisão linha a linha (categoria, descartar) → confirmar em bloco o pagamento das faturas passadas → recibo. **Extrato** (`/import/extrato`, 3 passos): upload → revisão dos três baldes (receita · débito · pagamento de fatura), com categoria sugerida, fatura candidata para o pagamento e a receita-que-casa-com-recorrência já desmarcada → recibo. Em ambos a revisão é **obrigatória** — é a rede que torna a extração por LLM aceitável. Ver §5.1.

---

## 4. Arquitetura Frontend (hivvo-web)

### Stack

| Camada | Tecnologia | Motivo |
|---|---|---|
| Framework | React + Vite | Build rápido, HMR, otimizado para PWA |
| Roteamento | React Router v6 | Rotas aninhadas para sub-páginas |
| Estilo | Tailwind CSS | Tokens do brand guide em classes, mobile-first |
| Estado global | Zustand | Auth e UI state, sem boilerplate |
| Requisições | TanStack Query | Cache/retry/sync — sem useEffect para fetch |
| Gráficos | Recharts | SVG responsivo, API declarativa |
| PWA | Vite PWA Plugin | Service Worker e manifest automáticos |
| Formulários | React Hook Form + Zod | Validação em tempo real |
| HTTP | Axios | Instância com interceptors JWT (refresh automático) |
| Deploy | Vercel | HTTPS, CDN, deploy no push |

### Estrutura de Pastas (atual)

```
hivvo-web/
├── index.html · vite.config.ts · tailwind.config.ts
├── public/  (manifest.json, icon-192.png, icon-512.png)
└── src/
    ├── layouts/      DesktopLayout, MobileLayout, AuthLayout
    ├── pages/        Dashboard, Transactions(/Summary), AddTransaction,
    │                 Cards(/Invoices/Parcelas), Assistant, Auth
    │                 (Login, Register, ForgotPassword, ResetPassword),
    │                 Settings, Legal(Terms, Privacy),
    │                 Import/ (CSV + ImportFaturaPage com fatura/{Step*},
    │                          ImportExtratoPage com extrato/{Step*})
    ├── components/    ui/, charts/, transaction/, cards/
    ├── hooks/         useBreakpoint, useTransactions, useCategories,
    │                  useStatistics, useCards, useAuth, useInstallments,
    │                  useImportFatura, useImportExtrato
    ├── lib/           unwrapList, extractDetail, tipoTransacao, observability
    ├── store/         authStore, uiStore
    ├── services/      api, auth, transactions, categories, cards, ai,
    │                  statistics, installments, importFatura, importExtrato
    └── styles/        tokens.css
```

### Regras de Implementação Frontend (não-negociáveis)

1. Nunca hardcodar cores — sempre tokens do Tailwind
2. Nunca CSS responsivo puro — sempre `MobileLayout` vs `DesktopLayout` (via `useBreakpoint`)
3. Dados de servidor: TanStack Query. Estado de UI: Zustand. Nunca misturar.
4. Componentes UI base em `src/components/ui/`, reutilizados em todo o projeto
5. Cada endpoint do FastAPI tem um arquivo correspondente em `src/services/`
6. Valores monetários: sempre `toFixed(2)` no JS
7. JWT nunca em localStorage — apenas httpOnly cookie ou memória

> **Pendências cross-repo (ver §8):** quando o backend mover para `/api/v1` e mudar o contrato de listagem para envelope paginado, a base URL e os serviços do frontend mudam junto. ✅ **Resolvido (FE-04):** a página de reset de senha já não deixa o token na URL — `ResetPasswordPage.tsx` captura o token uma única vez no estado inicial e limpa a query com `history.replaceState` no primeiro efeito, tirando-o do histórico e do `Referer`. Este doc já descreveu isso como pendente depois de corrigido.

---

## 5. Arquitetura Backend (hivvo-api)

### Stack

| Camada | Tecnologia |
|---|---|
| Framework | FastAPI |
| ORM | SQLModel |
| Banco de dados | PostgreSQL (Supabase) |
| Migrations | Alembic |
| Autenticação | JWT (httpOnly cookie) + bcrypt; refresh token rotativo |
| IA | Google Gemini API (google-genai) — chave separada para a importação (`GEMINI_IMPORT_API_KEY`) |
| E-mail | Resend (recuperação de senha) |
| Deploy | Railway — `railway.json` com `preDeployCommand: "alembic upgrade head"` |

### Estrutura de Pastas (estado REAL)

```
hivvo-api/
├── main.py · .env · requirements.txt
├── alembic/versions/
├── scripts/            avisar_vencimento.py (ciclo do aviso de vencimento, com
│                       --dry-run), mutacao.py (verificação por mutação), sync-docs.py
└── app/
    ├── models/          SQLModel models
    ├── repositories/    ⚠️ VAZIO hoje (só __init__.py — sem camada de acesso a dados separada)
    ├── services/        parcelas, faturas, estatisticas, categorias, recorrencias,
    │                    import_fatura/ e import_extrato/ (extração PDF, redação PII,
    │                    Gemini, reconciliação, enriquecimento, materialização),
    │                    notificacoes/ (consulta · email · envio — aviso de vencimento)
    │                    — ~3.570 linhas
    ├── routers/         auth, transactions, categories, cards, invoices,
    │                    installments, statistics, ai, recorrencias, import_fatura,
    │                    import_extrato
    │                    ← orquestração (auth/sessão/request-response); parte da
    │                    lógica de domínio ainda vive aqui também
    ├── schemas/         Pydantic (request/response)
    └── core/            auth.py (JWT+bcrypt), database.py, config.py,
                         gemini_safety.py (SAFETY_SETTINGS — fonte única)
```

> **Estado real da arquitetura em camadas:** `repositories/` está **vazio** (só `__init__.py`) — não existe camada de acesso a dados separada da regra de negócio. `services/` **não está vazio**: concentra lógica de domínio em `parcelas.py`, `faturas.py`, `estatisticas.py`, `categorias.py`, `recorrencias.py` e os pacotes `import_fatura/` e `import_extrato/` (extração de PDF, redação de PII, chamada ao Gemini, reconciliação, enriquecimento, materialização) — ao todo ~3.570 linhas. Essas funções recebem `Session` e fazem suas próprias queries — não é o Repository Pattern completo (acesso a dados separado da regra de negócio); é serviço com lógica + I/O misturados. Os routers fazem orquestração (auth, sessão, mapeamento request/response) e chamam `services/`; parte da lógica de domínio ainda vive direto nos routers, em funções privadas. Separar `services/` (regra) de `repositories/` (dados) é o refactor pendente (ver §7/§8) — não a criação de `services/` do zero, que já existe.

### Endpoints por Domínio (estado real)

| Domínio | Endpoints |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `POST /auth/logout-all`, `GET /auth/me`, `PUT /auth/me`, `DELETE /auth/me` ‡, `POST /auth/refresh`, `PUT /auth/password`, `POST /auth/forgot-password`, `POST /auth/reset-password`, `POST /auth/reset-data` |
| Transações | `GET /transactions`, `POST /transactions`, `PUT /transactions/{id}`, `DELETE /transactions/{id}` |
| Categorias | `GET /categories`, `POST /categories`, `DELETE /categories/{id}` |
| Cartões | `GET /cards`, `POST /cards`, `PUT /cards/{id}`, `DELETE /cards/{id}` |
| Faturas | `GET /cards/{id}/invoices`, `GET /cards/{id}/invoices/{month}` |
| Parcelas | `GET /installments`, `PUT /installments/{id}`, `DELETE /installments/{id}` |
| Estatísticas | `GET /statistics/monthly`, `GET /statistics/default-month`, `GET /statistics/projection`, `GET /statistics/yearly` †, `GET /statistics/categories` |
| Estatísticas — Resumo/análise (13/07/2026) | `GET /statistics/evolution`, `GET /statistics/evolution/categories`, `GET /statistics/comparison`, `GET /statistics/highlights`, `GET /statistics/coverage` — base CONSUMO, fonte única `_lancamentos_consumo_horizonte` (PLANO_RESUMO.md) |
| IA | `POST /ai/chat`, `GET /ai/historico`, `DELETE /ai/historico` |
| Importação por PDF (29/07/2026) | `POST /import/fatura/preview`, `POST /import/fatura/commit`, `POST /import/extrato/preview`, `POST /import/extrato/commit` — ver §5.1 |

> ✅ **Aplicado (T-28):** todas as rotas vivem sob `/api/v1` (`main.py`, os 10 routers). Os caminhos desta tabela são **relativos ao prefixo** — o real é `/api/v1/auth/login` etc. Este doc já descreveu o prefixo como "planejado", o que era falso.
>
> † **`/statistics/yearly` — candidato a aposentadoria (13/07/2026):** com o `/evolution` (série histórica do Resumo), o yearly perde o papel de "evolução mensal" — mas **não são equivalentes** (yearly = FLUXO em ano-calendário fixo; evolution = CONSUMO em horizonte relativo). Neste repo só testes/docs o referenciam. **Não remover** antes de confirmar que o hivvo-web não o consome.
>
> ‡ **`DELETE /auth/me` existe no backend desde sempre** (`app/routers/auth.py`, exige `{password}` → `204`) — este doc já o listou como "planejado", o que era falso. A exposição na UI, que este doc depois descreveu como pendente, também já existe: Configurações → **Meus dados** chama `handleDeleteAccount` (`SettingsPage.tsx`), que vai em `deleteMe` (`services/auth.ts`) → `api.delete('/auth/me')`, com reautenticação por senha (F-07/LGPD). É o fluxo que a Política de Privacidade §8 promete. Ver `PLANO_PERFIL_CONFIG.md` (§ INVENTÁRIO).

### 5.1 Importação de fatura e extrato por PDF (29/07/2026)

**Estado: implementada e viva, backend + frontend, nas duas metades.** Design completo e racional das
decisões em `PLANO_IMPORTACAO.md` — aqui fica só o que existe no código.

**A decisão-pivô:** a interpretação das linhas é feita por **LLM (Gemini pago, chave dedicada
`GEMINI_IMPORT_API_KEY`)**, não por parser determinístico por banco. Um schema serve todos os bancos; a
imperfeição é aceitável porque a **tela de revisão obrigatória é a rede** — e é o produto, não o remendo.

**Fluxo (idêntico nas duas metades): `preview` → revisão → `commit`.**

- **`preview` é STATELESS** — nada é persistido, nem o arquivo nem o resultado: processa em memória e
  descarta. Guardas de entrada: teto de bytes (`IMPORT_MAX_PDF_BYTES`, confirmado lendo `limite+1`, não
  pelo `Content-Length` que o cliente pode mentir), teto de páginas, **magic bytes `%PDF-`** (não o
  content-type), e PDF escaneado (sem camada de texto) → 422 explícito. Rate limit por IP e por usuário
  + cota diária, no preview E no commit.
- **`commit` é a ÚNICA rota que escreve**, e é **atômica**: tudo numa transação de banco; qualquer falha
  = rollback total, nunca uma importação meio-gravada.
- **Idempotência por lote, airtight:** tabelas `import_fatura_lote` e `import_extrato_lote` (ambas com
  RLS ativada no `upgrade()`). O lote é inserido **PRIMEIRO**, na mesma transação — o `UNIQUE` é o
  mecanismo, e reimportar levanta `IntegrityError` no flush → **409**. Um `EXISTS` pré-checado não
  fecharia a corrida de duplo-clique; o `UNIQUE` fecha. Chave da fatura: `(usuário, cartão,
  competência)`. Chave do extrato: `(usuário, banco normalizado, período de/até)`.
- **A revisão manda, o servidor confere.** O commit recebe o que o front editou e **revalida tudo**:
  categoria contra a lista do usuário (desconhecida → "Outros", nunca suja o banco), cartão contra a
  propriedade (404 — anti-enumeração, nunca 403), competência contra a existência da fatura (422).
- **PII:** o texto do PDF **nunca** vai para log — só metadados (bytes, páginas, chars, nº de linhas).
  `ValidationError` do schema é logado por contagem e `loc`, nunca inteiro (ele embute os valores
  rejeitados). Antes de ir ao Gemini, o texto passa por redação **best-effort** (declaradamente rede, não
  blindagem) — na fatura com pseudonimização reversível do portador; no extrato sem mapa reverso, cobrindo
  CPF, agência/conta **por rótulo de contexto** e o nome do titular.

**Fatura — o que é específico.** Reconcilia pelo **total de compras/lançamentos do ciclo**, não pelo
"total a pagar" (achado do spike: um banco pode imprimir "Total desta fatura 0,00" quando há débito
automático). Não bater **não é erro HTTP**: devolve 200 sinalizando, e o usuário decide. Materializa
parcelamento `X/N` como `1/N..N/N`, e **deduplica a parcelada ENTRE importações** por identidade
recomputada (`cartão + descrição normalizada + total de parcelas + origem implícita + valor da parcela`),
decidida contra um **snapshot** tirado antes de qualquer insert — sem isso, importar julho e agosto
duplicaria a parcelada que aparece nas duas faturas, que é o uso central (o Resumo só floresce com vários
meses). O preview devolve `faturas_passadas` para a revisão confirmar em bloco o pagamento do histórico —
senão todo mês importado nasce não-pago e o "A pagar" explode.

**Extrato — os três baldes.** Fatura e extrato descrevem o mesmo dinheiro por dois lados: importá-los
ingênuo **conta em dobro**. Por isso cada linha cai em um de três baldes que **não viram a mesma coisa**
(`services/import_extrato/persistencia.py`):

| Balde | Vira | Por quê |
|---|---|---|
| `receita` | `Transacao(tipo="receita", forma_pagamento="PIX")` na data da linha | entrada por transferência, não "Débito" |
| `debito` | `Transacao(tipo="despesa", forma_pagamento="Débito")` **sem `cartao_id` e sem `fatura_mes/ano`** | o dinheiro JÁ SAIU: é consumo realizado, nunca dívida de cartão a pagar |
| `pagamento_fatura` | `PagamentoFatura` — **NÃO é lançamento** | é a quitação das compras que a fatura já capturou |

Mais o **`rendimento`**, que não é linha: vem do RESUMO do extrato (o Nubank imprime "Rendimento
líquido" só ali) e vira receita da categoria padrão **"Rendimentos"** na data final do período. O
preview roda um **balance walk** (`saldo_inicial + rendimento + Σreceita − Σdébito − Σpagamento =
saldo_final`) em `Decimal` como guarda-costas determinístico, e um **enriquecimento por linha**
(categoria sugerida, fatura candidata para o pagamento, flag de recorrência) que só LÊ o banco.

**A armadilha do salário duplicado** (e o padrão que ela fixou): uma receita do extrato que casa com uma
recorrência vigente (≈valor + ≈dia) já é contada pela projeção — importá-la duplicaria o salário. Então
ela nasce **desmarcada**. O ponto de arquitetura é onde a regra mora: o `importar` de cada linha é
**TRI-ESTADO** — ausente significa "não decidido", e o servidor **recomputa o casamento** com o mesmo
matcher do preview. O default de segurança não pode depender de o front ter mandado a flag certa.

**A costura com o #9 — real vence assumido, nas duas ordens.** O extrato **prova** quais faturas foram
pagas, com valor e data REAIS. O commit de extrato sempre grava `valor_pago` = valor real da linha e
`data_pagamento` = data real; o commit de FATURA, que só conhece o total ASSUMIDO, **preserva**
competência que já tem `pago=True` (e reporta em `faturas_ja_confirmadas`). Funciona independente de qual
import rodar primeiro. Duas linhas do mesmo extrato para a mesma fatura **somam** num único
`PagamentoFatura` (pagar em duas transferências é real), com a data mais recente. Resíduo conhecido:
sem coluna de proveniência, dois extratos de períodos diferentes sobrescrevem em vez de somar
(PENDÊNCIAS #32).

### Cobertura de pagamento — `paga` vs `paga_parcial` (#9)

`PagamentoFatura.valor_pago` guarda **quanto** foi pago; o status é **derivado, nunca materializado**
(`status_fatura` em `services/faturas.py`): `pago=True` e `valor_pago >= total` atual → **`paga`**;
`valor_pago < total` → **`paga_parcial`**. A consequência é a que resolve o furo da compra retroativa:
lançar uma compra numa fatura já paga faz o total crescer → a fatura vira `paga_parcial` sozinha, e a
diferença `total − valor_pago` volta ao **"A pagar"** das estatísticas — sem nenhum write. Remover a
compra a devolve para `paga`, também sem write. `valor_pago` NULL com `pago=True` (que o CHECK impede)
degradaria seguro para `paga`, nunca para uma parcial falsa.

### Estorno — o terceiro tipo de transação

`tipo` aceita **`"receita" | "despesa" | "estorno"`** (CHECK no banco). Estorno é uma compra devolvida:
guardado com **valor POSITIVO** (o `CHECK valor > 0` continua valendo) e o **sinal é aplicado na
leitura** — ele SUBTRAI. Não é receita (não é renda nova) nem despesa. Compõe a fatura **abatendo**
(fonte única `valor_avulsa_liquido` em `faturas.py`) e as agregações de consumo o netam. Duas exceções
deliberadas: "maior despesa" do mês é BRUTA (um estorno nunca é a maior despesa) e o a_pagar clampa por
fatura (fatura net-negativa não vira crédito). Estorno **nunca é parcelado** — barrado no POST e no PUT.

### Validação fechamento × vencimento do cartão

Com `mes_offset_vencimento = 0` ("mesmo mês"), o vencimento tem que ser **estritamente depois** do
fechamento — uma fatura não pode vencer antes de fechar. Com offset ≥ 1 ("mês seguinte") o mês virou
entre fechar e vencer, então qualquer par vale. Regra única em `schemas/card.py`
(`fechamento_vencimento_coerentes`), aplicada no create e no update; o update é **parcial**, então
mescla o que veio com o que está no cartão e valida o RESULTADO — mas **só quando toca algum campo da
regra**, para que editar o nome de um cartão pré-existente inválido não trave. Espelhada no form do
`hivvo-web` (`CardFormModal`, `superRefine`) com o mesmo carve-out.

### Decisões de domínio (fixas)

- `fatura_mes`/`fatura_ano` derivados da **data de vencimento** da parcela, não da data da compra.
- Arredondamento de parcelas: última parcela absorve a diferença (`ROUND_HALF_UP`). *(Borda conhecida a corrigir: valores muito pequenos podem gerar última parcela ≤ 0 — T-33.)*
- Valores monetários: `Decimal` no Python, `Numeric(15,2)` no banco — sem `float` no caminho do dinheiro.
- Soft delete em categorias (`ativa=False`) para preservar histórico.
- Convenção de fatura: compra com `dia > dia_fechamento` entra no ciclo seguinte; `mes_offset_vencimento` desloca fechamento→vencimento; dia de vencimento clampado pelo último dia do mês.

---

## 6. Origem (migração FinanceAI → Hivvo)

O Hivvo nasceu da migração do FinanceAI (protótipo Python/Streamlit). A UI Streamlit foi descartada; a lógica de negócio foi transferida para o backend FastAPI.

| Origem | Status real na hivvo-api |
|---|---|
| `models.py` | ✅ Transferido — SQLModel com PostgreSQL |
| `logic.py` / `repositories.py` | 🔄 **Lógica transferida e funcional** — parte em `services/` (parcelas, faturas, estatísticas, recorrências, import_fatura), parte ainda nos routers; `repositories/` (acesso a dados separado da regra) segue vazio (planejado, §8) |
| `agent.py` (Gemini) | ✅ Adaptado para HTTP (`routers/ai.py`) com persistência de chat |
| `auth.py` | ✅ Adaptado — bcrypt + JWT (httpOnly cookie) + refresh token |
| `pages/` + `components/` (Streamlit) | ❌ Descartado — substituído pelo React |

As fases de construção (Backend → Frontend base → Telas restantes) estão **concluídas**. O detalhe histórico está nos diários de sessão (documentação privada).

---

## 7. Como Usar com Claude Code

### Prompt de abertura de sessão (atualizado)

```
Leia docs/Hivvo_Referencia.md e os planos em docs/ antes de começar.
Se tiver acesso ao repositório privado de documentação operacional, leia
também o diário de sessão, o backlog priorizado e o plano de execução.
Confirme que entendeu a arquitetura real, as decisões de stack e o plano de
correção em andamento. Não proponha alternativas de tecnologia — já decididas.
Uma tarefa/batch por vez, com aprovação antes do commit.
```

### Regras para Claude Code

1. Tokens de cor do brand guide — nunca hardcodar cores
2. Nunca CSS responsivo puro — `MobileLayout` vs `DesktopLayout`
3. Dados de servidor: TanStack Query. Estado de UI: Zustand. Nunca misturar.
4. Componentes UI base em `src/components/ui/`, reutilizados
5. Cada endpoint FastAPI tem arquivo em `src/services/`
6. Valor monetário: `Decimal` no Python, `toFixed(2)` no JS
7. JWT nunca em localStorage — apenas httpOnly cookie ou memória
8. Uma tarefa/batch por vez; rodar testes antes de concluir; atualizar o diário de sessão ao fim

---

## 8. Estado de Qualidade, Segurança e Roadmap

### Auditorias e backlog

O projeto mantém **auditorias internas de segurança e de arquitetura** e um
**backlog priorizado**, revisados ao longo do desenvolvimento e usados para
ordenar o trabalho.

Esses documentos são **privados**, e vivem num repositório separado. O motivo é
que descrevem um sistema **em produção** — postura de segurança, decisões de
infraestrutura e o estado operacional do serviço. Não são material incompleto
que se publicaria quando ficasse pronto: são documentos cuja utilidade para quem
opera o sistema é a mesma para quem quisesse atacá-lo.

O que este repositório publica é o resultado dessas revisões, que está **no
código**: a arquitetura descrita neste documento, os testes, as migrações e as
decisões de stack registradas aqui.

### Plano de correção

O plano de execução, em batches ordenados, também vive na documentação privada.
A espinha do trabalho pré-deploy está refletida na estrutura atual do código:
lógica de domínio consolidada em `services/`, cobertura de testes, hardening de
configuração e sessão, ajustes de banco (índices, pooler, cascades), resiliência
da integração com IA e rate limiting.

### Decisão pendente (gate de deploy)

**Topologia de hospedagem.** Recomendado: same-site sob `hivvo.app` — `app.hivvo.app` (Vercel) + `api.hivvo.app` (Railway), cookie `Domain=.hivvo.app` `SameSite=Lax`. Resolve o cookie cross-site e preserva a proteção CSRF sem precisar de tokens CSRF. Afeta DNS, cookies e CORS — decidir antes do deploy.

### Observabilidade (estado real — implementada nos dois repos)

**Não é item de roadmap: o código existe e está no master dos dois lados.** A ativação é por variável de ambiente, não por implementação pendente — sem `SENTRY_DSN` o Sentry é **no-op por design** (T-25), para que dev/CI não precisem de DSN nem quebrem sem ele.

| Camada | Onde | O que tem |
|---|---|---|
| Backend (hivvo-api) | `app/core/observability.py` | Logging estruturado, middleware de request-log, `init_sentry()` chamado no lifespan (`main.py`), scrub LGPD (`_before_send`) e `validate_startup_config` (fail-fast de boot). Dependência: `sentry-sdk[fastapi]` (`requirements.txt`). Coberto por `tests/test_observability.py`. |
| Frontend (hivvo-web) | `src/lib/observability.ts` | `@sentry/react`, `initSentry()` chamado no `main.tsx`, integrado ao `ErrorBoundary`. Espelha o backend: no-op sem DSN, `sendDefaultPii: false`, `beforeSend`/`beforeBreadcrumb` com scrub. |

**Regra de privacidade (dura, idêntica nos dois):** nunca enviar ao Sentry valor/descrição de transação, conteúdo de chat, senha, token ou cookie — só metadados. A defesa é em três camadas (no-op sem DSN → cortar na origem → refiltro no `beforeSend`), com **deny-all** onde não dá para saber se o dado é sensível e allowlist onde dá. Ao mexer em qualquer um dos dois arquivos, mantenha o espelho.

**Pendente (ops, não código):** setar `SENTRY_DSN` nos ambientes de deploy.

### Migrations no deploy — `preDeployCommand` (17/07/2026)

`railway.json` declara `deploy.preDeployCommand: "alembic upgrade head"` — o Railway roda isso **uma vez
por deploy, antes de a versão nova entrar no ar**. Antes disso o `Procfile` tinha
`release: alembic upgrade head`, que é **convenção do Heroku e o Railway ignora em silêncio**: o banco de
produção driftou do código e a `import_fatura_lote` simplesmente não nasceu. A linha `release:` foi
removida do `Procfile` para não haver dois mecanismos aparentes, um deles morto. **Regra:** migration
nova entra em produção pelo `preDeployCommand` — não há passo manual, e não se deve reintroduzir
`release:`.

### Arquitetura-alvo (pós-deploy)

- **Repository Pattern completo:** separar `repositories/` (acesso a dados, hoje vazio) de `services/` (regra de negócio, já existe mas hoje mistura queries) — tirando o que resta de lógica/queries dos routers.
- **RLS no Supabase** como defesa em profundidade (papel Postgres de privilégio mínimo + políticas por `SET LOCAL`).
- **Performance:** agregações no banco (não em Python), cache do contexto da IA, paginação com envelope.

### Roadmap de produto

- **Lançamento:** domínio `hivvo.app`, deploy (Railway/Render + Vercel), landing page, Product Hunt/LinkedIn, analytics (Posthog).
- **Monetização (Fase 4):** plano Free com limites (ex.: nº de cartões, transações/mês) + plano **Pro (~R$ 29,90/mês)**; gate de features no backend; integração Stripe ou Pagar.me; cota de IA por plano.
- **Features:** planejamento 50/30/20; importação inteligente de CSV; detecção de assinaturas recorrentes; alerta de gasto acima da média; área de consultoria de investimentos (futuro).
- **Agente de IA com CRUD (futuro):** dar capacidade de escrita ao assistente. **Pré-requisito de segurança:** mitigar prompt injection (F-21) — separar dados de instruções, allow-list de ferramentas, confirmação para ações mutáveis, autorização explícita por recurso.
- **Distribuição nas lojas (futuro):** o Hivvo é PWA. Google Play aceita via empacotamento (TWA). A App Store da Apple **não lista PWA diretamente** e é restritiva com wrappers finos — exigirá empacotamento (ex.: Capacitor) e atenção à revisão da Apple. Validar a estratégia antes de prometer presença nas lojas.

---

*Hivvo — Documento de Referência v2.0 — 10/06/2026*
*Repositório original FinanceAI: github.com/lucasdonnangelo/financeai*
