# E7 Custom Company Sources — Stack Orchestration & Log

**Purpose.** Build Phases 2–5 as a **stack of PRs** on top of Phase 1 (PR #243), so the **top branch contains everything** and can be tested end-to-end, while each phase stays an independently-reviewable PR. This file is the **living log**: the orchestrator appends an entry every time a phase's plan / implement / review / fix / PR step happens, so any agent (or Brendan) can pick up mid-stream without conversation history.

> Read `OVERVIEW.md` (architecture + why) and `BUILD-PLAN.md` (phase-by-phase spec) first. This file is the *orchestration* layer on top of them — it does not restate the specs, it points at them and records progress.

---

## Decisions locked (2026-08-09)

- **Stack tooling:** plain `git` + `gh`. Each phase = its own branch/PR based on the branch below it. The orchestrator restacks upward when a lower PR changes.
- **Base:** the whole stack sits on `feat/custom-company-sources-spike` (PR #243, Phase 1). #243 is **not** merged yet — that's intentional; Brendan wants to test the whole thing working end-to-end and merge once, rather than amend-gate each layer.
- **Phase 4 runtime:** **Browserbase**, using the free-tier key already in `.env.local` (`BROWSERBASE_API_KEY` + `BROWSERBASE_PROJECT_ID`). Wire it correctly; verify **sparingly** (a session or two) to stay inside free-tier limits. Never commit the key.
- **Per-PR agent loop (owner-mandated):** opus **plan** → opus **implement** → opus **adversarial review** → orchestrator folds fixes → PR finished **before Brendan looks**. Brendan reviews finished PRs / the top branch, not mid-implementation.
- **"Working" bar:** Phases 2–3 are built **and locally testable end-to-end**. Phase 4 (Browserbase) and Phase 5 calibration have pieces that can only be validated on prod / with real traffic — those ship behind flags and are marked `PROD-VERIFY` in the log, not claimed as locally proven.

## Constraints / cannot be verified locally (carry forward, don't re-litigate)

- Browserbase from Railway's egress IP; browser-subprocess memory on the 4 GB Railway container.
- Phase 4.5 per-company churn calibration — needs 2–3 weeks of prod data (largest single unknown).
- Facet-oracle single-valued generality across Workday tenants (verified on ~6, want ~20).
- Empty-board shapes for Greenhouse/Ashby/ADP/UKG/Paylocity (inferred, not all observed).

---

## The stack

| Order | Branch | Base | PR | Scope (see BUILD-PLAN) | Status |
|---|---|---|---|---|---|
| P1 | `feat/custom-company-sources-spike` | `main` | #243 | Phase 1 — private ATS companies, never-close gate | ✅ done, pushed |
| P2 | `feat/e7-phase2-gate-oracles` | P1 | **#247** | Phase 2 — the completeness gate + oracles; **fix Workday 2,000 cap**; fleet breaker; 36h floor; per-company baseline (§3, §4, §8, §9) | ✅ implemented + reviewed (clean) · PR open |
| P3 | `feat/e7-phase3-discovery` | P2 | **#248** | Phase 3 — **PIVOTED** to Browserbase **Stagehand** browser-agent discovery + runtime (was Sonnet-writes-JSON-recipe; superseded — see `PHASE-STAGEHAND-PLAN.md`). Subsumes P4. | 🔁 reworking (Stagehand) |
| ~~P4~~ | ~~`feat/e7-phase4-browser-runtime`~~ | — | — | **DROPPED / SUBSUMED** — Stagehand IS the browser runtime, folded into P3. | ⛔ subsumed |
| P5 | `feat/e7-phase5-repair-admin-name` | P4 | — | Phase 5 — board-identity repair, refuse UX, admin dashboard, name→URL input (§6 Phase 5, §4.4) | ⏳ queued |

**Top branch to test end-to-end = the highest branch that exists** (P5 when built; P2/P3/P4 in the meantime). Check it out; it contains every phase below it.

## Per-PR loop protocol

1. **Branch:** orchestrator creates the phase branch off the one below and checks it out.
2. **Plan (opus):** a fresh opus agent turns the BUILD-PLAN spec for this phase into a concrete, file- and test-level implementation plan; the orchestrator records a summary in the log and, if useful, a `PHASE-N-PLAN.md`.
3. **Implement (opus):** a fresh opus agent implements the plan on the phase branch, writes tests, gets them green. It first baselines (so it can tell its own breakage from inherited state).
4. **Adversarial review (opus):** a *separate* opus agent attacks it against live code — closure-safety invariants, the visibility leaks, source_id isolation, the new oracles' failure modes, SSRF at execution time — and reports CONFIRMED/PLAUSIBLE findings with a failure scenario each.
5. **Fix:** orchestrator routes findings back for fixes; loops until the review is clean; independently re-runs the key tests.
6. **PR:** orchestrator commits, pushes, opens the stacked PR (base = branch below), writes a self-contained description, and logs it.
7. **Verify claims against code before recording them** — this program already had to retract one unverified subagent assertion. Don't repeat it.

## Bug-routing model (once Brendan is testing the top branch)

A reported problem → identify which phase owns the behavior (gate/oracle → P2; discovery/scripts → P3; browser runtime/SSRF → P4; repair/admin/name → P5) → fix on that phase's branch → restack the branches above it → note it in the log. Fixes to Phase 1 land on #243's branch and restack the whole stack.

---

## LOG (append-only; newest at bottom)

- **2026-08-09** · orchestration · doc created; decisions locked (git+gh stack, Browserbase free-tier for P4, per-PR opus plan→implement→review loop). Base = #243 @ `b8d22d0` (Phase 1 done: 1676 backend + 62 frontend tests green, live Duolingo E2E verified, demo cleaned).
- **2026-08-09** · P2 · branch `feat/e7-phase2-gate-oracles` created off P1; opus plan agent dispatched (turn the §3 gate + §4 closure-safety + §8 regression-test + §9 Workday-cap specs into a file/test-level plan).
- **2026-08-09** · P2 · plan landed → `PHASE-2-PLAN.md`. ATS→oracle: `declared_probed` (tol 0) for Greenhouse (`meta.total`) + Workday (`total`); `self_consistent` (clean-termination + 3-run streak + delta) for Ashby/Lever/Gem/Eightfold (Eightfold `count` is evidence-only, unreliable). Tasks A–H; zero migration (all evidence cols exist); baseline computed on-the-fly from `company_harvests`.
- **2026-08-09** · P2 · orchestrator decisions confirmed: **D1** verdict-first close-precedence (record `unverified_harvest` even when the ratio guard would also trip — resolves a real §4-vs-§8 conflict; `unverified_harvest` must NOT count toward the partial-skip auto-release per §4.1; guard stays the secondary net for the VERIFIED-but-shrank case). **D2** gate DERIVES the effective oracle from the ATS provider, so existing Phase-1 `oracle_kind='none'` rows graduate with no backfill. **D3** Workday cap → client surfaces `cap_hit=True` → UNVERIFIED (do NOT raise, do NOT paginate past 2,000). **D4** skip `company_harvests.script_version`; use `company_scripts.updated_at` for the first-run-after-change gate (zero migration). **D5** expose `trackingStartedAt`, keep the day-0 caption, defer fancy chart-shading. Implement agent dispatched.
- **2026-08-09** · P2 · implement landed (commit `11e030e`): the gate, VERIFIED-only closing wired into the leaf task, Workday cap→UNVERIFIED, fleet breaker, 36h floor, per-company baseline. 1713 backend tests. Orchestrator re-verified 50 key tests independently (gate + the §8 close-path suite). *Note:* the implement agent disclosed it briefly ran tooling against the MAIN parent checkout + created/removed a stray file there; verified NO commits to any branch (base/main unchanged) and all changes are in the worktree — flagged to Brendan to `git status`/`git clean -n` his main checkout.
- **2026-08-09** · P2 · adversarial review → **verdict SAFE**, core invariant HOLDS (no path closes a job still on the board; close conjunction complete + correctly ordered; public crons byte-identical; source_id isolation intact). 5 findings, all Low/contained. **Fixed Finding 5** (self_consistent completeness now requires a genuine short/empty terminus, not a provider `count`-break — closed a narrow wrong-close path for a consistently-under-reporting Eightfold; commit follows). **Documented** Findings 1 (non-idempotent miss-increment under retry → already-gone stale job may close 1 run early), 2 (fleet-breaker 24h-window/onset race), 4 (declared_probed has no delta-band) as fleet-hardening TODOs — none a wrong close.
- **2026-08-09** · P2 · review fix committed; **1719 backend tests / 0 fail**, mypy clean, single head `fb8467065dfc`, public crons byte-identical. **PR #247 opened** (base = P1 / `feat/custom-company-sources-spike`). P2 complete. → Phase 3 next.
- **2026-08-09** · P3 · branch `feat/e7-phase3-discovery` created off P2; opus plan agent → `PHASE-3-PLAN.md`. 7 tasks: script schema + closed vocabulary (port `recipe_spike/recipe_schema.py`; add `paginate_facet`; reject `click_sequence` + browser transports), deterministic replay engine (`recipe_runner.py`, port `replay.py`, import-guarded incl. AST walk, emits the existing `HarvestEvidence` → Phase-2 gate needs no rewrite), richer oracles (fill the `harvest_verification.py:213` `NotImplementedError` seam — `facet_sum`/`header`/`sitemap`, exact tol 0), discovery agent (`services/discovery/*` — local Playwright observe → Sonnet author → validate/replay/gate, ≤2 attempts then REFUSE), non-ATS add → async `discover_custom_company` task, frontend 202/refuse states. **No schema migration** (values only). Adds `playwright`+`beautifulsoup4` to backend requirements (Docker needs Chromium — Railway-verify).
- **2026-08-09** · P3 · **decisions confirmed by Brendan:** discovery = **Sonnet** via the existing `ANTHROPIC_API_KEY`; **one paid ~$1 E2E run authorized** (real Playwright + Sonnet vs `amazon.jobs`, behind an env flag, never CI) as the ONLY paid test — replay/oracles/schema stay $0/fixture-tested; discovery runs **async** (Procrastinate 202), not inline. **Article gate LIFTED** (Brendan has no articles) — Phase 4 may proceed to Browserbase after P3. Implement agent dispatched.
- **2026-08-09** · P3 · built in two passes: **3a** ($0 foundation — schema + replay engine + richer oracles, commit `7b6738d`; orchestrator caught + fixed a fragile import-guard test — boundary genuinely intact) and **3b** (discovery agent + async add-flow + frontend, commit `3429515`). Orchestrator re-verified each independently.
- **2026-08-09** · P3 · adversarial review → **one CRITICAL must-fix: execution-time SSRF** (nightly replay fetched stored LLM-authored URLs with redirects on, no guard → could 302 to `169.254.169.254`/internal + exfil via the owner endpoint). Fixed with a sync `GuardedTransport` (no redirects, every hop re-validated via `url_guard`, host-pin + resolved-IP-pin closing DNS-rebind, TLS SNI preserved), commit `09bcf76`. Everything else HELD (agent-free boundary; no cross-tenant wrong-close; ships dark).
- **2026-08-09** · P3 · **live discovery brought up on `amazon.jobs`** across the 2 approved Sonnet runs (~$2). Fixed three real integration issues no mock could catch: Anthropic **strict structured output can't express the recipe schema** → switched author to a lenient **`submit_recipe` tool call** (`12949cc`); the prompt needed **exact per-op/per-oracle key guidance** (Sonnet put `total_path` on the wrong oracle kind) → precise keys + worked Amazon example (`f95cf74`). The confirmed run **authored a VALID Amazon recipe and entered replay past `validate_recipe`** — discovery works; the E2E only timed out on the slow full-board live fetch (timeout raised, `9259f4a`). **PR #248 opened** (base = P2). P3 complete → local stack + hand off, then Phase 4.
- **2026-08-09** · P3 · local stack handed off; Brendan tested. **Two gaps surfaced live:** (a) the discovery-pending UI never updates (no `companies` row exists during discovery, so the poll predicate can't fire — banner is terminal), and (b) discovery on **YC raindrop REFUSED** — the Sonnet author guessed a JSON *API* and got HTTP 404 instead of reading the embedded island (+ a `/jobs/jobs` URL-doubling bug). Also fixed a page-crashing hooks bug in MyCompaniesPage (`c19daf5`).
- **2026-08-09** · **PIVOT (owner):** the Sonnet-writes-JSON-recipe discovery is **too fragile** — replace it with **Browserbase Stagehand** (browser-agent that reads the real rendered page), bounded to **2–3 pages**, artifact stored + replayed on cadence; "big guns first, optimize the cheap/deterministic replay later." Stagehand collapses old P3 (discovery) + planned P4 (Browserbase runtime) into ONE `transport='browser_agent'`.
- **2026-08-09** · research + **one bounded validation run** (free-tier Browserbase, Python Stagehand v3, ~63s, ~1 browser-min): **read 9/9 jobs off YC raindrop** (the page Sonnet failed on) and did real 2-page bounded pagination on Amazon (stopped at 2 of 22k). **Crux risk:** Stagehand's schema'd `extract` returned DOM row-indices, not stable ids → mitigation = prove-stable-id-or-RAISE/UNVERIFIED (never wrong-close). Plan → `PHASE-STAGEHAND-PLAN.md` (`6424aa8`). Reuses gate/oracles/close-tail/add-flow/storage unchanged (adds a 3rd transport branch); removes observer/author; keeps `recipe_runner`/`guarded_client` as the later http_json optimization tier. Reworks on #248 (subsumes P4). Implement agent dispatched.
