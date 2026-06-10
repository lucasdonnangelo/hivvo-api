# Auditoria de Segurança — hivvo-api

**Data:** 10 de junho de 2026
**Escopo:** Backend FastAPI (`hivvo-api`) — autenticação, controle de acesso, integração Gemini, configuração, dependências e LGPD.
**Referências de cobertura:** OWASP Top 10 (2021), OWASP ASVS.
**Natureza:** Diagnóstico somente leitura. Nenhum arquivo de código foi alterado.
**Commit auditado:** `de35c33` (branch `master`).

> ⚠️ **Aviso sobre segredos neste relatório:** durante a auditoria foram lidos segredos reais presentes no arquivo `.env` local (senha do Postgres, `SECRET_KEY`, `GEMINI_API_KEY`, `RESEND_API_KEY`). **Esses valores não são reproduzidos aqui.** A recomendação de rotacioná-los antes do lançamento está em F-02 e F-05.

---

## 1. Resumo Executivo

A camada de **controle de acesso a objetos (IDOR/BOLA)** — apontada como prioridade máxima — está **bem implementada**: todos os endpoints que tocam dados de usuário escopam a query por `usuario_id == current_user.id` e nunca confiam em identificador vindo do cliente. Não foi encontrado nenhum IDOR. Esse é o ponto mais forte da aplicação.

Os riscos concentram-se em **configuração para produção, gestão de segredos, hardening de sessão/cookie cross-domain e ausência de rate limiting / defesa em profundidade (RLS)**. Há ainda lacunas de LGPD (sem exclusão de conta) e de hardening de cabeçalhos HTTP.

### Contagem por severidade

| Severidade | Qtd. | Bloqueadores de lançamento |
|---|---|---|
| 🔴 Crítico | 2 | 2 |
| 🟠 Alto | 6 | 5 |
| 🟡 Médio | 10 | 3 |
| 🔵 Baixo | 7 | 0 |
| **Total** | **25** | **10** |

### Top prioridades antes do deploy

1. **F-01** — Definir `SECRET_KEY` forte e remover o fallback inseguro do código (token forge total).
2. **F-02** — Rotacionar todos os segredos reais que já circularam em ambiente de desenvolvimento (DB, Gemini, Resend) e usar um papel Postgres não-superusuário.
3. **F-03** — Configurar CORS/cookies corretamente para o cenário cross-domain (Vercel ↔ Railway) **sem** abrir `allow_origins=["*"]`, com proteção CSRF.
4. **F-04** — Adicionar rate limiting (login por IP e, sobretudo, `/ai/chat` por custo).
5. **F-07** — Implementar exclusão de conta (direito ao esquecimento — LGPD).
6. **F-24** — Hashear refresh tokens e reset tokens antes de persistir no banco (hoje em texto claro).

---

## 2. Achados por Severidade

---

### 🔴 CRÍTICO

---

#### F-01 — `SECRET_KEY` com fallback inseguro e chave de produção fraca **[BLOQUEADOR DE LANÇAMENTO]**

**Localização:** `app/core/config.py:6`, `app/core/auth.py:22-28,74`

**Descrição:**
A configuração define um valor padrão para a chave de assinatura JWT:

```python
SECRET_KEY: str = "change-me-in-production"   # config.py:6
```

Se a variável de ambiente não estiver presente (ou o `.env` não carregar) em produção, a aplicação **sobe normalmente** com uma chave pública conhecida. Além disso, a chave real presente no `.env` de desenvolvimento não é um valor de 32 bytes gerado por CSPRNG (o próprio comentário recomenda `openssl rand -hex 32`, mas o valor configurado é uma string curta e de baixa entropia).

**Impacto:**
Qualquer pessoa que conheça (ou adivinhe) a `SECRET_KEY` consegue **forjar um JWT válido para qualquer `user_id`** e assumir a identidade de qualquer usuário — acesso total a transações, cartões, faturas e chat de toda a base. Como o token é assinado com HS256 (chave simétrica), a chave é o único segredo que protege toda a autenticação. Não há fail-fast: o erro passa despercebido até ser explorado.

**Correção recomendada:**
1. Remover o default e tornar a variável obrigatória, falhando na inicialização se ausente:
   ```python
   SECRET_KEY: str  # sem default — Pydantic Settings falha se não houver env var
   ```
2. Gerar a chave de produção com `openssl rand -hex 32` (32 bytes / 64 hex) e injetá-la apenas via variável de ambiente no painel do Railway/Render — nunca em arquivo.
3. Opcional: validar no startup que `len(SECRET_KEY) >= 32` e que `ENVIRONMENT == "production"` não usa o valor de exemplo.

---

#### F-02 — Backend conecta ao Postgres como superusuário; RLS do Supabase é ignorado **[BLOQUEADOR DE LANÇAMENTO]**

**Localização:** `app/core/database.py:4-7`, `.env` (`DATABASE_URL` usa o papel `postgres`)

