# Move Greenhouse to Backend Cron + Queue

## Context

Greenhouse jobs are currently fetched statelessly from the browser: the frontend hits `boards-api.greenhouse.io` via the `api/greenhouse.ts` Vercel CORS proxy, transforms the response client-side, and never persists anything. This was fine when Greenhouse was the only ATS we had, but it now blocks every downstream improvement that needs **stable, historical job data in our own database** — most immediately the location-normalization pipeline (`~/.claude/plans/silly-nibbling-sky.md`), which assumes jobs exist as rows in `job_listings` so they can be normalized async.

This plan moves Greenhouse fetching to the backend, mirroring the existing Google/Apple/Microsoft pattern but using a real task queue instead of an asyncio loop, because:
- Greenhouse is **JSON-only** — no Playwright, no subprocess, no per-job state machine. The 5-phase incremental algorithm (`scripts/shared/incremental.py`) used by Playwright scrapers is overkill: one HTTP call returns all open jobs.
- We have **~45+ Greenhouse companies** (`src/frontend/src/config/companies.ts:227–`), so fanning out per-company on a queue gives free parallelism + retry isolation. One company's 5xx doesn't block the rest.
- A queue is what location normalization needs anyway — landing it here means that plan only adds a **second task type** on the same infrastructure (`queue=normalize`), not a new system.

The new path runs side-by-side with the existing auto-scraper for Google/Apple/Microsoft; that loop stays untouched for v1.

**Outcome:** Greenhouse jobs land in `job_listings` like any other backend-scraped job. The frontend switches its ~45 Greenhouse company entries from `type: 'greenhouse'` to `type: 'backend-scraper'` and consumes them through the existing `/api/jobs?company=<id>` endpoint. The `api/greenhouse.ts` Vercel proxy is deleted. Future ATS migrations (Lever, Ashby, …) drop into the same queue.

---

## Decisions Locked (from clarifying-question round)

| Decision | Choice |
|---|---|
| Scope | Greenhouse only; Lever/Ashby/Workday/Gem/Eightfold stay frontend-stateless for now. |
| Task granularity | One Procrastinate task per company: `fetch_greenhouse_company(company_id)`. |
| Worker hosting | In-process with FastAPI; `app.run_worker_async(...)` in lifespan alongside existing `auto_scraper_loop`. |
| Cron frequency | Every 30 minutes. |
| Cron mechanism | Procrastinate's built-in `@app.periodic` (no extra Railway service). |
| Overlap policy | `queueing_lock=f"greenhouse:{company_id}"` per task — dedupes if a prior run for the same company is still pending/running. |
| Closed-job detection | Mirror existing pattern: `consecutive_misses` counter, mark `status='CLOSED'` when threshold reached. Reuse helpers in `scripts/shared/database.py`. |
| Fetch approach | In-process `httpx.AsyncClient` call from the task. No subprocess, no `run_scraper.py`. |
| Coexistence | Existing `auto_scraper.py` loop keeps running Google/Apple/Microsoft via Playwright/subprocess. New Procrastinate path handles Greenhouse only. |
| Procrastinate tables | Keep default names in `public` schema (renaming is non-trivial; not worth it). |
| Company list source | New `companies` table in Postgres, seeded by Alembic migration from current frontend config. |
| Frontend cutover | Flip Greenhouse companies in `companies.ts` to `type: 'backend-scraper'`. Delete `api/greenhouse.ts` when last entry migrated. |

---

## Repo Constraints (must follow)

- **Alembic autogenerate only.** Edit `src/backend/api/db_models.py`, run `alembic revision --autogenerate -m "..."`, review. Never hand-write migration files (memory: `feedback_use_alembic_migrations.md`).
- **No full-table rewrites.** Per the 2026-04-18 Postgres volume incident: `ALTER TABLE ADD COLUMN` (nullable, no default backfill), no `USING` clauses, no `NOT NULL` adds that trigger rewrites.
- **Bare table names — no `_{env}` suffix.** HEAD is `115476c`; tables are env-agnostic.
- **Connection style.** `psycopg2.pool.ThreadedConnectionPool` + `RealDictCursor` for FastAPI request paths. Procrastinate brings its own connector (`PsycopgConnector`) over the same `DATABASE_URL`.
- **`apply_alembic_migrations(database_url)` runs on FastAPI startup.** Procrastinate's own schema (its `procrastinate_jobs` etc.) is also applied at startup — see Unit 1.

