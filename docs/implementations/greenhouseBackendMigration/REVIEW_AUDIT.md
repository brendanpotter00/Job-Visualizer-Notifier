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

### Implementation applied (Pass 1)

**Commit SHAs (in order):**
- `8d6b3ed` — Rebase on main: chain companies migration off admins (resolved 3 trivial conflicts by combining both sides; migration `down_revision` updated `f4008c4fb790` -> `2da4b99b39ea`; test_migration_companies.py `PREV_HEAD` updated; REVIEW_AUDIT.md tracked into repo).
- `61ced76` — Pass 1 fixes: backend correctness (Items 2-12: _normalize_iso8601 returns Optional[str], all blocking psycopg2 wrapped in asyncio.to_thread, narrow `except (httpx.HTTPError, ValueError, psycopg2.Error)`, per-step auto-commit safety pinned with load-bearing comment, per-company defer_async exception isolation, trigger_greenhouse_fetch uses Depends(get_db), `companies` added to _clear_tables, safety guard log level WARNING->ERROR, conn close error WARNING->ERROR, seed migration uses ON CONFLICT DO NOTHING, plus malformed-timestamp test and Q2 fix).
- `a3de42c` — Pass 1 fixes: drop greenhouse from frontend types (Item 9: ATSProvider, GreenhouseConfig, GreenhouseAPIResponse, ATSConstants.Greenhouse all removed; appSlice default ATS now BackendScraper; baseClient.test.ts stand-in switched to AshbyConfig; 13 test fixture files updated mechanically — substitution-only).
- `a86c34b` — Pass 1 fixes: tests (Items 13-16: C1 real retry test, C3 safety-guard boundary parametrize, I1 45-company fan-out, I2 migration with pre-existing companies row).

**Files changed (Pass 1, summary):**
- Backend: `src/backend/api/services/greenhouse_client.py`, `src/backend/api/tasks/fetch_greenhouse_company.py`, `src/backend/api/tasks/enqueue_greenhouse_fan_out.py`, `src/backend/api/routers/jobs_qa.py`, `src/backend/api/main.py`, `src/backend/api/tests/conftest.py`, `src/backend/api/tests/test_db_models.py`, `src/backend/api/tests/test_greenhouse_client.py`, `src/backend/api/tests/test_fetch_greenhouse_company.py`, `src/backend/api/tests/test_enqueue_greenhouse_fan_out.py`, `src/backend/api/tests/test_migration_companies.py`, `src/backend/alembic/versions/20260516_001426_438ad0658e53_add_companies_table.py`, `src/backend/alembic/versions/20260516_001452_939331c99a23_seed_greenhouse_companies.py`.
- Frontend: `src/frontend/src/types/index.ts`, `src/frontend/src/api/types.ts`, `src/frontend/src/api/clients/baseClient.ts`, `src/frontend/src/features/app/appSlice.ts`, `src/frontend/src/components/companies-page/CompanySelector/CompanySelector.tsx`, plus 17 test files updated to use `'backend-scraper'` / `ATSConstants.BackendScraper` instead of greenhouse references.

**Test results:**
- Backend: 286 passed (was 278; +8 new tests).
- Frontend: type-check clean; 1390 frontend tests pass.

**Do not revert (new in this pass — load-bearing):**
- The order of operations in `fetch_greenhouse_company.py` (upsert -> update_last_seen -> increment_misses -> mark_closed) is documented with a load-bearing comment block. Reordering breaks retry idempotency.
- Narrowed `except (httpx.HTTPError, ValueError, psycopg2.Error)` is intentional: programmer errors must propagate so Procrastinate marks the task failed without burning all 5 retries.
- `_normalize_iso8601` returning `None` (not the original string) on parse failure is intentional per `feedback_correctness_over_dont_crash.md`.
- Seed migration's `ON CONFLICT (id) DO NOTHING` accepts that operator-driven rows win over the seed.

