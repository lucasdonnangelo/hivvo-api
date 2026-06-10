# Auditoria Técnica — hivvo-api

**Data:** 10 de junho de 2026
**Escopo:** Backend FastAPI (`hivvo-api`) — arquitetura, organização, banco de dados, performance, escalabilidade, manutenibilidade, design de API, integrações, qualidade de domínio e prontidão operacional.
**Commit auditado:** `0b7f464` (branch `master`).
**Natureza:** Diagnóstico somente leitura. Nenhum arquivo de código foi alterado.
**Relação com a auditoria de segurança:** este relatório **não reanalisa segurança**. Onde um ponto técnico toca segurança, há referência cruzada aos achados `F-xx` de `docs/AUDITORIA_SEGURANCA.md`.

**Suíte de testes:** solicitado rodar e reportar cobertura — **não existe suíte de testes no projeto** (nenhum diretório `tests/`, nenhum `test_*.py`, `pytest` ausente de `requirements.txt`). Cobertura efetiva: **0%**. Ver T-18.

**Legenda de esforço:** P = até meio dia · M = 1–2 dias · G = 3+ dias.
**Baldes:** [BEM CONSTRUÍDO] / [ACEITÁVEL] / [CORRIGIR] / [REFATORAR] / [RISCO FUTURO].

---

## 1. Resumo Executivo

O hivvo-api é uma base de código **pequena, legível e consistente** (~33 arquivos de aplicação), com a lógica de domínio mais difícil — o ciclo de fatura com fechamento/offset/clamp de dia — implementada **corretamente e de forma uniforme** nos três pontos que a calculam. O escopo por usuário é sólido (confirmado na auditoria de segurança), `Decimal/Numeric(15,2)` é usado em todos os valores monetários e as migrações Alembic estão limpas e reversíveis.

Os problemas se concentram em quatro frentes:

1. **O padrão arquitetural declarado não foi implementado.** `app/repositories/` e `app/services/` estão **vazios** — toda a lógica de negócio (incluindo o parcelamento, diferencial do produto) vive dentro dos routers, em funções privadas intestáveis isoladamente. A documentação (`Hivvo_Referencia.md` §6) afirma "repositories 100% reaproveitado", o que não corresponde ao código.
2. **Zero testes.** A aritmética de parcelas e fatura — exatamente onde "a precisão dos cálculos é o core do produto" — não tem um único teste automatizado. Há ao menos 4 bugs de domínio confirmados por leitura estática (T-34, T-36, T-37, T-40) que uma suíte mínima teria pego.
3. **Banco e queries não estão prontos para o crescimento previsto.** Conexão **direta** ao Supabase (não o pooler), sem `pool_pre_ping`; nenhum endpoint de listagem tem paginação; índices compostos ausentes nos padrões de acesso dominantes; filtros por `extract(month/year)` que impedem uso de índice; agregações feitas em Python carregando linhas inteiras; N+1 em `GET /cards`; `POST /ai/chat` dispara ~16 queries por mensagem.
4. **Caminho síncrono frágil para o Gemini.** Retry com `time.sleep` de até ~20s **sem timeout** no client, dentro do threadpool do Starlette — sob instabilidade do Gemini (os 503s já observados), poucas conversas simultâneas conseguem esgotar as threads e travar a API inteira.

Há ainda um achado de **integridade entre usuários** que complementa a auditoria de segurança: `PUT /transactions/{id}` aceita `cartao_id` sem validar propriedade, e as agregações de `GET /cards` não filtram por `usuario_id` — um usuário consegue inflar o total de fatura exibido a outro usuário (T-36).

### Contagem por classificação

| Classificação | Qtd. |
|---|---|
| [CORRIGIR] | 16 |
| [REFATORAR] | 4 |
| [RISCO FUTURO] | 4 |
| [ACEITÁVEL] | 6 |
| [BEM CONSTRUÍDO] | (ver §12 — Pontos Fortes) |

### Prioridades [ANTES DO DEPLOY]

1. **T-36** — Validar propriedade de `cartao_id` no update + filtrar `usuario_id` nas agregações de `GET /cards` (integridade entre usuários).
2. **T-34** — `DELETE /transactions/{id}?deletar_parcelas=false` causa 500 por violação de FK.
3. **T-13** — Trocar a conexão direta ao Supabase pelo transaction pooler + `pool_pre_ping`.
4. **T-21** — Timeout e limites no caminho síncrono do Gemini (risco de travar a API).
5. **T-09/T-10** — Índices compostos + filtros sargáveis por data.
6. **T-12** — Paginação (ou ao menos teto) nos endpoints de listagem.
7. **T-23** — Suíte mínima de testes para parcelamento e ciclo de fatura.
8. **T-35/T-40** — Validação e consistência derivada nos `update` de transação/cartão.
9. **T-42** — Definir e automatizar `alembic upgrade head` no deploy.
10. **T-28** — Versionar a API (`/api/v1`) antes de existirem clientes em produção.

---

## 2. Dimensão 1 — Arquitetura e camadas

### T-01 — Repository Pattern declarado, mas não implementado **[REFATORAR]** — Prioridade alta · Esforço G · [PÓS-DEPLOY]

**Localização:** `app/repositories/__init__.py` (vazio), `app/services/__init__.py` (vazio); routers em geral.

**O que existe hoje:** A arquitetura declarada (`docs/Hivvo_Referencia.md` §5–6: "Repository Pattern (migrado do FinanceAI)", "repositories.py ✅ 100% reaproveitado") não corresponde ao código: as duas pastas existem apenas com `__init__.py` vazios. Todo acesso a dados e toda regra de negócio estão dentro dos routers. Exemplos: a criação de parcelas e o cálculo de vencimento — o diferencial do produto — são funções privadas de router (`_criar_parcelas` em `app/routers/transactions.py:61-86`, `_data_vencimento_parcela` em `:36-58`); o build de contexto da IA são ~150 linhas dentro de `app/routers/ai.py:43-193`.

**Avaliação:** Para o tamanho atual, a estrutura "router gordo" funciona e é legível. O custo real é (a) lógica de domínio intestável sem subir HTTP, (b) duplicação entre routers (T-04) e (c) drift documental — quem ler a referência espera camadas que não existem.

**Recomendação:** Não é necessário introduzir o Repository Pattern completo antes do deploy. Em vez disso: extrair a lógica de domínio pura para `app/services/` em módulos sem dependência de FastAPI — `services/faturas.py` (`_add_months`, `_data_vencimento_parcela`, `_fatura_cartao_avulso`, `_current_open_fatura`, `_fatura_vencimento`), `services/parcelas.py` (`_criar_parcelas`), `services/estatisticas.py` (`_agregar`, `_categorias`, `_buscar_mes`), `services/ai_contexto.py`. Isso resolve T-02 e T-04, viabiliza T-18 (testes unitários) e alinha código com a documentação (ou atualizar a documentação, se a decisão for manter routers).

### T-02 — Acoplamento entre routers via import de helpers privados **[CORRIGIR]** — Prioridade média · Esforço P · [PÓS-DEPLOY]

**Localização:** `app/routers/ai.py:21` — `from app.routers.statistics import _agregar, _buscar_mes, _categorias`.

**O que existe hoje:** O router de IA importa três funções privadas (prefixo `_`) de outro router. Routers passam a depender uns dos outros, e uma mudança "interna" em `statistics.py` quebra `ai.py` silenciosamente.

**Recomendação:** Mover os helpers compartilhados para `app/services/estatisticas.py` (resolve-se junto com T-01).

### T-03 — Injeção de dependências consistente **[BEM CONSTRUÍDO]**

**Localização:** todos os routers.