---

## Architecture

```
┌──────────────────────── Railway: 1 service, 1 container ─────────────────────────┐
│                                                                                  │
│   FastAPI lifespan starts:                                                       │
│     1. apply_alembic_migrations()      ← our schema                              │
│     2. await procrastinate_app.open_async()  ← installs procrastinate schema     │
│     3. asyncio.create_task(auto_scraper_loop())   ← existing (Google/Apple/MS)   │
│     4. asyncio.create_task(                                                      │
│            procrastinate_app.run_worker_async(                                   │
│                queues=["greenhouse_fetch"],                                      │
│                concurrency=5))     ← NEW                                         │
│                                                                                  │
│   Tasks registered on procrastinate_app:                                         │
│     @app.periodic(cron="*/30 * * * *")                                           │
│     @app.task(queue="greenhouse_fetch")                                          │
│     async def enqueue_greenhouse_fan_out(timestamp):                             │
│         # SELECT id, board_token FROM companies                                  │
│         # WHERE ats='greenhouse' AND enabled                                     │
│         for company_id, board_token in companies:                                │
│             await fetch_greenhouse_company.configure(                            │
│                 queueing_lock=f"greenhouse:{company_id}"                         │
│             ).defer_async(company_id=company_id, board_token=board_token)        │
│                                                                                  │
│     @app.task(queue="greenhouse_fetch",                                          │
│               retry=RetryStrategy(max_attempts=5, exponential_wait=2))           │
│     async def fetch_greenhouse_company(company_id, board_token):                 │
│         run_id = insert_scrape_run(...)                                          │
│         jobs = await httpx_get(boards-api.greenhouse.io/.../{board_token}/jobs)  │
│         if len(jobs) < SAFETY_GUARD_RATIO * active_count:                        │
│             mark_run_failed(run_id, "safety_guard"); return                      │
│         upsert_jobs_batch(jobs)                                                  │
│         update_last_seen_at(seen_ids)        # resets consecutive_misses=0       │
│         increment_consecutive_misses(missing_ids)                                │
│         to_close = get_jobs_exceeding_miss_threshold(missing_ids, threshold=2)   │
│         mark_jobs_closed(to_close)                                               │
│         complete_scrape_run(run_id, counts)                                      │
└──────────────────────────────────────────────────────────────────────────────────┘

Frontend cutover: companies.ts entries flip greenhouse → backend-scraper.
Frontend calls `/api/jobs?company=stripe` (etc.) — same endpoint already used for Google/Apple.
The api/greenhouse.ts Vercel proxy is deleted once no entry references type: 'greenhouse'.
```

---

## Race Condition / Deadlock Audit (your specific concern)

Each risk and how it's neutralized:

| Risk | Mitigation |
|---|---|
| Two workers pick the same task | Procrastinate uses `SELECT … FOR UPDATE SKIP LOCKED` on `procrastinate_jobs`. Impossible by design. |
| Cron fires while prior batch still draining | `queueing_lock=f"greenhouse:{company_id}"` per-task. Procrastinate refuses to enqueue a second task with the same lock while one is pending/running. Per-company isolation: one slow company can't block others. |
| Periodic task itself fires twice (e.g. two FastAPI replicas) | Procrastinate's periodic scheduler holds a Postgres advisory lock; only one replica's worker takes a given periodic firing. |
| Concurrent upserts to same `job_listings.id` | `ON CONFLICT (id) DO UPDATE` (already in `upsert_jobs_batch`, line ~220 in `scripts/shared/database.py`). Postgres serializes. |
| Manual trigger races with cron | Both go through `fetch_greenhouse_company.configure(queueing_lock=...).defer_async(...)`. Lock dedupes. |
| Partial fetch (e.g. Greenhouse returns 50 of 5000 jobs) closes everything | `SAFETY_GUARD_RATIO = 0.1` already in `incremental.py` — port the check into the new task. If scraped count < 10% of active, skip close phase, mark run as failed, no destructive writes. |
| Migration startup race (2 replicas booting) | Alembic uses a Postgres advisory lock; second replica's `apply_alembic_migrations()` is a no-op. Procrastinate's `app.open_async()` is also idempotent. |
| Worker dies mid-task | Procrastinate's task state goes back to `todo` after a heartbeat timeout. `RetryStrategy(max_attempts=5)` handles it. Task is idempotent: `upsert_jobs_batch` + `ON CONFLICT` means a re-run sees the same end state. |

