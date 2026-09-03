---
name: verify-onesecondswe
description: >
  Drive the onesecondswe (Job-Visualizer-Notifier) app the way a user does and
  capture proof, over the isolated e2e stack. The app is a React SPA
  (src/frontend) on a FastAPI backend (src/backend); this skill drives it through
  the WebMCP tool surface exposed at `window.__webmcp__` (14 tools) instead of
  clicking DOM controls — WebMCP arranges/acts, the DOM (and the jobscraper_e2e
  DB) is where the proof is read. Reach for it to verify a user-facing feature
  works end-to-end, to reproduce a UI/feed/filter bug against a real stack, or
  before claiming a frontend change is "ready to test". NOT for the Add Companies
  regression gate — that has its own `e2e-gate` skill.
---

# verify-onesecondswe

A **verification** skill: launch the real app on the isolated e2e stack, exercise
a feature the way a user would (through the WebMCP tools, not raw DOM clicks), and
capture evidence. It **reuses the existing e2e harness** under `e2e/` verbatim —
the stack, the JWKS-seam auth, the DB helpers, the Playwright base — and adds
nothing to it. Everything here is additive and **nothing commits**.

All commands are written to run from the repo root:
`/Users/bpotter/developer/personal/Job-Visualizer-Notifier/.claude/worktrees/end-to-end-tests`
(set `REPO=` to it once and paste the blocks as-is).

```bash
REPO=/Users/bpotter/developer/personal/Job-Visualizer-Notifier/.claude/worktrees/end-to-end-tests
```

## The one idea that makes this skill different

The SPA registers 14 agent-callable tools on `window.__webmcp__` when
`VITE_WEBMCP=1` (dead code otherwise — `src/frontend/src/webmcp/config.ts`). You
drive them from Playwright with `page.evaluate`, and `call()` returns the tool's
raw `structuredContent` as clean JSON:

```ts
const res = await page.evaluate(
  ([name, args]) => window.__webmcp__.call(name, args),
  ['search_jobs', { company: ['apple'], timeWindow: 'all', limit: 200 }] as const,
);
// res.meta.filteredTotal, res.jobs[...] — every field grounded in RUN1-SPEC §1
```

The 14 tools (each calls an EXISTING app fetch client / RTK Query endpoint / Redux
action — none re-implements API logic):

| Tier | Tools |
|---|---|
| 1 · read (anonymous-safe, `readOnlyHint:true`) | `search_jobs`, `list_filter_options`, `list_companies`, `search_locations`, `get_job`, `get_company_hiring_trend` |
| 2 · drive the live page | `apply_feed_filters`, `reset_feed_filters`, `open_job` |
| 3 · personalize (sign-in required, except `submit_feedback`) | `request_sign_in`, `set_enabled_companies`, `save_filter_defaults`, `upvote_feature`, `submit_feedback` |

**WebMCP is the arrange/act layer; the DOM and the DB are the assert layer.** After
a Tier-2 tool, read the rendered page. After a Tier-3 tool, read the row it wrote in
`jobscraper_e2e`. See [`features/`](features/README.md) for the per-route playbooks.

## Launch

Boots the real app on the **isolated** ports (`:8201` backend, `:3201` frontend,
`jobscraper_e2e` DB) with the WebMCP flag on. Never touches the owner's
`:8000/:8100/:3000` stack — that guarantee is inherited from `stack_up.sh`.

```bash
bash "$REPO/.claude/skills/verify-onesecondswe/helpers/launch.sh"
```

`launch.sh` does exactly three things and prints what it did:
1. **Pins Node 22.14.0** onto `PATH` (the shell's default here is v22.1.0, which
   silently hangs Vite/Playwright — same pin `e2e/run.sh` makes).
2. **Exports `VITE_WEBMCP=1`** into the shell that `stack_up.sh` inherits, so the
   `nohup npx vite dev` child registers the shim. (Vite exposes `VITE_`-prefixed
   `process.env` vars to `import.meta.env`, so no `.env` edit is needed — the flag
   is process-scoped scaffolding that vanishes when the stack is torn down.)
3. Runs `e2e/shared/stack/stack_up.sh --artifacts-dir <skill>/artifacts/<run>/stack`,
   which refreshes the DB seam, boots uvicorn on the JWKS-patched
   `e2e/shared/stack/e2e_app.py`, boots `vite dev` under
   `e2e/shared/stack/vite.e2e.config.ts` (the whole-`/api` proxy), and health-waits
   both.