**O que existe hoje:** `Depends(get_session)` + `Depends(get_current_user)` aplicados uniformemente em todos os endpoints autenticados; nenhum endpoint cria sessão manualmente (exceto `/health`, que é deliberado); nenhum router acessa `engine` direto. Padrão coeso e correto.

### T-04 — Lógica de fatura duplicada em 3 routers + 1 script **[CORRIGIR]** — Prioridade alta · Esforço P · [PÓS-DEPLOY]

**Localização:** `_add_months` em `app/routers/transactions.py:26-33`, `app/routers/cards.py:25-32`, `app/routers/invoices.py:25-32` e `populate_db.py:45-52` (cópias idênticas); `_fatura_vencimento` duplicada em `cards.py:35-39` e `invoices.py:35-39`; `populate_db.py:43` admite "Helpers (espelham transactions.py)".

**O que existe hoje:** A aritmética de meses — base de todo o ciclo de fatura — existe em 4 cópias. Hoje estão idênticas; uma correção futura aplicada em só uma delas cria divergência silenciosa de cálculo entre criação de transação, listagem de cartões e detalhe de fatura (exatamente o tipo de bug de precisão que o produto não pode ter).

**Recomendação:** Consolidar em um único módulo (`app/services/faturas.py`) e importar nos três routers e no script. É a extração de maior retorno por esforço do projeto.

---

## 3. Dimensão 2 — Organização do código

### T-05 — Estrutura de pastas e nomenclatura **[ACEITÁVEL]**

**O que existe hoje:** Separação `models/ schemas/ routers/ core/` clara; nomenclatura consistente (domínio em português — `Transacao`, `Parcela`, `fatura_mes` —, infraestrutura em inglês); um schema e um router por domínio; formato dos routers uniforme (prefixo + tags, response_model em tudo, raiz `""` sem trailing slash documentado em `SESSAO_ATUAL.md`). Sem código morto dentro de `app/` além das pastas vazias (T-01).

### T-06 — Artefatos de desenvolvimento soltos na raiz **[CORRIGIR]** — Prioridade média · Esforço P · [ANTES DO DEPLOY]

**Localização:** raiz do projeto — `uvicorn.log`, `uvicorn.err`, `uvicorn_debug.log/.err`, `uvicorn_debug2.log/.err`, `cookies.xml`, `populate_db.py` (todos untracked, conforme `git status`).

**O que existe hoje:** Logs de desenvolvimento com dados sensíveis (já detalhado em **F-11** da auditoria de segurança — não repito aqui o aspecto de segurança) e um script de seed apontando para o banco de produção com e-mail real hardcoded (`populate_db.py:40`). Nada disso está no `.gitignore`.

**Recomendação:** Remover os logs/`cookies.xml`, adicionar `*.log`, `*.err`, `cookies.xml` ao `.gitignore`; mover `populate_db.py` para `scripts/` com guarda explícita contra rodar com `ENVIRONMENT=production` (hoje ele escreve direto no Supabase de produção).

### T-07 — Configuração centralizada, com vazamentos pontuais **[CORRIGIR]** — Prioridade média · Esforço P · [ANTES DO DEPLOY]

**Localização:** `app/core/config.py` (correto); `main.py:25` (CORS hardcoded — aspecto funcional do **F-03**); `app/routers/ai.py:29` (`_MODEL = "gemini-2.5-flash"`), `:216` (janela de 24h), `:272` (limite de 50 mensagens), `:311` (`_RETRY_WAITS`); `app/routers/auth.py:46-47` (lockout — esses dois estão OK como constantes de módulo).

**O que existe hoje:** `Settings` via pydantic-settings é o padrão correto e está em uso, mas o CORS ignora `settings.FRONTEND_URL` (vai quebrar no deploy — cruzar com F-03) e os parâmetros operacionais da IA (modelo, janela de sessão, tamanho do contexto, retries) estão hardcoded no router.

**Recomendação:** `allow_origins=[settings.FRONTEND_URL]` (já recomendado em F-03); promover modelo Gemini, janela de 24h, limite de 50 mensagens e política de retry para `Settings` — são exatamente os valores que se quer ajustar em produção sem redeploy de código.

### T-08 — Logging de depuração esquecido no caminho de produção **[CORRIGIR]** — Prioridade média · Esforço P · [ANTES DO DEPLOY]

**Localização:** `app/routers/ai.py:211-234` — seis `logger.info(...)` em `GET /ai/historico`, incluindo um loop que loga **o conteúdo de cada mensagem** do chat (`:233-234`).

**O que existe hoje:** Instrumentação adicionada durante a investigação dos 503s do Gemini e não removida. Em produção, cada abertura do Assistente despeja o histórico do usuário no log em nível INFO (a dimensão de privacidade já está coberta pelo **F-11**; aqui o ponto é higiene e ruído de log).

**Recomendação:** Remover os logs de conteúdo; manter no máximo um `logger.debug` com contagens/IDs.

---

## 4. Dimensão 3 — Banco de dados

### T-09 — Índices ausentes nos padrões de acesso dominantes **[CORRIGIR]** — Prioridade alta · Esforço P (1 migration) · [ANTES DO DEPLOY]

**Localização:** `alembic/versions/abdb546095c0_initial_schema.py` (índices criados: apenas `usuario_id` em cada tabela + `parcelas.transacao_id`); `alembic/versions/1046109fa1a2` (não indexa `sessao_id`); models correspondentes.

**O que existe hoje vs. o que as queries pedem:**

| Tabela | Índices hoje | Padrões de query sem índice adequado |
|---|---|---|
| `transacoes` | `usuario_id` | `cartao_id + fatura_mes + fatura_ano` (`cards.py:81-88`, `invoices.py:65-73,130-141`); `usuario_id + data` (todas as listagens/estatísticas) — **`cartao_id` não tem índice nenhum** |
| `parcelas` | `usuario_id`, `transacao_id` | `cartao_id + fatura_mes + fatura_ano` (`cards.py:71-78`, `invoices.py:57-63,118-128`); `usuario_id + fatura_mes + fatura_ano` (`installments.py:34-37`, `ai.py:46-54`) — **`cartao_id` não tem índice nenhum** |
| `chat_messages` | `usuario_id`, `created_at` | `usuario_id + sessao_id` (`ai.py:223-230,276-281`) — **`sessao_id` sem índice** (`app/models/chat.py:13`) |

Hoje, com poucas linhas, tudo resolve por seq scan. Com o crescimento previsto (público de alto volume, anos de histórico), cada render da tela de Cartões varre a tabela `parcelas` inteira.

**Recomendação:** Uma migration adicionando: `ix_transacoes_usuario_data (usuario_id, data)`, `ix_transacoes_cartao_fatura (cartao_id, fatura_ano, fatura_mes)`, `ix_parcelas_cartao_fatura (cartao_id, fatura_ano, fatura_mes)`, `ix_parcelas_usuario_fatura (usuario_id, fatura_ano, fatura_mes)`, `ix_chat_messages_sessao_id (sessao_id)`. Nota: o composto `(usuario_id, data)` só será usado depois de corrigir T-10.

### T-10 — Filtros por `extract("month"/"year")` impedem uso de índice **[CORRIGIR]** — Prioridade alta · Esforço P · [ANTES DO DEPLOY]

**Localização:** `app/routers/statistics.py:74-76` (`_buscar_mes` — usado também por `ai.py`), `app/routers/transactions.py:116-118`.

**O que existe hoje:** O filtro mensal usa `extract("month", Transacao.data) == mes AND extract("year", ...) == ano`. Expressão sobre a coluna é non-sargable: o Postgres não usa índice em `data` e varre todas as transações do usuário (ou da tabela) a cada dashboard, estatística e mensagem de IA — `_build_historico_anual` faz isso **12 vezes** por mensagem de chat.