No deadlocks possible — there's no multi-row locking ordered differently between tasks. All writes are single-row UPSERT or per-row UPDATE on `job_listings` keyed by `id`.

---

## Schema

New table (additive, bare-named, in `src/backend/api/db_models.py`):

```python
class Company(Base):
    __tablename__ = "companies"
    id            = Column(Text, primary_key=True)          # 'spacex', 'stripe', ...
    display_name  = Column(Text, nullable=False)
    ats           = Column(Text, nullable=False)            # 'greenhouse' (future: 'lever', etc.)
    board_token   = Column(Text, nullable=False)            # often == id, sometimes differs
    enabled       = Column(Boolean, nullable=False, server_default="true")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        Index("ix_companies_ats_enabled", "ats", "enabled"),
    )
```

No new columns on `job_listings` — it already has everything needed (`consecutive_misses`, `status`, `closed_on`, `last_seen_at`).

---

## Units of Work

Eight small, individually mergeable units. Order is load-bearing.

### Unit 1 — Bootstrap Procrastinate

**Status:** DONE

**Why first:** Nothing else works without the queue runtime.

**Changes:**
- Add `procrastinate[psycopg2]` and `httpx` to `src/backend/api/requirements.txt`.
- Create `src/backend/api/tasks/__init__.py` and `src/backend/api/tasks/procrastinate_app.py`:
  - Instantiate `App(connector=PsycopgConnector(conninfo=settings.database_url))`.
  - Single source-of-truth for `app.task(...)` registration.