**Descrição:**
A conexão é feita com a connection string direta do Supabase usando o papel **`postgres`** (superusuário do projeto). Com isso:
- O **Row Level Security (RLS)** do Supabase é totalmente ignorado — o superusuário faz `BYPASSRLS`.
- **Toda** a autorização recai exclusivamente na camada da aplicação (as checagens `usuario_id == current_user.id` nos routers).

Hoje essas checagens existem e estão corretas (ver §3), mas não há **defesa em profundidade**: um único endpoint futuro que esqueça o filtro por usuário vaza dados de toda a base, e qualquer SQL injection (mesmo que hoje não exista) seria executada com privilégio máximo.

**Impacto:**
Ausência de rede de segurança no banco. Em um app financeiro com LGPD, depender de uma única camada para isolar dados de usuários de alta renda é frágil. Um bug de escopo = vazamento massivo.

**Correção recomendada:**
1. Criar um papel Postgres dedicado e **sem** `BYPASSRLS` / sem superusuário, com apenas `SELECT/INSERT/UPDATE/DELETE` nas tabelas da aplicação, e apontar o `DATABASE_URL` de produção para ele.
2. Habilitar **RLS** nas tabelas `transacoes`, `cartoes`, `parcelas`, `categorias`, `chat_messages`, etc., como defesa em profundidade. Como o backend autentica via JWT próprio (não via Supabase Auth), defina políticas baseadas em uma variável de sessão (`SET LOCAL app.current_user_id`) ou, no mínimo, documente formalmente que a autorização é 100% aplicacional e cubra-a com testes automatizados de isolamento entre usuários.
3. Rotacionar a senha do banco antes do go-live (já circulou em ambiente de desenvolvimento).

---

### 🟠 ALTO

---

#### F-03 — Cookies de sessão e CORS não preparados para cross-domain; sem proteção CSRF **[BLOQUEADOR DE LANÇAMENTO]**

**Localização:** `app/routers/auth.py:52-71` (cookies), `main.py:23-29` (CORS)

**Descrição:**
Os cookies de autenticação são emitidos com `samesite="lax"` e `secure` apenas quando `ENVIRONMENT == "production"`:

```python
response.set_cookie(key=_COOKIE_ACCESS, value=token, httponly=True,
    secure=settings.ENVIRONMENT == "production", samesite="lax", ...)
```

O plano de deploy coloca o **frontend no Vercel** e a **API no Railway/Render** — domínios diferentes (cross-site). Com `SameSite=Lax`, o cookie **não é enviado** em requisições XHR/fetch cross-site, então o app simplesmente não autenticaria; a "correção" intuitiva (mudar para `SameSite=None`) **exige** `Secure` e, mais importante, **remove a proteção implícita contra CSRF** que o `Lax` fornecia. Não há token anti-CSRF nem verificação de `Origin`/`Referer` em nenhum endpoint mutável.

O CORS está hardcoded em `http://localhost:5173` e não usa `settings.FRONTEND_URL`. Isso é seguro hoje (não é `*`), mas vai quebrar em produção, e o risco é que a correção apressada vire `allow_origins=["*"]` com `allow_credentials=True` — combinação proibida e perigosa.

**Impacto:**
- Se migrarem para `SameSite=None` sem CSRF tokens → vulnerável a **Cross-Site Request Forgery** em todos os POST/PUT/DELETE (criar/apagar transações, trocar senha via `/auth/password`, etc.).
- Se "resolverem" o CORS com `*` + credenciais → qualquer site lê dados autenticados do usuário.

**Correção recomendada:**
1. Servir frontend e API sob o **mesmo site** (subdomínios de `hivvo.app`, ex.: `app.hivvo.app` e `api.hivvo.app`) e usar `SameSite=Lax` (ou `Strict`) com `Domain=.hivvo.app`. Isso preserva a defesa CSRF.
2. Se cross-site for inevitável: `SameSite=None; Secure` **+** implementar CSRF (double-submit token ou header customizado validado no backend).
3. Tornar o CORS dirigido por configuração: `allow_origins=[settings.FRONTEND_URL]`, nunca `*` com `allow_credentials=True`. Restringir `allow_methods`/`allow_headers` ao necessário em vez de `*`.

---

#### F-04 — Ausência total de rate limiting (login e, sobretudo, IA) **[BLOQUEADOR DE LANÇAMENTO]**

**Localização:** Toda a aplicação; com destaque para `app/routers/auth.py:97` (`/login`), `app/routers/ai.py:252` (`/ai/chat`)

**Descrição:**
Não há rate limiting por IP em nenhuma rota. O login tem **lockout por conta** (5 tentativas → bloqueio de 15 min, `auth.py:46-47,107-116`), o que é bom, mas:
- O lockout é **por conta**, não por IP — um atacante pode tentar uma senha em milhares de contas (password spraying) sem ser limitado, e ainda pode usar a contagem de tentativas para **negar serviço** a um usuário legítimo (lockout proposital).
- `/ai/chat` chama a API paga do Gemini a cada requisição, **sem nenhum limite**. Cada chamada ainda carrega histórico de até 50 mensagens + histórico anual no prompt (tokens elevados).