**Recomendação:** Trocar por range: `Transacao.data >= date(ano, mes, 1)` e `Transacao.data < date(prox_ano, prox_mes, 1)`. Mudança localizada em 2 funções, habilita o índice composto de T-09.

### T-11 — Colunas monetárias NULLABLE e ausência de constraints de integridade **[CORRIGIR]** — Prioridade média · Esforço P–M · [PÓS-DEPLOY]

**Localização:** `alembic/versions/abdb546095c0:70` (`transacoes.valor` `nullable=True`), `:91,94-95` (`parcelas.valor_parcela`, `taxa_juros`, `valor_juros` `nullable=True`); causa: `Field(sa_column=Column(Numeric(15, 2)))` sem `nullable=False` em `app/models/transaction.py:17` e `app/models/installment.py:17,22-23` — o `sa_column` explícito herda o default do SQLAlchemy (nullable), ignorando a obrigatoriedade do tipo Python.

**O que existe hoje:** As colunas monetárias core do produto aceitam NULL no banco, embora o model Python as trate como obrigatórias — um INSERT fora da aplicação (script, SQL manual, bug futuro) grava NULL e quebra agregações. Não há nenhum CHECK (`valor > 0`, `tipo IN ('receita','despesa')`, `fatura_mes BETWEEN 1 AND 12`, `numero_parcela <= total_parcelas`), nem UNIQUE em `parcelas (transacao_id, numero_parcela)` (permite parcela duplicada) ou `categorias (usuario_id, nome)` (permite categoria custom duplicada — `categories.py:45-60` não verifica).

**Recomendação:** Migration com `ALTER COLUMN ... SET NOT NULL` (+ `nullable=False` nos models) para as colunas monetárias; adicionar os CHECKs e o UNIQUE de parcelas. São a "rede de segurança" de precisão que o produto declara como core. Hoje a validação existe só no Pydantic da criação — e o **F-15** já mostrou que o caminho do update não repete essas validações.

### T-12 — Nenhum endpoint de listagem tem paginação **[CORRIGIR]** — Prioridade alta · Esforço M · [ANTES DO DEPLOY]

**Localização:** `GET /transactions` (`transactions.py:101-131`), `GET /installments` (`installments.py:16-40`), `GET /ai/historico` (`ai.py:196-239`), `GET /cards/{id}/invoices` (`invoices.py:49-105`).

**O que existe hoje:** Todas as listagens retornam o resultado completo. `mes`/`ano` em `/transactions` são **opcionais** — sem eles a API devolve a base inteira do usuário (o backup do frontend usa exatamente isso, `getAllTransactions()`). `/installments` sem filtro retorna todas as parcelas históricas. Para o público-alvo (180+ transações/mês, crescendo por anos), em 3 anos isso são ~6.500 linhas serializadas por request de backup, e o widget de parcelas do Dashboard (`useInstallments`) cresce sem teto.

**Recomendação:** Adicionar `limit`/`offset` (com `limit` default e máximo, ex. 100/500) aos endpoints de listagem e expor `X-Total-Count` ou envelope `{items, total}`. Importante fazer **antes** do deploy: adicionar paginação depois muda o contrato de resposta (lista nua → envelope) e quebra o frontend publicado (ver T-21/T-22). Para o caso backup, criar endpoint dedicado de export em vez de listagem irrestrita.

### T-13 — Conexão direta ao Supabase, sem pooler e sem `pool_pre_ping` **[CORRIGIR]** — Prioridade alta · Esforço P · [ANTES DO DEPLOY]

**Localização:** `app/core/database.py:4-7`; `.env` (`DATABASE_URL` → `db.pnpqiwyybvntsiuftjez.supabase.co:5432` — host/porta verificados sem ler credenciais).

**O que existe hoje:** O engine aponta para a **conexão direta** do Supabase (porta 5432), não para o transaction pooler (`*.pooler.supabase.com:6543`). `create_engine` usa defaults: `QueuePool` com `pool_size=5` + `max_overflow=10` → até **15 conexões por instância**. O limite de conexões diretas do Supabase (free/small tier, ~60, compartilhado com o próprio Supabase) esgota com poucas réplicas no Railway — e cada redeploy sobrepõe instância velha e nova, dobrando temporariamente o consumo. Sem `pool_pre_ping`, conexões derrubadas por idle timeout do Supabase geram `OperationalError` 500 intermitente na primeira request após ociosidade — clássico em free tier do Railway/Render que hiberna.

**Recomendação:** Em produção, usar a URL do **transaction pooler** (porta 6543) — compatível com o uso atual (psycopg2 sem prepared statements e sem `SET` de sessão); adicionar `pool_pre_ping=True`, `pool_recycle=300` e dimensionar `pool_size`/`max_overflow` explícitos (ex. 5/5). Cruzar com **F-02**: a troca de papel (não-superusuário) pode ser feita na mesma mudança de URL.

### T-14 — Sem `ON DELETE` em nenhuma FK — exclusão de conta (F-07) será dolorosa **[RISCO FUTURO]** — Prioridade média · Esforço P · [ANTES DO DEPLOY] (junto com F-07)

**Localização:** `alembic/versions/abdb546095c0:48,60,80-81,104-106`; `268b08c02e0a:29`; `207ebc9ef981:29`; `b034186cbf34:29` — todas as FKs sem `ondelete`.

**O que existe hoje:** Nenhum comportamento de cascade. O `DELETE /auth/me` exigido pelo **F-07** (LGPD) terá que apagar manualmente, em ordem correta, `parcelas` → `transacoes` → `cartoes`/`categorias`/`chat_messages`/`refresh_tokens`/`password_reset_tokens` → `usuarios`; qualquer esquecimento gera violação de FK no meio da transação. O mesmo vale para o bug já existente em T-24 (`parcelas.transacao_id`).

**Recomendação:** Migration adicionando `ondelete="CASCADE"` nas FKs de `usuario_id` (todas as tabelas) e em `parcelas.transacao_id`. Torna o F-07 um `DELETE FROM usuarios WHERE id=...` em transação única e elimina a classe de erro do T-24.

### T-15 — Migrações Alembic **[BEM CONSTRUÍDO]** / drift model↔schema **[ACEITÁVEL]**

**Localização:** `alembic/versions/*` (5 revisões lineares), `alembic/env.py`.

**O que existe hoje:** Cadeia linear sem branches; todos os `downgrade()` implementados e corretos; `1046109fa1a2` usa o padrão correto para adicionar coluna NOT NULL em tabela populada (nullable → backfill `gen_random_uuid()` → `SET NOT NULL`); `env.py` importa `app.models` para registrar metadata e lê a URL de `settings` (consistente com a aplicação). **Drift:** comparei cada model com as migrations — não há drift estrutural; a única divergência é semântica (colunas monetárias nullable, T-11). Ressalva menor: `env.py` injeta a URL com `config.set_main_option`, o que falha se a senha contiver `%` (escape de configparser) — improvável, mas vale conhecer.

### T-16 — Desnormalização deliberada de categoria/descrição **[ACEITÁVEL]**

**Localização:** `app/models/transaction.py:18` (`categoria: str`), `app/models/installment.py:25-26` (cópia de `descricao`/`categoria` na parcela).

**O que existe hoje:** Categoria é string solta (não FK para `categorias`), e a parcela copia descrição/categoria da transação. Trade-off consciente (soft delete de categoria preserva histórico — decisão registrada em `SESSAO_ATUAL.md`), com o custo conhecido: renomear categoria não propaga, e categoria custom apagada continua nas transações antigas como texto. Adequado ao produto; apenas documentar.