- Wire into `src/backend/api/main.py` lifespan, after `apply_alembic_migrations`:
  - `await procrastinate_app.open_async()` (installs Procrastinate's own schema idempotently).
  - `asyncio.create_task(procrastinate_app.run_worker_async(queues=["greenhouse_fetch"], concurrency=5))`.
  - On shutdown: cancel the worker task, `await procrastinate_app.close_async()`.
- Add a trivial no-op `@app.task` to verify plumbing.

**Files:**
- `src/backend/api/requirements.txt`
- `src/backend/api/tasks/__init__.py` (new)
- `src/backend/api/tasks/procrastinate_app.py` (new)
- `src/backend/api/main.py` (lifespan additions only — no router changes)
- `src/backend/api/tests/test_procrastinate_bootstrap.py` (new)

**Verification:**
- `pytest src/backend/api/tests/test_procrastinate_bootstrap.py` — defer no-op task, drain via worker, assert completed.
- Manual: start backend, `psql -c "\dt"` shows `procrastinate_jobs`.

---

### Unit 2 — `companies` table + seed migration

**Status:** DONE

**Why second:** The fan-out task needs this row source.

**Changes:**
- Edit `src/backend/api/db_models.py` — add `Company` model exactly as specified above.
- `alembic revision --autogenerate -m "add companies table"` from `src/backend/`.
- Generate a **second** Alembic data migration `seed_greenhouse_companies` that `op.bulk_insert`s the ~45 Greenhouse entries from `src/frontend/src/config/companies.ts`. Manually transcribe (this is the one acceptable hand-write; data migrations are not autogenerable). Each row: `(id, display_name, ats='greenhouse', board_token, enabled=true)`.

**Files:**
- `src/backend/api/db_models.py`
- `src/backend/alembic/versions/<ts>_add_companies_table.py` (autogenerated)
- `src/backend/alembic/versions/<ts>_seed_greenhouse_companies.py` (data migration, hand-written)

**Verification:**
- `alembic upgrade head` then `SELECT count(*) FROM companies WHERE ats='greenhouse';` returns the seeded count.
- New test `src/backend/api/tests/test_migration_companies.py` mirrors `test_migration_features.py` pattern; asserts round-trip `upgrade head` → `downgrade -2` → `upgrade head` is clean.

---

### Unit 3 — Greenhouse fetch helper (pure function)

**Status:** DONE

**Why third:** Isolate the HTTP layer for unit testing without a queue.

**Changes:**
- New module `src/backend/api/services/greenhouse_client.py`:
  - `async def fetch_jobs(board_token: str, http: httpx.AsyncClient) -> list[dict]` — GET `https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`. 30s timeout. Raises on non-200. Returns raw `response["jobs"]`.
  - `def transform_to_job_listings(company_id: str, raw_jobs: list[dict]) -> list[JobListing]` — maps each Greenhouse job to the `scripts/shared/models.JobListing` Pydantic model. Job ID format: `f"greenhouse_{board_token}_{raw['id']}"`. Mirrors what the frontend transformer currently produces, but written for the DB row shape.

**Files:**
- `src/backend/api/services/greenhouse_client.py` (new)
- `src/backend/api/tests/test_greenhouse_client.py` (new — fixtures from real Greenhouse responses, mocked `httpx.AsyncClient`)

**Verification:**
- Unit tests: happy path, empty result, 5xx (raises), malformed response (raises).
- Snapshot test: a captured Greenhouse response → expected `list[JobListing]`.

---

### Unit 4 — `fetch_greenhouse_company` task

**Status:** DONE

**Why fourth:** The actual worker logic. Depends on Units 1, 2, 3.

**Changes:**
- `src/backend/api/tasks/fetch_greenhouse_company.py`:
  ```python
  @app.task(queue="greenhouse_fetch",
            retry=RetryStrategy(max_attempts=5, exponential_wait=2))
  async def fetch_greenhouse_company(company_id: str, board_token: str) -> None:
      run_id = scrape_runs.start(company_id, mode="full")
      try:
          raw_jobs = await fetch_jobs(board_token, http_client)
          jobs = transform_to_job_listings(company_id, raw_jobs)

          active_count = db.count_active_jobs(conn, company_id)
          if active_count > 0 and len(jobs) < SAFETY_GUARD_RATIO * active_count:
              scrape_runs.complete(run_id, error="safety_guard_triggered",
                                   jobs_seen=len(jobs))
              return  # don't touch consecutive_misses or close anything

          seen_ids = {j.id for j in jobs}
          upsert_result = db.upsert_jobs_batch(conn, jobs)  # returns new vs existing
          db.update_last_seen_at(conn, list(seen_ids), now_iso())
          missing = db.get_active_job_ids(conn, company_id) - seen_ids
          db.increment_consecutive_misses(conn, list(missing))
          to_close = db.get_jobs_exceeding_miss_threshold(
              conn, list(missing), threshold=MISSED_RUN_THRESHOLD)
          db.mark_jobs_closed(conn, list(to_close), now_iso())

          scrape_runs.complete(run_id,
              jobs_seen=len(jobs),
              new_jobs=upsert_result.new_count,
              closed_jobs=len(to_close))
      except Exception:
          scrape_runs.complete(run_id, error="exception")
          raise  # let procrastinate retry
  ```
- Reuses **all** existing helpers in `scripts/shared/database.py`:
  - `upsert_jobs_batch` (line 200–269) — already returns new/existing via `xmax = 0`.
  - `update_last_seen_at` (line 307)
  - `increment_consecutive_misses` (line 329)
  - `mark_jobs_closed` (line 352)
  - `get_jobs_exceeding_miss_threshold` (line 380)
  - `MISSED_RUN_THRESHOLD = 2` constant from `scripts/shared/incremental.py`
  - `SAFETY_GUARD_RATIO = 0.1` constant from `scripts/shared/incremental.py`
- May need to add tiny helpers if missing: `count_active_jobs(company)`, `get_active_job_ids(company)`. Mirror existing style.
- Use a single psycopg2 connection per task invocation (Procrastinate gives one via dependency injection, or we acquire from the existing pool). All step writes in one transaction.

**Files:**
- `src/backend/api/tasks/fetch_greenhouse_company.py` (new)
- `scripts/shared/database.py` (additive helpers if needed)
- `src/backend/api/tests/test_fetch_greenhouse_company.py` (new — integration test against real Postgres + mocked `httpx`)

**Verification:**
- Pytest: seed `companies` row + 3 active jobs, mock httpx to return 2 of them + 1 new → assert 1 new insert, 1 missing has `consecutive_misses=1`, 0 closed.
- Re-run same task → `consecutive_misses=2` → `status='CLOSED'`.
- Safety guard: mock httpx returns 0 jobs while 100 are active → no closes, run logged with error.
- Failure: httpx raises 500 → task ends `failed` with retry counter > 0.

---

### Unit 5 — Periodic fan-out task

**Status:** DONE

**Why fifth:** This is what the cron actually does.

**Changes:**
- `src/backend/api/tasks/enqueue_greenhouse_fan_out.py`:
  ```python
  @app.periodic(cron="*/30 * * * *")
  @app.task(queue="greenhouse_fetch")
  async def enqueue_greenhouse_fan_out(timestamp: int) -> int:
      companies = db.list_enabled_companies(conn, ats="greenhouse")
      for c in companies:
          await fetch_greenhouse_company.configure(
              queueing_lock=f"greenhouse:{c.id}"
          ).defer_async(company_id=c.id, board_token=c.board_token)
      return len(companies)
  ```
- Procrastinate's `@app.periodic` requires the task to accept a single `timestamp: int` argument; the body ignores it.
- Add helper `db.list_enabled_companies(conn, ats: str)` to `src/backend/api/services/database.py`.

**Files:**
- `src/backend/api/tasks/enqueue_greenhouse_fan_out.py` (new)
- `src/backend/api/services/database.py` (add helper)
- `src/backend/api/tests/test_enqueue_greenhouse_fan_out.py` (new)

**Verification:**
- Pytest: seed 5 enabled + 1 disabled Greenhouse companies → call task → assert 5 rows added to `procrastinate_jobs` with `queueing_lock` populated, disabled one not enqueued.
- Re-run immediately → 0 new rows enqueued (locks held).
- Manual: `SELECT * FROM procrastinate_periodic_defers` shows the periodic firing schedule.

---

### Unit 6 — Admin trigger endpoints

**Status:** DONE

**Why sixth:** QA + emergency tooling. Mirrors `POST /api/jobs-qa/trigger-scrape` (which currently only handles Playwright scrapers).

**Changes:**
- Extend `src/backend/api/routers/jobs_qa.py`:
  - `POST /api/jobs-qa/trigger-greenhouse-fetch?company_id=stripe` — defers a single `fetch_greenhouse_company` task. 202 response.
  - `POST /api/jobs-qa/trigger-greenhouse-fan-out` — defers the fan-out task. 202 response.
- Both use the same `queueing_lock` semantics — concurrent manual + cron triggers dedupe.
- Auth: match existing `jobs_qa.py` pattern (likely no auth currently; if so, document and leave consistent).

**Files:**
- `src/backend/api/routers/jobs_qa.py` (extend)
- `src/backend/api/tests/test_jobs_qa_router.py` (extend)

**Verification:**
- `curl -X POST http://localhost:8000/api/jobs-qa/trigger-greenhouse-fetch?company_id=stripe` → 202.
- Within ~5s, `SELECT count(*) FROM job_listings WHERE company='stripe';` is non-zero.

---

### Unit 7 — Frontend cutover

**Status:** DONE

**Why seventh:** Once data is flowing into the DB, point the UI at it.

**Changes:**
- `src/frontend/src/config/companies.ts`: for every Greenhouse entry (lines 227–~340, ~45 entries), replace `createGreenhouseCompany(id, name, opts)` with `createBackendScraperCompany(id, name)`. Drop `boardToken` (now in DB).
- Verify `backendScraperTransformer.ts` correctly parses Greenhouse-shaped `details` JSON. Greenhouse jobs have a different `details` schema than Google/Apple. Either:
  - (a) make the transformer field-tolerant (already likely is — it parses optional `experience_level` / `is_remote_eligible`), or
  - (b) write Greenhouse-specific details into the `details` JSONB column in Unit 3's transform so the existing parser sees consistent fields.
  - Option (b) is cleaner; keep the JSONB structurally consistent across sources.
- After all entries are flipped: delete `api/greenhouse.ts` (Vercel function). Update `vercel.json`/`vercel.ts` if it references the route.
- Update `src/frontend/CLAUDE.md` and project root `CLAUDE.md` to reflect that Greenhouse is now backend-served.

**Files:**
- `src/frontend/src/config/companies.ts`
- `src/frontend/src/api/transformers/backendScraperTransformer.ts` (possibly)
- `api/greenhouse.ts` (delete)
- `vercel.json` / `vercel.ts` (cleanup if needed)
- `CLAUDE.md` (update both root and `src/frontend/CLAUDE.md`)

**Verification:**
- `npm run dev:vercel -w src/frontend`, navigate to a Greenhouse company (e.g. Stripe), confirm jobs render.
- `npm run type-check` clean.
- `npm test -w src/frontend` passes.
- Network tab shows requests to `/api/jobs?company=stripe` (not `/api/greenhouse/...`).

---

### Unit 8 — Deploy & verify

**Status:** DONE

**Why last:** Tie everything off in prod.

**Changes:**
- No code changes. Deploy each unit in order (units 1–6 to Railway; unit 7 to Vercel).
- Ensure Railway env vars are unchanged — Procrastinate reuses `DATABASE_URL`.
- Add a brief `docs/implementations/greenhouseBackendMigration/DEPLOY.md` with:
  - Order of merge: 1→8.
  - How to monitor: `SELECT status, count(*) FROM procrastinate_jobs WHERE queue_name='greenhouse_fetch' GROUP BY status;`
  - Rollback: revert the frontend cutover commit (Unit 7) first; backend keeps fetching harmlessly until the next code revert.

**Verification:**
- 30 min after deploy: `SELECT count(*) FROM scrape_runs WHERE company IN (SELECT id FROM companies WHERE ats='greenhouse') AND started_at > now() - interval '1 hour';` shows ~45 rows (one per company).
- 2 hours after deploy: `SELECT count(*) FROM job_listings WHERE company='stripe';` matches what Greenhouse's API reports for Stripe.
- Frontend: no console errors, no failed `/api/greenhouse/*` requests in network tab.
- Railway memory: stays within current ceiling (existing fix bumped pool 8→15; httpx fetches are cheap; no Playwright in this path).

---

## Out of Scope (follow-up plans)

- **Migrating Lever/Ashby/Workday/Gem/Eightfold to backend.** Same pattern; one PR per ATS.
- **Migrating Google/Apple/Microsoft Playwright scrapers to Procrastinate.** They work fine in the asyncio loop today. Worth doing eventually for unified observability.
- **Incremental fetch ("last 3 hours").** User flagged this as a possible future granularity. Greenhouse's API doesn't natively support it; would require a different strategy (e.g. comparing `updated_at`). Defer until the always-fetch-all cost matters.
- **Location normalization.** Separate prior-approved plan (`~/.claude/plans/silly-nibbling-sky.md`). With this plan landed, that plan trivially adds `queue="normalize"` to the same `procrastinate_app`.
- **Per-company observability dashboard.** `procrastinate_jobs` + `scrape_runs` is already queryable; building UI is a future thing.

---

## End-to-End Verification (after all 8 units)

1. Local: `docker compose up -d postgres`; `alembic upgrade head`; `PYTHONPATH=. uvicorn src.backend.api.main:app --reload`.
2. Confirm worker startup logs: `Worker starting on queues: ['greenhouse_fetch']`.
3. `curl -X POST 'http://localhost:8000/api/jobs-qa/trigger-greenhouse-fan-out'` → 202.
4. Wait ~30s; `psql -c "SELECT company, count(*) FROM job_listings WHERE id LIKE 'greenhouse_%' GROUP BY company ORDER BY 2 desc LIMIT 10;"` shows seeded companies.
5. Start frontend: `npm run dev:vercel -w src/frontend`. Open a Greenhouse company page — jobs load from `/api/jobs`.
6. Wait the cron interval (30 min). `SELECT count(*) FROM scrape_runs WHERE started_at > now() - interval '1 hour';` ~= # Greenhouse companies.
7. Simulate a job disappearing: manually drop one from a mock fetch response → after 2 cron cycles, that job's `status='CLOSED'` in DB.
8. `pytest src/backend/` all green, coverage ≥ existing baseline.
9. `npm run type-check && npm test -w src/frontend` clean.

---

## Critical Files Touched

| File | Purpose |
|---|---|
| `src/backend/api/requirements.txt` | Add `procrastinate[psycopg2]`, `httpx` |
| `src/backend/api/db_models.py` | Add `Company` model |
| `src/backend/alembic/versions/<ts>_add_companies_table.py` | Autogen |
| `src/backend/alembic/versions/<ts>_seed_greenhouse_companies.py` | Data migration |
| `src/backend/api/main.py` | Lifespan: open procrastinate app, run worker, close on shutdown |
| `src/backend/api/tasks/procrastinate_app.py` | New — App singleton |
| `src/backend/api/tasks/fetch_greenhouse_company.py` | New — the worker |
| `src/backend/api/tasks/enqueue_greenhouse_fan_out.py` | New — the cron |
| `src/backend/api/services/greenhouse_client.py` | New — HTTP + transform |
| `src/backend/api/services/database.py` | Add `list_enabled_companies` |
| `src/backend/api/routers/jobs_qa.py` | Add manual triggers |
| `scripts/shared/database.py` | Add `count_active_jobs`, `get_active_job_ids` if missing |
| `src/frontend/src/config/companies.ts` | Flip Greenhouse entries to backend-scraper |
| `src/frontend/src/api/transformers/backendScraperTransformer.ts` | Field-tolerant for Greenhouse `details` |
| `api/greenhouse.ts` | Delete |
| `docs/implementations/greenhouseBackendMigration/DEPLOY.md` | New — runbook |

## Existing Utilities Reused

- **Batch upsert + new-vs-existing detection**: `scripts/shared/database.py::upsert_jobs_batch` (line 200–269), `xmax = 0` trick at line 222.
- **Closed-detection helpers**: `update_last_seen_at` (307), `increment_consecutive_misses` (329), `mark_jobs_closed` (352), `get_jobs_exceeding_miss_threshold` (380) — all in `scripts/shared/database.py`.
- **Constants**: `MISSED_RUN_THRESHOLD = 2`, `SAFETY_GUARD_RATIO = 0.1` — `scripts/shared/incremental.py:34, 40`.
- **ScrapeRun bookkeeping**: `scripts/shared/database.py::insert_scrape_run` etc. (line 430+).
- **JobListing model**: `scripts/shared/models.py::JobListing`.
- **Backend `/api/jobs` endpoint**: `src/backend/api/routers/jobs.py:13` — already serves the camelCase shape the frontend's `backendScraperClient` consumes.
- **Migration test pattern**: `src/backend/api/tests/test_migration_features.py`.
- **Connection pool**: `src/backend/api/dependencies.py::get_db`.
- **Settings**: `src/backend/api/config.py::Settings`.