**Impacto:**
- **Abuso de custo:** um usuário autenticado (ou várias contas criadas em massa, já que o registro também não tem limite) pode disparar `/ai/chat` em loop e gerar custo arbitrário na conta Gemini — risco financeiro direto.
- **Brute force / password spraying** distribuído.
- **DoS de conta** via lockout forçado.

**Correção recomendada:**
1. Adicionar rate limiting (ex.: `slowapi`/Redis) global e por rota: limites apertados em `/auth/login`, `/auth/register`, `/auth/forgot-password` (por IP) e em `/ai/chat` (por usuário e por IP, ex.: N mensagens/min e cota diária).
2. Considerar quota/orçamento mensal de IA por usuário (encaixa no gating de plano da Fase 4).
3. Combinar lockout por conta (já existe) com throttling por IP.

---

#### F-05 — Segredos reais em `.env` local precisam de rotação antes do go-live **[BLOQUEADOR DE LANÇAMENTO]**

**Localização:** `.env` (não versionado)

**Descrição:**
**Ponto positivo:** o `.env` está no `.gitignore` (`.gitignore:1`) e **nunca foi commitado** — o histórico do git foi verificado e o `.env.example` versionado contém apenas placeholders (`[PASSWORD]`, `your-secret-key-here`). Não há vazamento de segredos no repositório.

**Porém**, o `.env` local contém valores **reais e ativos**: senha do Postgres de produção (Supabase), `GEMINI_API_KEY`, `RESEND_API_KEY` e a `SECRET_KEY`. Esses segredos já existiram em ambiente de desenvolvimento (e foram lidos durante esta auditoria), portanto devem ser considerados potencialmente expostos.

**Impacto:**
Chaves que circularam em estações de desenvolvimento, logs ou ferramentas têm risco de exposição. A `GEMINI_API_KEY` e a `RESEND_API_KEY` permitem custo/abuso em nome do projeto; a senha do DB dá acesso total aos dados.

**Correção recomendada:**
1. **Rotacionar todos os segredos** (DB, Gemini, Resend, SECRET_KEY) ao promover para produção e inseri-los apenas como variáveis de ambiente no painel do Railway/Render.
2. Restringir a `GEMINI_API_KEY` no Google AI Studio (restrições de aplicação/quota) e a `RESEND_API_KEY` ao escopo mínimo.
3. Garantir que o `.env` nunca seja copiado para a imagem de deploy.

---

#### F-06 — Filtros de segurança do Gemini desativados (`BLOCK_NONE`) **[PÓS-DEPLOY]**

**Localização:** `app/routers/ai.py:35-40`

**Descrição:**
Todas as quatro categorias de safety do Gemini estão em `BLOCK_NONE`:

```python
_SAFETY = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
    ... (HATE_SPEECH, SEXUALLY_EXPLICIT, DANGEROUS_CONTENT também BLOCK_NONE)
]
```

O conteúdo enviado ao modelo inclui texto livre controlado pelo usuário (mensagens do chat e descrições de transações). Desativar todos os filtros remove as barreiras do provedor contra geração de conteúdo nocivo.

**Impacto:**
Embora o assistente seja hoje somente-leitura e de domínio financeiro, desativar a moderação aumenta a superfície para uso indevido (gerar conteúdo abusivo via prompt) e remove uma camada de proteção que será importante quando o "agente com CRUD" for introduzido. Risco reputacional/conformidade.

**Correção recomendada:**
Remover os `BLOCK_NONE` e usar os limiares padrão do Gemini (ou no mínimo `BLOCK_ONLY_HIGH`), validando que não quebram o caso de uso financeiro legítimo. Não há motivo aparente para desligar moderação num app financeiro.

---

#### F-07 — Sem exclusão de conta: direito ao esquecimento (LGPD) não implementado **[BLOQUEADOR DE LANÇAMENTO]**

**Localização:** `app/routers/auth.py` (não há endpoint `DELETE /auth/me` nem equivalente)

**Descrição:**
Não existe nenhum endpoint para o usuário excluir a própria conta e seus dados. O `logout` apenas revoga o refresh token e apaga cookies; não há remoção de `usuarios`, `transacoes`, `cartoes`, `parcelas`, `categorias`, `chat_messages`, tokens de reset/refresh.

**Impacto:**
A LGPD (art. 18) garante ao titular a eliminação dos dados pessoais. Um app financeiro lidando com dados sensíveis de pessoa física precisa oferecer exclusão real (e não apenas `ativo=False`). Lacuna de conformidade para o lançamento.

**Correção recomendada:**
1. Implementar `DELETE /auth/me` autenticado que apague (ou anonimize, conforme política de retenção fiscal) **todos** os registros vinculados ao `usuario_id`, em transação única, incluindo `chat_messages`, `refresh_tokens` e `password_reset_tokens`.
2. Documentar a política de retenção e o fluxo na Política de Privacidade.
3. Registrar (log de auditoria) a solicitação de exclusão.