---

## 5. Dimensão 4 — Performance

### T-17 — N+1 e agregação em Python nos caminhos quentes **[CORRIGIR]** — Prioridade alta · Esforço M · [ANTES DO DEPLOY] (cards/invoices) / [PÓS-DEPLOY] (statistics)

**Localização e detalhamento:**

1. **`GET /cards` — N+1 real** (`cards.py:68-94`): 1 query para os cartões + **2 agregações SQL por cartão** dentro do loop. 5 cartões = 11 queries por render da tela inicial de Cartões. Reescrever com duas queries `GROUP BY cartao_id` (uma para parcelas, uma para avulsas) cobrindo todos os cartões de uma vez.
2. **`GET /cards/{id}/invoices` — varredura completa** (`invoices.py:57-93`): carrega **todas** as parcelas e todas as avulsas do cartão (histórico completo, sem filtro de período) e monta os totais por fatura em um dict Python. Cresce linearmente com os anos de uso. Substituir por `SELECT fatura_ano, fatura_mes, SUM(...), COUNT(...) GROUP BY` no banco.
3. **Estatísticas em Python** (`statistics.py:38-67,70-77`): `_agregar` e `_categorias` materializam todas as transações do mês e somam em Python; `monthly_stats` faz isso para 2 meses (atual + anterior). Para 180 tx/mês é irrelevante; para o público de alto volume e para o uso repetido via IA (T-19), mover para `SUM(...) FILTER (WHERE tipo='receita')` / `GROUP BY categoria` no banco. `yearly_stats` (`statistics.py:116-131`) ao menos evita N+1 buscando o ano em 1 query — bom — mas idem: é um `GROUP BY date_trunc('month', data)` natural.
4. **`_total_parcelas_proximo_mes`** (`ai.py:43-55`): carrega as linhas para somar em Python — é um `SELECT SUM(valor_parcela)`.

**Observação de honestidade:** os efeitos sob carga só são confirmáveis em runtime; a análise acima é estática (contagem de queries e padrões de varredura), mas os padrões são inequívocos.

### T-18 — (movido para Dimensão 6 — ver T-23, testes) —

*(numeração reservada; ver T-23.)*

### T-19 — Custo do build de contexto da IA: ~16 queries e prompt potencialmente grande por mensagem **[CORRIGIR]** — Prioridade alta · Esforço M · [PÓS-DEPLOY] (com T-10 antes do deploy já mitigando o pior)

**Localização:** `app/routers/ai.py:252-309` (`chat`), `:72-93` (`_build_historico_anual`).

**O que existe hoje, por mensagem de chat:** 1 query de histórico (50 msgs) + 1 count de sessão + `_buscar_mes` do mês atual + `_buscar_mes` do mês anterior (variação) + parcelas do próximo mês + **12 × `_buscar_mes`** no histórico anual ≈ **16 queries**, cada `_buscar_mes` materializando todas as transações do mês para agregar em Python — e todas non-sargables (T-10). Payload ao Gemini: o bloco de histórico anual é compacto (12 linhas — bem desenhado), mas o histórico de conversa são até 50 mensagens × até 4.000 chars ≈ até ~200 KB/request — custo de tokens e latência direto (e cruza com **F-04**: cada request dessas é paga).

**Recomendação:** (a) reduzir as 14 queries de agregação para 1–2 `GROUP BY mês` no banco; (b) cachear o contexto financeiro por usuário com invalidação simples (TTL curto ou bump em escrita de transação) — ele só muda quando o usuário grava transações; (c) reavaliar a janela de 50 mensagens completas vs. N mensagens recentes + resumo. A latência total (Gemini incluído) só é mensurável em runtime — registrado como pendente de medição.

---

## 6. Dimensão 5 — Escalabilidade

### T-20 — API stateless **[BEM CONSTRUÍDO]**

**O que existe hoje:** Nenhum estado em memória entre requests: lockout de login no banco (`usuarios.tentativas_login/bloqueado_ate`), refresh tokens no banco, sessões de chat no banco, JWT stateless. A aplicação escala horizontalmente sem sticky sessions. Única ressalva: o rate limiting que será adicionado (F-04) deve usar armazenamento compartilhado (Redis) e não memória de processo, para não regredir isso.

### T-21 — Gemini síncrono sem timeout pode esgotar o threadpool e travar a API **[CORRIGIR]** — Prioridade alta · Esforço M · [ANTES DO DEPLOY]

**Localização:** `app/routers/ai.py:311-350` (loop de retry com `time.sleep`), `:313` (`genai.Client` sem `http_options`/timeout).

**O que existe hoje:** O endpoint `chat` é `def` síncrono — roda no threadpool do Starlette (default ~40 threads, compartilhado por **todos** os endpoints síncronos da API). O caminho de falha do Gemini: até 5 tentativas + sleeps de 2+4+6+8 = **20s dormindo** + 5× a latência da chamada — e o client genai é criado **sem timeout configurado**, então uma conexão pendurada segura a thread indefinidamente. Com o Gemini instável (os 503s persistentes já observados em teste), ~40 conversas simultâneas em retry esgotam o pool e **a API inteira para de responder, incluindo `/health`** — o que no Railway pode disparar restart em loop. O retry em si está bem implementado (backoff, log, mensagem amigável; cruza com F-04 para o aspecto custo).

**Recomendação:** (1) configurar timeout explícito no client (`http_options=types.HttpOptions(timeout=...)`, ex. 30s); (2) reduzir o orçamento total de retry no caminho da request (ex. 2 tentativas; 5 retries fazem sentido em job assíncrono, não com o usuário esperando); (3) médio prazo: tornar o endpoint `async` com client async, tirando a espera do threadpool. Os failure modes restantes (Gemini fora → 503 amigável; chave ausente → 503 claro em `:258-262`) estão corretos.

### T-22 — Oportunidades de cache **[ACEITÁVEL]** — [PÓS-DEPLOY]

**O que existe hoje:** Nenhum cache (além do TanStack Query no frontend). Candidatos com bom retorno: contexto financeiro da IA (T-19), estatísticas de meses fechados (imutáveis na prática), categorias (já é constante em memória para as padrão — `categories.py:12-28`, adequado). Nenhum é bloqueador.

---

## 7. Dimensão 6 — Manutenibilidade

### T-23 — Zero testes; a lógica de parcelamento e fatura não tem nenhuma verificação automatizada **[CORRIGIR]** — Prioridade **máxima** da dimensão · Esforço M–G · [ANTES DO DEPLOY]

**Localização:** ausência de `tests/` em todo o projeto; `pytest` ausente de `requirements.txt`.

**O que existe hoje:** Nada. Todo o regime de qualidade é teste manual end-to-end (Blocos 1–5 do `SESSAO_ATUAL.md` — valioso, mas não regressivo). As funções mais críticas e mais cheias de borda do produto — `_add_months`, `_data_vencimento_parcela`, `_criar_parcelas` (arredondamento), `_fatura_cartao_avulso`, `_current_open_fatura` — são puras ou quase puras, ou seja, **trivialmente testáveis**, e não têm um teste. Bugs encontrados nesta auditoria por leitura (T-34, T-36, T-40) seriam pegos por testes de unidade/integração básicos. A auditoria de segurança também recomenda testes de isolamento entre usuários como compensação do F-02.

**Recomendação (ordem de valor):** (1) unit tests puros de fatura/parcela — fechamento dia 28/30/31, compra no dia do fechamento, dezembro→janeiro, offset 0/1/2, arredondamento com dízima, valores pequenos (T-33); (2) testes de API com banco de teste (SQLite in-memory funciona com SQLModel para o schema atual) cobrindo CRUD + isolamento entre usuários; (3) smoke test do build de contexto da IA com Gemini mockado. Meta mínima pré-deploy: 100% das funções de fatura/parcela cobertas.

