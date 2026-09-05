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

All commands are written to run from the repo root. Set `REPO` once, derived from
the checkout you are in (correct in any clone or worktree — do NOT hard-code a
path), then paste the blocks as-is. Run this from inside the checkout:

```bash
REPO="$(git rev-parse --show-toplevel)"
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
export NODE_PATH="$REPO/e2e/node_modules"                   # REQUIRED — see below
cd "$REPO/e2e" && npm install --no-audit --no-fund              # first run only
cd "$REPO/e2e" && npx --no-install playwright install chromium  # first run only
# --no-install: use the Playwright pinned in e2e/node_modules, never a version npx
# would otherwise download and run from the registry.
cd "$REPO/e2e" && npx --no-install playwright test \
  --config="$REPO/.claude/skills/verify-onesecondswe/helpers/verify.playwright.config.ts" \
  --grep '@drive'
```

**Module resolution needs one of these, and `cd "$REPO/e2e"` is NOT one of them.** Node
resolves a spec's imports from the SPEC FILE's directory upward, not from cwd. These
specs live under `.claude/skills/verify-onesecondswe/helpers/`, and there is no
`node_modules` anywhere above them until the repo root — which does not carry
`@playwright/test` (only `e2e/node_modules` does). Without a fix every spec dies with
`Cannot find module '@playwright/test'` before a single assertion runs.

`launch.sh` now creates the gitignored `helpers/node_modules` symlink that
`helpers/.gitignore` always anticipated, so after a Launch a bare `npx playwright test`
works. `NODE_PATH` above is the belt for a run that skipped Launch; `doctor.sh` exports
it itself.