---

#### F-24 — Refresh tokens e reset tokens armazenados em texto claro **[BLOQUEADOR DE LANÇAMENTO]**

**Localização:** `app/core/auth.py:31-49` (refresh — emissão e lookup), `app/routers/auth.py:217-248` (reset — emissão e lookup), `app/models/refresh_token.py:12`, `app/models/password_reset_token.py:12`

**Descrição:**
Tanto o refresh token quanto o token de recuperação de senha são gerados como `uuid.uuid4()` e **persistidos crus**, idênticos ao valor entregue ao cliente. Não há hashing.

- Refresh: `core/auth.py:34-41` cria `RefreshToken(token=token_str, ...)` e a validação em `:47-49` faz lookup por igualdade direta (`RefreshToken.token == old_token_str`).
- Reset: `routers/auth.py:217-218` cria `PasswordResetToken(token=token_str, ...)` e `:248` busca por `PasswordResetToken.token == body.token`.
- Os models (`refresh_token.py:12`, `password_reset_token.py:12`) definem a coluna `token` como `str` indexado/único, sem qualquer transformação.

O valor armazenado é, portanto, o mesmo que viaja no cookie de sessão e no link de e-mail.

**Impacto:**
Qualquer leitura do banco — dump, backup, read replica comprometida, ou acesso via a conexão **superusuário do F-02** — entrega os tokens prontos para uso. O atacante **não precisa do `SECRET_KEY`**: um refresh token cru já permite gerar novos access tokens via `POST /auth/refresh` (sequestro de sessão), e um reset token cru não-usado/não-expirado permite **takeover de conta** via `POST /auth/reset-password`. Compõe criticamente com o **F-02** (Postgres como superusuário): o mesmo acesso de leitura que ignora o RLS também coleta todos os tokens ativos.

**Correção recomendada:**
Hashear os tokens antes de persistir, comparando hash na validação:
1. Como são `uuid4` de alta entropia (~122 bits), **SHA-256 sem salt** é suficiente (não precisa de bcrypt) e preserva a busca por índice.
2. Na emissão: gerar o UUID, enviar o valor **cru** ao cliente (cookie/e-mail) e gravar `sha256(token_str).hexdigest()`.
3. No lookup: hashear o valor recebido e comparar com a coluna.

Mudança localizada nos 4 pontos (emissão + lookup de cada tipo), sem alterar o formato do que o cliente recebe. **Nota:** isso também fecha o vetor de log do **F-11** — o token cru deixa de existir em qualquer lugar além do cliente, então o echo de SQL não tem mais como vazá-lo.

---

### 🟡 MÉDIO

---

#### F-08 — Enumeração de usuários no registro **[PÓS-DEPLOY]**

**Localização:** `app/routers/auth.py:76-77`

**Descrição:**
O registro responde `400 "E-mail já cadastrado"` quando o e-mail existe. Isso permite a um atacante descobrir quais e-mails têm conta no Hivvo. (O fluxo de `forgot-password` já é genérico e correto — `auth.py:242` — bom contraste.)

**Impacto:**
Vazamento de informação que facilita phishing direcionado e credential stuffing contra titulares conhecidos. Sensível por ser público de alta renda.

**Correção recomendada:**
Padronizar a resposta de registro para não confirmar existência (ex.: enviar e-mail de verificação e responder sempre de forma genérica), ou aceitar o trade-off de UX documentando a decisão. No mínimo, combinar com rate limiting (F-04) para impedir enumeração em massa.

---

#### F-09 — Token de acesso de longa duração (24h) sem revogação **[PÓS-DEPLOY]**

**Localização:** `.env` (`ACCESS_TOKEN_EXPIRE_MINUTES=1440`), `app/core/auth.py:22-28,64-85`

**Descrição:**
O access token JWT dura **1440 min (24h)**. JWT é stateless: enquanto válido, não há como revogá-lo (só o refresh token é revogável no banco). `logout` apenas apaga o cookie no navegador e revoga o refresh — um access token já capturado continua válido por até 24h.

**Impacto:**
Janela longa de uso de um token roubado/vazado, sem mecanismo de invalidação server-side. Logout não encerra sessões em outros dispositivos/cópias do token.

**Correção recomendada:**
Reduzir o access token para 15–30 min (o refresh rotativo de 7 dias já existe e cobre a UX). Opcionalmente, manter uma denylist de `jti` para revogação imediata em logout/troca de senha.

---

#### F-10 — Troca/reset de senha não revoga sessões existentes **[PÓS-DEPLOY]**

**Localização:** `app/routers/auth.py:198-209` (change_password), `:245-265` (reset_password)

**Descrição:**
Ao trocar a senha (`PUT /auth/password`) ou redefini-la via token (`POST /auth/reset-password`), os refresh tokens existentes **não são revogados** e nenhum access token é invalidado.

**Impacto:**
Se a troca de senha foi motivada por comprometimento, o atacante que já possui um refresh/access token **continua com acesso** mesmo após a vítima trocar a senha. Quebra a expectativa de segurança do fluxo de recuperação.

