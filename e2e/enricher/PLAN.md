# E2E gate — the enricher (section `enricher`)

**Status: BUILT AND RUN** (2026-11-23, `feat/consolidate-enricher`). Real results are in
`CASES.md`; this file is the reasoning. The overall design lives in
`docs/implementations/enricher-consolidation/PLAN.md` §3.

## What this gates

`src/enricher/` is the local worker that labels JVN's jobs. In prod it is a launchd agent
that runs `scripts/enrich_tick_wrapper.sh` every 60 s; each tick claims OPEN jobs from the
backend, cleans them, classifies (and sometimes judges) them with a local model, and writes
the results back. This gate runs **that exact path** — the real wrapper, the real CLI, the
real backend endpoints, a real Postgres — with only the model weights replaced.

---

## 0. TL;DR

| | |
|---|---|
| **Run it** | `e2e/run.sh enricher` (measured 60 s, 16 cases) · `--fast` (27 s, 7 cases) · `--enricher-ref enricher-prod-eeff1c9` (51 s, 12 cases) |
| **Cost** | **$0, unconditionally.** The model is a stub on loopback. No `claude`, no real ollama, no Browserbase, a blank Anthropic key on the backend. |
| **Ports** | backend `8207`, kill-switch backend `8206` (EN-08 only), stub model `8215`. No frontend. |
| **Database** | **its own** — `jobscraper_e2e_enricher`, schema-only, plus a drift repair (§4) |
| **What runs** | a throwaway COPY of the enricher, outside the repo (§2) — never `src/enricher` itself |
| **Nothing starts red** | every case was green on a real run at HEAD and at the prod tag, and two deliberate mutations were used to prove they bite (§6) |

---

## 1. The stack

| Piece | What it is |
|---|---|
| Backend | the real `e2e.shared.stack.e2e_app:app` on :8207, `ENRICHMENT_USE_EXTERNAL=true`, the **internal-key middleware armed** with the test key from `env.enricher` |
| Kill-switch backend | a second, short-lived backend on :8206 over the same database with `ENRICHMENT_USE_EXTERNAL=false` (EN-08 only; the add-companies AC-09 pattern) |
| Model | `stub_ollama.py` on :8215 — stdlib HTTP, implements ollama's `POST /api/chat` |
| Enricher | a sandbox copy, its own venv (`uv sync --frozen --python 3.12`), its own `.env.local` |

**Shared infra was generalised, not forked** — three new `stack_up.sh` knobs, each defaulting
to the shipped behaviour:

| Knob | Default (= today) | This section |
|---|---|---|
| `E2E_SKIP_FRONTEND` | `0` | `1` — backend only; the frontend port is neither checked nor claimed |
| `E2E_INTERNAL_API_KEY` | empty → `INTERNAL_API_KEY` stays unset | the test key — the enricher's `JVNClient` refuses to call without one, so this is the first section whose backend runs with the middleware armed |
| `E2E_BLANK_ANTHROPIC_KEY` | `0` → inherit as before | `1` → exported **empty**, which beats the root `.env.local` the backend would otherwise read it from. The backend's `scan_unnormalized` task bills Haiku every 5 minutes when a key is set; with this, it cannot |

`stack_down.sh` already tolerated a missing frontend pidfile (verified, unchanged).

---

## 2. The sandbox — why a copy, and why outside the repo

Every durable path the enricher has is **package-relative** (`store.REPO_ROOT =
parents[2]`): the SQLite DB, the tick lock and the chunk directory live wherever the
package source lives. Running `src/enricher` directly would create `src/enricher/data/` in
the owner's checkout. So `sandbox.py`:

1. copies the working tree with `rsync` (excluding `.venv`, `data`, `.env`, `.env.local`,
   `.checkout-role`, `__pycache__`, `.pytest_cache`, `.coverage`, `.idea`,
   `dashboard/node_modules`, `dashboard/dist`) — or, with `--enricher-ref <ref>`,
   `git archive <ref>:src/enricher`;
2. `uv sync --frozen --python 3.12` (the only step allowed network, for a cold uv cache);
3. writes a `.env.local` with **test values only** (`JVN_BASE_URL=:8207`,
   `INTERNAL_API_KEY=e2e-enricher-not-a-secret`, `OLLAMA_BASE_URL=:8215`) and a
   `.checkout-role` of `e2e-sandbox`;
4. **proves the isolation**: the sandbox's own interpreter must report
   `job_enricher.store.REPO_ROOT` == the sandbox directory, or the run refuses.

