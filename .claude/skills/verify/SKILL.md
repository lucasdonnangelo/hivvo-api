---
name: verify
description: Como subir e dirigir o hivvo-api de verdade (uvicorn + SQLite isolado) para verificar mudanças ponta a ponta, sem tocar o banco do .env (Supabase).
---

# Verificar o hivvo-api ponta a ponta

**NUNCA suba o app com o `.env` do repo** — o `DATABASE_URL` real aponta para o
Supabase. Sempre sobrescreva por env vars (pydantic-settings: env var ganha do
`.env`).

## Receita (Git Bash)

```bash
SCRATCH_WIN="C:/caminho/windows/para/scratchpad"   # path WINDOWS na URL do sqlite (POSIX /c/... falha)
export DATABASE_URL="sqlite:///$SCRATCH_WIN/e2e.db" \
       SECRET_KEY="e2e-secret-key-0123456789abcdef0123456789abcdef" \
       RATE_LIMIT_ENABLED=false ENVIRONMENT=e2e

# 1. criar tabelas (não há create_all no boot; produção usa alembic)
PYTHONPATH="C:/Users/lucas/OneDrive/Desktop/hivvo-api" ./venv/Scripts/python.exe \
  -c "import app.models; from sqlmodel import SQLModel; from app.core.database import engine; SQLModel.metadata.create_all(engine)"

# 2. subir (background) e esperar /docs responder 200
./venv/Scripts/python.exe -m uvicorn main:app --host 127.0.0.1 --port 8765
```

## Dirigir a API

- Rotas de negócio sob **`/api/v1`**. Auth por **cookies** (`access_token`):
  `POST /api/v1/auth/register` `{email, nome_completo, password(≥8)}` já loga
  (201 + Set-Cookie) — com httpx, o `Client` guarda o jar sozinho.
- CSRF: `Origin` AUSENTE passa; `Origin` estranho em POST/PUT/DELETE → 403.
- Fluxo típico: register → `POST /transactions` (à vista/crédito; crédito
  avulso ganha `fatura_mes` pelo cartão) → `POST /cards`
  `{nome, tipo: "Crédito", dia_vencimento, dia_fechamento}` →
  `GET /statistics/monthly?mes=&ano=`, `/statistics/projection?meses=`,
  `PUT /installments/{id}` `{pago: true}`.
- Compra crédito em D com `dia_fechamento` F: D ≤ F → fatura do mês seguinte
  (offset 1); para cair fatura no mês M, compre em M−1 com D ≤ F.

## Gotchas

- Console Windows é cp1252: rode scripts com `PYTHONIOENCODING=utf-8` se
  imprimirem acentos/setas.
- httpx: `cookies=` por request MESCLA com o jar do client — para probe
  "sem sessão", use um client novo ou curl.
- Datas de negócio derivam de `app.core.dates.hoje()` (relógio real no app
  vivo) — cenários dependentes de dia devem ser calculados a partir de hoje.
