# e2e — regression gates

Runs **before** any agent says "ready to test" (see root `AGENTS.md` and
`.claude/skills/e2e-gate/SKILL.md`). Each subdirectory under `e2e/` is a **section** — one
feature area's end-to-end gate. `e2e/shared/` is feature-agnostic infrastructure every
section reuses: the stack (backend/frontend/DB), auth (mint a real token against a patched
JWKS seam), DB helpers, and the Playwright base config.

```
e2e/run.sh <section> [--fast] [--case AC-06] [--refresh-db]
```

## Sections

| Section | What it gates | Runtime (full / `--fast`) | Cost |
|---|---|---|---|
| `add-companies` | Add Companies (E7): careers-URL resolve, ATS add, one-time discovery, delete/purge, flags, ownership isolation, idempotency, the published-board-match suggestion | ~8 min full (measured; see PLAN.md report) / ~1 min `--fast` | a few live discovery calls to Claude Haiku on the full run; $0 on `--fast` |
| `company-name-search` | **Type a company name, get its job board** — the intent test over `POST /api/companies/search-by-name`, against a curated case list. See `company-name-search/README.md` | ~60 s full (measured) | **~38–39 live Browserbase Search calls ≈ $0.27 per run** (measured 2026-09-05: 39 calls, $0.273). Prints the count; `--max-searches` caps it; `--validate-only` and `--replay` are **$0** and skip the backend and the key entirely |
| `live-view` | **The discovery live view stays on screen** — five scripted sessions against a real browser, a real cross-origin iframe and a real poll, asserting the frame never blinks while the session is open and really goes when it ends. See `live-view/README.md` | ~3.5 min (measured) | **$0.** Opens no browser session. `--live` opts into exactly one real Browserbase discovery (~1 billed minute) |
| `subcategories` | **The SWE subcategory filter** — SC-00..SC-06: the parent category still returns its unlabelled rows, one subcategory returns only its own, filters AND, the `full_stack` widening stays one-way, the reveal flag gates the UI and nothing else, and `NULL` never becomes `[]`. See `subcategories/CASES.md` | ~80–95 s full (measured) / **10 s** `--fast` | **$0, unconditionally** — no LLM call, no Browserbase session, no opt-in that changes it |
| `billing` | **Stripe Pro plan** — BL-01..BL-15: checkout pays and grants Pro, renewal, declined card with 3-day grace, recovery, cancel at period end, portal, webhook signature/replay/out-of-order safety. Real Stripe sandbox + test clocks. See `billing/CASES.md` | ~2.7 min full (measured) | **$0** — sandbox only; a live key is refused. Needs `stripe login`; local-only |
| `onboarding` | **The first-sign-in questions** — OB-01..OB-09 (API) and OB-U1..OB-U13 (UI): a brand-new identity is asked once — straight from sign-in, never after a page loads — answers land on the filtered list, signing in again (a new browser context) never asks, Skip/Escape/leaving half-way, a failed save, an older backend, never on `/pricing`, phone layout. Fresh identity per case. See `onboarding/CASES.md` | **54–56 s** full (measured, twice) / **9 s** `--fast` | **$0, unconditionally** — PostHog blanked (and refused at boot), the browser fenced to `127.0.0.1` |
| `enricher` | **The local enrichment worker** — EN-00..EN-10: the REAL `enrich_tick_wrapper.sh` + CLI (a sandbox copy of `src/enricher`) against the real backend + Postgres, with a deterministic stub ollama: one tick end to end, judge routing, the metrics channel, the tick lock, engine outage, bad model output, idempotent re-delivery, the kill switch, the subcategory knob, isolation. `--enricher-ref <ref>` runs another version (e.g. the prod tag). See `enricher/CASES.md` | **60 s** full / **27 s** `--fast` (measured) | **$0, unconditionally** — stub model on loopback, no `claude`, never the real ollama, blank Anthropic key |
| `enricher-cutover` | **The enricher's move from `app/` to a JVN clone, and its merge trigger** — CO-01..CO-19, CO-REAL, WT-01..WT-07: the REAL `cutover.sh` / `watcher.sh` / `install_watcher.sh` against a throwaway sandbox per case (fake HOME, fake old prod + old dev git checkouts, a local bare repo standing in for GitHub JVN, a stub launchd that really fires a fake worker): park-before-unload, wedged tick, refusals, rollback with/without the DB copy-back, crash + resume, a first tick killed mid-run, read-only preflight, secrets, and the real prod tag's tree. No stack, no ports. **Also runs in GitHub CI.** See `enricher-cutover/CASES.md` | **~3.3 min** full / **28 s** `--fast` (measured) | **$0, unconditionally, and no network** — local file remotes, uv offline, stub `launchctl`/`gh`/`send.sh` |

