# hivvo-api

Backend for Hivvo — a personal finance app built around how Brazilian credit
cards actually work.

[app.hivvo.app](https://app.hivvo.app) · [frontend repo](https://github.com/lucasdonnangelo/hivvo-web)

[![CI](https://github.com/lucasdonnangelo/hivvo-api/actions/workflows/ci.yml/badge.svg)](https://github.com/lucasdonnangelo/hivvo-api/actions/workflows/ci.yml)

---

## The problem

Most personal finance software assumes **a transaction is an expense in the
month it happened**. In Brazil that assumption is wrong often enough to make the
numbers useless, for two reasons that compound.

**1. Instalments are the default, not the exception.** Brazilian retail runs on
`parcelamento`: a R$ 1,200 purchase is routinely charged as *12x de R$ 100*, at
no interest, and this is the normal way people buy. So a single purchase in
March is not a March expense. It is twelve monthly obligations spread across a
year, and eleven of them belong to months that have not happened yet. Any model
that stores "one purchase, one amount, one date" has already lost the
information the user needs most: *what do I actually owe in July?*

**2. The billing cycle is not the calendar month.** A card has a **closing day**
(`fechamento`) and a separate **due day** (`vencimento`), and they are usually in
different months. Buy on the 8th when the card closes on the 5th, and the charge
does not land on the invoice about to be paid — it lands on the *next* one, due
roughly seven weeks later. The mapping from purchase date to invoice depends on
the card, not on the calendar, and each of a person's cards has different days.

Put together: **the month a purchase happened, the month it is billed, and the
month it is paid are three different months**, and a user with four cards has
four different mappings running at once.

That is the modelling problem this backend exists to solve. Everything else here
is ordinary CRUD.

### One consequence worth spelling out

Because of the above, "how much did I spend this month?" has **two legitimate
answers**, and they are different numbers:

- **Cash flow** — what leaves the account this month. Invoices falling due now,
  regardless of when the purchases happened.
- **Consumption** — what was consumed this month. Purchases made now, regardless
  of when they will be billed or paid.

Neither is more correct. A user planning their balance needs the first; a user
asking whether they overspent needs the second. The API serves both from the
same records rather than picking one and calling it "spending".

---

## What it does

Verified against the code, not the roadmap.

- **Transactions** — income, expense and *estorno* (refund/chargeback) as a
  distinct third type, because a refund is not income and treating it as one
  distorts every category total.
- **Cards and invoices** — per-card closing day, due day and month offset;
  invoice composition, totals, and a derived status per billing period.
- **Instalments** — a purchase expands into `n` instalment rows, each mapped to
  the billing period that will actually carry it.
- **Invoice payment** — confirmation per card and period, with partial-coverage
  handling when the invoice grows after being marked paid.
- **Recurring entries** and forward projection.
- **Statistics** — monthly, yearly, evolution over time, category breakdown,
  card breakdown, comparison against the previous period, and highlights.
- **PDF import** — credit card statements (`fatura`) and bank statements
  (`extrato`), parsed by an LLM and reconciled against the totals the bank
  itself prints.
- **AI assistant** — chat and category suggestion, grounded in the user's real
  financial context.
- **Auth** — registration, login, refresh tokens, password reset by email,
  account deletion.
- **Due-date notifications** — a scheduled job that emails upcoming invoice due
  dates.

---

## Architecture

```
                    ┌──────────────────────┐
   browser ────────▶│  hivvo-web (Vercel)  │
                    │  React 19 · Vite     │
                    └──────────┬───────────┘
                               │  HTTPS, httpOnly cookies
                               ▼
                    ┌──────────────────────┐        ┌─────────────────┐
                    │  hivvo-api (Railway) │───────▶│  Gemini API     │
                    │  FastAPI · SQLModel  │        │  chat · import  │
                    └──────────┬───────────┘        └─────────────────┘
                               │  PostgreSQL
                               ▼
                    ┌──────────────────────┐
                    │  Supabase (Postgres) │
                    └──────────────────────┘

   scheduled job (Railway cron) ──▶ due-date email via Resend
```

| Choice | Why |
|---|---|
| **FastAPI** | Request/response schemas are the validation layer *and* the OpenAPI contract. One definition, and the contract is machine-readable — which is what lets a test assert routing topology against a published schema instead of framework internals. |
| **SQLModel** | One model class for table and schema. The cost is coupling; the benefit is that domain invariants live next to the column definitions where they are hard to forget. |
| **PostgreSQL / Supabase** | The domain needs real constraints — `UNIQUE` on natural keys, `CHECK` on value ranges — enforced by the database rather than by application code that can be bypassed. Managed hosting because operating a database is not the interesting part. |
| **Alembic** | Migrations run as the deploy platform's `preDeployCommand`, so schema and code ship in the same step instead of as two things someone has to remember to sequence. |
| **`Decimal` for money** | Every monetary column, contract field and calculation is `Decimal` — `app/models/` and `app/schemas/` contain no `float` at all. Splitting an instalment divides `Decimal` by `int`, quantises `ROUND_HALF_UP`, and gives the remainder to the last instalment so the parts sum exactly to the whole. The one `float` in `app/` is a *derived percentage* handed to the AI context, computed in `Decimal` and converted only at that boundary. |
| **Stateless auth, revocable sessions** | No in-memory session store, so any instance can serve any request. But refresh tokens *are* persisted, with `revogado` and `expires_at`, so sessions can be ended for real: logout, "log out everywhere", **and both password change and password reset** revoke every refresh token for the user in the same transaction. The trade is explicit — access tokens stay stateless JWTs, so revocation takes effect on the next refresh rather than instantly. |

---

## Engineering decisions

Five decisions where the reasoning is more interesting than the outcome.

### 1. Invoice status is derived, never stored

An invoice resolves to one of six states — `aberta` (open), `a_vencer` (closed,
not yet due), `atrasada` (overdue), `paga` (paid), `paga_parcial` (partially
covered) and `vazia` (nothing billed in the period). They are string values
returned by `services/faturas.status_fatura()`, not a stored enum: the obvious
design would keep that in a column, and this codebase computes it on read, every
time, and **never materialises it**.

The reason is that invoice status is a function of things that keep changing
underneath it: the current date, the composition of the invoice, and whether a
payment covers the current total. A stored status is a cache of a function over
mutable inputs, which means every write path that touches any input has to
remember to update it. Miss one and the invoice is silently wrong — and *silently
wrong* is the worst failure mode for a number a user makes decisions on.

Concretely: a user marks an invoice paid, then adds a purchase dated inside that
period. With a stored status, that purchase must trigger a status recalculation
or the invoice keeps claiming it is settled. With a derived status, the total
rises, the recorded payment no longer covers it, and the invoice becomes
*partially paid* on the next read — with the uncovered difference reappearing in
what the user owes. No write, no trigger, no cache to invalidate.

The one thing that *is* stored is the amount paid at the moment of payment. That
is a historical fact, not a derivation, and it is what makes coverage
computable.

### 2. The same data serves two lenses, deliberately

Following from the problem statement: cash flow and consumption are different
questions over the same records.

The temptation is to pick one and call it "spending". This project serves both,
which costs a second aggregation path and the discipline of keeping them
labelled. The reason is that collapsing them produces a number that is wrong for
both questions and looks authoritative — the failure mode where software is
worse than a spreadsheet, because a spreadsheet at least shows its work.

### 3. LLM extraction, deterministic reconciliation

PDF statement import uses an LLM, because bank statement layouts are numerous,
undocumented and change without notice. Writing a parser per bank is a treadmill.

But an LLM is **non-deterministic**, and this is financial data. So extraction is
never trusted on its own: every import is **reconciled against the totals the
bank itself printed on the statement.** Sum the extracted line items, compare to
the declared total, and carry the verdict through the whole flow.

**The reconciliation deliberately does not block the import**, and that is a
decision rather than a gap. A mismatch is not always an extraction error — some
issuers list a previous cycle's payment on the statement, which makes the
arithmetic legitimately disagree on a perfectly good import. So a failed
reconciliation is not an HTTP error: the preview returns `200` with `bate=false`,
the discrepancy is shown, and a human decides whether to commit. Refusing
automatically would reject good imports to feel safe; surfacing the number and
deferring to the person is what the two-step preview/commit flow exists for.

The subtle part — and this was found by testing against real statements — is
*which* declared total to anchor on. The intuitive choice is "total due". It is
the wrong one: that figure is **net**, embedding previous balance and payments
already made, so it produces false mismatches on perfectly good imports. The
anchor is the **gross consumption the bank declares for the cycle** (purchases
plus IOF), which is independent of the itemised lines — otherwise the check is
circular, validating the extraction against itself.

All arithmetic happens in `Decimal`, in Python, never in the model's output.

### 4. Idempotency enforced by the database, before anything else

Re-importing the same statement must not duplicate a year of instalments.

The naive guard is to check whether the batch already exists and bail out. That
loses to a double-click: two requests both check, both see nothing, both write.

Instead, the commit **inserts the batch record first**, in the same transaction,
against a `UNIQUE` on the natural key (user, card, billing period). The unique
violation *is* the guard. It is atomic because the database makes it atomic, and
it closes the race that a pre-check leaves open. A duplicate import gets a clean
409 instead of a corrupted ledger.

### 5. Domain logic in `services/`, and the Repository Pattern is *not* here

Business rules live in `app/services/` as functions operating on models, with
data access alongside them.

An earlier version of the project documentation described a layered architecture
with a repository abstraction **as though it already existed**. It did not. That
claim was corrected rather than quietly implemented, and the honest state is
this: `app/repositories/` exists as an empty package and nothing imports it. It
is a planned refactor, not a current fact.

Keeping it that way is a deliberate trade. The abstraction buys swappable
persistence and easier mocking; it costs an indirection layer in a codebase with
one database and no plan to change it. The pragmatic version ships, and the
tests reach the real database anyway. When the second consumer or the second
backend appears, the seam is worth building — and not before.

That this is written down as a gap, rather than described as done, is the point.

---

## Testing and quality

This is where most of the work is.

**1,148 tests**, across 66 test files, run on every push. Not a coverage
percentage — a count you can reproduce with `pytest --collect-only -q`.

**CI on both repositories.** This one runs the lock check, installs the locked
set, and runs the suite on Python 3.13.

**Dependencies locked with a drift gate.** `requirements.txt` is generated and
fully pinned. CI recompiles it from the intent files and **exits non-zero if the
result differs from what is committed** — before installing anything, so a lock
that has drifted from its declared intent never reaches the suite.

**What that gate does *not* do, stated precisely.** It reports; it does not
block. A branch ruleset is configured and shows as active, but repository
rulesets are not enforced on private repositories under the free plan — measured
rather than assumed, by a force push that went through on both repositories with
no bypass. So today the red is informational and the discipline is the
enforcement. That changes when these repositories become public and the ruleset
begins to apply, which is a thing to **re-measure then**, not presume.

### Mutation verification

The part worth reading about.

A passing test proves the test passes. It does not prove the test *tests
anything* — and coverage cannot tell the difference, because coverage records
that a line ran, not that anything would have failed if the line were wrong.

So the rule here is: **break the rule in the source, and the test must go red.**
`scripts/mutacao.py` applies an exact source substitution, runs one named test,
and reports whether the mutation **survived**. The specs are committed in
`scripts/mutacoes/`, so the proof is reviewable rather than a one-off.

It mostly catches bad *tests*, not bad code. The sharpest case: a test asserting
a route did not exist was passing **because the set of routes it inspected was
empty** under the FastAPI version production runs — the assertion was trivially
true over nothing. The fix reads the OpenAPI schema (a versioned contract)
instead of framework internals, and asserts the set is non-empty before
asserting anything about its contents.

Full detail in [docs/ENGINEERING.md](docs/ENGINEERING.md).

---

## How this was built

Built with AI assistance, and the method is the part worth describing.

Design was settled and reviewed **before** code, in writing. Verification was by
mutation, not by coverage: reintroduce the defect and watch the test fail, or the
test does not count. When a measurement contradicted a documented assumption, the
old claim was **struck through with the date and the evidence**, never quietly
deleted — so the correction survives the next reader.

Two examples, both real, both in the history of this repo. A test that had always
passed because it asserted over an empty set, found by mutation and rewritten
against a public contract. A frontend lockfile broken for months, hidden by
`npm install` and caught the first time strict `npm ci` ran in CI — then
falsified against five npm versions before the replacement was accepted.

The tooling is fast. Deciding what would have to be true for a green result to
mean something is the part that is not, and that part does not come from a model.

---

## Running locally

Requires **Python 3.13** and a **PostgreSQL** database.

> Postgres is not optional for the schema. The migrations use Postgres-only
> constructs — `gen_random_uuid()` in a data backfill, and `ENABLE ROW LEVEL
> SECURITY` on six tables — so `alembic upgrade head` against SQLite fails on
> the fifth of fourteen migrations. The **test suite** does run on SQLite, but
> it builds the schema with `SQLModel.metadata.create_all()` and never touches
> Alembic, which is why one works and the other does not.

```bash
git clone https://github.com/lucasdonnangelo/hivvo-api.git
cd hivvo-api

python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # Windows
# source .venv/bin/activate && pip install -r requirements-dev.txt  # Linux/macOS

cp .env.example .env        # then fill it in — see the table below

alembic upgrade head        # create the schema
python -m uvicorn main:app --reload
```

API docs at `http://localhost:8000/docs`. Business routes live under
`/api/v1`; `/health` stays at the root for the load balancer.

```bash
python -m pytest -q                       # the suite
python scripts/travar_deps.py --check     # dependency drift gate

# mutation harness — proves the tests actually test
PYTHONIOENCODING=utf-8 python scripts/mutacao.py scripts/mutacoes/topologia_api_v1.json
# -> 3/3 mortas — every rule in the spec has a test that proves it
```

> `PYTHONIOENCODING=utf-8` is needed on a Windows console: the default code page
> cannot encode the arrows in the report and the script dies while printing a
> result it already computed correctly. Known, tracked, cosmetic.

> The drift gate shells out to `uv`, which is intentionally **not** in the lock —
> it is the tool that *generates* the lock. Install it separately
> (`pip install uv==0.12.5`) if you want to run that gate.

### Environment variables

Never commit real values. `.env` is gitignored; `.env.example` documents the
shape.

| Variable | Required | What it does |
|---|---|---|
| `DATABASE_URL` | **yes** | Postgres connection string. No default — the app refuses to boot without it. |
| `SECRET_KEY` | **yes** | JWT signing key. No default; validated for strength in production. |
| `ENVIRONMENT` | no | `development` / `test` / `production`. Gates SQL echo, debug logging and production fail-fast checks. |
| `FRONTEND_URL` | no | Origin allowed by CORS and by the CSRF Origin check. |
| `GEMINI_API_KEY` | no | AI assistant. Absent, those endpoints return a clear error rather than crashing. |
| `GEMINI_IMPORT_API_KEY` | no | **Separate** key for PDF import — isolated cost and quota. Production will not boot without it. |
| `RESEND_API_KEY` | no | Transactional email (password reset, due-date notices). |
| `SENTRY_DSN` | no | Error monitoring. Absent is a no-op **by design**, not an error. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | Access token lifetime. |

---

## Repo map

```
app/
  core/          config, database, security, CSRF, dates, Gemini safety settings
  models/        SQLModel tables — the domain, with constraints attached
  schemas/       request/response contracts (Pydantic)
  routers/       HTTP endpoints, one module per resource
  services/      business logic — invoices, instalments, statistics, imports
  repositories/  empty: planned refactor, see Engineering decisions #5
alembic/         14 migrations; applied on deploy by preDeployCommand
tests/           66 files, 1,148 tests
scripts/
  travar_deps.py     lock generator + drift gate
  mutacao.py         mutation harness
  mutacoes/          committed mutation specs
  sync-docs.py       propagates shared docs to the frontend repo
docs/              product reference, design decisions, engineering practices
```

---

## Status and limitations

Feature-complete for its core and running in production. Honest gaps:

- **The Python interpreter version is not pinned.** CI fixes 3.13; the deploy
  platform resolves it per build. They agree today by coincidence of timing, not
  by rule. Known and tracked.
- **`app/repositories/` is empty.** The layered refactor is planned, not done —
  see Engineering decisions #5.
- **Rate limiting is in-memory**, which is correct for a single instance and
  would need a shared store before scaling horizontally.
- **Import is validated against real statements from a handful of Brazilian
  banks**, not exhaustively. Reconciliation surfaces an unfamiliar layout as a
  visible mismatch at preview, but **does not refuse the import** — the decision
  is the user's, see Engineering decisions #3.
- **PDF import needs a text layer.** No OCR, so scanned statements are out of
  scope.
- **Frontend dependency advisories** are tracked in the
  [hivvo-web README](https://github.com/lucasdonnangelo/hivvo-web#status-and-limitations).

<!-- SCREENSHOT: dashboard — two-lens monthly view -->
<!-- SCREENSHOT: invoice detail — instalments vs one-off charges -->
<!-- SCREENSHOT: PDF import — reconciliation result -->

---

The frontend lives in [hivvo-web](https://github.com/lucasdonnangelo/hivvo-web).

## License

Source is published for evaluation and portfolio review. **All rights
reserved** — no licence is granted for use, modification or redistribution.