**Correção recomendada:**
Em `change_password` e `reset_password`, revogar todos os `RefreshToken` do usuário (`UPDATE ... SET revogado=True WHERE usuario_id=...`). Combinado com F-09 (access token curto), isso encerra o acesso rapidamente.

---

#### F-11 — Logs de desenvolvimento com dados sensíveis presentes no diretório **[PÓS-DEPLOY]**

**Localização:** `uvicorn.log`, `uvicorn_debug.log`, `uvicorn_debug2.log`, `cookies.xml` (raiz do projeto); `app/core/database.py:6` (`echo=True` em dev)

**Descrição:**
Com `ENVIRONMENT=development`, o SQLAlchemy roda com `echo=True` e registra todas as queries e **valores de parâmetros**. Os arquivos de log presentes na raiz contêm, em texto claro, e-mails de usuários e **valores de refresh tokens** (ex.: `{'token': '67369154-...'}`). O `cookies.xml` é um artefato de teste de sessão. Nenhum desses está versionado, mas estão no diretório de trabalho.

**Impacto:**
Tokens de sessão em log permitem sequestro de sessão se os arquivos vazarem (backup, push acidental, máquina comprometida). `echo=True` em produção vazaria PII e tokens em massa. Esse vetor é agravado pelo **F-24** (tokens persistidos em texto claro): o valor que aparece no log é o mesmo gravado no banco e entregue ao cliente — hashear os tokens (F-24) elimina a possibilidade de o echo de SQL vazar um token utilizável.

**Correção recomendada:**
1. Garantir que produção use `ENVIRONMENT=production` (echo desligado — já é o comportamento do código).
2. Remover os arquivos `*.log`, `*.err` e `cookies.xml` do diretório e adicioná-los ao `.gitignore` (`*.log`, `*.err`, `cookies.xml`).
3. Nunca logar valores de tokens; se precisar de logging de SQL, desabilitar binds sensíveis.

---

#### F-12 — Ausência de cabeçalhos de segurança HTTP **[PÓS-DEPLOY]**

**Localização:** `main.py` (nenhum middleware de headers)

**Descrição:**
A API não emite `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options`/`frame-ancestors`, nem `Content-Security-Policy`.

**Impacto:**
Sem HSTS, há janela para downgrade/SSL-strip; sem `X-Content-Type-Options`, MIME sniffing; sem proteção de framing, clickjacking nas respostas. Defesa em profundidade ausente.

**Correção recomendada:**
Adicionar um middleware que injete HSTS (em produção), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` e uma CSP mínima nas respostas da API. O frontend (Vercel) também deve definir CSP/headers próprios.

---

#### F-13 — `/docs`, `/redoc` e schema OpenAPI expostos em produção **[PÓS-DEPLOY]**

**Localização:** `main.py:15-21`

**Descrição:**
`docs_url="/docs"` e `redoc_url="/redoc"` ficam habilitados incondicionalmente, expondo toda a superfície da API publicamente.

**Impacto:**
Facilita o reconhecimento por atacantes (enumeração de endpoints, schemas, parâmetros). Não é vulnerabilidade direta, mas reduz a fricção de ataque numa API financeira.

**Correção recomendada:**
Desabilitar docs em produção (`docs_url=None, redoc_url=None` quando `ENVIRONMENT == "production"`), ou protegê-las atrás de autenticação.

---

#### F-14 — `/health` retorna detalhe interno do erro do banco **[PÓS-DEPLOY]**

**Localização:** `main.py:41-48`

**Descrição:**
```python
raise HTTPException(status_code=503, detail=f"Database unavailable: {str(e)}")
```
A mensagem de exceção do driver é devolvida ao cliente.

**Impacto:**
Pode vazar detalhes de infraestrutura (host, driver, motivo da falha) úteis para reconhecimento. Information disclosure de baixo a médio impacto.

**Correção recomendada:**
Retornar mensagem genérica (`"Database unavailable"`) e registrar o detalhe apenas no log server-side.

---

#### F-15 — `TransacaoUpdate` permite valores não positivos e ajuste manual de fatura **[PÓS-DEPLOY]**

**Localização:** `app/schemas/transaction.py:49-66`, `app/routers/transactions.py:179-196`

**Descrição:**
`TransacaoCreate` valida `valor > 0` e `tipo ∈ {receita, despesa}` (`transaction.py:28-40`), mas `TransacaoUpdate` **não** repete essas validações. Via `PUT /transactions/{id}` é possível gravar `valor` zero/negativo, `tipo` arbitrário, ou alterar `fatura_mes`/`fatura_ano` manualmente.

**Impacto:**
Inconsistência de integridade dos valores monetários e da lógica de faturas — uma transação pode ficar com valor negativo ou fatura inconsistente, distorcendo estatísticas e totais de fatura. O escopo por usuário está correto (não é IDOR), mas a integridade de dados é fraca.

**Correção recomendada:**
Aplicar em `TransacaoUpdate` as mesmas validações de `valor > 0` e `tipo` válido; reavaliar se `fatura_mes`/`fatura_ano` devem ser editáveis pelo cliente ou derivados no backend.

---

#### F-16 — `sessao_id` malformado gera erro 500 não tratado **[PÓS-DEPLOY]**

**Localização:** `app/routers/ai.py:264` (`uuid.UUID(body.sessao_id)`), também `:220`

**Descrição:**
`ChatRequest.sessao_id` é validado apenas por comprimento (36 chars, `schemas/ai.py:22`). Um valor de 36 caracteres que não seja um UUID válido faz `uuid.UUID(...)` lançar `ValueError`, resultando em **HTTP 500** em vez de 422.

**Impacto:**
Robustez/erro não tratado; em produção, 500s podem expor traceback se o handler de erro padrão estiver verboso. Baixo risco de segurança, mas má higiene de validação de input.

**Correção recomendada:**
Validar `sessao_id` como `UUID` no schema Pydantic (`sessao_id: uuid.UUID`) para que entradas inválidas retornem 422 automaticamente.

---

#### F-25 — Reset token trafega na query string do link de e-mail **[PÓS-DEPLOY]**

**Localização:** `app/routers/auth.py:234`

**Descrição:**
O link de recuperação enviado por e-mail embute o token como query string:

```python
f"<a href='{settings.FRONTEND_URL}/reset-password?token={token_str}'>"
```

Com o token na URL (`/reset-password?token=...`), ele tende a aparecer em **logs de servidor/proxy/CDN**, no header **`Referer`** (caso a página de reset carregue qualquer recurso de terceiros — analytics, fontes, pixels), no histórico do navegador e na sincronização entre dispositivos.

**Impacto:**
Exposição do token de reset por canais laterais. Combinado com o armazenamento em texto claro (**F-24**) e a janela de 15 min de validade, amplia a superfície para takeover de conta caso o token vaze por log ou `Referer`.

**Correção recomendada:**
- **Mitigação imediata:** definir `Referrer-Policy: no-referrer` na rota de reset (encaixa no **F-12**) e garantir que a página de reset não carregue recursos de terceiros enquanto o token está na URL.
- **Fix estrutural:** mover o token para o **fragmento** da URL (`#token=`, que o navegador não envia em `Referer` nem em logs de servidor) ou usar **POST**. Acoplado ao frontend `hivvo-web` — verificar na página de reset se o token é removido da URL após o uso e se há recursos externos carregados.

