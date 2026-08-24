# Engineering Practices

How this codebase is built and verified. Written because the *practices* are the
part of this project worth reading — the domain logic only matters if you can
trust that it works.

> **This document is shared between the two repositories** (`hivvo-api` and
> `hivvo-web`) and is byte-identical in both — it is generated into the frontend
> repo by a sync script, not edited there. **Unqualified paths refer to
> `hivvo-api`**, where most of the tooling lives; frontend paths are named as
> such. So `scripts/mutacao.py` means `hivvo-api/scripts/mutacao.py`, and you
> will not find it in the frontend checkout.

---

## The problem with green tests

A passing suite proves the tests pass. It does not prove the tests *test
anything*. The gap between those two statements is where most of the effort in
this project went.

Coverage does not close it. Coverage tells you a line executed. It does not tell
you that anything would have failed if that line were wrong.

### Mutation verification as a gate

The rule: **break the rule in the source, and the test must go red.** A test that
stays green after the behaviour it claims to guard has been removed is not a
test — it is a comment that costs CI minutes.

This is automated. `scripts/mutacao.py` takes a JSON spec, applies an exact
source substitution, runs one named test, and reports whether the mutation
**survived**. Specs live in `scripts/mutacoes/`, versioned, so the proof is
reviewable and repeatable instead of something someone did once by hand:

```json
{
  "titulo": "business route mounted outside /api/v1",
  "arquivo": "main.py",
  "de":   "app.include_router(feedback.router, prefix=\"/api/v1\", dependencies=_csrf)",
  "para": "app.include_router(feedback.router, dependencies=_csrf)",
  "teste": "tests/routers/test_api_v1_prefix.py::test_toda_rota_de_negocio_esta_sob_api_v1"
}
```

The harness restores the file even on crash or Ctrl-C, replaces only the first
occurrence, and — importantly — **fails loudly when the snippet is not found**
instead of reporting a cheerful green. That property was added after an accent
mismatch between the spec and the source (`não` against `nao`) meant the
substitution never happened, and the run reported success over a mutation it had
not applied.

**What it actually caught.** The technique is usually sold as a way to find bad
*code*. Here it has mostly found bad *tests*:

- A `getattr` in a test swallowed the `AttributeError` it was meant to detect,
  so the assertion never ran.
- In one batch, **two of five mutations survived**. One test passed because a
  different validator already rejected the case on its own, so the filter under
  test was never what made it pass; the other because the fixture happened to
  place the relevant rows last, making position and index coincide and hiding a
  positional bug. Both fixes were in the *test*, not in the code.

> These are recorded cases, not illustrations. All three are documented in the
> module docstring of `scripts/mutacao.py`, which is where they were written
> down when they happened — a document arguing *do not assert what you have not
> measured* should say where its own examples come from.

### The test that passed on an empty set

The sharpest example. A test asserted that a particular route did not exist
under the versioned prefix. It passed. It had always passed — because the set of
routes it inspected was **empty** under the FastAPI version production actually
runs, so the assertion was trivially true over nothing.

The cause is worth knowing. Until FastAPI 0.136, `include_router` flattened
sub-routes into `app.routes`; from 0.141 it appends one opaque wrapper object
per included router instead. Routing did not change. **Introspection did.** The
test was reading an internal structure rather than a contract, and the internal
structure moved underneath it.

Two changes came out of it, and both are the lesson:

1. The test now reads the **OpenAPI schema** — a public, versioned contract —
   instead of `app.routes`. The same paths and operations appear under both
   FastAPI versions, byte-identical.
2. The test asserts the set is **non-empty before asserting anything about it**:

   ```python
   assert rotas, "expected business routes published in the schema"
   ```

   One line. It is the whole difference between *nothing violated the rule* and
   *nothing was checked*.

The mutation spec that kills the rewritten test is committed beside it, with
three variants — because the first mutation that "should" have caught the
original did not, and discovering that is the entire point of running them.

---

## Dependencies: locked, with a gate that has teeth

Both repos pin the full dependency graph, transitives included. That part is
ordinary. The part that matters is that **something fails when the lock and the
declared intent drift apart.**

### Backend

