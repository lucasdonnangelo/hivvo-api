# Plano de Execução — hivvo-api

Roteiro de correções, em ordem de execução, mesclando `docs/AUDITORIA_SEGURANCA.md` (F-xx) e `docs/AUDITORIA_TECNICA.md` (T-xx).

Cada batch é um prompt para o Claude Code na pasta `hivvo-api`. Os detalhes de cada achado (arquivo:linha, recomendação) estão nos relatórios — os prompts referenciam por ID.

---

## Como usar

- Execute **um batch por vez, na ordem**. Traga o resultado para revisão antes de avançar.
- Cada prompt já carrega a regra-padrão: ler os docs de referência + os dois relatórios, mostrar plano antes, implementar só o listado, atualizar `SESSAO_ATUAL.md` ao fim, aguardar aprovação antes do commit.

### Gates (não ignorar)

1. **Batches 1 → 2 → 3 são sequenciais e obrigatórios nessa ordem**: consolidar → testar → corrigir. Você não corrige a matemática de fatura/parcela sem a rede de testes no lugar.
2. **Batch 11 depende da sua decisão de topologia** (recomendado: same-site `app.hivvo.app` + `api.hivvo.app`). Não rode antes de decidir.
3. **Batch 7 tem passos manuais no Supabase** (criar papel, trocar URL, rotacionar senha) — não é só código.
4. Tudo aqui é **hivvo-api**. O **hivvo-web** tem trilha própria (auditoria + batches). Pontos de coordenação cross-repo estão marcados no fim.

---

# PRÉ-DEPLOY

## Batch 1 — Consolidar lógica de fatura/parcela (T-04 + extração alvo do T-01)

```
Antes: leia Hivvo_Referencia.md, SESSAO_ATUAL.md, docs/AUDITORIA_SEGURANCA.md e docs/AUDITORIA_TECNICA.md. Mostre o plano antes de executar. Implemente APENAS o listado. Ao fim, atualize SESSAO_ATUAL.md e aguarde aprovação antes do commit.

Refactor SEM mudança de comportamento. Objetivo: eliminar as cópias duplicadas e extrair a lógica de domínio pura (sem dependência de FastAPI) para módulos testáveis.

- Criar app/services/faturas.py com: _add_months, _data_vencimento_parcela, _fatura_cartao_avulso, _current_open_fatura, _fatura_vencimento (mover de transactions.py / cards.py / invoices.py).
- Criar app/services/parcelas.py com _criar_parcelas.
- Criar app/services/estatisticas.py com _agregar, _categorias, _buscar_mes. (T-02: ai.py passa a importar daqui, não de statistics.py)
- Substituir as 4 cópias de _add_months e as cópias de _fatura_vencimento em transactions.py, cards.py, invoices.py e populate_db.py por imports do novo módulo. (T-04)
- NÃO alterar nenhuma regra de cálculo nem resposta de endpoint — é só mover código. Confirmar que nenhum endpoint muda de saída.
```

## Batch 2 — Rede de testes do domínio (T-23, subconjunto)

```
[regra-padrão como no Batch 1]

Adicionar a suíte de testes das funções puras de domínio. Não alterar código de aplicação além de adicionar tests/ e pytest ao requirements.

- Adicionar pytest (+ pytest-mock) ao requirements e a estrutura tests/.
- Testes unitários para services/faturas.py e services/parcelas.py cobrindo: fechamento em meses de 28/30/31 dias; compra no dia exato do fechamento; virada dezembro→janeiro; offset 0/1/2; clamp do dia de vencimento; _add_months com salto > 12 meses; arredondamento de parcela com dízima; soma das parcelas == valor total.
- Incluir os casos que documentam bugs conhecidos (vão FALHAR contra o código atual e serão fechados no Batch 3): T-33 (R$ 0,10 em 12× não pode gerar parcela <= 0) e T-38 (variação % com saldo anterior negativo deve usar abs()). Marcar como xfail com motivo apontando o Batch 3.
- Meta: 100% das funções de fatura/parcela cobertas.
```

## Batch 3 — Correção dos bugs de domínio (contra os testes do Batch 2)

