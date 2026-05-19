# Ashby Backend Migration PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

**Branch:** `ashby-backend-migration`
**Base:** `main`
**Pre-flight verifier availability:** Vercel ✓, Postgres prod ✓, Railway ✓ — all three production verifiers available.

**Pre-existing failures (NOT introduced by this PR, do NOT fix):**
- 3 test failures in `src/frontend/src/__tests__/pages/RecentJobsFilters.test.tsx` (SpaceX chip lookup). Verified pre-existing by Unit 7's implementation agent. The pr-test-analyzer may surface these; do not fix as part of this PR.

---

## 2026-05-17 — Review pass 1

8 agents dispatched in parallel (5 code-review + 3 prod-verifier). All returned.

### Code-review findings

**Critical:**
- (none)

**Important:**
- `src/frontend/src/types/index.ts:210-216` — `sourceAts` is structurally decoupled from the `backend-scraper` discriminant. The "only backend-scraper carries this" invariant lives in a doc comment, not the type system. A nonsensical literal `{ ats: 'lever', sourceAts: 'ashby', ... }` compiles. Structurally correct home is on `BackendScraperConfig`. (agent: type-design-analyzer) — **DEFER: plan-locked design choice; not a correctness bug. Fix in a follow-up PR.**
- `src/frontend/src/types/index.ts:189-205` — `Company.ats` and `Company.config.type` are duplicate discriminants that can desync. Pre-existing, not introduced here. (agent: type-design-analyzer) — **DEFER: pre-existing, out of scope.**
- `src/backend/api/services/ashby_client.py:11-16` — Module docstring asserts "Ashby raw ids are UUIDs and globally unique across the Ashby Job Board platform" as fact. This is an unverified vendor claim. Recommend softening so the composite PK (not the id format) is the load-bearing uniqueness mechanism. (agent: comment-analyzer) — **FIX this pass.**
- `src/backend/api/tasks/fetch_ashby_company.py:53-62` — `asyncio.shield` comment says "connection-pool ceilings bound the cumulative leak" — but the task uses `db.get_connection` (direct psycopg2, not the pool). Factually wrong. (agent: comment-analyzer) — **FIX this pass.**
- `test_jobs_qa_router.py:518-560` — Two new "without_admin" tests assert `403`, but no test exercises the 401 (no Authorization header) branch. If auth dependency order ever changes, regression would be silent. (agent: pr-test-analyzer) — **FIX this pass.**
- `test_jobs_qa_router.py:476-498` — `test_trigger_ashby_fetch_second_call_reports_already_enqueued` only collapses two *manual* triggers. PLAN invariant is that **manual trigger + periodic fan-out** collapse via the per-company queueing lock; no test covers this cross-origin collision. (agent: pr-test-analyzer) — **FIX this pass.**
- `test_fetch_ashby_company.py` — No test where `active_count == 0` (cold start, board genuinely empty) + empty Ashby response, which must NOT trip the safety guard. The `active_count > 0` precondition at `fetch_ashby_company.py:105` is the cold-start protection. (agent: pr-test-analyzer) — **FIX this pass.**
- `src/backend/api/tasks/fetch_ashby_company.py:249-253` — When both primary and fallback `record_scrape_run` writes fail, the function continues. If the fetch otherwise succeeded, the task exits cleanly with a missing `scrape_runs` row and no visible signal in Procrastinate. (agent: silent-failure-hunter) — **DEFER: this mirrors `fetch_greenhouse_company.py`'s pattern exactly. Fixing for Ashby alone would create inconsistency; track as a follow-up to fix both ATSes together.**