Adding a section = one directory under `e2e/` (its own `PLAN.md`, `CASES.md`, `api/`, `ui/`),
one file under `.claude/skills/e2e-gate/sections/`, one row above. See
`add-companies/PLAN.md` §1 for the three-rule convention.

**Rule 2 in practice — generalise `shared/`, never fork it.** `subcategories` needed a second
stack (its own ports, its own database, because it SEEDS fixtures). Rather than copying
`stack_up.sh`, it parameterised the shared one: ports, env file, pidfile directory, target
database and `--schema-only` provisioning are all knobs now, and **every default is the value
that shipped**, so `add-companies` and `live-view` are byte-for-byte unaffected. The same goes
for `vite.e2e.config.ts`, `e2e_app.py`, `ensure_db.sh`, `assertions.py` and both Playwright
files. A section sets those knobs once, in its own `run.sh`. `enricher` added three more to
`stack_up.sh` the same way — `E2E_SKIP_FRONTEND` (backend only), `E2E_INTERNAL_API_KEY` (run the
backend with the internal-key middleware armed) and `E2E_BLANK_ANTHROPIC_KEY` — each defaulting
to the old behaviour (`enricher/PLAN.md` §1). See `subcategories/PLAN.md` §3 for
the full table — including the two guards the knobs came with (`stack_up.sh` refuses to start on
`:8000`/`:8100`/`:3000`; `ensure_db.sh` and `e2e_app.py` refuse any database not named
`jobscraper_e2e` or `jobscraper_e2e_<section>`).

**Provisioning from a dev database** (`E2E_SOURCE_DB=jobscraper`, when `jobscraper_pr243` is
absent): `ensure_db.sh --schema-only` copies the source's `alembic_version` row, so the clone is
only as right as that row. Two generalisations (both no-ops for an older source) cover the gaps
an up-to-date dev DB hits: `job_subcategories` rows are copied from the source when the clone is
still empty after `upgrade head`, and `E2E_SOURCE_DB_REVISION=<rev>` stamps a FRESH clone at the
revision the source's schema is really at — for a source a test fixture `alembic stamp head`-ed
without upgrading (the local `jobscraper` on 2026-11-22: stamped `ef0f7d8c8e11`, column missing;
`E2E_SOURCE_DB_REVISION=bcbc67dbd87e … --refresh-db`).

## Which runner owns what

There are **two** front doors to this repo's end-to-end coverage, and they are not
alternatives — they own different things. `e2e/run.sh` is the gate; the
`verify-onesecondswe` skill is the $0 driving surface that a person or an agent reaches
for to *see a feature work*.