```
[regra-padrão]

Corrigir os bugs de domínio. Os testes do Batch 2 (inclusive os xfail) devem ficar verdes.

- T-36: validar propriedade de cartao_id em update_transaction (mesmo código da criação) E adicionar usuario_id == current_user.id às duas agregações de cards.py. (também é achado de segurança — poluição de fatura entre usuários)
- T-34: em DELETE /transactions/{id}, remover o parâmetro deletar_parcelas (sempre apagar parcelas junto) OU implementá-lo de verdade; eliminar o 500 por violação de FK.
- T-35 (+F-15): no update de transação, rederivar fatura_mes/ano quando data ou cartao_id mudarem; para transação parcelada, bloquear edição de valor/data (orientar excluir e recriar) OU recalcular as parcelas não pagas; remover fatura_mes/ano do TransacaoUpdate; aplicar valor>0 e tipo válido no TransacaoUpdate.
- T-40: replicar os validators de CartaoCreate no CartaoUpdate (tipo; dia_vencimento/dia_fechamento entre 1 e 31; mes_offset_vencimento >= 0).
- T-33: rejeitar valor < total_parcelas × 0.01 no schema de criação (422).
- T-38: usar abs(anterior) no denominador de _variacao e unificar com a versão correta já existente em ai.py (via services/estatisticas.py).
- T-41: criação de transação parcelada em transação única — flush() para obter o id, criar as parcelas, um único commit no fim do endpoint.
- T-37: não revalidar dados vindos do banco com HistoricoItem (max_length=4000) — construir os types.Content direto das rows ou truncar ao reidratar.
- T-27 (só a data de negócio): criar um helper único de "hoje" no fuso do produto (America/Sao_Paulo) e usá-lo onde hoje há date.today() (installments.py:61, cards.py:66, etc.). O sweep de utcnow() fica para o Batch 16.
```

## Batch 4 — Config, higiene e versionamento

```
[regra-padrão]

Mudanças pequenas e independentes.

- F-01: SECRET_KEY obrigatória, sem default; fail-fast no startup se ausente; em produção, validar len >= 32 e que não é o valor de exemplo.
- F-09: ACCESS_TOKEN_EXPIRE_MINUTES de 1440 para 30.
- F-13: docs_url / redoc_url / openapi_url = None quando ENVIRONMENT == "production".
- F-14: /health retorna mensagem genérica; detalhe do erro só no log.
- F-16: ChatRequest.sessao_id tipado como uuid.UUID (entrada inválida vira 422).
- F-22: max_length em todos os campos de texto dos schemas de entrada.
- F-23: bcrypt.gensalt(rounds=12) explícito.
- F-06: SafetySetting BLOCK_NONE -> limiares padrão do Gemini (ou BLOCK_ONLY_HIGH); validar que não quebra o caso financeiro.
- F-11 + T-08: remover *.log, *.err e cookies.xml do diretório e adicioná-los ao .gitignore; remover os logger.info que despejam conteúdo do chat em /ai/historico.
- T-06: mover populate_db.py para scripts/ com guarda explícita contra rodar com ENVIRONMENT=production.
- T-07: CORS via settings.FRONTEND_URL (não hardcoded); promover modelo Gemini, janela de 24h, limite de 50 mensagens e política de retry para Settings.
- T-28: montar todos os routers sob /api/v1. (cross-repo: a base URL do frontend muda junto)
```

## Batch 5 — Tokens e sessão

```
[regra-padrão]

- F-24: hashear refresh tokens E reset tokens com SHA-256 antes de persistir; enviar o valor CRU ao cliente (cookie/e-mail); no lookup, hashear o recebido e comparar. 4 pontos: criação + lookup de cada tipo. A coluna token permanece str. Tokens em texto claro já existentes deixam de validar (aceitável pré-lançamento).
- F-10: em change_password e reset_password, revogar TODOS os RefreshToken do usuário na mesma transação.
- F-18 + T-31: Resend — commitar o token ANTES do envio (ou usar BackgroundTask); try/except no envio com log server-side; manter a resposta genérica ao cliente; mover resend.api_key para a inicialização.
```

## Batch 6 — Banco: índices, sargabilidade, constraints, cascades

