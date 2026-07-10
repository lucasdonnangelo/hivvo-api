# Hivvo — Estado do Projeto (handoff para nova sessão)

> Atualizado ao fim da sessão de 08–10/07/2026. Substitui a versão de 06/07.

## O que é o Hivvo
PWA de finanças pessoais (BR), foco em **parcelamento por fatura de cartão** (diferencial nº1),
assistente IA (Gemini), tema escuro premium, público high-income multi-cartão. O core é
**projeção de fluxo futuro**: "como estarei em dezembro" = receitas recorrentes menos o que vence,
por competência de fatura.

**Monorepo:**
- **hivvo-api** — FastAPI + SQLModel + PostgreSQL/Supabase + Alembic + JWT httpOnly cookies.
  Deploy: Railway (api.hivvo.app).
- **hivvo-web** — React + Vite + TS + Tailwind + Zustand + TanStack Query + Recharts + PWA.
  Deploy: Vercel (app.hivvo.app).
- Cookies Domain=.hivvo.app, SameSite=Lax. Windows/PowerShell. PT-BR com termos técnicos em EN.
- **Único usuário é o Lucas** (`usuario_id=2`, lucasjrd10@gmail.com), conta de teste, sem base
  instalada. Reset via SQL no Supabase quando necessário (ordem: transacoes → parcelas → cartoes →
  recorrencias; `transacoes.cartao_id` e `parcelas.cartao_id` são NO ACTION, o resto é CASCADE).

## Como o Claude age nesta área do projeto (o processo — MANTER)
- **Claude é revisor/arquiteto, NÃO implementa.** Gera prompts que o Lucas roda no Claude Code
  (um batch por vez), revisa o resultado antes do commit. Aprovação explícita antes de cada commit.
- **Complexidade sinalizada:** 🟢 trivial, 🟡 médio, 🔴 complexo → modelo potente do Claude Code.
- **Nos 🔴, o Claude Code mostra o PLANO antes do código;** Claude revisa, aprova, aí implementa.
- **Design fechado antes de implementar.** As grandes mudanças desta sessão (Dashboard em dois
  blocos, eixo saiu/a-vencer, PagamentoFatura) tiveram conceito + layout travados em documento
  ANTES de qualquer código. Funcionou.
- **Defesa em profundidade:** integridade no backend (fronteira real), UX no frontend. **Lógica de
  negócio SEMPRE no backend; frontend só o essencial.** (Aplicado: o preview da parcelada NÃO
  replica a regra de competência de fatura — degrada em vez de mentir.)
- **Quando um teste muda:** exigir a distinção "a regra ficou mais correta" (ok) vs "amaciado" (não).
- **Validação E2E** com Claude no Chrome / Claude Code como avaliador independente. Foi assim que os
  bugs mais importantes desta sessão foram achados — **usando o produto, não lendo código**.
- **Docs canônicos** (todos devem estar nos DOIS repos): `PLANO_PROJECAO.md` (o modelo),
  `PLANO_DASHBOARD_DOIS_BLOCOS.md`, `PLANO_3D_PAGAMENTO_FATURA.md`, `PLANO_IMPORTACAO.md`,
  `DECISAO_A_PAGAR_SALDO.md`, `SESSAO_ATUAL_API.md`, `SESSAO_ATUAL_WEB.md`.
- Tom: conciso, direto, honesto; nomeia trade-offs; não bajula.

## Regras arquiteturais não-negociáveis
- Tokens Tailwind (nunca hex). MobileLayout/DesktopLayout via `useBreakpoint` (nunca media queries).
- Server-state em TanStack Query, UI-state em Zustand (nunca misturar).
- JWT em httpOnly cookie. `Decimal` no Python / string+`toFixed(2)` no JS.
- **SEM lib de ícones** (glifos unicode; não instalar lucide-react).
- Não prometer na UI o que o backend não faz.
- **Botão nunca fica `disabled` silenciosamente** — sempre clicável, com erro inline dizendo o que
  falta. (Corrigido no AddTransactionPage; **o CardFormModal ainda usa `disabled={!isValid}`** —
  pendente.)

## O MODELO (o coração — PLANO_PROJECAO.md)
- **Duas leituras de despesa, mostradas SIMULTANEAMENTE (o toggle morreu):**
  - **DESPESAS (consumo)** = o que se gastou/comprou no mês (valor cheio, mesmo parcelado).
  - **A PAGAR (fluxo estrito)** = o que **vence e ainda não saiu**. À vista/PIX/débito/recorrência
    **não entram** (já saíram no ato). Só crédito não pago.
  - **SALDO** = caixa projetado de fim de mês = Receitas − todas as saídas de fluxo (pago + a vencer).
    NÃO é "Receitas − A pagar".
- **Eixo "já saiu vs a vencer"** (implementado): chave = forma de pagamento (à vista = já saiu;
  crédito = a vencer), refinada por vencimento. **Não** usar `a_vir` puro por data.
- **`PagamentoFatura` é a fonte única de "fatura paga"** (substitui `Parcela.pago`, que ficou
  obsoleto mas não foi dropado). Status derivado: `paga` / `aberta` / `a_vencer` / `atrasada`.
  O sistema **nunca presume** pago pela data — o usuário confirma.
- **Fatura NÃO é entidade** — é agregação de (`cartao_id`, `fatura_mes`, `fatura_ano`).
- **Fronteira travada por teste-guarda:** a projeção integral (realizado/a_vir/anual/consumo)
  **não depende de pagamento**; só o `a_pagar` consulta `PagamentoFatura`.
- Recorrência: on-the-fly, mensal, vigências versionadas, não passa por cartão.