---

### 🔵 BAIXO

---

#### F-17 — `forgot-password` é síncrono e pode permitir enumeração por timing **[PÓS-DEPLOY]**

**Localização:** `app/routers/auth.py:212-242`

**Descrição:** A resposta é genérica (bom), mas o envio do e-mail via Resend ocorre **dentro** do request apenas quando o usuário existe. A diferença de latência (com vs. sem envio de e-mail) pode permitir inferir se um e-mail está cadastrado.

**Impacto:** Enumeração de usuários por canal lateral de tempo. Baixo.

**Correção recomendada:** Enviar o e-mail de forma assíncrona (fila/background task) para uniformizar o tempo de resposta independente de o usuário existir.

---

#### F-18 — Falha no envio de e-mail derruba o fluxo de recuperação **[PÓS-DEPLOY]**

**Localização:** `app/routers/auth.py:225-240`

**Descrição:** `resend.Emails.send(...)` é chamado sem try/except; o `session.commit()` do token vem **depois** do envio. Se a Resend falhar, a exceção propaga e o token não é persistido — além de poder vazar detalhe do provedor no erro.

**Impacto:** Disponibilidade do fluxo de reset e possível information disclosure. Baixo.

**Correção recomendada:** Encapsular o envio em try/except, logar falhas server-side e manter a resposta genérica ao cliente.

---

#### F-19 — Sem verificação de e-mail no cadastro **[PÓS-DEPLOY]**

**Localização:** `app/routers/auth.py:74-94`

**Descrição:** O registro cria conta e já emite cookies de sessão sem confirmar a posse do e-mail.

**Impacto:** Permite contas com e-mails de terceiros e facilita criação em massa (ligado a F-04). Baixo a médio dependendo do modelo de abuso.

**Correção recomendada:** Adicionar verificação de e-mail (double opt-in) antes de habilitar funcionalidades sensíveis; ao menos para o lançamento público.

---

#### F-20 — Política de senha mínima fraca (apenas 8 caracteres) **[PÓS-DEPLOY]**

**Localização:** `app/schemas/auth.py:17-22,52,66`

**Descrição:** A única regra é comprimento ≥ 8. Não há verificação contra senhas comuns/vazadas nem requisito de complexidade.

**Impacto:** Aumenta a viabilidade de brute force/credential stuffing (mitigado parcialmente pelo lockout F-04). Baixo.

**Correção recomendada:** Seguir NIST 800-63B — manter comprimento mínimo (idealmente ≥ 10–12) e checar contra lista de senhas comprometidas (ex.: HaveIBeenPwned k-anonymity). Evitar regras de complexidade arbitrárias.