**Suggestion / Nit:**
- `CLAUDE.md:74` — "Adding a Company" example shows `createBackendScraperCompany(id, name, 'https://boards.greenhouse.io/${id}')` without `sourceAts: 'greenhouse'`. After Unit 9, every Greenhouse entry needs `sourceAts: 'greenhouse'` or it falls into "Custom Web Scrapers". (agent: code-reviewer) — **FIX this pass.**
- 3 frontend test files still register MSW handlers for `/api/ashby/v1/jobBoard/:boardName/jobs` (`App.test.tsx:39`, `AppEnabledCompaniesGlobalLoad.test.tsx:62`, `useCompanyLoader.test.tsx:40`). Dead code post-cutover. (agent: vercel-prod-verifier) — **FIX this pass.**
- `src/backend/api/services/ashby_client.py:88` — Cross-ATS comparison comment "Ashby's `location` is already a flat string (unlike Greenhouse's `{name: ...}` object)" ages poorly. (agent: comment-analyzer) — DEFER (Nit).
- Seed migration docstring line-range reference to `companies.ts (lines ~280-410)` will rot. (agent: comment-analyzer) — DEFER (Nit).
- WhyPage Ashby grouping test is somewhat tautological (groups by `getATSGroupKey()` then asserts each grouped company has `sourceAts === 'ashby'`). (agent: pr-test-analyzer) — DEFER (Suggestion, not blocking).
- Frontend `getClientForATS` could throw on stale persisted `'ashby'` in localStorage. (agent: silent-failure-hunter) — DEFER: low impact; addressed by appSlice default to BackendScraper.
- Various other suggestions/nits (ATSConstants enum redundancy, branded types, etc.) — DEFER to follow-up.

### Production-environment findings

**Critical:**
- (none)

**Important:**
- (none)

**Suggestion:**
- `EXPLAIN` on the future `fetch_ashby_company` query plans an Index Scan via `idx_job_listings_company` then post-filters `source_id` and `status`. Cost is trivial today (~25,974 rows). As Ashby data lands, a partial index `(company, source_id) WHERE status='OPEN'` or composite `(source_id, company, status)` would tighten the plan. Not required for merge. (agent: postgres-prod-verifier) — DEFER (Suggestion).
- DEPLOY.md's post-merge `trigger-ashby-fan-out` step is load-bearing for closing the 30-min gap. With both Greenhouse + Ashby fan-outs colliding at `*/30`, ~91 jobs queue at the same tick; concurrency=5 drains in ~60-90s empirically. Worth eyeballing the first cron tick. (agent: railway-prod-verifier) — DEFER (already in DEPLOY.md operator notes).
- Microsoft scraper `ON CONFLICT DO UPDATE` errors in `scripts/shared/batch_writer.py` — unrelated to this PR, lives in Playwright path. (agent: railway-prod-verifier) — DEFER (out of scope).

**Could not verify:**
- (none)

### Production verifier confirmations

- **postgres-prod-verifier**: Alembic head `ebb479b7eed5` matches the new migration's `down_revision`. Zero id collisions with the 46 candidate Ashby ids. `job_listings` composite PK `(source_id, id)` confirmed in prod. Zero pre-existing `source_id='ashby_api'` rows. `companies.enabled` server default `true` confirmed. `procrastinate_jobs` Greenhouse queue clean (2,622 succeeded, no backlog).
- **railway-prod-verifier**: Latest deploy SUCCESS at 2026-05-18T02:37:46Z; ~17h stable. Pool created `min=1, max=15, timeout=5.0s`. No PoolTimeout / OOM / SIGKILL in the last 24h. `DATABASE_URL` + auth env vars set; no Ashby-specific secret needed. `_configure_logging` ERROR → stderr → Railway `@level:error` path confirmed working via existing Microsoft scraper errors.
- **vercel-prod-verifier**: Project `prj_7moC3xZ9H5vKmEkGb0ROXMARzmtT`, latest 3 prod deploys all Ready. No env vars reference Ashby. `vercel.json` rewrite removal cleanly pairs with `api/ashby.ts` deletion. No `functions{}`/`crons`/per-route config references `api/ashby`.

### Deferred (not fixing this pass)

- `sourceAts` → `BackendScraperConfig` structural relocation (Important, plan-locked design).
- `Company.ats` vs `config.type` duplicate discriminant (Important, pre-existing).
- Fallback `record_scrape_run` swallow → synthetic exception (Important; defer to fix both Ashby + Greenhouse together for parity).
- All Suggestion/Nit items not listed in the "FIX this pass" set above.

### Fixes to apply (this pass)

1. Soften UUID-as-fact docstring claim in `ashby_client.py`.
2. Fix incorrect "connection-pool ceilings" reference in `fetch_ashby_company.py` shield comment.
3. Add test for 401 (no Authorization header) on `/trigger-ashby-fetch` and `/trigger-ashby-fan-out`.
4. Add test for race between `enqueue_ashby_fan_out` defer + manual `/trigger-ashby-fetch` (cross-origin queueing-lock dedupe).
5. Add cold-start safety-guard test (`active_count == 0` + 0 jobs returned → no guard trip).
6. Delete 3 dead MSW handlers for `/api/ashby/v1/jobBoard/:boardName/jobs` in `App.test.tsx`, `AppEnabledCompaniesGlobalLoad.test.tsx`, `useCompanyLoader.test.tsx`.
7. Update root `CLAUDE.md:74` Greenhouse example to include `sourceAts: 'greenhouse'`.