The rules every drive follows:
- **Invoke tools through the shim, never through DOM selectors:** `page.evaluate(([n,a]) => window.__webmcp__.call(n,a), [name, args])`.
- **WebMCP arranges/acts; the DOM asserts.** After `apply_feed_filters`, read the
  rendered Recent list. The list is **virtualized (signed-in) / hard-capped at ~12
  (signed-out)**, so it never mounts all N rows — assert the *per-card invariant*
  (every visible `JobListingCard` matches the filter), NOT a row-count equality
  against a header number (see the Recent-feed
  feature file's Gotchas — this trips people).
- **Anonymous flows use a plain `page`;** Tier-3 side-effect flows use
  `signedInPage`/`signedInContext` (the fixture, never `request_sign_in`, drives the
  auth — that tool cannot complete headlessly).
- Real handles on the Recent page (`components/shared/JobCard/`): job title is a
  `role=heading level=3`; the company name renders as text (e.g. `Apple`); each card
  has an `Apply` link; the page title is a `role=heading level=1` reading `Recent Job
  Postings`. There is NO header metric row — it was removed on 2026-09-05, so anchor
  "the chrome rendered" on that title rather than on a count.

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
3. **Resets the Tier-3 side-effect state `reset_user` does NOT touch** (`helpers/reset_tier3.py`,
   through `assertions.connect`, which refuses any DB but `jobscraper_e2e`): the drive's
   anonymous `feedback` rows (`submit_feedback` inserts a durable row with no owner), and
   `user_enabled_companies` / `user_saved_filters` / `feature_upvotes` for **both** fixture
   identities — persisted company scope, saved filters and vote state would otherwise leak into
   a later authenticated run against a non-refreshed DB.
4. Removes any `VITE_WEBMCP=1` scaffolding the `--env-file` launch wrote to
   `src/frontend/.env.local` (the default process-env launch leaves the tree untouched, so
   there is nothing to undo) — and removes **only** the marker-comment + flag block `launch.sh`
   appended, never a `VITE_WEBMCP=1` a user set elsewhere in the file.
5. **Re-confirms the evidence still exists** at `<skill>/artifacts/<run>/` and prints the
   path — a cleanup that ate the proof would fail this step.

Evidence survives teardown by construction; the stack does not.

## Helpers

Every script this skill ships is executable and its exact invocation is shown above. Nothing
here needs reverse-engineering.

| Helper | What it is | Invocation |
|---|---|---|
| `helpers/launch.sh` | Node pin + `VITE_WEBMCP=1` + `stack_up.sh` | `bash …/launch.sh [--env-file] [--refresh-db]` |
| `helpers/doctor.sh` | health + worker + 14-tool shim probe | `bash …/doctor.sh` |
| `helpers/cleanup.sh` | `stack_down.sh` + company sweep + Tier-3 state reset + scaffolding removal + evidence re-check | `bash …/cleanup.sh` |
| `helpers/reset_tier3.py` | delete the drive's anonymous `feedback` + reset `user_enabled_companies`/`user_saved_filters`/`feature_upvotes` for both fixtures (via `assertions.connect`) | `.venv/bin/python …/reset_tier3.py` (called by `cleanup.sh`) |
| `helpers/db_assert.py` | read a Tier-3 side-effect row from `jobscraper_e2e` (via `assertions.connect`) | `.venv/bin/python …/db_assert.py --table … [--email …] [--contains …] [--feature-id …]` |
| `helpers/verify.playwright.config.ts` | Playwright config extending `e2e/shared/playwright/playwright.config.ts` | passed as `--config` to `npx playwright test` |
| `helpers/doctor.spec.ts` | `@doctor` — asserts the 14-tool shim surface | `npx --no-install playwright test --config … --grep '@doctor'` (run by `doctor.sh`) |
| `helpers/drive.spec.ts` | `@drive` — the worked proof: Recent company-filter + `submit_feedback` + `set_enabled_companies`, writing evidence | `npx --no-install playwright test --config … --grep '@drive'` (run from `$REPO/e2e`) |
| `helpers/seed_live_view.py` | arrange ONE `discovering` row carrying a full-length live-view URL, through the product's own writers (`add_discovering_placeholder` + `ProgressLedger` + `record_discovery_progress`) | called by `live_view.spec.ts`; standalone: `.venv/bin/python …/seed_live_view.py --live-view-url '…'` |
| `helpers/live_view.spec.ts` | `@live-view` — the discovery live view: the URL reaches the `<iframe src>` UNCLIPPED, and the frame is **alive** rather than merely mounted | `npx --no-install playwright test --config … --grep '@live-view'` (run from `$REPO/e2e`) |

### The `@live-view` drive, and why it is not shim-driven

The discovery live view is the embedded Browserbase iframe shown while a company's job
feed is discovered. It was reported fixed **three times** and was still broken, because
every earlier check was a unit test and the bug lived where jsdom cannot look:
`progress.py` clipped every URL in the discovery blob at 400 characters, and
Browserbase's `debuggerFullscreenUrl` is 479 — so the iframe loaded a truncated `?wss=`
and its socket died ~700ms after every load.

`e2e/live-view` is the gate for this panel and states its own blind spot: its
deterministic mode answers `GET /api/users/companies` from its own script, so it is
structurally blind to a URL the backend mangled. Only `--live` (one billed Browserbase
minute) caught the truncation.

This spec closes that for **$0** by moving the seam: the row is arranged through the
product's own writers and the **real** backend answers the **real** poll, so the URL is
asserted where it actually lands — on the wire, in the `<iframe src>`, and in what the
frame paints.

**Presence is not liveness**, and that is the trap this spec is built around. Measured
across the regression, the pre-closers commit kept the frame on screen for **98.7%** of
the session while it painted *"Debugging connection was closed"* the entire time. An
on-screen percentage would have passed there. So the backbone assertion is **URL
integrity** (not truncated, no `…`, byte-identical to what the ledger was handed) and the
liveness check reads what the frame **rendered**.

**It is not driven through `window.__webmcp__`**, and that is a limit of the tool
surface, not a shortcut: none of the 14 tools touches the Add Companies surface — see
[`features/add-companies.md`](features/add-companies.md). Every other convention here is
kept: the shared `signedInPage` fixture, `verify.playwright.config.ts`, the
`assertions.connect` DB guard, and evidence in the run's artifacts dir.

**It proves it can fail.** A test that only ever passes is exactly what let this bug
survive three rounds, so the failing case is reproducible without editing any source
(the owner's dev stack serves this tree live):

```bash
LIVE_VIEW_SEED_CLIPPED=1 npx --no-install playwright test --config … --grep '@live-view'
```

seeds the URL byte-for-byte as the pre-fix backend would have stored it (400 chars + the
ellipsis) and **must fail** — at the wire, at the `<iframe src>`, and at the painted
frame. If that run ever passes, the spec has stopped testing anything.

## Feature map

[`features/README.md`](features/README.md) indexes one file per user-facing route from
`src/frontend/src/config/routes.ts`. Each file has exactly four H2s — `## Sub-features`,
`## How to get to it (user POV)`, `## Driving it with WebMCP`, `## Gotchas`. The map is the
maintained source of truth for what to verify; a proof that drives one convenient route is
incomplete while the map lists others. Keep it honest with `/maintain-verification-skill` as
the app changes.