**Location: `$TMPDIR/jvn-e2e-<repo hash>/enricher-sandbox/<run id>/`**, not under
`artifacts/` as first planned. `vercel dev` watches the whole repo, and a venv of a few
thousand files appearing and vanishing under it is exactly the kind of churn that has taken
the owner's dev server down before (see `e2e/run.sh`'s lock comment). `run.sh` copies every
case's `data/` into `artifacts/<run>/enricher-data/` on the way out, then removes the
sandbox (`--keep-up` keeps it).

**Each case starts from an empty local state.** The conftest moves the sandbox's `data/`
aside to `data-archive/NN-<case>` after every case, so no case inherits another's DB, lock,
knobs or half-classified rows.

---

## 3. How every enricher process runs here: launchd's environment

The prod plist runs `ProgramArguments = [<checkout>/scripts/enrich_tick_wrapper.sh]` with
`WorkingDirectory = <checkout>` and `EnvironmentVariables = {PATH:
/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin}`. `sandbox.tick_env()` builds exactly that
**from scratch** (HOME/USER/LOGNAME/SHELL/TMPDIR + the plist's PATH), so the enricher's
config comes from `.env.local` alone, as in prod, and nothing exported in the gate's own
shell (`OLLAMA_BASE_URL`, `JVN_BASE_URL`, `INTERNAL_API_KEY`) can leak into a tick. Three
e2e-only additions, none of which changes what the wrapper does:

* `UV_OFFLINE=1` — `uv run` may not reach the network mid-tick;
* every proxy variable points at `127.0.0.1:9` (discard; nothing listens) with
  `NO_PROXY=127.0.0.1,localhost` — any non-loopback HTTP the enricher tried would fail fast
  instead of leaving the machine;
* `ENRICH_TICK_TIMEOUT_SECS=600` — each tick leaves its watchdog's `sleep` behind as an
  orphan (pre-existing, harmless: its parent subshell is killed, so the `kill` never runs);
  ten minutes instead of three hours keeps a gate run from leaving dozens. No case runs near it.

**Boot guards** (`sandbox.py guard`, before any case): the sandbox path is not under
`~/developer/personal/{app,enricher-prod,job-enricher}` or `src/enricher`;
`.env.local`'s `OLLAMA_BASE_URL` is loopback `:8215` (never `:11434`), `JVN_BASE_URL`
loopback `:8207`, the key is the test key; `cli init` + `cli health` report
`classify_engine=ollama` and `judge_engine=ollama` — so the wrapper can never take the
`claude -p` branch.

---

## 4. The database — and the drift it needed repaired

`ensure_db.sh --schema-only` clones `jobscraper_pr243`, and that local source is
**drifted**: its `alembic_version` is stamped past migrations whose effects it does not have.
Measured 2026-11-23, and the same in every local `jobscraper*` database:

| Missing | From | Effect on the enricher's write path |
|---|---|---|
| `job_listings.search_text`, `primary_country` | `e3b1a4c9d7f2` | `apply_result` recomputes `search_text` on every row → **every** `/results` item fails `UndefinedColumn` |
| `job_categories.data_scientist` | `0fa33aca5bda` | a correct data-science label FK-fails |
| `job_levels.intern` | `0b61e444ea25` | a correct intern label FK-fails |

`seed.repair_known_drift()` (run by `run.sh` after the stack is up) adds the two columns as
the migration declares them (nullable `text`, no default) and upserts both dimension tables
from `src/backend/taxonomy.json` — JVN's **generated** taxonomy artifact, read, never
re-typed. Idempotent, printed (`artifacts/<run>/drift-repair.txt`), and section-local on
purpose: changing `ensure_db.sh` would change every other section's database too. A
from-scratch `alembic upgrade head` was tried first and does not work (the chain assumes a
pre-existing base schema: `relation "users" does not exist`).

**Seeding** is raw SQL fenced by `assertions.connect` on rows with `source_id =
'e2e_enricher'` (same reasoning as `subcategories/seed.py`: there is no product endpoint
that creates a job listing). Two writes reach beyond those rows, both in this section's own
database and both documented in `seed.py`: `enrichment_ticks` is cleared per case (only this
section ever pushes metrics here), and **every company except the fixture company is
disabled** — the schema-only clone arrives with enabled ashby companies, and the backend's
`*/30` fan-outs would otherwise scrape real boards into this database, rows the enricher
would then claim. `assert_no_foreign_claimable_rows` fails loudly if a fan-out got there
first.

---

## 5. The stub model

ollama's native API is one call: `POST /api/chat` with `{model, messages, stream: false,
format: <json schema>, options: {temperature: 0}}`, answered by `{message: {content}}`.
`OLLAMA_BASE_URL` pointed at the stub therefore runs the enricher's REAL engine code — prompt
build, HTTP, envelope parse, JSON-array recovery, the retry nudge, single-input identity
repair — with only the weights replaced.

It reads the LAST `<job_data>` block of the prompt, tells classify / judge / subcategory
prompts apart by their opening line (identical in the v6 tag and v7 main), and answers each
job from `fixtures.py` — so every assertion compares JVN against the answer the stub was
TOLD to give, never against the code under test. Answers always carry the v7 keys too; the
v6 recorder ignores keys it does not read.

Misbehaviour is either **global** (`POST /__stub/mode`: `http500`, `garbage`,
`hallucinate_id`, `invalid_facet`, `slow`, optionally scoped to one stage) or **per row**
(`Job.behaviour`: `extra_ghost`, `invalid_category`, `garbled`, `http_garbage`, `long_tag`),
so one tick can mix good and bad rows (EN-06). Every request is logged
(`GET /__stub/requests`) with stage, model, temperature, format type, job ids, source ids,
Host, whether it carried the retry nudge, and the status it got.

---

## 6. Proven to bite

A gate that has only ever been green has not been tested. Two deliberate mutations were
applied, the cases re-run, and the mutation reverted (`git status` clean / the stub
restored byte-for-byte from a copy):

| Mutation | Result |
|---|---|
| **M1** — `enrich_tick_wrapper.sh`'s in-process branch skips `write-back` (`: MUTATION-M1`) | **EN-01 RED** — `FAILED while: reading JVN's job_listings…` (`EN01-SWE-SR: status 'claimed'`). **EN-05 RED** — `FAILED while: tick 1, model down` (`the outage tick never reached write-back`). |
| **M2** — the stub silently omits one row's answer (`EN10-A`) | **EN-10 RED** — `the enricher queued 3+1 chunks but the stub saw 5 calls` (the omitted row triggered the engine's nudged retry, so the request count no longer equals the chunk count). |