### T-24 — Tratamento de erros sem handler central **[ACEITÁVEL]** → ver também F-14/F-16 — Esforço P · [PÓS-DEPLOY]

**Localização:** `main.py` (sem exception handlers); `HTTPException` ad hoc em todos os routers.

**O que existe hoje:** O formato de erro é o `{"detail": ...}` padrão do FastAPI, consistente entre rotas, com mensagens PT-BR uniformes — aceitável. Falta um handler central para exceções não-HTTP (hoje viram 500 genérico sem log estruturado) e os dois vazamentos pontuais já catalogados (F-14 `/health`, F-16 `sessao_id`). Adicionar um `exception_handler(Exception)` que loga com stack e retorna 500 genérico resolve a observabilidade do caso.

### T-25 — Logging e observabilidade inexistentes **[CORRIGIR]** — Prioridade alta · Esforço P–M · [ANTES DO DEPLOY]

**Localização:** projeto inteiro — único `logging.getLogger` em `ai.py:24`; nenhuma configuração de logging; nenhum Sentry/APM; nenhum request-id.

**O que existe hoje:** Em produção no Railway, os únicos sinais serão o access log do uvicorn e os prints de exceção. Sem Sentry, o primeiro 500 em produção será invisível até um usuário reclamar — num app financeiro entrando em produção, é o gap operacional mais barato de fechar.

**Recomendação:** (1) `logging.basicConfig`/dictConfig com nível por `ENVIRONMENT`; (2) Sentry (SDK FastAPI, free tier) antes do deploy; (3) middleware simples de request log com duração. Cruzar com F-11: nunca logar conteúdo de mensagens/tokens.

### T-26 — Type hints **[ACEITÁVEL]**

**O que existe hoje:** Helpers de domínio bem anotados (`-> dt.date`, `-> tuple[int, int]`, etc.); models e schemas tipados por construção. Faltas menores: retornos de endpoints não anotados (FastAPI não exige), `get_current_user` sem tipo de retorno (`core/auth.py:64`), `ctx: dict` sem shape (`ai.py:99`) — um `TypedDict`/dataclass documentaria o contrato entre `chat()` e `_build_system_instruction()`. Não bloqueia nada; melhorar oportunisticamente.

### T-27 — `datetime.utcnow()` deprecado + mistura UTC/hora local **[CORRIGIR]** — Prioridade média · Esforço P · [PÓS-DEPLOY]

**Localização:** `datetime.utcnow()` em `core/auth.py:23,38,51`, `routers/auth.py:107,113,221,257`, `models/user.py:14`, `models/chat.py:16`, `ai.py:216`; `dt.date.today()` em `models/card.py:23`, `models/category.py:16`, `models/installment.py:31`, `installments.py:61`, `cards.py:66`.

**O que existe hoje:** `utcnow()` está deprecado desde o Python 3.12 (datas naive) e convive com `date.today()`, que usa o **fuso local do servidor**. No Railway o servidor estará em UTC: para um usuário no Brasil (UTC-3), entre 21h e meia-noite, `date.today()` já é "amanhã" — `data_pagamento` preenchida automaticamente (`installments.py:61`) e a fatura aberta calculada em `cards.py:66` podem cair no dia/ciclo errado na janela noturna. Borda real para um app financeiro brasileiro.

**Recomendação:** Padronizar `datetime.now(timezone.utc)` para timestamps; para datas de negócio "hoje", decidir e fixar o fuso do produto (ex. `America/Sao_Paulo`) num helper único em vez de `date.today()` solto.

---

## 8. Dimensão 7 — Design de API

### T-28 — Sem versionamento de API **[CORRIGIR]** — Prioridade média · Esforço P · [ANTES DO DEPLOY]

**Localização:** `main.py:31-38` — routers montados na raiz (`/transactions`, `/cards`, ...).

**O que existe hoje:** Nenhum prefixo de versão. O cliente é um PWA — atualiza sozinho, **mas** o service worker do Vite PWA pode servir um bundle antigo por horas/dias após um deploy; nesse intervalo, frontend velho fala com API nova. Qualquer mudança de contrato (a paginação do T-12 é o exemplo imediato: lista nua → envelope) quebra usuários com app aberto/cacheado.

**Recomendação:** Montar tudo sob `/api/v1` antes do primeiro deploy (custo: um prefixo no `include_router` + a base URL do frontend). Depois que houver usuários, o mesmo movimento exige janela de compatibilidade dupla.

### T-29 — Consistência de status codes, response models e erros **[ACEITÁVEL]** — Esforço P · [PÓS-DEPLOY]

**O que existe hoje:** Muito consistente no geral: `response_model` em 100% dos endpoints; 201 em criações; 204 em deletes/updates sem corpo; erros sempre `{"detail": str}` em PT-BR; convenção de filtros uniforme (`mes`/`ano` com `ge/le`); rotas raiz `""` sem redirect 307 (decisão documentada). Desvios menores: `register` usa 400 para e-mail duplicado (409 é o semântico; ver também F-08 antes de mudar), `reset-password` usa 404 para token inválido e 400 para expirado (inconsistente entre si), e listas são retornadas "nuas" — sem envelope, o que colide com a futura paginação (T-12). Nenhuma convenção de ordenação exposta (fixa por endpoint — aceitável). `GET /transactions` ordena por `data DESC` sem desempate (`transactions.py:130`) — adicionar `id DESC` para ordenação estável entre páginas quando houver paginação.

---

## 9. Dimensão 8 — Integrações

### T-30 — Integração Gemini: retry bem feito, lacunas de timeout e cobertura **[ACEITÁVEL com ressalvas]** — ver T-21 para o aspecto crítico

**Localização:** `app/routers/ai.py:311-350`.

**O que existe hoje (bom):** retry 5× com backoff linear para `ServerError` (503), logging de tentativa, mensagem 503 amigável ao usuário, fail-fast claro quando `GEMINI_API_KEY` ausente (`:258-262`), resposta vazia tratada (`:325-329`), persistência user+assistant só após sucesso (atômica, `:352-365`).
**Lacunas:** sem timeout no client (→ T-21, crítico); o retry não cobre 429/`ClientError` de quota (vai direto pro `except Exception` → 503 sem retry — comportamento aceitável, mas cego ao `retry-after`); `genai.Client` reconstruído a cada request (custo pequeno; pode ser singleton de módulo); sem circuit breaker — com o Gemini fora, cada mensagem ainda gasta o orçamento inteiro de retry antes de falhar.

### T-31 — Integração Resend frágil: sem try/except, sem timeout, ordem envio→commit **[CORRIGIR]** — Prioridade média · Esforço P · [ANTES DO DEPLOY]

**Localização:** `app/routers/auth.py:225-240`.

**O que existe hoje:** Os aspectos de disponibilidade/segurança já estão em **F-17/F-18** (não repito). O ângulo técnico adicional: a ordem das operações é *enviar e-mail* → *commit do token* (`:226` antes de `:240`); se o commit falhar após o envio, o usuário recebe um link cujo token **não existe no banco** (reset impossível, sem erro visível). E `resend.api_key` é setado a cada request (global de módulo — funciona, mas é efeito colateral escondido num router).

**Recomendação:** Commitar o token antes (ou usar BackgroundTask para o envio, que também resolve F-17), try/except no envio com log, e mover a configuração da chave Resend para inicialização.

---

## 10. Dimensão 9 — Qualidade das funcionalidades (lógica de domínio)

### T-32 — Ciclo de fatura: correto e uniforme **[BEM CONSTRUÍDO]**

