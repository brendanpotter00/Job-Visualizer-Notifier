# Greenhouse Backend Migration PR Review Audit Log

**Purpose:** Running log of review findings and fixes on this PR. Read this before proposing changes — decisions here may override the original PLAN. Update when you apply a fix so the next reviewer has context.

**Branch:** `feat/greenhouse-backend-cron-queue`
**Base:** `main`
**Diff scope:** `git diff origin/main...HEAD`

---

## 2026-05-15 — Review pass 1

Diff: `git diff origin/main...HEAD` (39 files, +3032/-951). 6 agents dispatched in parallel: code-reviewer, silent-failure-hunter, pr-test-analyzer, postgres-prod-verifier, railway-prod-verifier, vercel-prod-verifier.

### Code-review findings

**Critical:**
- `src/backend/api/tasks/fetch_greenhouse_company.py:99-118` — Per-step auto-commit breaks task atomicity. Helpers (`upsert_jobs_batch`, `update_last_seen`, `increment_consecutive_misses`, `mark_jobs_closed`) each commit internally. If `mark_jobs_closed` fails after upsert + miss-increment already committed, retry will re-increment misses on already-incremented rows → eventually mis-close. (agent: code-reviewer)
- `src/backend/api/tasks/fetch_greenhouse_company.py:76-118` — Sync DB calls inside async task block the FastAPI event loop. Worker shares the FastAPI event loop; concurrency=5 sync helpers can freeze `/api/jobs` etc. for 100ms+ on a Stripe-sized board. Wrap in `asyncio.to_thread`. (agent: code-reviewer)
- `src/backend/api/services/greenhouse_client.py:175-187` — `_normalize_iso8601` silently passes through malformed timestamp on parse failure. Violates `feedback_correctness_over_dont_crash.md`. Either raise (let retry handle it) or set `posted_on=None`. (agents: silent-failure-hunter #6, code-reviewer)
- `src/backend/api/tasks/fetch_greenhouse_company.py:125` — Broad `except Exception` swallows programmer errors (AttributeError, TypeError, NameError). All 5 retries fire on a deterministic typo. Narrow to `(httpx.HTTPError, ValueError, psycopg2.Error)`. (agent: silent-failure-hunter #1)

**Important:**
- `src/backend/api/tasks/fetch_greenhouse_company.py:86-94` — Safety guard logs WARNING when it triggers. Persistent guard trips will repeat invisibly every 30 min. Use `logger.error` so Railway routes to stderr; consider sentinel `error_count` value. (agent: silent-failure-hunter #2)
- `src/backend/api/tasks/enqueue_greenhouse_fan_out.py:75-88` — Per-company `defer_async` only catches `AlreadyEnqueued`. Any other exception (e.g. transient connector blip) aborts the whole loop, leaving alphabetically-later companies unprocessed for the entire 30-min window. Catch broader, log per-company, continue. (agent: silent-failure-hunter #3)
- `src/backend/api/routers/jobs_qa.py:115-131` — `trigger_greenhouse_fetch` opens a fresh psycopg2 connection per request, bypassing the bounded `ThreadedConnectionPool`. Under concurrent QA spam can exceed prod `max_connections`. Use `Depends(get_db)`. (agents: silent-failure-hunter #4, code-reviewer)
- `src/backend/api/tasks/enqueue_greenhouse_fan_out.py:55-62` — Same async/sync mismatch — periodic task acquires sync connection, blocks event loop. Move under `asyncio.to_thread`. (agent: code-reviewer)
- `src/backend/api/tests/conftest.py:223-234` — Autouse `_clear_tables` doesn't include `companies`. Two test files work around this manually; future tests will inherit stale rows. Add `companies` to TRUNCATE. (agent: code-reviewer)
- `src/frontend/src/types/index.ts:108-116, 225` + `src/frontend/src/api/types.ts:41, 303` — Dead `GreenhouseConfig` / `GreenhouseAPIResponse` types still exported and in `Company.config` union; `'greenhouse'` still in `ATSProvider`. A typo creating `type: 'greenhouse'` would type-check but throw at runtime. (agent: code-reviewer)
- `src/backend/api/tasks/fetch_greenhouse_company.py:165-168` — Connection close error logged at WARNING. Leaked psycopg2 connections (direct, not pooled) won't show in pool metrics. Use ERROR. (agent: silent-failure-hunter #5)

**Suggestion / Nit:**
- `src/backend/api/tasks/procrastinate_app.py:35-55` — `ensure_schema_async` race window between probe and apply (negligible today, single-replica Railway). (agent: code-reviewer)
- `src/backend/api/tasks/fetch_greenhouse_company.py:79-80` — `httpx.AsyncClient` instantiated per-task. PLAN doc-string mentions long-lived shared client preferred. (agents: code-reviewer, railway-prod-verifier)
- `src/backend/api/tasks/fetch_greenhouse_company.py:96-119` — `pre_upsert_active` / `post_upsert_active` queries duplicate work. Could use `xmax = 0` from upsert. (agent: code-reviewer)
- `src/backend/alembic/versions/...seed_greenhouse_companies.py:91` — Seed migration uses `op.bulk_insert` with no idempotency guard. PK conflict if rows backfilled out-of-band. Use `INSERT ... ON CONFLICT (id) DO NOTHING`. (agent: code-reviewer)
- `src/backend/api/tasks/fetch_greenhouse_company.py:34` — `Set` import; project uses lowercase `set`. (agent: code-reviewer)
- `src/backend/api/main.py:16-17` — Duplicate import of procrastinate_app via package re-export + submodule (name-shadow trap). (agent: code-reviewer)
- Other smaller items from silent-failure-hunter #7-11.

### Production-environment findings

**Critical:**
- **`src/backend/alembic/versions/...add_companies_table.py:16` — Migration chain BROKEN against current prod head.** Prod is at `2da4b99b39ea` (PR #108 / commit `66ac047 Add admin dashboard`, merged after our branch diverged from `f4008c4fb790`). Our migration's `down_revision = 'f4008c4fb790'` will create dual heads on merge. Must rebase the branch on `origin/main` and fix `down_revision` to `2da4b99b39ea` (or regenerate after rebase). (agent: postgres-prod-verifier)
- **Backend has zero Greenhouse rows in prod right now.** Confirmed via `curl /api/jobs?company={stripe,anthropic,figma,airbnb,robinhood}` → all `200 []`. After merge, all ~45 Greenhouse companies render empty until first cron tick (up to 30 min). DEPLOY.md already documents the manual `POST /api/jobs-qa/trigger-greenhouse-fan-out` mitigation; ensure the runbook is followed. (agent: vercel-prod-verifier)

**Important:**
- Connection accounting under fan-out load — peak ~30 simultaneous connections per Railway service (15 request pool + 6 worker fresh + ~10 Procrastinate connector). Fits Railway default `max_connections=100` with margin but breaks the documented `db_pool_max=15` budget. Future location-normalization PR doubles this. (agent: railway-prod-verifier)
- Branch is missing `66ac047 Add admin dashboard` from main. No merge conflict expected (different files), but rebase before final review so CI exercises the post-merge tree. (agent: vercel-prod-verifier)
- **Hand-written seed migration** acknowledged by file docstring as "the documented exception" — should get explicit user sign-off given the standing rule. (agent: postgres-prod-verifier; user-acknowledged in PLAN.md)

**Suggestion:**
- `scrape_runs.started_at` / `completed_at` are `text` (ISO-8601 strings). Lexicographic ordering works only because ISO-8601 sorts lexicographically. Future non-ISO insert breaks ordering silently. (agent: postgres-prod-verifier)
- Could not verify Railway Postgres app user has CREATE privileges in `public` (audit role read-only). High-probability yes since DB owner. (agent: postgres-prod-verifier)
- Frontend dead-code cleanup: `baseClient.ts:157,207`, `types/index.ts:111` still reference `'greenhouse'` literal. (agent: vercel-prod-verifier; same as code-reviewer item)

**Could not verify:**
- vercel-prod-verifier — baseline error rate on `/api/jobs`, `/api/jobs-qa`, `/api/users`, `/api/features` (no inbound traffic during audit window).
- postgres-prod-verifier — actual app-user grants in `public` schema.

### Test-coverage findings

**Critical:**
- C1: No real retry test exercising attempt > 1. The only failure test only checks `attempts >= 1` with status in `("todo", "failed", "doing")` — would pass even with `@retry` removed entirely. Add: handler returns 503 then 200, drain twice, assert success. (agent: pr-test-analyzer)
- C2: `record_scrape_run` fallback path (line 145-163) untested. The defensive code that opens a fresh connection on poisoned-conn failure has zero coverage. (agent: pr-test-analyzer)
- C3: SAFETY_GUARD threshold boundary not pinned (only extreme 0/100 case tested). Ratio change or `<` → `<=` change wouldn't be caught. (agent: pr-test-analyzer)
- C4: Concurrent-task race for the same company not tested at the worker-side lock level (only enqueue-side `AlreadyEnqueued` tested). (agent: pr-test-analyzer)

**Important:**
- I1: Fan-out tested with 5 companies, never 45. (agent: pr-test-analyzer)
- I2: Migration test doesn't cover the "rows already exist in companies" case. Downgrade `DELETE WHERE ats='greenhouse'` regression to `TRUNCATE` would silently nuke unrelated rows. (agent: pr-test-analyzer)
- I3: Test isolation workaround fragile — Procrastinate tables in `public` schema, manual cleanup not scoped by xdist worker. (agent: pr-test-analyzer)
- I4: Frontend MSW shape unverified against backend runtime serializer. (agent: pr-test-analyzer)
- I5: `transform_to_job_listings` doesn't test malformed offices/departments shapes. (agent: pr-test-analyzer)

**Quality issues:**
- Q1: `test_main_lifespan.py:111-119` enforces `scraper < worker` start order — they're concurrent `create_task`s; brittle. (agent: pr-test-analyzer)
- Q2: `test_id_format_uses_board_token` uses identical company_id and board_token — defeats the test. (agent: pr-test-analyzer)
- Q3: `_make_raw_job` fixtures don't represent real Greenhouse diversity. (agent: pr-test-analyzer)

### Deferred (not fixing this pass)

These will be revisited in pass 2 if not addressed:
- Code-reviewer Suggestions/Nits beyond the high-impact ones (httpx client lifecycle, query dedup, import cleanup, `Set` → `set`).
- Silent-failure-hunter items #7-11 (subprocess exit-code logging, periodic task retry, fallback bookkeeping logging, BaseException type annotation, helper extraction).
- Test-coverage I4, I5, S1-S5, Q1-Q3 (will reassess after pass 2 picks up Critical fixes).
- Bundle-size warning (1.32 MB pre-existing, not introduced by this PR).

### To be picked up by fix agent (Pass 1)

Fixing in this pass:
1. **CRITICAL: Rebase branch on `origin/main`** — fix migration `down_revision` from `f4008c4fb790` → `2da4b99b39ea`.
2. **CRITICAL: Fix `_normalize_iso8601`** — set `posted_on=None` on parse failure (correctness over don't-crash).
3. **CRITICAL: Wrap blocking DB helpers in `asyncio.to_thread`** in `fetch_greenhouse_company.py` and `enqueue_greenhouse_fan_out.py`.
4. **CRITICAL: Address per-step auto-commit non-idempotency** — at minimum, document why retries remain safe; ideally restructure miss/close ordering.
5. **CRITICAL: Narrow broad `except Exception`** in `fetch_greenhouse_company.py` to expected exception types.
6. **IMPORTANT: Use `Depends(get_db)`** in `trigger_greenhouse_fetch` instead of fresh connection.
7. **IMPORTANT: Catch broader exceptions per-company** in `enqueue_greenhouse_fan_out` so one bad defer doesn't poison the rest.
8. **IMPORTANT: Add `companies` to `_clear_tables`** in conftest.
9. **IMPORTANT: Drop `'greenhouse'`/`GreenhouseConfig`/`GreenhouseAPIResponse`** from frontend types — full deprecation.
10. **IMPORTANT: Use `INSERT ... ON CONFLICT DO NOTHING`** in seed migration for idempotency.
11. **IMPORTANT: Safety guard log level** — `logger.warning` → `logger.error`.
12. **IMPORTANT: Connection close error logging** — WARNING → ERROR.
13. **TEST: Add C1 (real retry test)** — handler returns 503 then 200, assert success on retry.
14. **TEST: Add C3 (boundary tests for safety guard)**.
15. **TEST: Add I1 (45-company fan-out test)**.
16. **TEST: Add I2 (migration test with pre-existing companies row)**.
17. **TEST: Fix Q2 (test_id_format_uses_board_token uses distinct values)**.