**Prerequisites** (launch.sh checks and fails loudly if missing):
- Postgres container up: `docker compose up -d postgres` (source clone
  `jobscraper_pr243` must exist — `ensure_db.sh` clones it into `jobscraper_e2e`).
- `.venv` present at repo root, and root `npm install` has run (frontend deps).

**Ready when** `stack_up.sh` exits 0 **and** the shim reports all 14 tools — run
Doctor next; it proves both.

Fallback if your Vite build ignores process-env `VITE_` vars (older Vite): write
`VITE_WEBMCP=1` into `src/frontend/.env.local` as verification scaffolding, and
delete that line in Cleanup. `launch.sh --env-file` does this for you and records
it so Cleanup can undo it.

## Doctor (read-only "is this instance worth driving?")

```bash
bash "$REPO/.claude/skills/verify-onesecondswe/helpers/doctor.sh"
```

Three read-only checks, in order (exit non-zero on the first hard failure):
1. `curl -fsS http://127.0.0.1:8201/health` → `OK` 200 (pool alive).
2. `curl -fsS http://127.0.0.1:8201/health/worker` → 200, polled up to ~30s.
   **Soft check** — the Procrastinate lanes heartbeat a few seconds after boot, and
   none of the 14 tools need the worker, so a lingering 503 is reported as a WARNING,
   not a failure.
3. The **shim probe**: loads `http://127.0.0.1:3201/` in headless Chromium and
   asserts `window.__webmcp__.list()` returns exactly the 14 expected tool names.
   A missing/short shim means `VITE_WEBMCP` didn't take (a drift-fix under edit
   scope, not a product bug) — re-run Launch. This runs the Playwright spec
   `helpers/doctor.spec.ts` via `helpers/verify.playwright.config.ts`.

Run Doctor before the first drive, and again after any surprising failure.

## Drive