`requirements.in` and `requirements-dev.in` hold *intent*, edited by hand.
`requirements.txt` and `requirements-dev.txt` are **generated**, fully pinned to
`==`, by `scripts/travar_deps.py`.

`travar_deps.py --check` recompiles from the `.in` files into a temporary
directory and compares against what is committed. CI runs it **before**
installing anything — because if the lock does not match the intent, whatever
the next step installs is not the set anyone approved, and the suite result
would describe nothing reviewable.

Two design details carry the weight:

- **The resolver version is pinned.** The comparison is exact, so a differently
  formatted output is a false failure.
- **`--exclude-newer` cuts the package index at a fixed date**, which is what
  makes the recompile deterministic. This is not convenience. Without it, the
  only way to recompile without failing on the calendar would be to let the
  resolver read its own previous output as *preference* — and then a pin someone
  downgraded by hand would be respected by the recompile, and the drift would
  pass silently. That was measured before choosing, and it did pass. With the
  cut, resolution does not depend on the file, so hand edits reappear as a diff.

Updating dependencies means **raising that date and re-running the script**. The
date appears in the diff and someone approves it. Until it moves, no newly
published release enters — not in CI, not in the deploy build.

The same script also carries a correction worth repeating here, because it is
the kind of thing that quietly becomes false: its own docstring used to claim
the check compared files **byte for byte**. It does not. It reads both sides
with Python text mode, which normalises line endings before comparing — so the
gate is structurally blind to CRLF. The claim was fixed to say what the code
does. A gate that promises more than it delivers is worse than one that promises
less.

### Frontend

The lockfile is the pin, and `npm ci` is the gate: it refuses what `npm install`
tolerates.

That distinction was not theoretical. **The lockfile had been broken for
months** and nobody knew, because `npm install` kept papering over it locally.
The first CI run rejected it immediately.

After it was regenerated, the new lock was **falsified against five npm
versions** with `npm ci --dry-run --ignore-scripts` before being accepted. All
five accepted it.

That test also refined its own claim, which is the part worth keeping: it proves
the lock is **installable and consistent with `package.json`**. It does **not**
prove every npm version builds an identical tree — two of the five would install
64 additional packages from the same lock, a difference in how major versions
resolve platform-optional dependencies. Not a defect, but not something to
assume either.

---

## Hypotheses are struck through, not deleted

When a documented assumption turns out to be wrong, the old claim stays in the
document, struck through, with the date and the measurement that killed it.

This is deliberate. Deleting a wrong claim erases the evidence that the question
was ever settled, and the same wrong assumption gets re-derived months later by
someone reading a document that now looks confident. Keeping the correction
visible makes it durable, and makes the reasoning auditable.

The habit has a companion rule: **do not assert what has not been measured.**
Several claims in this project's documentation were, at some point, descriptions
of what was *planned*, written as though they already existed. Every one of them
cost real time later, because design work got built on top of fiction. The rule
now is that a document may state only what was verified in the code or observed
in a running system, and anything partial has to say that it is partial.

A concrete case, from infrastructure rather than product. A branch protection
ruleset was configured, showed as **Active** in the UI with force-push blocking
enabled, and was documented as protecting the default branch. A later operation
needed a force push — and it went through, on both repositories, with no bypass
and no configuration change. The configuration was real; the protection was not.
The claim was struck through and replaced with the measurement, plus an explicit
note that the behaviour has to be re-checked rather than assumed when the
surrounding conditions change.

**Configuration you can see is not protection you have.** That sentence cost a
measurement to earn, which is exactly why it is written down.

---

## Where the effort went

| Practice | What it buys |
|---|---|
| Design settled and reviewed before code | Fewer rewrites; the argument stays on record |
| Mutation specs committed beside tests | Proof that a test tests, re-runnable by anyone |
| Lock plus drift gate | The set CI runs is the set someone approved |
| Struck-through hypotheses | Corrections that survive the next reader |
| Reconciliation against declared totals | Non-deterministic extraction, deterministic check |

None of this is exotic. It is mostly the discipline of asking, for every green
result, *what would have made this red?* — and then arranging for the answer to
be something a machine can demonstrate.