## DASHBOARD — dois blocos (implementado)
- **Bloco 1 "Seu mês"** — mês corrente FIXO, sem navegação. 4 cards: RECEITAS · DESPESAS (consumo)
  · A PAGAR (fluxo estrito, vermelho, sem sublinha nem variação) · SALDO. Donut de categorias
  (lente consumo). Últimas transações.
- **Bloco 2 "Sua projeção"** — 12 meses. `series[0]` = **primeiro mês FUTURO com fluxo** (nunca o
  corrente) em card destacado; 11 linhas compactas. Exibe `despesas` (fluxo integral) sob o rótulo
  "a pagar" — porque **no futuro nada saiu ainda**, logo fluxo integral = tudo a pagar. O `a_pagar`
  estrito é exclusivo do Bloco 1.
- Endpoint: `GET /statistics/projection?meses=12`. O `/statistics/default-month` foi **absorvido**
  (o `/projection` já começa no mês certo) e removido do frontend.

## O QUE ESTÁ FEITO (backend ~399 testes verdes)
- Recorrência completa (modelo, vigências, CRUD, operações de erro, regra do dia, piso por DATA da
  primeira ocorrência).
- Projeção por competência, realizado/a-vir (§1.3.1), consumo.
- Dashboard em dois blocos (3 batches).
- **Eixo saiu/a-vencer**: campo `a_pagar`, vencimento real da Fonte 2 (derivado do `dia_vencimento`
  do cartão), fronteira do `pago` travada.
- **Lente 3d Leva 1**: `GET /invoices/{ano}/{mes}` (faturas de N cartões numa competência) +
  `GET /invoices/next-due`. Frontend: modo "Por mês" na tela de Cartões (toggle no header, total
  agregado, detalhe em modal).
- **Leva 2 backend**: `PagamentoFatura` + migration `a3d9f4c2b7e1` (vazia, sem backfill) +
  `PUT /invoices/{cartao_id}/{ano}/{mes}/pagamento` + `status` derivado nos 3 endpoints de fatura +
  `a_pagar` unificado + helper único de composição de fatura.
- Bugs corrigidos: cartão de débito, Salvar travado (o selo `✦ IA` pintava de âmbar sem selecionar),
  `inicioManual` morto, cartão sem defaults de dia, limite opcional, preview consumo×impacto.

## PRÓXIMO PASSO IMEDIATO
**Frontend da Leva 2** — badge de status (paga/aberta/a_vencer/atrasada, atrasada destacada) +
ação "marcar paga" (um clique, reversível) na tela de Cartões. **Urgente:** o backend já conta
faturas vencidas não confirmadas em "A pagar", e **não há UI para quitar**. Atenção: confirmar
pagamento muda o `a_pagar` → **invalidar as queries de statistics**, não só as de fatura.

## BACKLOG (por peso)
1. **3c — Resumo.** Precisa **redesenho conceitual**: o design antigo ("ambas as visões + gráfico
   estendido") ficou desatualizado com os dois blocos e a morte do toggle. Decidir o que o Resumo
   é agora, antes de codar.
2. **Importação de fatura/extrato** (`PLANO_IMPORTACAO.md`). Feature de várias sessões. Insumo real:
   fatura Nubank ("Parcela 4/7", linhas de IOF, seção "Pagamentos e Financiamentos" a ignorar).
   Coletar mais exemplos reais antes de implementar. **Requisito:** faturas importadas de meses
   passados entram já marcadas como pagas.
3. **Backend expor a competência da compra** — mata a degradação do preview no caso `mes_offset=0`.
4. **`CardFormModal`**: botão sempre clicável + erro inline (consistência com o AddTransactionPage).
5. **Dívidas registradas:**
   - **Compra retroativa em fatura paga**: aceita, status continua `paga` — o pagamento confirmado
     não cobre o lançamento novo. Furo silencioso. Decidir: invalidar a confirmação, ou sinalizar.
   - `editar data_vencimento` de parcela não rederiva `fatura_mes` (pré-existente).
   - `transacoes.cartao_id` e `parcelas.cartao_id` são `NO ACTION` — "excluir cartão" na UI bateria
     em FK. Hoje a UI só desativa.
   - `Parcela.pago` obsoleto (não dropado). `total_parcelas_pagas`, `?pago=` e `ParcelaResponse.pago`
     mantidos como legado (o SummaryPage ainda lê `!p.pago`).
6. **Bugs visuais**: o "+" (FAB) cortado no mobile; o segundo retângulo/badge duplicado no cartão.
7. UI pendentes: favicon + Open Graph, redirect apex hivvo.app → app.hivvo.app, e-mail de reset com
   template HTML.
8. Encerrar recorrência em data futura (PATCH aceitar `mes_fim`/`ano_fim`).
9. Reorganização Perfil vs. Configurações.

## APRENDIZADOS DESTA SESSÃO
- Os bugs mais importantes vieram de **usar o produto como usuário novo**, não de ler código. O
  "A pagar" inflado, o "Projeção de julho" sem sentido, o Salvar travado — todos achados na tela.
- **Confusão do usuário ≠ código quebrado.** "Sinto que nada funciona mas está funcionando" era
  dados bagunçados + falta de clareza visual. Consultar o banco direto dissolveu em segundos.
- **Um número certo pela lógica errada ainda é um bug.** O Saldo acertava porque o "A pagar" errava.
- **Não construir defesa contra um estado que o sistema corrigido não produz** (não zerar campos de
  débito no backend; não fazer backfill de migration sem base instalada).
- **Colisão de cor = colisão de significado.** O `✦ IA` em âmbar (a cor de "selecionado") fez o
  usuário achar que a categoria estava escolhida.
- Quando o Claude Code discorda com evidência, ele costuma estar certo. Verificar > presumir.
