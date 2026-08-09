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
| P2 | `feat/e7-phase2-gate-oracles` | P1 | — | Phase 2 — the completeness gate + oracles; **fix Workday 2,000 cap**; fleet breaker; 36h floor; per-company baseline (§3, §4, §8, §9) | 🔜 planning |
| P3 | `feat/e7-phase3-discovery` | P2 | — | Phase 3 — closed primitive vocabulary + stored HTTP scripts + one-time local-browser agent discovery (§6 Phase 3, §9) | ⏳ queued |
| P4 | `feat/e7-phase4-browser-runtime` | P3 | — | Phase 4 — Browserbase runtime + execution-time SSRF/CDP host pinning (§6 Phase 4) | ⏳ queued |
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