```
[regra-padrão]

Uma migration Alembic + ajuste de 2 funções de query. downgrade() completo e reversível.

- T-09: criar índices compostos — ix_transacoes_usuario_data(usuario_id, data); ix_transacoes_cartao_fatura(cartao_id, fatura_ano, fatura_mes); ix_parcelas_cartao_fatura(cartao_id, fatura_ano, fatura_mes); ix_parcelas_usuario_fatura(usuario_id, fatura_ano, fatura_mes); ix_chat_messages_sessao_id(sessao_id).
- T-10: trocar extract("month"/"year") por range de datas (data >= date(ano,mes,1) AND data < próximo mês) em _buscar_mes (services/estatisticas.py) e em transactions.py — habilita o índice (usuario_id, data).
- T-14: ondelete="CASCADE" nas FKs de usuario_id (todas as tabelas) e em parcelas.transacao_id.
- T-11 (parte barata): SET NOT NULL nas colunas monetárias (+ nullable=False nos models); CHECK valor>0, tipo IN ('receita','despesa'), fatura_mes BETWEEN 1 AND 12, numero_parcela <= total_parcelas; UNIQUE parcelas(transacao_id, numero_parcela) e categorias(usuario_id, nome).
```

## Batch 7 — Pooler de conexão + papel Postgres (CÓDIGO + OPS)

```
[regra-padrão]

Parte é código, parte é operação no painel do Supabase (executada por mim, Lucas).

Código (app/core/database.py):
- Usar a URL do transaction pooler do Supabase (porta 6543) em produção.
- Adicionar pool_pre_ping=True, pool_recycle=300, pool_size/max_overflow explícitos (ex. 5/5).
- Confirmar que nada depende de features de sessão incompatíveis com o pooler em modo transaction (SET de sessão, prepared statements server-side, LISTEN/NOTIFY).

Ops (Lucas, fora do código):
- Criar papel Postgres dedicado SEM superusuário / SEM BYPASSRLS, com apenas SELECT/INSERT/UPDATE/DELETE nas tabelas da aplicação (F-02).
- Apontar o DATABASE_URL de produção (pooler) para esse papel e rotacionar a senha (F-05).
```

## Batch 8 — Queries pesadas + teto de listagem (sem quebrar contrato)

```
[regra-padrão]

- T-17 invoices: reescrever GET /cards/{id}/invoices com SUM/COUNT GROUP BY fatura_ano, fatura_mes no banco — eliminar a varredura do histórico completo.
- T-17 cards: reescrever as agregações de GET /cards com 2 queries GROUP BY cartao_id (uma para parcelas, uma para avulsas) cobrindo todos os cartões — eliminar o N+1.
- T-12 (mínimo, NÃO quebrar contrato agora): adicionar limit (default 100, máx 500) e offset aos endpoints de listagem, mantendo o formato de lista atual; criar um endpoint dedicado de export para o caso getAllTransactions() do frontend, em vez de listagem irrestrita. A migração para envelope {items, total} fica coordenada com a passada do frontend.
- GET /transactions: adicionar id DESC como desempate na ordenação (estabilidade entre páginas).
```

## Batch 9 — Resiliência da IA + rate limiting

```
[regra-padrão]

- T-21: configurar timeout explícito no genai.Client (http_options, ~30s); reduzir o orçamento de retry no caminho da request (ex. 2 tentativas, não 5); tornar o client singleton de módulo.
- F-04: adicionar slowapi — limites apertados por IP em /auth/login, /auth/register, /auth/forgot-password; em /ai/chat, limite por usuário + por IP (N/min) + cota diária. Manter o lockout por conta já existente.
- Registrar no SESSAO_ATUAL.md: store em memória não sobrevive a múltiplas instâncias — ao escalar horizontalmente, migrar para Redis.
```

## Batch 10 — Operacional e deploy

```
[regra-padrão]

- T-25: configurar logging (dictConfig, nível por ENVIRONMENT); integrar Sentry (SDK FastAPI); middleware de request log com duração e request-id. Nunca logar conteúdo de mensagens nem tokens.
- T-42: adicionar Procfile/config do Railway com fase de release "alembic upgrade head" e start "uvicorn main:app --host 0.0.0.0 --port $PORT".
- T-43: lifespan com fail-fast de config no boot (estender o fail-fast do F-01 para GEMINI_API_KEY/RESEND_API_KEY ausentes em produção); engine.dispose() no shutdown.
```

## Batch 11 — Topologia (cookies/CORS) + exclusão de conta LGPD

```
[regra-padrão]

NÃO rode antes de decidir a topologia. Recomendado: same-site — app.hivvo.app (Vercel) + api.hivvo.app (Railway).

- F-03: cookies com Domain=.hivvo.app e SameSite=Lax (preserva a proteção CSRF); CORS allow_origins=[settings.FRONTEND_URL], allow_credentials=True, métodos/headers restritos (nunca "*"). Checagem de header Origin nos endpoints mutáveis como reforço.
- F-07: DELETE /auth/me autenticado que apaga TODOS os dados do usuário em transação única (trivial agora com os cascades do T-14: DELETE FROM usuarios WHERE id=...). Registrar log de auditoria da exclusão. Atualizar a Política de Privacidade.
```