**Localização:** `transactions.py:36-58` (`_data_vencimento_parcela`), `:89-98` (`_fatura_cartao_avulso`), `cards.py:42-52` (`_current_open_fatura`), `cards.py:35-39`/`invoices.py:35-39` (`_fatura_vencimento`).

**O que existe hoje:** As três implementações do ciclo aplicam **a mesma convenção**: compra com `day > dia_fechamento` entra no ciclo seguinte (compra exatamente no dia do fechamento entra na fatura atual — convenção consistente, vale documentar); `mes_offset_vencimento` desloca fechamento→vencimento; o dia de vencimento é clampado pelo último dia do mês (`min(dia, monthrange(...))` — fevereiro/meses de 30 dias corretos); `_add_months` lida com overflow de ano corretamente, inclusive saltos >12 meses. `fatura_mes/ano` derivados da data de **vencimento** da parcela (decisão registrada em `SESSAO_ATUAL.md`) — aplicada consistentemente em `transactions.py:77-78`. A única fragilidade é estrutural (4 cópias — T-04) e a ausência de testes (T-23).

### T-33 — Arredondamento de parcelas: correto no caso geral, última parcela pode ficar ≤ 0 em valores pequenos **[CORRIGIR]** — Prioridade baixa (borda) · Esforço P · [PÓS-DEPLOY]

**Localização:** `transactions.py:63-64`.

**O que existe hoje:** `valor_base = (valor/total).quantize(0.01, ROUND_HALF_UP)`; `valor_ultima = valor − base×(n−1)` — a última parcela absorve a diferença, conforme a decisão documentada. Correto para valores normais (verificado manualmente para várias combinações). **Borda:** quando `valor/n` arredonda para cima, a última parcela pode zerar ou ficar **negativa**: R$ 0,10 em 12× → base R$ 0,01, última = 0,10 − 0,11 = **−R$ 0,01** persistido em `valor_parcela`. Improvável no público-alvo, mas é exatamente o tipo de imprecisão que o produto não pode exibir, e não há CHECK no banco que a impeça (T-11).

**Recomendação:** Validar `valor >= total_parcelas × 0.01` no schema de criação (rejeita o caso degenerado com 422), ou usar distribuição de resto (largest remainder). Adicionar o caso à suíte do T-23.

### T-34 — `DELETE /transactions/{id}?deletar_parcelas=false` → 500 por violação de FK **[CORRIGIR]** — Prioridade alta · Esforço P · [ANTES DO DEPLOY]

**Localização:** `transactions.py:199-215`; FK em `alembic/versions/abdb546095c0:105` (`parcelas.transacao_id` NOT NULL → `transacoes.id`, sem `ondelete`).

**O que existe hoje:** O parâmetro `deletar_parcelas: bool = Query(True)` oferece um caminho impossível: com `false` numa transação parcelada, o `session.delete(transacao)` viola a FK NOT NULL das parcelas → `IntegrityError` → **500**. O contrato do endpoint anuncia uma opção que sempre quebra.

**Recomendação:** Remover o parâmetro (sempre deletar as parcelas junto — semântica natural), ou implementá-lo de verdade (FK nullable + `SET NULL`). Resolve-se em conjunto com T-14 (cascades).

### T-35 — Update de transação não mantém consistência derivada (parcelas e fatura) **[CORRIGIR]** — Prioridade alta · Esforço M · [ANTES DO DEPLOY]

**Localização:** `transactions.py:179-196` (update genérico via `setattr`); criação: `:161-163` (fatura derivada) e `:170-172` (parcelas).

**O que existe hoje:** `PUT /transactions/{id}` aplica campos cegamente: (a) alterar `valor` de transação **parcelada** não recalcula as parcelas — a soma das parcelas diverge silenciosamente do valor da transação, e a divergência aparece nas faturas; (b) alterar `data` ou `cartao_id` de despesa avulsa de crédito não rederiva `fatura_mes/fatura_ano` (que na criação são calculados em `:162-163`) — a transação fica na fatura errada; (c) o cliente pode enviar `fatura_mes/fatura_ano` manualmente (já apontado como **F-15**; aqui o ângulo é a correção do domínio, não a validação). Para o produto cujo diferencial é precisão de parcelamento/fatura, o caminho de edição quebra os invariantes que o caminho de criação garante.

**Recomendação:** No update: rederivar `fatura_mes/ano` quando `data`/`cartao_id` mudarem; para transações parceladas, ou bloquear edição de `valor`/`data` (orientando excluir e recriar — UX já tem "Gerenciar parcelas"), ou recalcular as parcelas não pagas. Remover `fatura_mes/ano` do `TransacaoUpdate` (alinha com F-15).

### T-36 — `cartao_id` no update sem validação de propriedade + agregações de `GET /cards` sem filtro de usuário → poluição de fatura entre usuários **[CORRIGIR]** — Prioridade **alta** · Esforço P · [ANTES DO DEPLOY]

**Localização:** `transactions.py:190-191` (setattr sem checagem — o caminho de **criação** valida em `:141-144`, o de update não); `cards.py:71-78` e `:80-88` (agregações filtram só `cartao_id + fatura`, **sem `usuario_id`**).

**O que existe hoje:** Um usuário autenticado pode editar a própria transação apontando `cartao_id` para um cartão **de outro usuário** (o update não repete a validação de propriedade da criação). As listagens de fatura em `invoices.py` filtram por `usuario_id` e não exibem a transação alheia — mas as **agregações de `GET /cards` não filtram por usuário**: o total da fatura aberta exibido ao dono do cartão passa a incluir a transação do outro usuário. Resultado: corrupção do total de fatura entre usuários (e inconsistência interna: o total do card não bate com o detalhe da fatura). Complementa o quadro do F-15 (a auditoria de segurança validou os caminhos de leitura; este é um caminho de escrita+agregação).

**Recomendação:** (1) validar propriedade do `cartao_id` em `update_transaction` (mesmo código da criação); (2) adicionar `usuario_id == current_user.id` às duas agregações de `cards.py` (defesa em profundidade mesmo após o fix 1 — e necessário de todo modo, já que parcelas/transações legadas inválidas continuariam contando).

### T-37 — Persistência do chat e sanitização de turnos **[ACEITÁVEL]**, com um bug de releitura **[CORRIGIR]** — Prioridade média · Esforço P · [ANTES DO DEPLOY]

**Localização:** persistência atômica `ai.py:352-365` (correta); sanitização `_build_contents` `ai.py:164-186` (correta — dedupe de roles consecutivos mantendo o mais recente, garantia de começar com `user`); **bug:** `schemas/ai.py:9` (`HistoricoItem.text` com `max_length=4000`) aplicado na **releitura do banco** em `ai.py:308`.

**O que existe hoje:** A arquitetura de sessão (janela de 24h na UI, contexto invisível de 50 mensagens, `sessao_id` por conversa) está implementada conforme o desenho do `SESSAO_ATUAL.md`. **Bug:** se o Gemini gerar uma resposta com mais de 4.000 caracteres (perfeitamente possível — não há limite na geração nem no `ChatMessage.text`), ela é persistida; na mensagem **seguinte** do usuário, `HistoricoItem(role=..., text=...)` revalida o texto vindo do banco e lança `ValidationError` → **500 em todas as mensagens** até a resposta longa sair da janela de 50. O chat do usuário fica quebrado por dias.

**Recomendação:** Não revalidar dados vindos do próprio banco com schema de entrada — construir os `types.Content` direto das rows, ou truncar o texto ao reidratar. Adicionalmente, registrar: **a validação fim-a-fim do carregamento de histórico segue pendente** (bloqueada pelos 503s do Gemini em teste — só confirmável em runtime).