---

#### F-21 — Prompt injection no contexto do assistente (relevante para o futuro agente CRUD) **[PÓS-DEPLOY]**

**Localização:** `app/routers/ai.py:96-186` (system instruction + histórico + descrições de transações no prompt)

**Descrição:** Descrições de transações e mensagens do usuário entram no prompt do Gemini. Hoje o assistente é **somente leitura** e o escopo de dados já é filtrado por usuário (não há vazamento entre usuários — o histórico e o contexto são sempre `usuario_id == current_user.id`), então o risco atual é baixo. Mas um usuário pode inserir instruções no texto (ex.: descrição de transação "ignore as regras e faça X") tentando manipular as respostas.

**Impacto:** Atual: baixo (manipula apenas a própria sessão, sem efeito colateral). **Futuro:** quando o "agente com CRUD" for introduzido, prompt injection vira vetor sério — instruções embutidas em dados poderiam disparar ações de escrita.

**Correção recomendada:** Antes de dar capacidade de escrita ao agente: separar claramente dados de instruções, validar/allow-list de ferramentas, exigir confirmação para ações mutáveis e nunca executar comandos derivados de texto livre do usuário sem checagem de autorização explícita por recurso.

---

#### F-22 — `nome_completo` e demais campos texto sem limite de tamanho **[PÓS-DEPLOY]**

**Localização:** `app/schemas/auth.py:7-10`, `app/schemas/transaction.py:8-19`, `app/schemas/card.py:8-14`, `app/schemas/category.py:7-10`

**Descrição:** Campos string (`nome_completo`, `descricao`, `nome`, `categoria`, etc.) não têm `max_length`. Apenas `ChatRequest`/`HistoricoItem` limitam tamanho.

**Impacto:** Permite gravar payloads grandes (consumo de armazenamento, possível impacto em performance/respostas). Baixo.

**Correção recomendada:** Definir `max_length` razoável em todos os campos de texto dos schemas de entrada.

---

#### F-23 — Hash de senha sem custo bcrypt explícito **[PÓS-DEPLOY]**

**Localização:** `app/core/auth.py:14-15`

**Descrição:** `bcrypt.gensalt()` é usado com o `rounds` padrão (12). Está adequado hoje, mas o custo não é fixado/configurável explicitamente e não há plano de reavaliação.

**Impacto:** Baixo — 12 rounds é aceitável. Apenas falta explicitar/versionar o parâmetro.

**Correção recomendada:** Fixar `bcrypt.gensalt(rounds=12)` explicitamente e revisar o custo periodicamente conforme o hardware evolui.

---

## 3. Pontos Fortes (o que está bem implementado)

- **Controle de acesso a objetos (IDOR/BOLA) — sólido.** Todos os endpoints de dados filtram por `usuario_id == current_user.id` e validam propriedade antes de qualquer operação:
  - Transações: `transactions.py:113` (list), `:143` (valida cartão do dono ao criar), `:187` (update), `:207` (delete).
  - Cartões: `cards.py:62,138,157`. Faturas: `invoices.py:42-46` (`_get_card_for_user`), `:55,116`.
  - Parcelas: `installments.py:26,51,83`. Categorias: `categories.py:38,70`.
  - Estatísticas: `statistics.py:87,116,152` (sempre `current_user.id`). IA: `ai.py:204,247,269` (histórico e contexto sempre escopados ao usuário).
  - **Nenhum endpoint confia em `user_id`/id de recurso vindo do cliente.** Os schemas de entrada não expõem `usuario_id`, evitando mass assignment de propriedade.
- **Senhas com bcrypt** (`core/auth.py:14-19`) — sem armazenamento reversível; `passlib` foi corretamente abandonado em favor do `bcrypt` direto.
- **Lockout de conta** contra brute force: 5 tentativas → 15 min de bloqueio (`auth.py:46-47,107-116`).
- **Fluxo de recuperação de senha bem desenhado:** token uuid4 (≈122 bits), expiração de 15 min, uso único via flag `usado`, e **resposta genérica** que não revela existência do e-mail (`auth.py:242,251-258`).
- **Refresh token rotativo com revogação** no banco (`core/auth.py:44-61`), revogado no logout (`auth.py:158-165`).
- **JWT** com algoritmo explícito (HS256) e verificação de expiração via `jose`; `get_current_user` revalida o usuário no banco e checa `ativo` (`core/auth.py:64-85`).
- **Cookies `HttpOnly`** — JWT nunca exposto ao JS, em conformidade com a regra arquitetural (sem token em localStorage).
- **Valores monetários em `Decimal`/`Numeric(15,2)`** em todos os models (`transaction.py`, `card.py`, `installment.py`); arredondamento `ROUND_HALF_UP` com a última parcela absorvendo a diferença.
- **Uso consistente do ORM (SQLModel/SQLAlchemy)** com queries parametrizadas — **nenhuma SQL raw** com interpolação de input do usuário foi encontrada (o único `text("SELECT 1")` em `main.py:45` é constante). Sem SQL injection identificada.
- **Validação de input via Pydantic** com validadores de tipo/positividade na criação de transações e cartões.
- **Response models explícitos** que não expõem `senha_hash` nem outros campos sensíveis (`UserResponse` em `schemas/auth.py:35-43` omite o hash).
- **Segredos fora do versionamento:** `.env` no `.gitignore` e ausente do histórico git; `.env.example` versionado contém apenas placeholders.
- **`.env` não vazou no git** — verificado em todo o histórico.

