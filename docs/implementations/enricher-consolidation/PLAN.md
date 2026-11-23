# Enricher consolidation — job-enricher moves into JVN `src/enricher/`

**Status: PLANNED.** Branch `feat/consolidate-enricher` (cut from `origin/main` @ `0c773ae0`).
Commit `402919b5` already imported job-enricher **with history** into `src/enricher/`
(tree byte-identical to job-enricher@`66f768b`). Never amend or rewrite that commit; every
unit below adds new commits on top.

One PR. Five sequential units (§9). Each leaves the branch green.

---

## 0. TL;DR

| | |
|---|---|
| **Goal** | JVN is the only home of the enricher. The separate `job-enricher` repo is retired and archived. |
| **What runs in prod after the merge** | **The exact same code as today.** The cutover moves *where* the code comes from, not *what* runs: the new prod checkout is pinned to the JVN commit whose `src/enricher` tree hash equals the live tree (`471165a3…`, tag `enricher-prod-eeff1c9`). |
| **What does NOT ship** | job-enricher PRs #18–#20 (v7 taxonomy, store v4 one-way migration, evals, backfill). They are on JVN `main` now but **not deployed**. Deploying them is a separate, documented step (§6). |
| **The switch** | An on-machine launchd watcher polls JVN `origin/main`. The moment the merged cutover script appears there, it runs that script (taken from merged main). Nothing switches before the merge. |
| **New prod path** | `~/developer/personal/enricher-prod` (a JVN clone); enricher dir `enricher-prod/src/enricher`. |
| **New dev path** | `~/developer/personal/Job-Visualizer-Notifier/src/enricher` (or a JVN worktree). |
| **Retired** | `~/developer/personal/app` (kept on disk, untouched except markers — it is the rollback artifact) and `~/developer/personal/job-enricher` (markers only). |
| **Tests added** | enricher unit suite in GitHub CI; e2e section `enricher` (real CLI + real wrapper + real JVN backend + Postgres + stub ollama, $0); e2e section `enricher-cutover` (sandboxed cutover + watcher, $0, also in CI). |

---

## 1. Facts verified while planning (read these before trusting anything else here)