### T-38 — Estatísticas: sinal de variação invertido com saldo anterior negativo + divergência entre implementações **[CORRIGIR]** — Prioridade média · Esforço P · [PÓS-DEPLOY]

**Localização:** `statistics.py:31-35` (`_variacao` divide por `anterior` **sem** `abs()`); `ai.py:58-69` (`_variacao_saldo_pct` divide por `abs(saldo_ant)` — correto).

**O que existe hoje:** Duas fórmulas diferentes para a mesma métrica. Em `_variacao`, com saldo anterior **negativo** o sinal inverte: saldo −100 → −50 (melhora de R$ 50) é reportado como variação **−50%**; saldo −100 → +100 vira **−200%**. O dashboard exibe esses percentuais (`variacao_saldo` em `MensalResponse`). A versão da IA está correta; a do dashboard não.

**Recomendação:** Usar `abs(anterior)` no denominador de `_variacao` e unificar as duas implementações num helper único (T-01/T-02).

### T-39 — Regime de competência: compra parcelada conta valor cheio no mês da compra nas estatísticas **[ACEITÁVEL — decisão a documentar]** · [PÓS-DEPLOY]

**Localização:** `statistics.py:70-77` (estatísticas leem apenas `transacoes` pela data da **compra**); parcelas nunca entram em `_agregar`.

**O que existe hoje:** Uma compra de R$ 1.200 em 12× aparece como despesa de R$ 1.200 no mês da compra no Dashboard/Resumo, e **R$ 0** nos 11 meses seguintes — enquanto a tela de Faturas mostra R$ 100/mês. São dois regimes (competência nas estatísticas, caixa nas faturas) coexistindo. Internamente consistente, e o campo "parcelas do próximo mês" compensa em parte — mas para o público-alvo (alto volume parcelado), o "saldo do mês" do Dashboard não reflete o desembolso real, e a diferença entre as duas telas pode soar como bug de precisão.

**Recomendação:** Não é defeito de código — é decisão de produto que precisa ser **explícita** (documentada e, idealmente, comunicada na UI). Alternativa futura: toggle competência/caixa nas estatísticas (caixa = somar parcelas por `fatura_mes` + avulsas não-crédito por data).

### T-40 — Validações ausentes no update de cartão **[CORRIGIR]** — Prioridade média · Esforço P · [ANTES DO DEPLOY]

**Localização:** `schemas/card.py:31-38` (`CartaoUpdate` sem nenhum validator — contraste com `CartaoCreate:16-28`).

**O que existe hoje:** Mesmo padrão do F-15, no cartão: `PUT /cards/{id}` aceita `tipo` arbitrário, `dia_vencimento`/`dia_fechamento` fora de 1–31 e `mes_offset_vencimento` negativo. Consequência técnica concreta: `dia_vencimento=0` passa pelo `min(0, monthrange(...))` e `dt.date(ano, mes, 0)` lança `ValueError` → **500** em `GET /cards`, `GET /cards/{id}/invoices` e na criação de transações com esse cartão — um único update malformado quebra três telas para o usuário.

**Recomendação:** Replicar os validators do `CartaoCreate` no `CartaoUpdate` (e `mes_offset_vencimento >= 0`).

### T-41 — Atomicidade da criação de transação parcelada **[CORRIGIR]** — Prioridade média · Esforço P · [PÓS-DEPLOY]

**Localização:** `transactions.py:165-172` — `session.commit()` da transação (`:166`) **antes** de `_criar_parcelas`, que commita de novo (`:85`).

**O que existe hoje:** Dois commits separados: se a geração de parcelas falhar (erro de dados, queda de conexão), a transação fica persistida como `parcelado=True` com **zero parcelas** — estado inconsistente que aparece nas estatísticas mas em nenhuma fatura.

**Recomendação:** Uma única transação de banco: `flush()` para obter `transacao.id`, criar as parcelas, e um único `commit()` no final do endpoint.

---

## 11. Dimensão 10 — Prontidão operacional

### T-42 — Sem estratégia de migração e start para o deploy **[CORRIGIR]** — Prioridade alta · Esforço P · [ANTES DO DEPLOY]

**Localização:** raiz do projeto — não há `Procfile`, `railway.toml`/`railway.json`, `Dockerfile` nem script de start; nada executa `alembic upgrade head`.

**O que existe hoje:** O deploy no Railway/Render precisará de um comando de start (`uvicorn main:app --host 0.0.0.0 --port $PORT`) e de uma fase de release rodando as migrações — nada disso existe ou está documentado. Risco prático: API nova subindo contra schema velho na primeira mudança de banco pós-deploy.

**Recomendação:** Adicionar `Procfile`/config do Railway com `release: alembic upgrade head` (ou start script que roda `alembic upgrade head && uvicorn ...` — aceitável com instância única; com múltiplas réplicas, preferir release phase para não rodar migração concorrente).

### T-43 — Health check existe; sem lifespan, sem validação de config no startup **[ACEITÁVEL]** — Esforço P · [PÓS-DEPLOY]

**Localização:** `main.py:41-48` (`/health` com `SELECT 1` — bom; vazamento de detalhe já coberto pelo **F-14**); ausência de `lifespan` em `main.py`.

**O que existe hoje:** `/health` verifica o banco de verdade (não é um ping vazio) — adequado para o health check do Railway. Faltas menores: nenhum handler de startup/shutdown (sem `engine.dispose()` no shutdown; sem fail-fast de configuração no boot — o fail-fast de `SECRET_KEY` já é o **F-01**; vale estender para `GEMINI_API_KEY`/`RESEND_API_KEY` vazias em produção, que hoje só falham no primeiro uso).

### T-44 — Configuração por ambiente parcial **[ACEITÁVEL]** — [ANTES DO DEPLOY] (itens já cobertos por F-03/F-13)

**O que existe hoje:** `ENVIRONMENT` controla `echo` do SQLAlchemy (`database.py:6`) e flag `secure` dos cookies (`auth.py:57,68`). Não controla CORS (F-03/T-07), `docs_url` (F-13) nem nível de log (T-25). A mecânica está certa; falta estender aos pontos listados — todos já têm achado próprio.

### T-45 — Monitoramento de erros (Sentry/APM) ausente **[CORRIGIR]** — ver T-25 · [ANTES DO DEPLOY]

Consolidado em T-25 — listado aqui apenas para completude da dimensão.

---

## 12. Pontos Fortes

- **Ciclo de fatura correto e uniforme** — a lógica mais difícil do domínio (fechamento, offset, clamp de dia em meses curtos, virada de ano) está certa e aplicada com a mesma convenção nos três pontos de cálculo (`transactions.py:36-58,89-98`, `cards.py:42-52`). T-32.
- **`Decimal`/`Numeric(15,2)` em 100% dos valores monetários**, com `ROUND_HALF_UP` e última parcela absorvendo a diferença — sem nenhum `float` no caminho do dinheiro.
- **Escopo por usuário sólido** nos caminhos de leitura (validado em detalhe na auditoria de segurança, §3) — única exceção encontrada é o caminho de escrita do T-36.
- **API stateless de ponta a ponta** — escala horizontal sem retrabalho (T-20).
- **Migrações Alembic limpas, lineares e reversíveis**, incluindo o padrão correto de coluna NOT NULL com backfill (T-15).
- **`response_model` explícito em todos os endpoints** — nenhum model de banco vaza cru; schemas de criação com validação real (`valor > 0`, `tipo`, parcelamento ≥ 2).
- **Retry do Gemini bem implementado** (backoff, logging, mensagem amigável, fail-fast de chave ausente) e **persistência atômica user+assistant** só após sucesso (T-30, T-37).
- **Sanitização de turnos do chat** (`_build_contents`) — dedupe de roles consecutivos e garantia de abertura com `user`, exatamente o que o Gemini exige.
- **Decisões técnicas documentadas** — `SESSAO_ATUAL.md` registra trade-offs (soft delete de categorias, `fatura_mes` pela data de vencimento, trailing slash) com qualidade rara em projeto solo.
- **Injeção de dependências uniforme** e routers com formato consistente (T-03, T-29).
- **`yearly_stats` evita N+1** buscando o ano em uma query (`statistics.py:116-121`) — o instinto certo, faltando só empurrar a agregação para o banco.
- **Health check real** (`SELECT 1` no banco), pronto para o probe do Railway.