### Implementation applied

**Commit:** `dcd01ae` — "Review pass 1: comment fixes, additional tests, dead MSW handler cleanup"

**Files changed:**
- `src/backend/api/services/ashby_client.py` — Fix 1: softened the UUID claim in module docstring + the in-body `_transform_one` comment so the composite PK (not the id format) is the load-bearing uniqueness mechanism.
- `src/backend/api/tasks/fetch_ashby_company.py` — Fix 2: replaced "connection-pool ceilings bound the cumulative leak" with "worker concurrency=5 bounds in-flight leaks" in the `asyncio.shield` rationale comment.
- `src/backend/api/tests/test_jobs_qa_router.py` — Fix 3: added `test_trigger_ashby_fetch_without_auth_returns_401` and `test_trigger_ashby_fan_out_without_auth_returns_401`, each adjacent to its matching `_without_admin_returns_403` test. Fix 4: added `test_trigger_ashby_fetch_after_fan_out_defer_collapses_via_lock` (manual trigger after `enqueue_ashby_fan_out(timestamp=0)` returns `already_enqueued=True`, exactly 1 `procrastinate_jobs` row).
- `src/backend/api/tests/test_fetch_ashby_company.py` — Fix 5: added `test_cold_start_does_not_trip_safety_guard` (active=0 + jobs=[] → `error_count=0`, jobs_seen=0, new_jobs=0, closed_jobs=0).
- `src/frontend/src/__tests__/app/App.test.tsx` — Fix 6: removed dead `http.get('/api/ashby/v1/jobBoard/:boardName/jobs', ...)` MSW handler.
- `src/frontend/src/__tests__/app/AppEnabledCompaniesGlobalLoad.test.tsx` — Fix 6: removed dead Ashby MSW handler.
- `src/frontend/src/__tests__/app/hooks/useCompanyLoader.test.tsx` — Fix 6: removed dead Ashby MSW handler.
- `CLAUDE.md` — Fix 7: updated the "Adding a Company" example to `createBackendScraperCompany(id, name, 'https://boards.greenhouse.io/${id}', { sourceAts: 'greenhouse' })` and added an explicit note that omitting `sourceAts` drops the company into "Custom Web Scrapers".

**Verification:**
- Backend: `cd src/backend && pytest -q` → `384 passed` (380 → 384, +4 new tests: 2x 401 trigger tests, 1x cross-origin race-collapse, 1x cold-start safety-guard).
- Frontend: `npm run type-check` clean. `npm test` → 1424 passed, 3 failed (only the pre-existing `RecentJobsFilters.test.tsx` SpaceX-chip failures; no new failures).
- `grep -rE "/api/ashby" src/frontend/src/__tests__/` → zero matches (Fix 6 verified).

**Do not revert (new in this pass):**
- Soft UUID claim in `ashby_client.py` docstring — do NOT revert to the strong "Ashby raw ids are UUIDs and globally unique across the Ashby Job Board platform" claim. The composite `(source_id, id)` PK is the actual cross-source uniqueness mechanism; the vendor-side UUID guarantee is observed-only, not contractually load-bearing.
- "Worker concurrency=5 bounds in-flight leaks" comment in `fetch_ashby_company.py` shield rationale — do NOT revert to "connection-pool ceilings". The task uses `db.get_connection` (direct psycopg2), not the FastAPI pool; pool ceilings have no relevance to this leak path.
- The `_without_auth_returns_401` tests pop BOTH `require_admin` and `get_current_user` overrides — popping only `require_admin` (mirroring the 403 test) would still hit the conftest's `get_current_user` override and return 200, masking the regression. Do not "simplify" by dropping the second pop.
- Cross-origin race-collapse test invokes `enqueue_ashby_fan_out(timestamp=0)` directly (not via the periodic deferrer) — this is intentional: the periodic deferrer is not what carries the queueing lock, and routing through it would slow the test without exercising additional production logic.

**Manual action required before merge:**
- (none — no Vercel/Railway env vars need touching this pass)

---

---

## 2026-05-17 — Review pass 2


8 agents dispatched in parallel. All returned. Pass-1 fixes verified clean and asserting what they claim.

### Code-review findings (new only)

