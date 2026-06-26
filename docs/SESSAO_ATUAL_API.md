# Hivvo — Sessão Atual

## Antes de começar
Leia `docs/Hivvo_Referencia.md`, `docs/SESSAO_ATUAL.md`, `docs/AUDITORIA_SEGURANCA.md`, `docs/AUDITORIA_TECNICA.md` e `docs/PLANO_EXECUCAO_API.md` para entender o produto, a arquitetura **real**, as decisões de stack e o plano de correção em andamento. Não proponha alternativas de tecnologia — já decididas. Uma tarefa/batch por vez, com aprovação antes do commit.

---

## Estado do Projeto

**Fase atual:** Hardening pré-deploy (correções de segurança e técnicas)
**Status:** As fases de construção (backend + frontend + telas) estão concluídas e o app é funcional/instalável. Em 10/06/2026 o backend passou por **duas auditorias** (segurança e técnica) que revelaram **bloqueadores de lançamento**. O trabalho ativo agora é executar o plano de correção (`docs/PLANO_EXECUCAO_API.md`) **antes** do deploy.
**Próximo passo imediato:** Batch 4 — config, higiene e versionamento (F-01, F-09, F-13, F-14, F-16, F-22, F-23, F-06, F-11+T-08, T-06, T-07, T-28).
**Batch 1 concluído (11/06/2026, commitado):** lógica de fatura/parcela/estatísticas consolidada em `app/services/`.
**Batch 2 concluído (11/06/2026, commitado):** primeira suíte automatizada — 44 testes (42 pass + 2 xfail), 100% de cobertura em `services/faturas.py` e `services/parcelas.py` — ver seção "Batch 2" abaixo.
**Batch 3a concluído (12/06/2026, commitado `c315a3a`):** validação de entrada + fechamento dos 2 xfail (T-33, T-38, T-40, T-35 parte de schema) — ver seção "Batch 3a" abaixo.
**Batch 3b concluído (12/06/2026, commitado `124086f`):** comportamento de endpoint (T-36, T-34, T-35-endpoint, T-41, T-37, T-27 data de negócio) — ver seção "Batch 3b" abaixo. **Fecha o Batch 3 inteiro.**
**Fase 2 cross-repo concluída (12/06/2026, commitado `2fc837f`):** `POST /ai/suggest-category` — endpoint dedicado de sugestão de categoria, stateless (raiz do FE-08; o **Web-Batch 4** do hivvo-web vai consumi-lo) — suíte com **101 testes, todos verdes** — ver seção "Fase 2" abaixo.
**Teste de regressão round-trip parcelada→fatura concluído (26/06/2026, commitado `f3565c8`):** só testes — fecha o gap de cobertura do caminho de SUCESSO da criação parcelada (havia só atomicidade/FALHA do T-41). Suíte com **103 testes, todos verdes** — ver seção "Regressão round-trip" abaixo.
**T-29 ordenação estável de transações concluído (26/06/2026, aguardando commit):** desempate determinístico `data DESC, id DESC` em `GET /transactions` e nas avulsas do detalhe de fatura. Suíte com **106 testes, todos verdes** — ver seção "T-29" abaixo.
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

## Testes — Estado Real

✅ **Suíte automatizada (Batches 2, 3a, 3b, Fase 2, regressão round-trip e T-29):** `tests/` com pytest — **106 testes, todos verdes, zero xfail** (`tests/services/` domínio com SQLite in-memory; `tests/schemas/` validação pydantic pura; `tests/routers/` endpoints via TestClient com override de auth/sessão, incluindo isolamento entre usuários, o round-trip de criação parcelada→fatura e a ordenação estável de transações), 100% de cobertura nas funções de fatura/parcela (`services/faturas.py`, `services/parcelas.py`). Datas de negócio nos testes: sempre fixadas via patch em `app.core.dates.hoje` — nenhum teste depende do relógio real. Rodar com `venv\Scripts\python.exe -m pytest tests`. Os "Blocos" abaixo foram **testes manuais end-to-end**, valiosos mas não regressivos.

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

*Última atualização: 26 de junho de 2026 — T-29 ordenação estável de transações (`data DESC, id DESC` em GET /transactions e avulsas de fatura; 106 testes verdes). Próximo: Batch 4 (config, higiene e versionamento) · Web-Batch 4 consome o novo endpoint.*
*Projeto: Hivvo — gestão financeira pessoal com IA · Repositório FinanceAI original: github.com/lucasdonnangelo/financeai*