---

## 13. Tabela-resumo dos achados

| ID | Dim. | Título | Balde | Prior. | Esforço | Quando |
|---|---|---|---|---|---|---|
| T-01 | 1 | Repository/Services declarados mas inexistentes; lógica nos routers | REFATORAR | Alta | G | PÓS-DEPLOY |
| T-02 | 1 | `ai.py` importa helpers privados de `statistics.py` | CORRIGIR | Média | P | PÓS-DEPLOY |
| T-03 | 1 | Depends/injeção uniforme | BEM CONSTRUÍDO | — | — | — |
| T-04 | 1 | `_add_months`/fatura duplicados em 4 lugares | CORRIGIR | Alta | P | PÓS-DEPLOY |
| T-05 | 2 | Estrutura de pastas e nomenclatura | ACEITÁVEL | — | — | — |
| T-06 | 2 | Logs/cookies.xml/populate_db.py soltos na raiz | CORRIGIR | Média | P | ANTES DO DEPLOY |
| T-07 | 2 | CORS e parâmetros da IA fora do Settings | CORRIGIR | Média | P | ANTES DO DEPLOY |
| T-08 | 2 | Debug logging com conteúdo de chat em `/ai/historico` | CORRIGIR | Média | P | ANTES DO DEPLOY |
| T-09 | 3 | Índices ausentes (cartao_id, compostos de fatura, sessao_id) | CORRIGIR | Alta | P | ANTES DO DEPLOY |
| T-10 | 3 | `extract(month/year)` non-sargable | CORRIGIR | Alta | P | ANTES DO DEPLOY |
| T-11 | 3 | Colunas monetárias NULLABLE; sem CHECK/UNIQUE | CORRIGIR | Média | P–M | PÓS-DEPLOY |
| T-12 | 4 | Sem paginação em nenhuma listagem | CORRIGIR | Alta | M | ANTES DO DEPLOY |
| T-13 | 5 | Conexão direta ao Supabase; sem pooler/pre_ping | CORRIGIR | Alta | P | ANTES DO DEPLOY |
| T-14 | 3 | FKs sem ON DELETE (bloqueia F-07; causa T-34) | RISCO FUTURO | Média | P | ANTES DO DEPLOY |
| T-15 | 3 | Migrações limpas e reversíveis; sem drift estrutural | BEM CONSTRUÍDO | — | — | — |
| T-16 | 3 | Desnormalização de categoria/descrição | ACEITÁVEL | — | — | — |
| T-17 | 4 | N+1 em `GET /cards`; varredura em invoices; agregação em Python | CORRIGIR | Alta | M | ANTES (cards/invoices) |
| T-19 | 4 | ~16 queries + prompt de até ~200KB por mensagem de IA | CORRIGIR | Alta | M | PÓS-DEPLOY |
| T-20 | 5 | API stateless | BEM CONSTRUÍDO | — | — | — |
| T-21 | 5 | Gemini síncrono sem timeout pode travar a API | CORRIGIR | Alta | M | ANTES DO DEPLOY |
| T-22 | 5 | Oportunidades de cache não exploradas | ACEITÁVEL | Baixa | M | PÓS-DEPLOY |
| T-23 | 6 | Zero testes (parcelamento/fatura sem cobertura) | CORRIGIR | Máxima | M–G | ANTES DO DEPLOY |
| T-24 | 6 | Sem exception handler central | ACEITÁVEL | Baixa | P | PÓS-DEPLOY |
| T-25 | 6 | Sem logging configurado, sem Sentry | CORRIGIR | Alta | P–M | ANTES DO DEPLOY |
| T-26 | 6 | Type hints com lacunas pontuais | ACEITÁVEL | Baixa | P | PÓS-DEPLOY |
| T-27 | 6 | `utcnow()` deprecado + `date.today()` em fuso local | CORRIGIR | Média | P | PÓS-DEPLOY |
| T-28 | 7 | Sem versionamento de API (`/api/v1`) | CORRIGIR | Média | P | ANTES DO DEPLOY |
| T-29 | 7 | Status codes/formato consistentes; desvios menores | ACEITÁVEL | Baixa | P | PÓS-DEPLOY |
| T-30 | 8 | Gemini: retry bom; sem timeout/cobertura 429/circuit breaker | ACEITÁVEL | Média | M | ver T-21 |
| T-31 | 8 | Resend: sem try/except; envio antes do commit | CORRIGIR | Média | P | ANTES DO DEPLOY |
| T-32 | 9 | Ciclo de fatura correto e uniforme | BEM CONSTRUÍDO | — | — | — |
| T-33 | 9 | Última parcela pode ficar ≤ 0 em valores pequenos | CORRIGIR | Baixa | P | PÓS-DEPLOY |
| T-34 | 9 | `deletar_parcelas=false` → 500 (violação de FK) | CORRIGIR | Alta | P | ANTES DO DEPLOY |
| T-35 | 9 | Update não recalcula parcelas/fatura derivada | CORRIGIR | Alta | M | ANTES DO DEPLOY |
| T-36 | 9 | `cartao_id` sem validação no update + agregação sem `usuario_id` → fatura poluída entre usuários | CORRIGIR | Alta | P | ANTES DO DEPLOY |
| T-37 | 9 | Chat: resposta >4000 chars quebra o chat na releitura | CORRIGIR | Média | P | ANTES DO DEPLOY |
| T-38 | 9 | Variação % com sinal invertido em saldo negativo | CORRIGIR | Média | P | PÓS-DEPLOY |
| T-39 | 9 | Competência vs caixa nas estatísticas — documentar decisão | ACEITÁVEL | Média | — | PÓS-DEPLOY |
| T-40 | 9 | `CartaoUpdate` sem validações → `dia=0` quebra 3 telas | CORRIGIR | Média | P | ANTES DO DEPLOY |
| T-41 | 9 | Criação parcelada em 2 commits (não atômica) | CORRIGIR | Média | P | PÓS-DEPLOY |
| T-42 | 10 | Sem comando de start nem `alembic upgrade head` no deploy | CORRIGIR | Alta | P | ANTES DO DEPLOY |
| T-43 | 10 | Sem lifespan/fail-fast de config no boot | ACEITÁVEL | Baixa | P | PÓS-DEPLOY |
| T-44 | 10 | Config por ambiente parcial (CORS/docs/log) | ACEITÁVEL | — | — | ver F-03/F-13/T-25 |

**Pendências só verificáveis em runtime (não afirmadas neste relatório):** comportamento sob carga das queries (T-17/T-19), latência fim-a-fim do `/ai/chat`, validação do carregamento de histórico do Assistente (bloqueada pelos 503s do Gemini — cenários 1–7 do `SESSAO_ATUAL.md`).

---

*Relatório gerado em 10/06/2026 — auditoria somente leitura; nenhuma alteração de código realizada. Correções a priorizar e aplicar uma a uma, com aprovação, conforme a seção de prioridades do resumo executivo.*