**Critical:** (none)

**Important:**
- `src/backend/api/tests/test_ashby_client.py:148-151` — Test comment still asserts "Ashby raw IDs are UUID strings, globally unique across the Ashby platform" as fact. Pass-1 softened this exact claim in `ashby_client.py` but missed the parallel test-side comment. The production docstring and its own test now contradict each other. (agent: comment-analyzer) — **FIX this pass.**

**Suggestion / Nit:**
- `src/backend/api/tasks/fetch_greenhouse_company.py:89` — Identical "connection-pool ceilings" comment in the Greenhouse task; pass-1 deferred to "fix both ATSes together" parity follow-up. (agent: code-reviewer) — DEFER (already tracked).
- `src/backend/api/tests/test_fetch_ashby_company.py:293` — Test docstring references `fetch_ashby_company.py:~105` for the active_count guard. Line refs rot. (agent: code-reviewer) — DEFER (Nit).
- `src/backend/api/tests/test_jobs_qa_router.py:518-567` — Cross-origin race test only covers one direction (fan-out then manual). Symmetric branch (manual then fan-out) is covered transitively by `test_already_enqueued_per_company_continues_loop`. (agent: pr-test-analyzer) — DEFER (Suggestion, redundant coverage exists).
- `src/backend/api/tests/test_jobs_qa_router.py:560-567` — Cross-origin race test asserts `args["company_id"]` but not `args["board_token"]`. (agent: pr-test-analyzer) — DEFER (Nit, weak failure mode).
- New 401 tests don't reset `db_conn`/`procrastinate_open` fixtures. Safe by inspection (401 short-circuits before DB access). (agent: pr-test-analyzer) — DEFER (Nit, test-isolation invariant).

### Production-environment findings

- All 3 prod verifiers: **No new findings.** Vercel project healthy (9 most recent prod deploys Ready). Railway deploy unchanged from pass 1 — pass-1 commit was tests + comments only, no Railway redeploy needed. Postgres: zero collisions, alembic head unchanged, schema assumptions still hold.

### Deferred

- Same items as pass 1 plus the new pass-2 Suggestions/Nits listed above.

### Fixes to apply (this pass)

1. Soften the UUID-as-fact claim in `test_ashby_client.py:148-151` to match the source-of-truth `ashby_client.py` docstring softening from pass 1.

### Implementation applied

**Commit:** `05d0725` — "Review pass 2: align test comment with softened UUID claim in ashby_client.py"

**Files changed:**
- `src/backend/api/tests/test_ashby_client.py` — Softened the `test_id_format` comment to mirror the pass-1 production docstring revision in `ashby_client.py`: the composite `(source_id, id)` PK on `job_listings` is the load-bearing uniqueness mechanism; the UUID-shaped id format is observed-stable but not contractually guaranteed.

**Verification:**
- `cd src/backend && pytest api/tests/test_ashby_client.py -v` → 28 passed.
- `cd src/backend && pytest -q` → 384 passed (unchanged from pass 1; comment-only change).

**Do not revert (new in this pass):**
- Softened UUID claim in `test_ashby_client.py` comment — keep in sync with `ashby_client.py` docstring.

**Manual action required before merge:**
- (none)

---

## 2026-05-17 — Review pass 3


8 agents dispatched in parallel. All returned with: **No new findings — ship-ready.**

### Code-review findings (new only)

**Critical:** (none)
**Important:** (none)
**Suggestion / Nit:** (none)

### Production-environment findings

- vercel-prod-verifier: Vercel project still healthy (9 most recent prod deploys Ready). No new findings.
- railway-prod-verifier: Latest deploy `e4f3f32c` SUCCESS ~16.5h stable. Only pre-existing Microsoft scraper errors in logs (out of scope). No new findings.
- postgres-prod-verifier: Alembic head still `ebb479b7eed5`. Zero id collisions for the 46 Ashby candidates. No new findings.

### Deferred

- All items deferred in passes 1 + 2 remain deferred (plan-locked design choices and Ashby+Greenhouse parity follow-ups).

### Fix agent: not dispatched

No Critical or Important findings this pass — fix agent skipped per the skill spec.

---

## Final tally

- Pass 1: 8 Important findings → 7 fixed + 1 deferred. 1 commit: `dcd01ae`.
- Pass 2: 1 Important finding → 1 fixed. 1 commit: `05d0725`.
- Pass 3: 0 new findings. No fix commit.

PR is ship-ready.