---

## 7. `--enricher-ref`

`e2e/run.sh enricher --enricher-ref enricher-prod-eeff1c9` runs the same cases against the
exact code the cutover will put in prod (its `src/enricher` tree is `471165a3…`, the live
checkout's tree). Cases marked `v7` need the v7 epic (#18–#20: subcategories, P0-3's error
counting); `run.sh` asks the ref's own CLI whether it has `subcategory-push` and, if not,
**deselects** them with `-m "not v7"` — they are not collected, so they cannot read as
BLOCKED. Measured: 12 PASS, 4 deselected, GREEN.

---

## 8. What this section does NOT cover

* **launchd itself.** The gate execs the wrapper the way launchd does (same argv, cwd and
  env) but never loads a plist. The cutover's launchd handling is `enricher-cutover`'s job.
* **The `claude-code` engine.** That path runs `claude -p` (real money, real model) and the
  boot guard refuses it by design. Its prompts and recorders are covered by the unit suite.
* **The subcategory backfill lane** (`subcategory-backfill`, `subcategory-push`). By-hand
  operator commands, not in the tick wrapper. The stub answers the subcategory prompt, so a
  case can be added later.
* **The 3 h watchdog firing.** No case waits for it; `ENRICH_TICK_TIMEOUT_SECS` is 600 here.
* **Real model quality.** Deterministic answers prove the plumbing, not the labels. That is
  the eval gate's job (`cli eval --gate`).
* **The Vercel proxy.** The enricher talks to the backend directly in prod too, so there is
  no proxy hop to miss.

---

## 9. Re-runnability

* `ensure_db.sh` provisions once; `--refresh-db` re-clones. The drift repair is idempotent.
* `seed.reseed` drops and rewrites the case's rows (and the tick table) at the start of every
  case; each case also gets a fresh local DB (§2).
* The stub is reset to `normal` before every case.
* `run.sh` takes its own lock (`$TMPDIR/jvn-e2e-<hash>/enricher.lock`), tears down on
  failure and Ctrl-C (kills any process still running from the sandbox path, the stub and
  the kill-switch backend by pidfile, then `stack_down.sh`), and labels an interrupted run
  **ABORTED**.
* After pytest, `run.sh` re-checks that `src/enricher/data` in the dev tree is exactly as it
  found it, behind EN-10.