---

## 4. Tabela-resumo dos achados

| ID | Severidade | Título | Marcação |
|---|---|---|---|
| F-01 | 🔴 Crítico | `SECRET_KEY` com fallback inseguro / chave fraca | BLOQUEADOR |
| F-02 | 🔴 Crítico | Postgres como superusuário; RLS ignorado | BLOQUEADOR |
| F-03 | 🟠 Alto | Cookies/CORS cross-domain sem CSRF | BLOQUEADOR |
| F-04 | 🟠 Alto | Sem rate limiting (login e IA) | BLOQUEADOR |
| F-05 | 🟠 Alto | Rotação de segredos reais antes do go-live | BLOQUEADOR |
| F-06 | 🟠 Alto | Filtros de safety do Gemini desativados | PÓS-DEPLOY |
| F-07 | 🟠 Alto | Sem exclusão de conta (LGPD) | BLOQUEADOR |
| F-24 | 🟠 Alto | Refresh/reset tokens em texto claro | BLOQUEADOR |
| F-08 | 🟡 Médio | Enumeração de usuários no registro | PÓS-DEPLOY |
| F-09 | 🟡 Médio | Access token de 24h sem revogação | PÓS-DEPLOY |
| F-10 | 🟡 Médio | Troca/reset de senha não revoga sessões | PÓS-DEPLOY |
| F-11 | 🟡 Médio | Logs com tokens/PII no diretório; echo em dev | PÓS-DEPLOY |
| F-12 | 🟡 Médio | Sem cabeçalhos de segurança HTTP | PÓS-DEPLOY |
| F-13 | 🟡 Médio | `/docs` e `/redoc` expostos em produção | PÓS-DEPLOY |
| F-14 | 🟡 Médio | `/health` vaza detalhe de erro do DB | PÓS-DEPLOY |
| F-15 | 🟡 Médio | `TransacaoUpdate` sem validação de valor/tipo | PÓS-DEPLOY |
| F-16 | 🟡 Médio | `sessao_id` malformado → HTTP 500 | PÓS-DEPLOY |
| F-25 | 🟡 Médio | Reset token na query string do link de e-mail | PÓS-DEPLOY |
| F-17 | 🔵 Baixo | Enumeração por timing no forgot-password | PÓS-DEPLOY |
| F-18 | 🔵 Baixo | Falha de envio de e-mail derruba reset | PÓS-DEPLOY |
| F-19 | 🔵 Baixo | Sem verificação de e-mail no cadastro | PÓS-DEPLOY |
| F-20 | 🔵 Baixo | Política de senha fraca (mín. 8) | PÓS-DEPLOY |
| F-21 | 🔵 Baixo | Prompt injection (risco futuro do agente CRUD) | PÓS-DEPLOY |
| F-22 | 🔵 Baixo | Campos texto sem `max_length` | PÓS-DEPLOY |
| F-23 | 🔵 Baixo | Custo bcrypt não explícito | PÓS-DEPLOY |

---

## 5. Dependências (pip-audit)

Executado `pip-audit` no ambiente virtual. **Nenhuma vulnerabilidade conhecida** nas dependências de runtime da aplicação (fastapi 0.136.3, starlette 1.2.1, sqlmodel 0.0.38, pydantic 2.13.4, python-jose 3.5.0, bcrypt 5.0.0, cryptography 48.0.0, google-genai 2.7.0, psycopg2-binary 2.9.12, resend 2.30.1, httpx 0.28.1).

A única ferramenta com avisos foi o **`pip` 25.2** (build tooling, não faz parte do runtime em produção): `CVE-2025-8869`, `CVE-2026-1703`, `CVE-2026-3219`, `CVE-2026-6357`, `PYSEC-2026-196`. **Impacto baixo** (não exposto em produção), mas recomenda-se atualizar o `pip` no ambiente de build.

**Observação sobre fixação de versões:** o `requirements.txt` usa apenas pisos (`>=`), não versões fixadas. Para builds reproduzíveis e previsíveis em produção, recomenda-se **fixar versões exatas** (`==`) ou usar um lockfile (`pip-tools`/`uv`). Builds com `>=` podem trazer versões novas (potencialmente vulneráveis ou breaking) sem controle.

---

*Relatório gerado em 10/06/2026 — auditoria somente leitura, nenhuma alteração de código realizada. As correções devem ser priorizadas e aplicadas uma a uma com aprovação, começando pelos 10 bloqueadores de lançamento.*