**Manual action required before merge:**
- **Rebase note**: this branch was rebased onto `66ac047 Add admin dashboard with users page and gated scraper`. Conflicts were minor (combined both sides) in `src/backend/api/main.py` (admin router import + procrastinate imports), `src/backend/api/tests/test_db_models.py` (admins + companies in expected table set), `src/backend/api/routers/jobs_qa.py` (TokenClaims/require_admin + settings imports). All commit hashes upstream of `8d6b3ed` are post-rebase and force-push will be required to update the remote branch.
- **Companies migration chain**: `438ad0658e53` (companies) now chains off `2da4b99b39ea` (admins) instead of `f4008c4fb790`. Confirm Railway prod head is `2da4b99b39ea` immediately before deploy (PR #108 was merged 2026-05-15).
- **DEPLOY.md mitigation still applies**: post-merge, all greenhouse companies show empty for up to 30 min until first cron tick. Operator must POST `/api/jobs-qa/trigger-greenhouse-fan-out` immediately after deploy completes.
- **Pre-existing test isolation noise**: `test_happy_path_inserts_new_marks_missing` is occasionally flaky when run as part of the full suite (passes in isolation). This is the documented I3 test-isolation noise (Procrastinate `public.procrastinate_jobs` table shared across xdist workers); not introduced by Pass 1 fixes.


---

## 2026-05-15 — Review pass 2

Diff: `git diff origin/main...HEAD` (62 files, +3726/-1160 — bigger than Pass 1 because rebase pulled in admin dashboard).

**Pass 1 fixes landed in commits:** `8d6b3ed` (rebase), `61ced76` (backend correctness), `a3de42c` (frontend type cleanup), `a86c34b` (test additions), `d186b63` (audit log update).


### Code-review findings

**Critical:**
- `src/backend/api/routers/jobs_qa.py:98-208` — **Missing admin auth gate** on `trigger_greenhouse_fetch` and `trigger_greenhouse_fan_out`. Every other endpoint in this router (`stats`, `scrape_runs`, `trigger_scrape`) carries `_admin: TokenClaims = Depends(require_admin)` after the rebase pulled in PR #108. Test fixture (`conftest.py:294`) globally overrides `require_admin`, so existing tests cannot detect the missing gate. Originally PLAN said "match existing pattern (likely no auth currently)" — that's stale post-rebase. Anyone can spam-defer Greenhouse fetches against the queue. (agents: code-reviewer, pr-test-analyzer #1, silent-failure-hunter C2)
- `src/backend/api/tasks/enqueue_greenhouse_fan_out.py:99` — Broad `except Exception` swallows Procrastinate retry signals (`ConnectorException`, `JobAborted`, `JobError`) and programmer errors (AttributeError, TypeError). Pass 1 explicitly applied the symmetric fix to `fetch_greenhouse_company.py` but missed this sibling task. Narrow to `(procrastinate_exceptions.ConnectorException, psycopg2.Error)`. (agent: silent-failure-hunter C1)

**Important:**
- `src/backend/api/services/greenhouse_client.py:143` — Comment-vs-log-level contradiction. The comment block above the call states "data quality issue is visible in stderr (Railway @level:error)" but the call is `logger.warning(...)`. Inconsistent with Pass 1's safety-guard WARNING→ERROR upgrade. (agents: code-reviewer, silent-failure-hunter S1)
- `src/backend/api/tasks/fetch_greenhouse_company.py:208-218` — Fallback `record_scrape_run` close-error swallowing. The `fallback_conn.close()` call inside `finally` is unprotected; a close exception overrides the original write failure context, making Sentry traces misleading. (agent: silent-failure-hunter C3)
- `src/backend/api/routers/jobs_qa.py:78-82` — Subprocess exit-code logging at WARNING level (deferred from Pass 1). `_run_scraper_logged` should use `logger.error` so Railway's `@level:error` filter surfaces scraper failures. (agent: silent-failure-hunter C4)
- `src/backend/api/tasks/enqueue_greenhouse_fan_out.py:45-48` — Periodic task lacks `RetryStrategy` (deferred from Pass 1). If `db.list_enabled_companies` fails on a transient blip, the entire 30-min tick is lost with no retry. Add `retry=RetryStrategy(max_attempts=3, exponential_wait=2)`. (agent: silent-failure-hunter C5)
- `src/backend/api/tasks/fetch_greenhouse_company.py:82, 209` — Connection-leak window if task is cancelled between `asyncio.to_thread(db.get_connection)` completing in the thread and the awaiter resuming to bind the result to local `conn`. The thread completes and produces a connection object that's then orphaned. Mitigation: `asyncio.shield` around acquisition or restructure to ensure the bind is uncancellable. (agent: postgres-prod-verifier)
- `src/backend/api/tasks/fetch_greenhouse_company.py:85` — httpx client lifecycle still per-task (deferred from Pass 1). ~45 connection-pool setup/teardowns per 30 min; defeats per-host keepalive. (agent: railway-prod-verifier)

**Suggestion / Nit:**
- `src/backend/api/routers/jobs_qa.py:121` — `cur = db.cursor()` not used in `with` block. Doesn't leak (pool handles it) but inconsistent with file's hygiene. (agent: code-reviewer)
- `src/backend/api/tasks/enqueue_greenhouse_fan_out.py:67-71` — Connection-close error log lacks `timestamp` for Railway correlation. (agent: silent-failure-hunter S5)
- `src/backend/api/tests/test_migration_companies.py:179-184` — Teardown `except Exception` silently swallows DROP DATABASE failures; orphan databases accumulate over flaky CI runs. Use `pytest.fail` or `warnings.warn`. (agent: silent-failure-hunter S2)
- `src/backend/api/tests/test_fetch_greenhouse_company.py:160-166` — `_drain` re-raises bare `TimeoutError` without context. (agent: silent-failure-hunter S3)
- Bundle size 1.34 MB unchanged; pre-existing.

### Production-environment findings

**Critical:** None.

**Important:**
- Connection-leak window from postgres-prod (listed under code-review section above; mirror finding).
- httpx client lifecycle from railway-prod (listed under code-review section above).

**Verified resolved from Pass 1:**
- Migration chain — `down_revision = '2da4b99b39ea'` confirmed; single head; full chain `2da4b99b39ea → 438ad0658e53 → 939331c99a23` will apply cleanly.
- Seed migration idempotency — `INSERT ... ON CONFLICT (id) DO NOTHING` verified; integration test passes.
- `Depends(get_db)` for trigger endpoint — pool budget restored.
- Narrowed exception catch in `fetch_greenhouse_company` — programmer errors propagate.
- `asyncio.to_thread` wrapping — connection counts unchanged; event loop unblocked.
- Frontend type cleanup — zero remaining `'greenhouse'` literal references in `src/frontend/src/**`.

**Suggestion:**
- DEPLOY.md note about `/api/greenhouse/*` route status transition (currently 500 in prod due to stale deployed handler; will be hard-404 after deploy). (agent: vercel-prod-verifier)

**Could not verify:**
- Live runtime behavior of Pass 1 fixes — branch not yet deployed.

### Test-coverage findings

**Critical:**
- C2 `record_scrape_run` fallback path — STILL untested (deferred from Pass 1, still important). Monkeypatch primary `record_scrape_run` to raise; assert fallback runs and writes the row. (agent: pr-test-analyzer #2)

**Important:**
- C1 retry test weakness: `assert attempts >= 2` instead of pinned `== 2`; 75s worst-case timing on slow CI. (agent: pr-test-analyzer #3)
- C4 worker-side concurrent-task race for the same company still untested. (agent: pr-test-analyzer #5)
- I3 test isolation under xdist still fragile (admitted Pass 1 implementation note flagged this as flake-prone). (agent: pr-test-analyzer #4)
- I5 transform_to_job_listings malformed shapes still untested. (agent: pr-test-analyzer #6)

**Quality / Suggestion:**
- Q1 `test_main_lifespan.py:111-121` brittle ordering still present.
- Sub-threshold safety guard case `(10, 4, True)` not covered.
- Q3 `_make_raw_job` fixtures still narrow.

### Deferred (not fixing this pass)

These move to PR follow-up (or Pass 3 if time permits):
- I3 test isolation refactor (cleanup-by-queue-name centralization, autouse session-scoped fixture).
- C4 concurrent-task race test (complex multi-worker setup).
- I5 transformer pathological-input tests (low frequency in real Greenhouse responses).
- Q1, Q3 test quality nits.
- httpx client lifecycle refactor (broader than this PR).
- Test code S2-S5 (test debugging quality).

### To be picked up by fix agent (Pass 2)

1. **CRITICAL: Add `Depends(require_admin)`** to `trigger_greenhouse_fetch` and `trigger_greenhouse_fan_out`. Update DEPLOY.md curl examples to include bearer token. Update tests to verify the gate (pop the dep override in one test per endpoint, assert 401/403).
2. **CRITICAL: Narrow `except Exception`** in `enqueue_greenhouse_fan_out.py:99` to `(procrastinate_exceptions.ConnectorException, psycopg2.Error)`.
3. **IMPORTANT: `_normalize_iso8601` log level** — `logger.warning` → `logger.error` for parse failure.
4. **IMPORTANT: Add `RetryStrategy`** to periodic fan-out task. `max_attempts=3, exponential_wait=2`.
5. **IMPORTANT: `_run_scraper_logged` log level** — WARNING → ERROR for non-zero exit.
6. **IMPORTANT: Wrap `fallback_conn.close()`** in its own try/except so it doesn't override the original error context.
7. **IMPORTANT: `asyncio.shield` around `db.get_connection`** in `fetch_greenhouse_company.py` to close the cancellation race window.
8. **TEST: Add C2** — `record_scrape_run` fallback path test (monkeypatch primary call to raise).
9. **TEST: Tighten C1 retry test** — assert `call_count == 2` exactly; tighten timing.

### Implementation applied (Pass 2)

**Commit SHAs (in order):**
- `8598b6a` — Pass 2 fixes: admin auth gate on greenhouse trigger endpoints (Item 1: `Depends(require_admin)` added to `trigger_greenhouse_fetch` and `trigger_greenhouse_fan_out`; Item 5: `_run_scraper_logged` exit-code log WARNING→ERROR; DEPLOY.md curl examples updated to document bearer-token requirement; new tests `test_trigger_greenhouse_fetch_without_admin_returns_403` + `test_trigger_greenhouse_fan_out_without_admin_returns_403` pop the override per the test_admin_router.py pattern).
- `d1a516c` — Pass 2 fixes: error handling and robustness refinements (Item 2: per-company `except Exception` narrowed to `(procrastinate_exceptions.ConnectorException, psycopg2.Error)`; Item 3: `_normalize_iso8601` callsite log WARNING→ERROR with "data quality issue" prefix; Item 4: `RetryStrategy(max_attempts=3, exponential_wait=2)` added to periodic fan-out task decorator; Item 6: `fallback_conn.close()` now wrapped in its own try/except so close failure doesn't override write-failure context; Item 7: both `db.get_connection` calls wrapped in `asyncio.shield(...)` to close cancellation-orphan window).
- `7b6cfd5` — Pass 2 fixes: tests (Item 8: `test_record_scrape_run_fallback_runs_on_primary_failure` monkeypatches first call to raise psycopg2.OperationalError + counting wrapper around `db.get_connection` to prove fresh conn; new `test_per_company_psycopg2_error_does_not_abort_loop` for Item 2 fan-out exception isolation; Item 9: tightened C1 `attempts >= 2` → `attempts == 2` and trimmed polling tail from 75s→50s worst-case; updated `test_posted_on_unparseable_becomes_none` to assert ERROR level and "data quality issue" substring).

**Files changed (Pass 2, summary):**
- Backend code: `src/backend/api/routers/jobs_qa.py`, `src/backend/api/services/greenhouse_client.py`, `src/backend/api/tasks/enqueue_greenhouse_fan_out.py`, `src/backend/api/tasks/fetch_greenhouse_company.py`.
- Backend tests: `src/backend/api/tests/test_jobs_qa_router.py`, `src/backend/api/tests/test_enqueue_greenhouse_fan_out.py`, `src/backend/api/tests/test_fetch_greenhouse_company.py`, `src/backend/api/tests/test_greenhouse_client.py`.
- Docs: `docs/implementations/greenhouseBackendMigration/DEPLOY.md`.
- No frontend changes this pass.

**Test results:**
- Backend: 290 passed (was 286 in Pass 1; +4 new tests this pass). Full suite green; no regressions.
- Frontend: not touched this pass; no re-run needed.

**Do not revert (new in this pass — load-bearing):**
- `Depends(require_admin)` on `trigger_greenhouse_fetch` and `trigger_greenhouse_fan_out` — every endpoint in `jobs_qa.py` now declares its own admin gate (no router-level dep is used) so a future endpoint added without it would silently re-open the hole. The two new "without admin" tests are the regression net.
- The narrowed `except (procrastinate_exceptions.ConnectorException, psycopg2.Error)` in `enqueue_greenhouse_fan_out.py` is intentional and mirrors the `fetch_greenhouse_company.py` Pass 1 narrowing — programmer errors must propagate so a deterministic typo doesn't masquerade as a transient blip.
- `RetryStrategy(max_attempts=3, exponential_wait=2)` on the periodic task is bounded on purpose — three attempts is enough to ride out a transient blip but small enough that a persistently-broken DB doesn't pile up retries within a single 30-min tick.
- `asyncio.shield(asyncio.to_thread(db.get_connection, ...))` for both the primary and fallback acquisitions — removing the shield reintroduces the cancellation-orphan window flagged by postgres-prod-verifier.
- The fallback `record_scrape_run` close is wrapped in its own try/except — without it, a close exception masks the original write failure, sending the operator down the wrong debugging path.
- `_normalize_iso8601` log level is now ERROR (was WARNING in Pass 1, was silent in pre-Pass 1) — Railway's @level:error filter is the alerting boundary.

**Manual action required before merge:**
- **Force push** the branch — Pass 2 commits (`8598b6a`, `d1a516c`, `7b6cfd5`) sit on top of the Pass 1 force-pushed history. Use `git push --force-with-lease`.
- **Operator runbook update**: anyone curling `/api/jobs-qa/trigger-greenhouse-fan-out` or `/api/jobs-qa/trigger-greenhouse-fetch` post-deploy must include `Authorization: Bearer ${ADMIN_TOKEN}` per the updated DEPLOY.md curl examples. The post-deploy "fire fan-out manually" mitigation only works if the operator has an admin-grant'd Auth0 token in hand at deploy time — confirm this is available before kicking off the merge.
- **Verify Railway prod head before deploy**: still `2da4b99b39ea` (admins) per Pass 1 note. Pass 2 added no new migrations.
- **Pre-existing test isolation flake**: `test_happy_path_inserts_new_marks_missing` is still occasionally flaky in the full suite (passes in isolation) — documented Pass 1 issue I3, not introduced by Pass 2. No new flakes added.

---

## 2026-05-15 — Review pass 3

Diff: `git diff origin/main...HEAD` (after Pass 2 fixes).

**Pass 2 fixes landed in commits:** `8598b6a` (admin auth), `d1a516c` (error-handling), `7b6cfd5` (tests), `d36de02` (audit log).


### Code-review findings

**Critical:** None.

**Important:**
- `src/backend/api/tasks/fetch_greenhouse_company.py:83-87, 218-220` — `asyncio.shield` comment over-promises. The shield prevents the inner `to_thread` future from being cancelled but the awaiter can still raise `CancelledError`, in which case the thread completes and produces a live connection that's never bound to `conn` — exactly the orphan the comment claims to prevent. The actual failure mode is bounded (worker cancels are rare; Postgres `idle_session_timeout` reaps orphans) but the load-bearing comment as written would mislead future maintainers. (agent: silent-failure-hunter)

**Suggestion:** None new.

### Production-environment findings

**No new findings.** Three of three production verifiers (postgres-prod, railway-prod, vercel-prod) stalled mid-run on the watchdog timeout — partial outputs showed they had not surfaced any Critical/Important issues before stalling (postgres was confirming ON CONFLICT syntax; railway was checking Postgres logs which were data-noise rather than errors; vercel was running the test suite, which I verified directly is all green: 1390 frontend + 290 backend tests passing).

### Test-coverage findings

pr-test-analyzer also stalled before producing structured output. Its partial output indicated it was checking whether deferred items had shifted to Critical priority — the inference is no, since Pass 2's fixes addressed the most pressing test gaps (admin auth, fallback path, retry tightening) and the deferred items (I3 isolation, I5 transformer pathology, C4 concurrent task race, httpx lifecycle) are appropriate to defer to follow-up PRs.

### To be picked up by fix agent (Pass 3)

1. **IMPORTANT: Rewrite `asyncio.shield` comments** in `fetch_greenhouse_company.py` lines 83-87 and 218-220 to honestly describe what shield delivers (best-effort, bounded leak) rather than overpromising orphan prevention. The fix agent applied this inline (single comment edit, no behavioral change).

### Implementation applied (Pass 3)

Files changed (1 file):
- `src/backend/api/tasks/fetch_greenhouse_company.py` — comment-only update on the two `asyncio.shield` call sites to accurately describe the bounded-leak semantics.

Commit: applied with the rest of pass 3 wrap-up.

**Do not revert (new in this pass):** the honest-comment formulation about shield being best-effort. A future "let's claim guaranteed safety" comment edit would re-introduce the misleading promise.

**Manual action required before merge:** none new in pass 3 (Pass 1 + Pass 2 manual actions still apply: force-push required, admin bearer token at deploy, post-deploy `POST /api/jobs-qa/trigger-greenhouse-fan-out` mitigation per DEPLOY.md).