---

## → DEPLOY

- **F-05**: rotacionar TODOS os segredos (DB, Gemini, Resend, SECRET_KEY) e inseri-los só como env vars no painel do Railway/Render — nunca em arquivo.
- Restringir a GEMINI_API_KEY (restrições/quota no Google AI Studio) e a RESEND_API_KEY ao escopo mínimo.
- Fixar versões das dependências (`==` ou lockfile com pip-tools/uv) para builds reproduzíveis.
- Garantir que o `.env` não vai para a imagem de deploy.

---

# PÓS-DEPLOY

> Não deixe nenhum item daqui atrasar o lançamento.

## Batch 12 — Repository Pattern completo (T-01, T-02)

```
[regra-padrão]

Refactor arquitetural SEM mudança de comportamento (a suíte do Batch 2 é a rede de segurança). Introduzir app/repositories/ por domínio (acesso a dados) e finalizar app/services/ (regra de negócio), removendo o acesso a dados de dentro dos routers. Atualizar Hivvo_Referencia.md para refletir a arquitetura real.
```

## Batch 13 — Performance de IA e estatísticas (T-19, T-17 statistics, T-22)

```
[regra-padrão]

- T-19: reduzir as ~14 queries de agregação do contexto da IA para 1–2 GROUP BY mês no banco; cachear o contexto financeiro por usuário (TTL curto ou invalidação na escrita de transação); reavaliar a janela de 50 mensagens completas vs. N recentes + resumo.
- T-17 statistics: mover _agregar/_categorias para SUM(...) FILTER (WHERE ...) / GROUP BY no banco.
- T-22: cachear estatísticas de meses fechados (imutáveis na prática).
```

## Batch 14 — Hardening de segurança (rodada 2)

```
[regra-padrão]

- F-12: middleware de cabeçalhos (HSTS em produção, X-Content-Type-Options: nosniff, X-Frame-Options: DENY, CSP mínima, Referrer-Policy: no-referrer — este cobre a mitigação imediata do F-25).
- F-08: register com resposta não-confirmatória (ou verificação de e-mail); usar 409 onde for semântico.
- F-19: verificação de e-mail (double opt-in) no cadastro.
- F-20: política de senha NIST — comprimento >= 10–12 + checagem contra HaveIBeenPwned (k-anonymity).
- F-17: envio de e-mail assíncrono (se não tiver sido resolvido via BackgroundTask no Batch 5).
```

## Batch 15 — RLS como defesa em profundidade (resto do F-02)

```
[regra-padrão]

Habilitar RLS nas tabelas (transacoes, cartoes, parcelas, categorias, chat_messages, etc.) com políticas baseadas em SET LOCAL app.current_user_id (compatível com o pooler em modo transaction, pois SET LOCAL é por transação). Definir o SET LOCAL no início de cada request autenticada. Adicionar testes automatizados de isolamento entre usuários.
```

## Batch 16 — Polimento e dívida

```
[regra-padrão]

- T-24: exception_handler(Exception) central com log estruturado + 500 genérico.
- T-26: type hints faltantes (get_current_user; ctx como TypedDict do contexto da IA).
- T-29: consistência de status codes (409 em duplicidade; padronizar 400/404 do reset).
- T-27: sweep restante de utcnow() -> datetime.now(timezone.utc).
- F-25 (estrutural): mover o reset token para o fragmento da URL (#token=) ou para POST — COORDENAR com a página de reset do hivvo-web.
- Idempotência em POST /transactions (chave de idempotência) contra duplicação por duplo toque.
```

---

# Notas

**Excluídos de propósito:**
- **T-39** (competência vs. caixa nas estatísticas) é **decisão de produto**, não bug — vai para a conversa de produto.
- **F-21** (prompt injection) só vira crítico quando o agente com CRUD existir — não implementar agora.

**Trilha paralela hivvo-web** (auditoria própria + batches): CSRF no client, guardas de rota, página de reset (F-25), e os pontos de coordenação cross-repo abaixo.

**Coordenação cross-repo (backend ↔ frontend):**
- `/api/v1` — Batch 4 (a base URL do frontend muda junto).
- Contrato de listagem / envelope de paginação — Batch 8.
- Reset token no fragmento — Batch 16 / F-25.