| Fact | Evidence |
|---|---|
| Prod DB is `user_version=3`, ~636 MB, and **WAL** while in use *(Unit 3 correction: `-wal`/`-shm` sit next to it during a tick and vanish when the last connection closes; the planning probe's `immutable=1` open always reports `delete`)* | `ls app/data` mid-tick; `init_schema` sets `journal_mode=WAL` on every CLI start |
| `sqlite3 -readonly` on the live DB fails with `CANTOPEN (14)` from an agent shell | same probe; use `?mode=ro` URIs, fall back to `?immutable=1` (may read a torn page; informational only) |
| Ticks run back-to-back, ~2 h 15 m each; the idle gap between ticks is **~60 s** | ticks 2213→2215 (`ended_at` 02:15:56, next `started_at` 02:16:58) |
| Prod engine = committed default `ollama` / `qwen3:32b` (no `classify:engine` override in `meta`) | `meta` rows; `enrich_config.py` at the tag |
| The prod tag is an **ancestor of the branch HEAD** | `git merge-base --is-ancestor 3ea04981 HEAD` |
| Tag commit `3ea04981`'s tree contains **only** `src/` (= `src/enricher`) | `git ls-tree 3ea04981` |
| App untracked state: `.env.local`, `.checkout-role`, `.venv/`, `data/enricher.db`, `data/.tick.lock`, `data/chunks/`, `data/classify-run-t*.log` (×3), `__pycache__/` | `git -C app status --ignored --untracked-files=all` |
| App venv: CPython **3.12.13** at `~/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin`, uv 0.11.14 | `app/.venv/pyvenv.cfg`; `/opt/homebrew/bin/uv --version` |
| Wrapper / deploy / installer / dashboard scripts are **identical** at the tag and at main | `git diff enricher-prod-eeff1c9 HEAD -- src/enricher/scripts/{enrich_tick_wrapper,deploy,install_launchagents,run_dashboard}.sh` → empty *(at planning time; Unit 1 then rewrote `run_dashboard.sh` and one comment in `install_launchagents.sh` on main — the cutover runs the tag's copies, so prod is unaffected)* |
| Enricher unit suite passes **in the monorepo location**: 814 passed, 9 skipped, 11 s | `cd src/enricher && uv sync --locked && uv run pytest` |
| JVN `src/backend/taxonomy.json` is **byte-identical** to the enricher's vendored `golden/taxonomy-parity/jvn_facets.json` | `cmp` |
| JVN root has **no** `CLAUDE.md`/`CLAUDE.local.md`; root `.claude/settings.json` holds only `enabledPlugins` (no hooks) | `ls`; `cat` |
| JVN root `.env.local` defines **no** `JVN_BASE_URL`/`INTERNAL_API_KEY`/`OLLAMA_*` | key names only |
| No root `pyproject.toml` → `uv` treats `src/enricher` as its own project (no workspace capture) | `find . -maxdepth 3 -name pyproject.toml` |
| `src/backend/Dockerfile` copies explicit paths only; Vercel builds `src/frontend` only; root npm workspaces = `["src/frontend"]` | files |
| Recent JVN merges are **squash** merges; merge commits are allowed in repo settings | `git log --merges`; `gh api repos/…` |
| `~/.claude/skills/everything-running/check.sh` hardcodes `ENRICHER_DIR=$HOME/developer/personal/app` | line 15 |
| Imported history (22 commits) has no hits for common secret patterns | pattern scan of `git log -p 402919b5^2` (redacted) |
| Ports `8205`, `8206`, `8215`, `3205` are free; `8204`/`3204` belong to `billing` | `lsof` |
| `src/backend/uv.lock` is untracked in the JVN checkout and is **not ours** | `git status` — never `git add -A` |

**Unverified (designed around, not relied on):** whether `launchctl unload` SIGTERMs an
in-flight wrapper. The tag's `deploy.sh` comment claims it does not; launchd's documented
`bootout` behaviour says it stops running instances. The cutover never unloads while a tick
runs (§4.3), so it is correct under either answer. `deploy.sh` on main gets the same fix (§6).

---

## 2. Monorepo integration (Unit 1)

### 2.1 Layout and build isolation

| Item | Change |
|---|---|
| `src/enricher/` | stays where the import put it (mirrors `src/backend`, `src/frontend`) |
| `src/enricher/.python-version` | **add** `3.12` (prod's interpreter line; CI and future deploys resolve the same minor) |
| `src/enricher/.idea/` | `git rm -r --cached` — JVN ignores `.idea/` repo-wide; these 6 files only show up as "tracked but ignored" |
| `.dockerignore` | add `src/enricher` (keeps 3.7 MB + golden data out of the Railway build context; Dockerfile never copies it) |
| root `.gitignore` | add `.checkout-role` and `CLAUDE.local.md` (both are per-checkout markers the cutover writes at a JVN clone's root/area) |
| `vercel.json`, `railway.toml`, root `package.json` | **no change.** Record in the PR why: Vercel builds `-w src/frontend`; `api/` function count unchanged; the dashboard has its own lockfile and is not a workspace |
| `.no-mistakes.yaml` `document.instructions` | list `src/enricher` among the per-area AGENTS.md files (takes effect from main) |

### 2.2 CI — new job in `.github/workflows/ci.yml`

```yaml
  enricher:
    name: Enricher
    runs-on: macos-latest        # prod is macOS: BSD stat, sysctl kern.boottime, plutil, launchctl stubs
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }  # the enricher-cutover CO-REAL case needs tag enricher-prod-eeff1c9
      - uses: astral-sh/setup-uv@v6
        with: { version: "0.11.14" }
      - run: cd src/enricher && uv sync --locked && uv run pytest
      # Unit 4 adds:  - run: bash e2e/run.sh enricher-cutover
```

No path filter: every other job runs unconditionally; the suite is ~15 s of tests plus setup.
JVN is public, so macOS minutes are free. `uv sync --locked` doubles as the guard that nothing
upstream (a future root `pyproject.toml` with `[tool.uv.workspace]`) captured `src/enricher`.

### 2.3 Cross-repo references → intra-repo

| Where | Today | After |
|---|---|---|
| `tests/test_cross_repo_parity.py` + `cli.TAXONOMY_PARITY_SNAPSHOT` | reads a **vendored copy** of JVN's `taxonomy.json` + a `.sha256` | reads **`<JVN root>/src/backend/taxonomy.json` directly** (`REPO_ROOT.parents[1] / "src" / "backend" / "taxonomy.json"` — define one helper, `JVN_ROOT`, in `store.py` or `cli.py`). Delete `golden/taxonomy-parity/jvn_facets.json` + `.sha256`; rewrite that dir's README to say "the artifact is in-tree now". The sha test goes (git + the backend's `test_taxonomy_artifact.py` already guard the file). The "levels key proves provenance" test stays, pointed at the in-tree file. Rename the test module to `test_taxonomy_parity.py` and drop "cross-repo" wording. |
| `cli parity-check --write-snapshot` | refreshes the vendored copy | **refuses** with exit 2 and a message ("the snapshot is JVN's generated `src/backend/taxonomy.json`; regenerate it with `src/backend/tools/generate_taxonomy_artifact.py`"). Keep the flag accepted so an installed plist cannot crash on argparse. Drop it from `check_taxonomy_parity.sh`. |
| `scripts/com.bp.jvn-taxonomy-parity.plist` | log paths `REPO_ROOT_PLACEHOLDER/../../Library/Logs` (assumes the repo is 2 levels below `$HOME` — wrong in the monorepo) | `HOME_PLACEHOLDER/Library/Logs/…`; update the substitution instructions in its header. It is not installed on this machine (verified) — no live change. |
| `scripts/rehearse_v4_migration.sh` default `LIVE=` | `…/personal/app/data/enricher.db` | `…/personal/enricher-prod/src/enricher/data/enricher.db` |
| `scripts/run_dashboard.sh` | `PROJECT_DIR=$HOME/developer/personal/job-enricher`; **`git switch main && git pull`** | derive `PROJECT_DIR` from the script's own location; **remove all git mutation** (in the monorepo it would switch Brendan's whole JVN checkout — and `com.bp.jvn-health-watch` runs from that working tree). Print branch + short sha; keep the prod-role refusal and the dirty-tree refusal; `cli dashboard`'s own off-main warning stays the staleness signal. |
| `scripts/diagnose_stuck_cohort.py`, `docs/BACKFILL.md`, `docs/RUNBOOK-subcategory-backfill.md`, `docs/handoffs/*` | hardcode `…/personal/app` | flip to the new prod path **except** in dated handoffs/incidents (historical record — leave them). |
| `tests/test_deploy_script.py` docstring | "runs from `/Users/bpotter/developer/personal/app`" | new prod path |
| JVN `MONETIZATION-PLAN.md:63`, `docs/enrichment/HANDOFF.md:11`, `src/backend/AGENTS.md:549`, `src/backend/api/routers/internal_enrichment.py:1` docstring | "lives in its own repo", "both this repo and the job-enricher" | "lives in `src/enricher/`" / "both the backend and `src/enricher`". Leave `docs/incidents/**` and `custom-company-sources/ROLLOUT.md` alone (historical). Code comments that use "job-enricher" as the component's name are fine. |

### 2.4 `claude -p` from inside the monorepo (main's `claude-code` engine path only)

Prod's ollama path never invokes `claude` (verified in the wrapper). For main's
`claude-code` engine, `claude -p /enrich-tick-once` runs with cwd `src/enricher`. Claude Code
loads `CLAUDE.md`/`CLAUDE.local.md` from the cwd **and every ancestor**, and project
settings/commands/agents from the cwd's `.claude/`. Today no ancestor inside JVN carries a
`CLAUDE.md`, and JVN's root `.claude/settings.json` has no hooks. Unit 1 must:

1. Confirm that loading rule against the current Claude Code docs **without running a model**
   (docs page / `claude --help`; no `claude -p` call — no LLM spend).
2. Add guard test `tests/test_monorepo_guards.py`:
   - no tracked `CLAUDE.md` / `CLAUDE.local.md` in `src/` or the JVN root (an ancestor file
     would be injected into every enrichment prompt; the message explains this);
   - the JVN root `.claude/settings.json` has no `hooks` and no `permissions` keys;
   - `src/enricher/.claude/{agents,commands}` still exist (the sandboxed sub-agents);
   - `store.REPO_ROOT` resolves to `src/enricher` (package-relative state stays per-area).
   Each test skips with a clear reason when run outside the monorepo (e.g. the prod tag's
   tree, which has no JVN root) — the CI run is always inside it.

**Unit 1 findings (Claude Code docs: memory, large-codebases, skills, sub-agents, settings;
no model run).** CLAUDE.md/CLAUDE.local.md load from the cwd and every ancestor, into the
tick AND every sub-agent. AGENTS.md loads only when no CLAUDE.md exists at or above the cwd
(default mode), so `src/enricher/CLAUDE.md` keeps every JVN AGENTS.md out. Project skills
load from the cwd up to the repo root and a **root skill wins** over a nested namesake (a
skill also beats a commands file) — so the guard file also asserts no JVN-root skill/command
shadows an enricher one, and that `src/enricher/CLAUDE.md` exists. Shared
`.claude/settings.json` is read from the starting dir only (the root-settings guard is a
tripwire), but `.claude/settings.local.json` is read from the **git root** (untracked, so not
CI-guardable; documented in `src/enricher/AGENTS.md`).

### 2.5 Docs

Correct existing sections; do not add sprawl.

- **Root `AGENTS.md`**: add `src/enricher/` to *Project Structure* ("local enrichment worker
  — see `src/enricher/AGENTS.md`") and one *Common Tasks* entry ("Working on the enricher":
  dev = this checkout's `src/enricher`; prod = `~/developer/personal/enricher-prod`, deployed
  only by `deploy.sh <ref>`; never run its CLI against prod).
- **New `src/enricher/AGENTS.md`** (short, like the other area files): what it is, test command
  (`cd src/enricher && uv run pytest`), e2e sections, the prod/dev/retired table, "package-
  relative state: each checkout owns its own `data/`", and "the full operating manual is
  `CLAUDE.md` in this directory (what `claude` loads with cwd = `src/enricher`)".
- **`src/enricher/CLAUDE.md`** "Which checkout am I in?": prod =
  `~/developer/personal/enricher-prod/src/enricher` (`.checkout-role` = `prod`); dev = the JVN
  checkout's `src/enricher` or a JVN worktree; `retired` = `~/developer/personal/app` and
  `~/developer/personal/job-enricher` — stop and work in JVN. Also fix the stale "every 10 min"
  (it is a 60 s continuous worker). Keep every `test_docs_drift.py` assertion green.
- **`src/enricher/README.md`**, **`docs/ENVIRONMENTS.md`** path tables. (Unit 3 rewrites the
  deploy/rollback runbook sections of `ENVIRONMENTS.md`.)

### 2.6 Public-repo gate (do this FIRST in Unit 1)

JVN is public; job-enricher was private. Pushing this branch publishes its whole history.
Before any other Unit 1 work, scan every imported commit for secrets:

- pattern scan of `git log -p 402919b5^2` (Anthropic/GitHub/AWS/Slack/SendBlue key shapes,
  private keys, `INTERNAL_API_KEY=<value>`, phone numbers) — print only redacted hits;
- **exact-value scan** for each value in `app/.env.local` (and the dev `.env.local` if present):
  read values into a process-local variable, `grep -c -F` the history, print only the count.
  Never echo, log or copy a value.

Any hit → **stop the run and report** to the orchestrator. It cannot be fixed without
rewriting `402919b5`, which only the orchestrator may decide.

---

## 3. E2E section `enricher` (Unit 2)

Follows `e2e/README.md` exactly: `e2e/enricher/` with `PLAN.md`, `CASES.md`, `run.sh`, `api/`
(no `ui/` — the enricher has no UI in this gate), `.claude/skills/e2e-gate/sections/enricher.md`,
a row in `e2e/README.md` and in the skill's table, a cost banner + hand-off in `e2e/run.sh`.

### 3.1 The stack

| | |
|---|---|
| Backend | real `e2e.shared.stack.e2e_app:app` on **:8205**; a short-lived kill-switch backend on **:8206** (EN-08) |
| Frontend | **none** — new `stack_up.sh` knob `E2E_SKIP_FRONTEND=1` |
| Database | **`jobscraper_e2e_enricher`**, `--schema-only` (it seeds its own rows) |
| LLM | `e2e/enricher/stub_ollama.py` on **:8215** — a stdlib HTTP server implementing `POST /api/chat` |
| Enricher | a **sandbox copy** of the enricher tree under `$TMPDIR/jvn-e2e-<hash>/enricher-sandbox/<run>/` *(as built: outside the repo; each case's `data/` is copied into `artifacts/<run>/enricher-data/`)*, `uv sync --frozen`, real CLI + real `scripts/enrich_tick_wrapper.sh` |
| Cost | **$0, unconditionally.** No Claude, no Anthropic API, no real ollama, no Browserbase, no host but loopback |

**Shared changes (generalise, never fork; every default = today's behaviour):**

- `e2e/shared/stack/stack_up.sh`: `E2E_SKIP_FRONTEND` (default `0`); `E2E_INTERNAL_API_KEY`
  (default empty → the existing `unset INTERNAL_API_KEY` stands; non-empty → export it after
  the unset). The enricher **must** present a key (`JVNClient` raises without one), so this
  section is the first to run the backend with the internal-key middleware armed.
- *(as built)* `E2E_BLANK_ANTHROPIC_KEY` (default `0` → inherit as today; `1` → export it
  EMPTY, which beats the root `.env.local` the backend reads directly). Without it the
  backend's 5-minute `scan_unnormalized` task holds a real Haiku key during the run.
- `stack_down.sh` already tolerates a missing frontend pidfile — verify, don't change.
- `e2e/run.sh`: banners + `exec` hand-offs for `enricher` and `enricher-cutover` (same shape
  as `subcategories`), and the usage text.

**Why a sandbox copy, not `src/enricher` itself.** Every durable path is package-relative
(`store.REPO_ROOT = parents[2]`), so the DB, lock and chunk dir live wherever the package
source lives. Running the dev tree would write `src/enricher/data/` in Brendan's checkout.
`sandbox.py` copies the working tree (rsync, excluding `.venv`, `data`, `dashboard/node_modules`,
`dashboard/dist`, `__pycache__`) — or, with `--enricher-ref <ref>`, `git archive <ref>:src/enricher`
— then `uv sync --frozen --python 3.12`, writes the sandbox `.env.local`, and asserts
`uv run python -c "from job_enricher.store import REPO_ROOT; print(REPO_ROOT)"` equals the
sandbox path. That assertion is the isolation proof; the run refuses if it fails.

**Boot guards (`run.sh`, before any case):** sandbox `.env.local` has
`OLLAMA_BASE_URL=http://127.0.0.1:8215` (refuse `:11434` or any non-loopback host),
`JVN_BASE_URL=http://127.0.0.1:8205`, `INTERNAL_API_KEY=e2e-enricher-not-a-secret`
(committed in `env.enricher`; it is a test value); the sandbox path is not under
`~/developer/personal/{app,enricher-prod,job-enricher}`; `cli health` in the sandbox reports
`classify_engine=ollama` and `judge_engine=ollama` (so the wrapper can never reach `claude -p`).

*(As built)* the guard runs `cli init` before `cli health`: `cli health` does not create
`data/` and fails `unable to open database file` on a never-initialised checkout.

**Database drift (found while building).** The schema-only clone of `jobscraper_pr243` lacks
`job_listings.search_text`/`primary_country` and the `data_scientist`/`intern` dimension rows
(the local source DB is stamped past migrations it never ran), which makes EVERY `/results`
item fail. `e2e/enricher/seed.py` repairs the section's own DB idempotently from
`src/backend/taxonomy.json` + the migration's column definition; `ensure_db.sh` is unchanged.
It also disables every non-fixture company so the backend's `*/30` fan-outs cannot scrape real
boards into the DB the enricher claims from. Details: `e2e/enricher/PLAN.md` §4.

**`--enricher-ref <ref>`** runs the same cases against another version — notably
`enricher-prod-eeff1c9`, the code the cutover will put in prod. Cases that need v7-only
behaviour carry `@pytest.mark.v7`; `run.sh` deselects them (`-m "not v7"`, so they are not
collected and cannot read as BLOCKED) when the ref's CLI lacks `subcategory-push`.

**Stub ollama.** Parses the `<job_data>` JSON block out of the prompt (see
`engines/prompts.py`), and answers deterministically per job from a keyword table in
`fixtures.py` (title → category/level/tags/locations/confidence). Recognises classify vs judge
vs subcategory prompts by their headers. Control endpoints (loopback only):
`POST /__stub/mode {"mode": normal|http500|garbage|hallucinate_id|invalid_facet|slow, "slow_s": N}`,
`GET /__stub/requests` (count + models + options seen), `POST /__stub/reset`. It must answer
both the tag's (v6) and main's (v7) response shapes; extra keys are ignored by v6.

### 3.2 Cases

| ID | Proves | Tier/marker |
|---|---|---|
| **EN-00** | Contract: the sandbox enricher's `taxonomy.CATEGORIES`/`LEVELS` (and, v7, `SUBCATEGORIES`) agree with the e2e backend's `GET /api/jobs/facets`. A known drift at the prod tag is marked known-red in CASES.md, never weakened. | fast |
| **EN-01** | One real wrapper fire enriches the seeded OPEN jobs end-to-end: JVN `job_listings.enrichment_*` set, `enrichment_status` leaves `claimed`, `job_enrichment` carries taxonomy version/confidence/reasoning *(as built: JVN stores neither model nor tick — `classify_model = qwen3:32b` and `tick_id` are asserted in the enricher's LOCAL `enrichments`, the model also in the `/metrics` knobs)*; local tick closes `ok` with `claimed == classified == sent`; the stub saw only `/api/chat`, `model=qwen3:32b`, `temperature=0`. | fast |
| **EN-02** | Judge routing: only low-confidence rows reach the judge; a judge revision lands in JVN; a verdict below `judge:human_floor` arrives as `needs_human`. | |
| **EN-03** | Metrics channel: a `running` snapshot appears mid-tick (stub `slow`) and the final `ok` push upserts the **same** `tick_uuid` in JVN's tick table; `GET /api/internal/enrichment/health` reflects `last_enriched_at`. | |
| **EN-04** | Single-flight lock: a second wrapper fired during a running tick prints `lock held; skipping this fire`, exits 0 and leaves the lock untouched; a dead-holder lock aged > 3 h is reclaimed; a lock whose mtime predates boot is reclaimed immediately. | fast |
| **EN-05** | Delivery-first under engine failure: stub `http500` → the tick still reaches write-back + tick-end, nothing is sent, rows stay pending; the next tick (stub `normal`) delivers them, with no duplicates in JVN. | slow |
| **EN-06** | Bad model output never kills a wave: hallucinated ids are skipped and counted, an invalid facet slug reaches JVN as a nulled facet with a `warnings[]` entry, non-JSON output is an engine error for that chunk only. *(As built: the enricher nulls an invalid slug locally, so JVN gets `null` and no warning — `warnings[]` is exercised by an over-long tag; at batch 1 a mis-echoed id is repaired, so the hallucination is an EXTRA object; prose content records nothing and counts no error, an HTML body is the engine error.)* | |
| **EN-07** | Idempotent re-delivery: re-posting the same results leaves `job_enrichment` / `job_tags` row counts and values unchanged. | |
| **EN-08** | Kill switch: against the :8206 backend with `ENRICHMENT_USE_EXTERNAL=false`, a tick claims 0, closes `ok`, and touches no JVN row. | slow |
| **EN-09** | (v7) Subcategory dark knob: with `writeback:send_subcategories` off (default) SWE rows keep `enrichment_subcategories IS NULL` (not `'{}'`); after `set` on, the next write-back populates SWE rows only. | v7 |
| **EN-10** | Isolation: after the run, the dev tree's `src/enricher/data/` is unchanged (absent today), the sandbox DB holds every tick *(as built: each case gets a fresh local DB, so this is per-case accounting)*, and the stub's request count equals the chunks queued. | fast |

`--fast` = the `fast` cases only. Every case writes `cases/<test>/step.txt` naming the failing
step in words. Prove at least **two** cases bite with a deliberate, reverted mutation
(suggested: make the wrapper skip `write-back` on the in-process path → EN-01/EN-05 red; make
the stub omit one id → EN-10 red) and record it in `e2e/enricher/PLAN.md` §"proven to bite",
as `subcategories` did.

**Seeding.** Raw SQL fenced by `assertions.connect` and keyed on `source_id = 'e2e_enricher'`
(copy `subcategories/seed.py`'s pattern and its "why raw SQL" note). Reseed per test.

**CI.** Local-only, like every stack section: it needs the `jobscraper-postgres` container and
the `jobscraper_pr243` source DB that `ensure_db.sh` clones from.

**As built (Unit 2, 2026-11-23).** 16 cases; GREEN at HEAD (60 s), `--fast` (7 cases, 27 s)
and `--enricher-ref enricher-prod-eeff1c9` (12 cases, 4 `v7` deselected, 51 s). Proven to bite
with two reverted mutations (wrapper skips write-back → EN-01 + EN-05 red; stub omits one row →
EN-10 red). Results, corrections and the pre-existing behaviours it pinned:
`e2e/enricher/CASES.md`.

---

## 4. The cutover (Unit 3) — design in full

Code lives in `src/enricher/scripts/cutover/`:

| File | Role |
|---|---|
| `cutover.sh` | entry. Finds an interpreter (the `home` in `<old prod>/.venv/pyvenv.cfg` + `/python3`; fallback `uv python find 3.12`), `exec`s `python -I cutover.py "$@"` |
| `cutover.py` | the state machine. **stdlib only**, Python ≥ 3.11 (`sqlite3`, `plistlib`, `hashlib`, `subprocess`, `json`, `shutil`) |
| `watcher.sh` | the merge trigger (§4.9) |
| `com.bp.jvn-enricher-cutover.plist.template` | the watcher's launchd agent |
| `install_watcher.sh` | installs the watcher (`--dry-run` prints the plan). **The orchestrator runs it, at the very end.** |
| `README.md` | operator runbook: modes, states, exit codes, how to read the log, how to re-arm |

### 4.1 Modes and exit codes

```
cutover.sh --preflight [--jvn-repo <path>] [--json]   # read-only, any time (pre-merge too)
cutover.sh --rehearse --scratch <dir> [--jvn-repo <path>]  # full dry rehearsal into scratch, no launchd, no app/ writes
cutover.sh --run                                     # what the watcher calls; resumable
cutover.sh --status                                  # print state.json
```

Exit: `0` done / no-op · `10` deferred (transient — retry next watcher fire) · `20` failed
before any swap (terminal, nothing to roll back) · `30` rolled back (terminal) · `2` usage.

### 4.2 Knobs (all env, all defaulted from `$HOME`, so a fake `HOME` sandboxes everything)

`CUTOVER_OLD_PROD` (`~/developer/personal/app`), `CUTOVER_NEW_PROD`
(`~/developer/personal/enricher-prod`), `CUTOVER_OLD_DEV` (`~/developer/personal/job-enricher`),
`CUTOVER_STATE_DIR` (`~/Library/Application Support/jvn-enricher-cutover`),
`JVN_REMOTE_URL` (`https://github.com/brendanpotter00/Job-Visualizer-Notifier.git`),
`CUTOVER_ENRICHER_PLIST` (`~/Library/LaunchAgents/com.bp.job-enricher.plist`),
`CUTOVER_SEND_SH` (`~/.claude/skills/message-brendan/send.sh`), `UV_BIN`
(`/opt/homebrew/bin/uv`), `LAUNCHCTL` (`launchctl`), `GH_BIN` (`gh`), and the budgets
`CUTOVER_PARK_BUDGET_S` (14400), `CUTOVER_FIRST_TICK_START_S` (900),
`CUTOVER_FIRST_TICK_CLOSE_S` (18000), `CUTOVER_FIRST_TICK_HARD_CAP_S` (86400),
`CUTOVER_POLL_S` (5). The old-prod path is **never** derived from anything but this knob +
the plist (they must agree, or refuse).

### 4.3 Clocks and waiting

- Wall clock only (`time.time()`), polled every `CUTOVER_POLL_S` with short sleeps — never a
  long `sleep`, which stalls while the laptop sleeps.
- **Sleep-gap credit:** if two consecutive polls are more than `max(60, 6×poll)` seconds
  apart, the laptop slept; add the gap to every live deadline and log it. A night's sleep must
  not read as a wedged tick.
- Every network call has a wall-clock kill (`subprocess.run(timeout=…)`) and git gets
  `GIT_HTTP_LOW_SPEED_LIMIT=1000 GIT_HTTP_LOW_SPEED_TIME=30`. DNS/network failure after wake
  is **transient** → exit 10, retried next fire.

### 4.4 Phases (state file `$STATE/state.json`, written atomically: tmp + `os.replace`)

**Single flight:** `$STATE/cutover.lock` (mkdir + pid; reclaimed only if the pid is dead).
**Resume rule:** every start re-derives reality instead of trusting `phase` (where does the
plist point? does the new prod exist and carry `.cutover-owned`? what is the max tick id in
each DB?), then continues from the first incomplete phase.

**A — Prepare (worker still running; nothing in old prod is written).**
1. Preflight checks (§4.7); any hard failure → exit 20 (or 10 if transient).
2. Mirror: `git clone --bare $JVN_REMOTE_URL $STATE/jvn.git` once, then
   `git -C … fetch --prune --tags origin +refs/heads/main:refs/heads/main`.
3. **Derive the ref** from `APP_TREE = git -C <old prod> rev-parse HEAD^{tree}` (old prod
   must have no tracked changes): first every tag `enricher-prod-*` with
   `rev-parse <tag>:src/enricher == APP_TREE`; else walk `git rev-list --all -- src/enricher`
   in the mirror for the first commit whose `src/enricher` tree matches. **No match → exit 20
   (REFUSE).** Record `ref`, `commit`, `APP_TREE`.
4. Clone: `git clone --no-checkout $STATE/jvn.git <new prod>`, `remote set-url origin
   $JVN_REMOTE_URL`, `checkout --detach <commit>`, write `<new prod>/.cutover-owned` (the only
   dirs the cutover may delete are ones carrying this marker). Assert
   `rev-parse HEAD:src/enricher == APP_TREE` and a clean `status --porcelain`.
5. `uv sync --frozen --python <app interpreter>` in `<new prod>/src/enricher`. Assert the new
   `.venv/pyvenv.cfg` `version_info` equals old prod's, and
   `uv pip list --format=freeze` equals old prod's after dropping the editable
   `job-enricher` line.

**B — Park the old worker without killing a tick.**
1. Wait (≤ `CUTOVER_PARK_BUDGET_S`) for `<old prod>/data/.tick.lock` to be absent, then take it
   with `O_CREAT|O_EXCL` writing `"<cutover pid>|<iso>"` — the enricher's own lock format, so
   every launchd fire from now exits 75 (`lock held`). Poll fast (1 s) while waiting: the gap
   between ticks is ~60 s and a fire takes seconds to reach `tick-acquire`; losing the race
   just means waiting for the next tick.
   *Orphan:* lock present, holder pid dead, no `enrich_tick_wrapper.sh` process for that path
   → reclaim it with the same rename-then-`O_EXCL` dance `lock.py` uses.
2. Only now `launchctl unload <plist>`; assert the label is gone from `launchctl list`; wait
   ≤ 120 s for any `pgrep -f '<old prod>/scripts/enrich_tick_wrapper.sh'` to exit (a fire that
   raced us exits 75 within seconds). Then `lsof <old prod>/data/enricher.db` must show no
   process.
3. Budget exhausted (a wedged tick) → release our lock if we took it, leave launchd as found,
   exit 10, text Brendan **once** ("cutover waiting: an enricher tick looks wedged").

**C — Copy (worker parked).**
1. Save the original plist **once** to `$STATE/com.bp.job-enricher.plist.orig` (never
   overwritten) and old `.checkout-role`.
2. Every SQLite file under `data/` (`*.db`, today just `enricher.db`): Python
   `sqlite3` online backup (`src.backup(dst)`), then on the copy `PRAGMA integrity_check` =
   `ok`, `user_version` equal, every table's `COUNT(*)` equal, `max(ticks.id)` equal, `meta`
   rows byte-equal. Record `copy_sha256` and `old_db_sha256` (both files, after the backup).
   Never `cp` a database. Skip `-wal`/`-shm`/`-journal` (the backup reads through them).
3. Untracked state from `git -C <old prod> status --porcelain --ignored --untracked-files=all -z`:
   **regenerate** (skip) `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `data/chunks/`,
   `data/.tick.lock`, `data/.backfill.lock`, `data/.subcategory-push.lock`,
   `dashboard/node_modules/`, `dashboard/dist/`, `.checkout-role`; **DB** handled above;
   **everything else is copied** with `shutil.copy2` (mode + mtime kept — `.env.local`, the
   `data/classify-run-*.log` files, any `golden/scorecards/predictions*.json`), each verified by
   sha256. The log lists names and sizes only — **never** contents. `.env.local` must arrive
   byte-identical.
4. `cli health` in **both** checkouts (old prod's is the documented sanity command `deploy.sh`
   already runs there; at an equal `user_version` `init_schema` is a no-op) and compare the
   JSON after dropping volatile keys (`*_age_s`, `*_at`, `now`). Must be equal.
5. Any mismatch → **unpark** (restore lock/launchd exactly as found) and exit 20.

**D — Swap (the atomic switch point is the plist write).**
1. `<new prod>/src/enricher/.checkout-role` = `prod`; `<new prod>/CLAUDE.local.md` = "PROD
   enricher checkout — do not edit; dev is `~/developer/personal/Job-Visualizer-Notifier/src/enricher`".
   ⚠ *(Unit 1 finding)* an ancestor `CLAUDE.local.md` is loaded into every `claude -p`
   enrichment prompt and sub-agent. Harmless on prod's ollama path (no `claude` call), but
   it would change prompts once main's `claude-code` engine runs there — Unit 3 decides
   whether to keep it or use a non-auto-loaded marker.
   Old prod `.checkout-role` = `retiring` (its `deploy.sh` then refuses to run there).
2. New plist = original bytes with the old-prod path replaced by `<new prod>/src/enricher`;
   **exactly two replacements** (`ProgramArguments[0]`'s prefix and `WorkingDirectory`) or
   refuse; `plistlib` parse of new == parse of original with those two values swapped (same
   `StartInterval`, `EnvironmentVariables`, log paths); `plutil -lint`; write tmp +
   `os.replace`. From this instant a reboot loads the new prod — so the new tree is complete
   first, and a reboot before this line loads the old one. Both are safe.
3. `launchctl load`; assert `launchctl print gui/<uid>/com.bp.job-enricher` shows
   `program = <new prod>/src/enricher/scripts/enrich_tick_wrapper.sh`.
4. Release the old-prod lock (only if it still holds our pid). Remove `.cutover-owned` →
   replace with `.cutover-swapped` (records swap epoch). State `SWAPPED`
   (`swap_epoch`, `copied_max_tick_id`, `copy_sha256`, `old_db_sha256`).

**E — Verify the first tick.**
1. A tick with `id > copied_max_tick_id` must appear in the new DB within
   `CUTOVER_FIRST_TICK_START_S` (launchd's first fire is ≤ 60 s after load).
2. It must close within `CUTOVER_FIRST_TICK_CLOSE_S`; if that passes while the tick is still
   **progressing** (new `stage_timings` rows / heartbeat in the last 30 min), extend, up to
   `CUTOVER_FIRST_TICK_HARD_CAP_S`.
3. Pass = `status == 'ok'` **and** behavioural equivalence: if `claimed > 0` then
   `classified > 0` and `sent > 0` — unless old prod's last 3 closed ticks show the same stall
   (then it is not the cutover's fault; log it). Also: old prod's DB sha256 is still
   `old_db_sha256` (nothing ran there), and the plist still points at the new prod.
4. Pass → `VERIFIED`. Fail → rollback (§4.5).

**F — Retire (only after `VERIFIED`; each step best-effort, recorded, never rolls back).**
1. Old prod and old dev: `.checkout-role` = `retired`; untracked `CLAUDE.local.md`:
   "RETIRED. The enricher lives in JVN `src/enricher/`. Prod: `…/enricher-prod`. Dev:
   `…/Job-Visualizer-Notifier/src/enricher`. Do not edit here." For old dev it also lists the
   local branches with commits not on `origin/main` and the port recipe
   (`git format-patch` + `git am --directory=src/enricher`).
2. `git -C <old dev> bundle create $STATE/job-enricher-all-refs.bundle --all` (read-only on
   the repo; insurance for its 20+ local branches before the remote goes read-only).
3. Temp clone of job-enricher (`git -C <old prod> remote get-url origin`) in `$STATE`; prepend a
   short "Moved to Job-Visualizer-Notifier `src/enricher/`" banner to `README.md` and
   `CLAUDE.md`; commit; push to `main`. Then `gh repo archive <owner>/<repo> --yes`
   (owner/repo parsed from that URL).
4. Text Brendan (§4.8). State `DONE`. The watcher removes itself on its next fire (§4.9).

### 4.5 Rollback (any failure in D or E)

1. Park the **new** prod exactly as in B (claim its lock at idle; budget 30 min; if a tick is
   wedged past that, unload and TERM the wrapper's python child, then the wrapper — the
   runbook order from the sleep-socket-hang incident).
2. If the new DB's sha256 ≠ `copy_sha256` (it did work): online-backup new → old prod
   `data/enricher.db.rollback-tmp`, integrity check, rename the old prod's stale DB to
   `enricher.db.pre-rollback-<ts>`, `os.replace` the tmp in. **No enrichment is lost** — the
   rows the new prod already sent to JVN arrive back marked sent.
3. Restore the saved original plist bytes, old `.checkout-role`, `launchctl load`, release
   locks. New prod `.checkout-role` = `failed-cutover`; leave it on disk for diagnosis.
4. State `ROLLED_BACK`, text Brendan with the failing check, exit 30. Terminal: the watcher
   stops; re-arming needs a human (`install_watcher.sh`).

### 4.6 Idempotency and re-entrancy

| Start state found | Action |
|---|---|
| `DONE` | no-op, exit 0 |
| `FAILED` / `ROLLED_BACK` | no-op, exit 20/30, no new text |
| plist → old prod, no new prod | phase A |
| plist → old prod, new prod with `.cutover-owned` | delete it (marker proves we made it) and redo A |
| plist → old prod, new prod **without** a marker | refuse, exit 20 (someone else's dir) |
| plist → new prod, state `SWAPPED` | continue E (never re-copy the DB) |
| plist → new prod, state `VERIFIED` | continue F |
| plist → new prod, no state file | refuse, exit 20 (a human moved it) |

### 4.7 `--preflight` (read-only; the orchestrator runs it on the real machine before merge)

Writes nothing outside a `mktemp -d` it deletes; never touches old prod, the plists, launchd
(only `launchctl list`/`print`) or `$STATE`. Checks and reports (human + `--json`):
old prod exists, `.checkout-role=prod`, no tracked changes, `HEAD^{tree}`; ref derivation
(against `--jvn-repo <path>` when given, else a temp bare fetch); untracked-state inventory
(names, sizes, classification); DB `user_version`, table counts, size (`?mode=ro`, fallback
`?immutable=1` flagged "may be torn"); free space at the new-prod location ≥ 3 × DB size;
interpreter from `pyvenv.cfg` exists; `uv` version; plist parses and holds exactly two
old-prod paths; label loaded + program path; new-prod path absent; send.sh executable;
`gh auth status`; `git ls-remote` reaches JVN and job-enricher; current tick id, age and the
lock holder's liveness; whether `origin/main` already contains `cutover.py`. Exit 0 iff every
hard check passes.

`--rehearse --scratch <dir>` runs A + C into `<dir>` (clone, uv sync, online-backup of the
**live** DB — a shared lock for ~2 s — untracked copy **minus `.env.local`**, counts, `cli
health` on the **scratch copy only**) and stops. No launchd call, no write to old prod.

### 4.8 Notifications

`send.sh` with a 60 s wall-clock kill, best-effort, each event at most once (recorded in
state): `DONE` (new path @ sha, first tick id, archive yes/no, README push yes/no), `DEFERRED`
(wedged tick), `FAILED` (which check), `ROLLED_BACK` (which check, DB copied back yes/no).
Never include secrets or `.env.local` content.

### 4.9 The watcher

`watcher.sh` (bash 3.2-safe), installed **as a copy** in `$STATE/watcher.sh` — it must not
run from any checkout's working tree (branches move; `com.bp.jvn-health-watch` already bit
on that). Each fire:

1. `$STATE/state.json` terminal (`DONE`/`FAILED`/`ROLLED_BACK`) → move its own plist to
   `$STATE/retired/`, `launchctl remove com.bp.jvn-enricher-cutover`, exit.
2. mkdir-lock `$STATE/watcher.lock` (pid liveness) — launchd never overlaps a label anyway.
3. Fetch the mirror (as §4.4 A2, with timeouts). Failure → log "fetch failed, retry next
   interval", exit 0.
4. `git -C $STATE/jvn.git cat-file -e main:src/enricher/scripts/cutover/cutover.py` absent →
   "not merged yet", exit 0.
5. Present → `git archive main src/enricher/scripts | tar -x -C $STATE/run/<sha>` (the
   whole `scripts/` dir: `cutover.py` imports `scripts/lib/park_worker.py`, §6) and
   `exec $STATE/run/<sha>/src/enricher/scripts/cutover/cutover.sh --run` — **the
   cutover always comes from merged main**, so review fixes made after install are honoured.

Plist: label `com.bp.jvn-enricher-cutover`, `ProgramArguments = /bin/bash $STATE/watcher.sh`,
`StartInterval 300`, `RunAtLoad true` (a reboot mid-verification resumes within a minute),
logs `~/Library/Logs/jvn-enricher-cutover.{log,err}`, `PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin`.
`install_watcher.sh`: copy `watcher.sh`, render + `plutil -lint` the plist, `launchctl load`,
print the next steps. `--dry-run` prints without doing.

---

### 4.10 As built (Unit 3, 2026-11-23)

Code: `src/enricher/scripts/cutover/` + `scripts/lib/park_worker.py`; runbook
`scripts/cutover/README.md`. Unit tests: `tests/test_cutover_{ref,plist,untracked,health_normalize,clock,resume}.py`,
`tests/test_park_worker.py`, `tests/test_deploy_script.py` (now also sandboxed behaviour).
A scratch sandbox (fake HOME, stub launchctl that really fires the wrapper, the real tag tree)
ran: happy path → `DONE`; first tick never starts → `ROLLED_BACK`, no copy-back; first tick
"stalls" → `ROLLED_BACK` **with** DB copy-back; wedged tick → exit 10 + one text → redo →
orphan reclaim → `DONE`; phase-C health failure → `FAILED`, `app/` reloaded as found.
Unit 4 turns these into the `enricher-cutover` section. Decisions and corrections:

- **No `<new prod>/CLAUDE.local.md`** (resolves the Unit 1 flag): an ancestor
  `CLAUDE.local.md` would be injected into every `claude-code`-engine prompt. The new prod
  gets a root `.checkout-role=prod` instead (plus `src/enricher/.checkout-role`).
- The clone is `mkdir` + `.cutover-owned` **first**, then `git init`/`fetch`/`checkout
  --detach` (not `git clone --no-checkout`), so a crash mid-clone leaves a deletable dir.
  Markers go in the clone's `.git/info/exclude` (the tag tree has no root `.gitignore`), so
  `status --porcelain` stays clean.
- History walk = every commit (`git rev-list --all`, one batched `cat-file`), not a
  path-limited walk that history simplification could prune.
- `--run` itself defers (exit 10) unless the mirror's `main` holds `cutover.py` — belt and
  braces against a manual run before the merge.
- B also waits for the finishing wrapper **before** the unload (launchd SIGTERMs a running
  job, which would cut the previous tick's final `metrics-push`), not only after.
- `park_worker.py` ignores orphaned watchdog subshells (ppid 1, only a `sleep` child):
  found in the sandbox — a wrapper killed mid-tick leaves one carrying the wrapper's command
  line for up to 3 h, which would otherwise read as "a wrapper is running".
- Old prod's `cli health` runs `uv run --frozen --no-sync` (never touches `app/.venv`); the
  new prod's runs plain `uv run` like the wrapper, then must leave no tracked change.
- `copy_sha256`/`old_db_sha256` are taken at the END of C (after both health runs).
- "Progressing" in E = the new DB file (or its `-wal`) written within
  `CUTOVER_PROGRESS_WINDOW_S`. Sleep credit = wall − monotonic (Darwin's
  `mach_absolute_time` stops in sleep) once a gap exceeds `max(60, 6×poll)`, so a slow
  subprocess is not credited.
- Extra phases: `SWAPPING` (written before the plist write) and `ROLLING_BACK` (a rollback
  that cannot finish texts `ROLLBACK_STUCK` once and retries every fire; not terminal).
  Extra texts: `DEFERRED:repeated` (24 deferrals), `UNPARK_FAILED`. A refused half-built new
  prod is marked `.checkout-role=failed-cutover`.
- Extra knobs: `CUTOVER_LOCK_POLL_S` (1), `CUTOVER_WRAPPER_EXIT_S` (120),
  `CUTOVER_ROLLBACK_PARK_BUDGET_S` (1800), `CUTOVER_PROGRESS_WINDOW_S` (1800),
  `CUTOVER_DEFER_ALERT_AFTER` (24), `CUTOVER_{NET,UV,HEALTH}_TIMEOUT_S`,
  `CUTOVER_OLD_REPO_SLUG`, `CUTOVER_{GIT,PLUTIL,LSOF}_BIN`, `CUTOVER_LAUNCHD_DOMAIN`,
  `CUTOVER_PYTHON` (cutover.sh); watcher/installer: `CUTOVER_WATCHER_PLIST`,
  `CUTOVER_WATCHER_NET_TIMEOUT_S`, `CUTOVER_LAUNCHAGENTS_DIR`.
- `cutover.lock` and `watcher.lock` are reclaimed when their dir predates the current boot
  (a reused pid after a reboot must not block forever).
- `install_watcher.sh`: refuses after `DONE`; refuses a terminal `FAILED`/`ROLLED_BACK`
  unless `--rearm` (which archives `state.json`); refuses a new-prod dir without
  `.cutover-owned`; `--dry-run` lints the render via stdin and writes nothing.
- `--preflight` on the real machine (2026-11-23, mid-tick): exit 0, ref
  `enricher-prod-eeff1c9` → `3ea04981`, tree `471165a3`; a sha256 manifest of `app/` (minus
  the live DB, lock and chunks), both plists and the state dir showed **0 changes**. Its
  only warning: the tag is not on the remote yet (the orchestrator pushes it).

---

## 5. Sandboxed test of the cutover + watcher — section `enricher-cutover` (Unit 4)

`e2e/enricher-cutover/` (`PLAN.md`, `CASES.md`, `run.sh`, `api/`, `fixtures/`), a skill
section file, README + skill rows, a `run.sh` banner/hand-off. **$0, no ports, no network,
no Postgres.** Runs in GitHub CI (macOS job) as well as locally.

**The sandbox (built per test in `tmp_path`):**

- fake `HOME` with `Library/LaunchAgents/com.bp.job-enricher.plist` (the real plist's shape,
  sandbox paths) and `Library/Logs/`;
- fake old prod: a git repo whose tree is `fixtures/fake_enricher/` — a tiny `job_enricher`
  package honouring exactly the contract the cutover relies on (`data/enricher.db` with
  `ticks`/`meta`/`stage_timings`, the `pid|iso` lock, `cli health` JSON, `cli tick-acquire`
  exit 75, a `scripts/enrich_tick_wrapper.sh` that takes the lock, writes a tick row, runs for
  `FAKE_TICK_S` and closes `ok`/`error` per `FAKE_TICK_STATUS`), `.env.local` holding a
  **canary secret**, `.checkout-role=prod`, a `.venv` made by `uv sync`;
- a local bare repo standing in for GitHub JVN: a history whose tagged commit
  `enricher-prod-<x>` has `src/enricher` = the fake tree, and a `main` that does or does not
  contain `src/enricher/scripts/cutover/` (copied from the real working tree);
- a bare repo standing in for job-enricher (README/CLAUDE.md, accepts the banner push);
- PATH stubs: `launchctl` (records argv + timestamps; keeps loaded-label state; `load` starts
  a fire loop that runs the plist's program in its `WorkingDirectory` every `FAKE_INTERVAL_S`
  while loaded; `unload` stops the loop and — when `FAKE_UNLOAD_KILLS=1` — SIGTERMs a running
  job, so both possible real behaviours are tested; `list`, `print`, `remove`), `gh`
  (records, configurable exit), `send.sh` (appends messages to a file);
- budgets scaled to seconds via the §4.2 knobs.

| ID | Proves |
|---|---|
| **CO-01** | Happy path end to end: park → backup → copy → equivalence → plist swap (byte-diff = exactly two path substitutions) → load → first tick `ok` → retire (markers, `CLAUDE.local.md`, bundle, banner commit pushed to the fake job-enricher remote, `gh repo archive` called) → one text → `DONE` |
| **CO-02** | Never unloads mid-tick: with a fake tick in flight, `unload` is recorded only after the wrapper exited and the cutover held the lock; passes with `FAKE_UNLOAD_KILLS` both 0 and 1 |
| **CO-03** | Wedged tick: park budget expires → no plist change, launchd as found, lock released, exit 10, exactly one text; a later run completes |
| **CO-04** | No matching JVN ref → refuse, exit 20, nothing in old prod or the plist changed |
| **CO-05** | Old prod has a tracked modification → refuse, exit 20 |
| **CO-06** | No tag, but a commit in history matches → found by the history walk, proceeds |
| **CO-07** | First tick closes `error` → rollback: plist bytes restored, the new DB's ticks are copied back into old prod (no lost work), old prod loaded, exit 30, one text, watcher stops |
| **CO-08** | First tick never starts → rollback without a DB copy-back (sha unchanged) |
| **CO-09** | Crash and resume: killed after the copy but before the plist write → rerun redoes A–C cleanly (deletes only the `.cutover-owned` dir); killed after the swap → rerun continues verification and **does not re-copy** the DB |
| **CO-10** | Interpreter from `pyvenv.cfg` missing → refuse in phase A, before parking |
| **CO-11** | `--preflight` is read-only: sha256 of every file under fake HOME/old prod/state before == after; the `launchctl` stub saw only `list`/`print`; exit 0 with a full report |
| **CO-12** | Retirement steps fail (`gh` exits 1, banner push rejected, `send.sh` fails) → still `DONE`, each failure named in the log |
| **CO-13** | Orphan lock (dead pid, no wrapper process) → reclaimed, cutover proceeds |
| **CO-14** | Secrets: `.env.local` arrives byte-identical with its mode; the canary appears in **no** log, state file, text or stdout |
| **CO-15** | Re-run after `DONE` is a no-op |
| **CO-16** | A copy whose counts differ (a PATH-stubbed backup that drops rows, or a `.backup` target pre-seeded wrong) → unpark, exit 20 |
| **CO-REAL** | The real tag tree (`git archive enricher-prod-eeff1c9:src/enricher`) as old prod with a `cli init` DB: phases A–D with the **real** `uv sync` + real `cli health` equivalence; launchd stubbed, first tick faked. Needs the tag (CI checks out with `fetch-depth: 0`); missing tag = FAIL with the fix in the message, never a skip |
| **WT-01** | `main` without `cutover.py` → no-op, no cutover started, no text |
| **WT-02** | Remote unreachable (bad URL / DNS) → exit 0, "retry next interval", no state change |
| **WT-03** | Merged → runs the cutover **from merged main**: the remote's copy is a marked variant; assert the marker ran, not the installed copy |
| **WT-04** | Second watcher while the first runs → exits immediately |
| **WT-05** | Terminal state → plist moved to `retired/`, `launchctl remove` recorded, no cutover run |

`run.sh` uses `$REPO_ROOT/.venv/bin/python` when present, else
`uv run --project src/enricher python` (CI has no root venv); summary via `e2e/write_summary.py
--section enricher-cutover`. Prove two cases bite (e.g. drop the "unload only after park" ordering
→ CO-02 red; skip the rollback DB copy-back → CO-07 red).

---

## 6. Future deploy of `main` from the monorepo layout (documented, not executed)

Unit 3 makes main's tooling ready and documents the runbook in `docs/ENVIRONMENTS.md`:

- **`deploy.sh` (main):** park via the same lock-claim-at-idle routine as the cutover (shared
  helper `scripts/lib/park_worker.py`, used by `cutover.py` too), with a wall-clock budget
  (`DEPLOY_PARK_BUDGET_S`, default 14400) — replacing "abort if a tick is running", which can
  never succeed against back-to-back ticks; refuse the no-arg `pull` form on a detached HEAD
  ("pass a ref"); `uv sync --frozen`; `DEPLOY_PROJECT_DIR` override so the first main deploy
  can run main's script against a prod still on the tag; release the claimed lock in the EXIT
  trap (only if it holds our pid). Extend `test_deploy_script.py` and add a sandboxed behaviour
  test of `park_worker.py` (reuse Unit 4's stubs if they exist by then; otherwise a focused
  pytest with a fake lock holder).
- **Runbook (the separate product decision):** read #18–#20's changes; rehearse the v4
  migration on an online-backup copy (`scripts/rehearse_v4_migration.sh`, new default path);
  split it if > 30 s; then
  `git -C ~/developer/personal/enricher-prod fetch origin && git -C … show origin/main:src/enricher/scripts/deploy.sh > "$TMPDIR/deploy.sh" && DEPLOY_PROJECT_DIR=~/developer/personal/enricher-prod/src/enricher sh "$TMPDIR/deploy.sh" <main-sha>`.
  *(As built: main's `deploy.sh` needs `lib/park_worker.py` next to it, so the runbook in
  `docs/ENVIRONMENTS.md` extracts the whole dir — `git archive origin/main
  src/enricher/scripts | tar -x -C "$D"` — and runs `$D/src/enricher/scripts/deploy.sh`.
  deploy.sh also resolves a branch name to origin's copy and always checks out detached;
  it reloads the worker only once the unload was issued, so a park timeout leaves launchd
  untouched.)*
  Rollback = restore the backup DB **and** `deploy.sh <previous ref>` (a git rollback alone
  does not undo `user_version`). After that first deploy the checkout's own `deploy.sh` is main's.
- `install_launchagents.sh` already derives its path (→ `…/src/enricher`); no change.
- The old prod `app/` remains the pre-cutover rollback artifact until Brendan deletes it.

---

## 7. `everything-running` skill (Unit 5, outside the repo — the one allowed exception)

`~/.claude/skills/everything-running/` is not a git repo; edit in place.

- `check.sh`: `ENRICHER_DIR` = `WorkingDirectory` of `~/Library/LaunchAgents/com.bp.job-enricher.plist`
  (`/usr/libexec/PlistBuddy -c 'Print :WorkingDirectory'`), fallback the old path. Identical
  result before the cutover, correct after it, and after any rollback.
- `SKILL.md`: the enricher row and the "plist missing" recovery line name the plist-derived
  prod path (`…/enricher-prod/src/enricher` after cutover), drop "job-enricher is dev".
- Verify with `bash -n` and by running **only** the extracted derivation snippet (it prints a
  path). **Do not run `check.sh` itself** — it runs `cli health` against prod.

---

## 8. Orchestrator checklist (not a unit — the orchestrator does these)

1. Push tags `enricher-prod-eeff1c9` and `enricher-import-66f768b` **before** the PR's CI
   runs (CO-REAL and the cutover's tag lookup need them).
2. Run `cutover.sh --preflight --jvn-repo <JVN checkout>` (and optionally `--rehearse`) on the
   real machine; attach the report to the PR.
3. Run `e2e/run.sh enricher` at HEAD **and** `--enricher-ref enricher-prod-eeff1c9`.
4. Raise the PR through no-mistakes. In the PR body: **merge with "Create a merge commit"** to
   keep the enricher history on main (squash still works for the cutover — the tag carries the
   prod commit — but flattens 22 imported commits into one).
5. After the PR is up and green: `install_watcher.sh` (from this branch's copy). It idles until
   the merge.
6. After `DONE`: update auto-memory notes that name `~/developer/personal/app` (job-enricher
   entries, everything-running entry, personal-services launchd map).

---

## 9. Units

Each unit is a coherent commit series, conventional-commit subjects, trailer
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. `git add` explicit paths only
(`src/backend/uv.lock` is someone else's untracked file). Never pipe a test run through
`tail`/`head`. No worktrees, no branch switches, no pushes.

1. **Unit 1 — Monorepo integration.** §2 (public-repo gate first), plus CI job.
2. **Unit 2 — e2e `enricher`.** §3.
3. **Unit 3 — Cutover engine, watcher, deploy-of-main readiness.** §4, §6, unit tests in
   `src/enricher/tests/test_cutover_*.py` (pure functions: ref derivation, plist rewrite +
   two-substitution guard, untracked classification, health-JSON normalisation, sleep-gap
   credit, state resume table) and `test_park_worker.py`.
4. **Unit 4 — e2e `enricher-cutover`.** §5, plus the CI step.
5. **Unit 5 — Skill update + final sweep + verification matrix.** §7; README/skill rows
   consistent; this PLAN's status line → BUILT with measured runtimes; run the full matrix
   (enricher unit, both e2e sections incl. `--enricher-ref`, `--preflight` and `--rehearse` on
   the real machine — both read-only toward prod — frontend type-check/build, backend pytest
   vs main's baseline).