Reuse `e2e/shared/playwright/` — `fixtures.ts` (`signedInPage`/`signedInContext`,
a JWKS-seam minted token injected the app's own way) and the base
`playwright.config.ts`. The drive specs here import `test`/`expect` from that
fixtures module, never from `@playwright/test` directly.

Run the bundled proof drive (one fully-worked feature: Recent-feed company filter,
plus two Tier-3 side effects), from `$REPO/e2e` so Node resolves `e2e/node_modules`:

```bash
export PATH="$HOME/.nvm/versions/node/v22.14.0/bin:$PATH"   # 22.1.0 hangs Playwright
cd "$REPO/e2e" && npm install --no-audit --no-fund          # first run only
cd "$REPO/e2e" && npx playwright install chromium           # first run only
cd "$REPO/e2e" && npx playwright test \
  --config="$REPO/.claude/skills/verify-onesecondswe/helpers/verify.playwright.config.ts" \
  --grep '@drive'
```

The rules every drive follows:
- **Invoke tools through the shim, never through DOM selectors:** `page.evaluate(([n,a]) => window.__webmcp__.call(n,a), [name, args])`.
- **WebMCP arranges/acts; the DOM asserts.** After `apply_feed_filters`, read the
  rendered Recent list. The list is **virtualized (signed-in) / hard-capped at ~12
  (signed-out)**, so it never mounts all N rows — assert the *per-card invariant*
  (every visible `JobListingCard` matches the filter) and the **"Displayed Jobs"**
  metric, NOT a row-count equality against `meta.filteredTotal` (see the Recent-feed
  feature file's Gotchas — this trips people).
- **Anonymous flows use a plain `page`;** Tier-3 side-effect flows use
  `signedInPage`/`signedInContext` (the fixture, never `request_sign_in`, drives the
  auth — that tool cannot complete headlessly).
- Real handles on the Recent page (`components/shared/JobCard/`): job title is a
  `role=heading level=3`; the company name renders as text (e.g. `Apple`); each card
  has an `Apply` link; the metric row shows the label `Displayed Jobs`.

To drive a feature yourself, copy `helpers/drive.spec.ts` as a template and follow
the matching file in [`features/`](features/README.md).

## Evidence (proof standards)

Every drive writes into the run's artifacts dir (survives teardown — it lives OUTSIDE
the stack): `<skill>/artifacts/<run>/` (the run id is the launch timestamp; specs read
`E2E_VERIFY_ARTIFACTS`, defaulting under the skill). Per driven feature capture:
1. **ARIA snapshot** of the asserted region — `await locator.ariaSnapshot()` written to
   `<feature>.aria.txt`.
2. **Screenshot** of the resulting page — `await page.screenshot({ path: <feature>.png })`
   (explicit, because the base config only keeps screenshots on failure).
3. **`meta` counts** from the tool result (`filteredTotal`/`serverReturned`) written to
   `<feature>.meta.json` — the quantitative anchor the DOM must be coherent with.
4. **A DB row** proving a Tier-3 side effect, read from `jobscraper_e2e` through
   `helpers/db_assert.py` (which connects via `e2e/shared/db/assertions.py::connect`,
   itself refusing any database but `jobscraper_e2e`):

```bash
# after submit_feedback (anonymous) — a feedback row exists
"$REPO/.venv/bin/python" "$REPO/.claude/skills/verify-onesecondswe/helpers/db_assert.py" \
  --table feedback --contains "verify-onesecondswe smoke"
# after set_enabled_companies as the primary identity — user_enabled_companies rows
"$REPO/.venv/bin/python" "$REPO/.claude/skills/verify-onesecondswe/helpers/db_assert.py" \
  --table user_enabled_companies --email 'e2e+add-companies@jvn.test'
```

Proof standards, held here:
- Exercise the **real user path** — a `window.__webmcp__.call(...)` that hits the real
  endpoint/store — never an internal setter or a test-only route.
- `open_job` verifies the popup **intent** (`page.on('popup')` or a `window.open` stub),
  not a live navigation: headless popups are blocked. Documented, not hidden.
- `request_sign_in` is **smoke-only** — it fires the prompt path; real Tier-3 auth comes
  from the JWKS-seam fixture (`e2e/shared/auth/storage_state.ts`).
- Enrichment is ~100% NULL in `jobscraper_e2e`, so a `category`/`level` filter proves the
  *mechanism* with `filteredTotal ≈ 0`, not a non-empty list — assert on the `meta` shape,
  and use company/keyword/timeWindow filters (which have real data) when you need the list
  to narrow to something non-empty. This is a real limit of the clone; don't read it as a
  broken tool.

## Cleanup

```bash
bash "$REPO/.claude/skills/verify-onesecondswe/helpers/cleanup.sh"
```

`cleanup.sh`:
1. Runs `e2e/shared/stack/stack_down.sh` — kills only the pidfile-recorded backend/frontend,
   **never by process name**.
2. Sweeps both test identities' owned companies through the product's own delete path
   (`python -m e2e.shared.db.reset_user`), exactly as `fixtures.ts:sweepOwnedCompanies` does.
3. Removes any `VITE_WEBMCP=1` scaffolding the `--env-file` launch wrote to
   `src/frontend/.env.local` (the default process-env launch leaves the tree untouched, so
   there is nothing to undo).
4. **Re-confirms the evidence still exists** at `<skill>/artifacts/<run>/` and prints the
   path — a cleanup that ate the proof would fail this step.

Evidence survives teardown by construction; the stack does not.

## Helpers

Every script this skill ships is executable and its exact invocation is shown above. Nothing
here needs reverse-engineering.

| Helper | What it is | Invocation |
|---|---|---|
| `helpers/launch.sh` | Node pin + `VITE_WEBMCP=1` + `stack_up.sh` | `bash …/launch.sh [--env-file] [--refresh-db]` |
| `helpers/doctor.sh` | health + worker + 14-tool shim probe | `bash …/doctor.sh` |
| `helpers/cleanup.sh` | `stack_down.sh` + user sweep + scaffolding removal + evidence re-check | `bash …/cleanup.sh` |
| `helpers/db_assert.py` | read a Tier-3 side-effect row from `jobscraper_e2e` (via `assertions.connect`) | `.venv/bin/python …/db_assert.py --table … [--email …] [--contains …] [--feature-id …]` |
| `helpers/verify.playwright.config.ts` | Playwright config extending `e2e/shared/playwright/playwright.config.ts` | passed as `--config` to `npx playwright test` |
| `helpers/doctor.spec.ts` | `@doctor` — asserts the 14-tool shim surface | `npx playwright test --config … --grep '@doctor'` (run by `doctor.sh`) |
| `helpers/drive.spec.ts` | `@drive` — the worked proof: Recent company-filter + `submit_feedback` + `set_enabled_companies`, writing evidence | `npx playwright test --config … --grep '@drive'` (run from `$REPO/e2e`) |

## Feature map

[`features/README.md`](features/README.md) indexes one file per user-facing route from
`src/frontend/src/config/routes.ts`. Each file has exactly four H2s — `## Sub-features`,
`## How to get to it (user POV)`, `## Driving it with WebMCP`, `## Gotchas`. The map is the
maintained source of truth for what to verify; a proof that drives one convenient route is
incomplete while the map lists others. Keep it honest with `/maintain-verification-skill` as
the app changes.