| Runner | Owns | Cost |
|---|---|---|
| `e2e/run.sh add-companies` | The Add Companies regression gate — AC-01..AC-12: resolve, add, discovery, delete/purge, flags, ownership, idempotency | $0; ~3 live Haiku calls on a full run, none on `--fast` |
| `e2e/run.sh company-name-search` | The name-search **intent** test against the live web — is the answer still right *today* | **~$0.27** |
| `e2e/run.sh company-name-search --replay <f>` / `--validate-only` | The same judge over recorded bodies / the case-file rules | **$0** (no backend, no key) |
| `e2e/run.sh live-view` | Live-view **continuity** — LV-01..LV-05, is the frame on screen from first paint until the session really ends, and which closer fired | $0 (`--live`: one billed browser-minute) |
| `e2e/run.sh subcategories` | The SWE-subcategory filter — SC-00..SC-06: parent-vs-child scope, exact single-slug matching, AND composition (and the specialty scope: a specialty narrows only SWE rows), the one-way `full_stack` widening, the reveal flag's UI-only reach, and the `NULL`/`'{}'` distinction | **$0** |
| `e2e/run.sh onboarding` | The first-sign-in questions — OB-01..OB-09, OB-U1..OB-U13: asked exactly once per account, across sign-ins, contexts and devices | **$0** |
| `e2e/run.sh enricher` | The local enrichment worker — EN-00..EN-10: the real wrapper + CLI against a real backend with a stub model; `--enricher-ref <ref>` for another version (the prod tag before a deploy or the cutover) | **$0** |
| `e2e/run.sh enricher-cutover` | The enricher cutover + its merge watcher — CO-01..CO-19, CO-REAL, WT-01..WT-07, each in its own sandboxed "machine"; runs locally and in CI | **$0**, no network |
| `verify-onesecondswe` skill | Driving the app the way a user does through `window.__webmcp__`, plus the two surfaces the shim cannot reach: `@live-view` (URL **integrity** + liveness) and `@name-search` (the typed name reaches the endpoint **verbatim**) | **$0**, except `helpers/name_search.sh --live` which delegates straight back to `e2e/run.sh` |

The skill does not re-implement any judging. `helpers/name_search.sh` shells out to this
section's `intent_test.py`, and `helpers/name_search.sh --live` `exec`s `e2e/run.sh`. One
judge, one case file, two entry points.

**Deliberately still separate:** the `add-companies` gate (AC-01..AC-12) is not folded into
the skill — it is a twelve-case regression gate with its own boards, pre-flight and
BLOCKED semantics, and `features/add-companies.md` points at it rather than duplicating it.

## Non-negotiables (every section)

- Its own backend/frontend/DB — never the owner's `:8000`/`:8100`/`:3000` stack. `stack_up.sh`
  now **refuses** to start on those three ports rather than trusting each section to get it
  right; a section that collided would not merely fail to bind, it would have its
  `stack_down.sh` kill the owner's dev server by pidfile on the way out. Ports in use today:
  `:8201`/`:3201` (add-companies + live-view, sharing one stack and one lock), `:8202`
  (add-companies' short-lived flagged backends), `:8203`/`:3203` (subcategories), `:8204`/`:3204`
  (billing), `:8205`/`:3205` (onboarding), `:8207` + `:8206` + `:8215` (enricher: backend, its
  short-lived kill-switch backend, the stub ollama; no frontend). `enricher-cutover` binds no
  port at all.
- **A section that SEEDS rows owns its own database.** Two sections writing fixtures into one
  database is the same class of bug as two runs sharing one stack — one silently changes the
  other's answers. `add-companies` and `live-view` share `jobscraper_e2e` because neither seeds;
  `subcategories`, `billing`, `onboarding` and `enricher` each have their own `jobscraper_e2e_<section>`.
- `CAPTURE_USE_BROWSERBASE=false`, asserted at boot. Browser hours are the expensive
  line and no section may ever bill one.
- A blank Browserbase key, asserted at boot — with TWO deliberate exceptions.
  `company-name-search` tests the feature whose first step *is* a paid Browserbase
  Search call, so it requires the key and asserts its presence instead. It still
  refuses to boot with `CAPTURE_USE_BROWSERBASE=true`, so it can bill searches
  ($0.007 each, counted and printed) and can never bill a browser hour. It carries
  its own guards in `company-name-search/stack_app.py` rather than weakening
  `e2e/shared/stack/e2e_app.py`, which protects the far more frequently run gate.
  The second exception is `live-view --live`, and it is the only thing in this repo
  that deliberately bills a BROWSER session. It has to: a hosted live view exists
  only on a Browserbase capture, so a stack that cannot open one cannot observe the
  feature at all, and the root cause of the bug it was built for was the third-party
  frame's own behaviour. It is opt-in, never part of the default run, opens exactly
  one session (~1 billed minute), and carries inverted guards in
  `live-view/stack_app.py`. `e2e/run.sh live-view` with no flag opens nothing.
- Re-runnable back to back with no manual reset.
- A third-party outage reads as **BLOCKED**, never as a code regression (PASS/FAIL/BLOCKED,
  never a silent pass-or-fail binary).
