# Move Ashby to Backend Cron + Queue

## Context

Ashby is currently fetched statelessly from the browser: the frontend calls `api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` through the `api/ashby.ts` Vercel CORS proxy, runs `ashbyTransformer.ts` client-side, and never persists anything. This is the same shape Greenhouse had before commit `92bfdf6` ("Move Greenhouse to Backend Cron + Queue") moved it to a Procrastinate-backed backend pipeline. The Greenhouse migration produced two follow-up commits — `e57693f` (batched `/api/jobs` for Recent Jobs page) and `168701a` ("Split Greenhouse out of Why page custom scrapers column"). We bake the Why-page split into this PR so we don't have to ship a follow-up cosmetic PR for Ashby.

The Greenhouse migration is now the canonical pattern for JSON-only ATS providers:

- Per-company Procrastinate task with retries and queueing locks
- 30-minute periodic fan-out driven by Procrastinate's built-in `@app.periodic` cron
- Existing `companies` table holds `(id, display_name, ats, board_token, enabled)` — Ashby just adds 47 more rows
- Existing `job_listings` composite PK `(source_id, id)` already supports multi-source coexistence
- Frontend cutover flips Ashby entries from `createAshbyCompany(...)` to `createBackendScraperCompany(...)` and reads them through `/api/jobs?company=<id>` (already serving Greenhouse + Google/Apple/Microsoft)

**Outcome:** Ashby jobs land in `job_listings` with `source_id = 'ashby_api'`. The 47 Ashby entries in `companies.ts` are flipped to `backend-scraper` carrying a new `sourceAts: 'ashby'` marker. The Why page renders Ashby in its own column (not "Custom Web Scrapers"). The Greenhouse entries are retro-fitted to use `sourceAts: 'greenhouse'`, ending the two-mechanism inconsistency in `atsGrouping.ts`. `api/ashby.ts`, `ashbyClient.ts`, `ashbyTransformer.ts`, their tests, and all references to `'ashby'` / `AshbyConfig` in the frontend client-selection logic are removed.

---

## Decisions Locked

| Decision | Choice |
|---|---|
| Scope | Ashby only. Lever/Workday/Gem/Eightfold stay frontend-stateless. |
| Source ID | `"ashby_api"` (added to `SourceId` in `scripts/shared/constants.py`). |
| Procrastinate queue | New queue `"ashby_fetch"` (separate from `"greenhouse_fetch"`). |
| Worker hosting | In-process; expand `main.py` worker to `queues=["greenhouse_fetch", "ashby_fetch"]`, concurrency stays at **5**. |
| Cron frequency | `*/30 * * * *` (matches Greenhouse, no stagger). |
| Overlap policy | `queueing_lock=f"ashby:{company_id}"` per per-company task. |
| ID format | Raw Ashby UUID as string (`str(raw["id"])`) — no prefixing. Composite PK on `(source_id, id)` handles cross-source uniqueness. |
| `details` JSONB shape | Greenhouse-style keys where they overlap, Ashby-specific where unique. Keys: `experience_level: None` (Ashby doesn't expose), `is_remote_eligible: bool(raw.isRemote)`, `employment_type`, `department`, `team`, `secondary_locations`, `compensation_summary` (from `raw.compensation.compensationTierSummary`), `description_html`, `published_at`. |
| `posted_on` source | `raw.publishedAt` only (no fallback). Parsed by the same `_normalize_iso8601` helper Greenhouse uses (duplicate it; ~10 lines). |
| Seed migration | Hand-written Alembic data migration `seed_ashby_companies.py` (one acceptable hand-write — data migrations are not autogenerable). 47 rows `(id, display_name, ats='ashby', board_token=<jobBoardName>, enabled=true)`. |
| Frontend cutover | Each `createAshbyCompany(id, name, opts)` → `createBackendScraperCompany(id, name, jobsUrl, { ..., sourceAts: 'ashby' })`. Default `jobsUrl` for Ashby was `https://careers.ashbyhq.com/${jobBoardName}` — preserve per company. Custom URLs (cursor → `https://cursor.com/careers`, saronic → `https://jobs.ashbyhq.com/saronic`, plaid → `https://jobs.ashbyhq.com/plaid`) preserved verbatim. |
| Ashby grouping on Why page | Add optional `sourceAts?: 'ashby' \| 'greenhouse'` to the `Company` type. `getATSGroupKey` checks `sourceAts` first. Cursor stays on `cursor.com/careers` — Why-page grouping no longer depends on URL prefix for Ashby. |
| Greenhouse Why-page retrofit | After the Ashby split, retrofit the 45 existing Greenhouse entries to set `sourceAts: 'greenhouse'`. Remove `GREENHOUSE_BOARD_URL_PREFIX` detection from `atsGrouping.ts` — end the two-mechanism state. |
| Vercel proxy deletion | Delete `api/ashby.ts` + its test file at the end of the frontend cutover unit. Once all 47 Ashby entries are backend-scraper, the proxy is dead code. |
| Frontend dead-code deletion | Delete `ashbyClient.ts`, `ashbyTransformer.ts`, their test files. Remove `AshbyConfig`/`AshbyJobResponse`/`AshbyAPIResponse` from `types/index.ts` and `api/types.ts`. Remove `'ashby'` from `ATSProvider` and from `ATSCompanyConfig` unions in `baseClient.ts`. If `appSlice.ts` defaults `selectedATS` to `Ashby`, change to `BackendScraper`. |
| QAPage UI | Match what Greenhouse has. The implementation agent inspects QAPage during Unit 6 and adds Ashby trigger UI iff Greenhouse has its own. |
| `rewriteCursorJobUrls` utility | If Ashby was the only caller (grep `src/frontend/src/` during Unit 7), delete `cursorJobUrl.ts` and its tests. Otherwise leave. |
| Deploy gap mitigation | One PR (Units 1–10). DEPLOY.md instructs the operator to hit `POST /api/jobs-qa/trigger-ashby-fan-out` immediately after Railway finishes deploying Units 1–6 so the first batch lands within ~30s instead of waiting up to 30 min for the cron. |
| Feature directory slug | `ashbyBackendMigration` (matches `greenhouseBackendMigration` sibling). |
| Default ATS in appSlice | Inspect during Unit 7. If Ashby was the default, change to `BackendScraper`. |

---

## Repo Constraints (must follow)

- **Alembic autogenerate only.** Edit `src/backend/api/db_models.py` → `alembic revision --autogenerate` → review. Never hand-write migration files. Exception: data migrations (the seed in Unit 2). Memory: `feedback_use_alembic_migrations.md`.
- **No full-table rewrites.** This plan doesn't add columns to `job_listings` or `companies`. Only INSERTs.
- **Bare table names.** `companies` and `job_listings` are env-agnostic.
- **Correctness over "don't crash"**: narrow exception handling in tasks (catch only `httpx.HTTPError`, `ValueError`, `psycopg2.Error`); programmer errors propagate. Memory: `feedback_correctness_over_dont_crash.md`.
- **Stay inside owned files per unit.** Each unit's "Owned files" / "Shared-file edits" lists are the boundary. Touching unlisted files is a stop-and-ask trigger.

---

## Architecture

```
┌──────────────────────── Railway: 1 service, 1 container ─────────────────────────┐
│                                                                                  │
│   FastAPI lifespan (Unit 5 expands worker queue list):                           │
│     1. apply_alembic_migrations()                                                │
│     2. await procrastinate_app.open_async()                                      │
│     3. await ensure_schema_async(procrastinate_app)                              │
│     4. asyncio.create_task(auto_scraper_loop())   ← Google/Apple/MS, untouched   │
│     5. asyncio.create_task(                                                      │
│            procrastinate_app.run_worker_async(                                   │
│                queues=["greenhouse_fetch", "ashby_fetch"],  ← UPDATE in Unit 5   │
│                concurrency=5))                                                   │
│                                                                                  │
│   New tasks (import-side-effect registered on procrastinate_app):                │
│     @app.periodic(cron="*/30 * * * *", periodic_id="ashby_fan_out")              │
│     @app.task(queue="ashby_fetch", retry=RetryStrategy(3, 2))                    │
│     async def enqueue_ashby_fan_out(timestamp: int) -> int:                      │
│         companies = db.list_enabled_companies(conn, "ashby")                     │
│         for c in companies:                                                      │
│             await fetch_ashby_company.configure(                                 │
│                 queueing_lock=f"ashby:{c['id']}"                                 │
│             ).defer_async(company_id=c['id'], board_token=c['board_token'])      │
│                                                                                  │
│     @app.task(queue="ashby_fetch", retry=RetryStrategy(5, 2))                    │
│     async def fetch_ashby_company(company_id, board_token):                      │
│         # Identical 5-phase shape to fetch_greenhouse_company:                   │
│         # to_thread(get_connection) → fetch_jobs → transform → safety_guard      │
│         # → upsert → update_last_seen → increment_consecutive_misses             │
│         # → mark_jobs_closed → record_scrape_run                                 │
└──────────────────────────────────────────────────────────────────────────────────┘

Frontend cutover (Unit 7): companies.ts entries flip ashby → backend-scraper, each carrying sourceAts: 'ashby'.
Frontend calls `/api/jobs?company=notion` — same endpoint already used for Greenhouse + Google/Apple/Microsoft.
api/ashby.ts is deleted in Unit 7.

Why page split (Unit 8): adds sourceAts to Company type, updates atsGrouping.getATSGroupKey to prefer sourceAts.
Greenhouse retrofit (Unit 9): existing 45 Greenhouse entries gain sourceAts: 'greenhouse'; URL-prefix detection in atsGrouping.ts is removed.
```

---

## Race Condition / Deadlock Audit

Each risk and how it's neutralized:

| Risk | Mitigation |
|---|---|
| Two workers pick the same task | Procrastinate uses `SELECT … FOR UPDATE SKIP LOCKED` on `procrastinate_jobs`. Impossible by design. |
| Cron fires while prior batch still draining | `queueing_lock=f"ashby:{company_id}"` per-task. Procrastinate refuses to enqueue a second task with the same lock while one is pending/running. Per-company isolation: one slow company can't block others. |
| Periodic task itself fires twice (e.g. two FastAPI replicas) | Procrastinate's periodic scheduler holds a Postgres advisory lock; only one replica's worker takes a given periodic firing. |
| Concurrent upserts to same `job_listings (source_id, id)` | `ON CONFLICT (source_id, id) DO UPDATE` in `upsert_jobs_batch`. Postgres serializes. Composite PK keeps Ashby and Greenhouse from colliding even if raw IDs ever overlap. |
| Manual trigger races with cron | Both go through `fetch_ashby_company.configure(queueing_lock=...).defer_async(...)`. Lock dedupes. |
| Partial fetch (e.g. Ashby returns 5 of 500 jobs) closes everything | `SAFETY_GUARD_RATIO = 0.1` in `incremental.py` — port the check into the new task. If scraped count < 10% of active, skip close phase, mark run as failed, no destructive writes. |
| Migration startup race (2 replicas booting) | Alembic uses a Postgres advisory lock; second replica's `apply_alembic_migrations()` is a no-op. Procrastinate's `app.open_async()` is also idempotent. |
| Worker dies mid-task | Procrastinate's task state goes back to `todo` after a heartbeat timeout. `RetryStrategy(max_attempts=5)` handles it. Task is idempotent: `upsert_jobs_batch` + `ON CONFLICT` means a re-run sees the same end state. |
| Two ATS fan-outs fire at the same `*/30 * * * *` tick → both ATSes pile ~92 jobs onto 5 worker slots | Worker concurrency=5 + per-company `queueing_lock` means up to 5 companies fetch in parallel, the rest queue. Each per-company task is fast (~1s of HTTP + ~200ms of DB writes). Empirically drains in ~1 minute. No deadlock: every task acquires the same connection-pool resource without inter-task lock ordering. |

No deadlocks possible — there's no multi-row locking ordered differently between tasks. All writes are single-row UPSERT or per-row UPDATE on `job_listings` keyed by `(source_id, id)`.

---

## Schema (no DDL changes)

The `companies` table from the Greenhouse migration already supports Ashby — `ats` is a free-form `Text` column. The only schema-touching migration in this plan is the data-migration seed of the 47 Ashby company rows.

`job_listings` is unchanged: composite PK `(source_id, id)`, `consecutive_misses`, `status`, `closed_on`, `last_seen_at` all exist. The `details` JSONB column accepts arbitrary shape.

---

## Shared Contracts

The following contracts are frozen for the duration of this plan. Every Unit reads them; no Unit changes them without first changing this section.

**HTTP — Ashby Job Board fetch**

```
GET https://api.ashbyhq.com/posting-api/job-board/{board_token}?includeCompensation=true
Timeout: 30s
Response: { "jobs": list[dict], ... }
```

`fetch_jobs(board_token, http)` raises `httpx.HTTPStatusError` on non-2xx and `ValueError` on missing/non-list `"jobs"` key.

**`details` JSONB shape (written by `transform_to_job_listings`, consumed by `backendScraperTransformer.ts`)**

```python
{
    "department": raw.get("department"),
    "team": raw.get("team"),
    "secondary_locations": [s.get("location") for s in raw.get("secondaryLocations", []) if isinstance(s, dict)],
    "employment_type": raw.get("employmentType"),
    "is_remote_eligible": bool(raw.get("isRemote")),
    "compensation_summary": (raw.get("compensation") or {}).get("compensationTierSummary"),
    "published_at": raw.get("publishedAt"),
    "description_html": raw.get("descriptionHtml"),
    "experience_level": None,
}
```

**`JobListing` row shape (per-row written to `job_listings`)**

| Field | Source |
|---|---|
| `source_id` | `SourceId.ASHBY` = `"ashby_api"` |
| `id` | `str(raw["id"])` (raw Ashby UUID, no prefix) |
| `company` | `company_id` (Ashby `companies.id`) |
| `title` | `raw["title"]` |
| `url` | `raw["jobUrl"]` |
| `location` | `raw["location"]` |
| `posted_on` | `_normalize_iso8601(raw["publishedAt"])` |
| `details` | JSONB shape above |
| `status` | (managed by `upsert_jobs_batch` / `mark_jobs_closed`) |
| `last_seen_at` | (managed by `update_last_seen`) |
| `consecutive_misses` | (managed by `increment_consecutive_misses`) |

**Procrastinate task signatures**

```python
@procrastinate_app.task(
    queue="ashby_fetch",
    name="fetch_ashby_company",
    retry=RetryStrategy(max_attempts=5, exponential_wait=2),
)
async def fetch_ashby_company(company_id: str, board_token: str) -> None: ...

@procrastinate_app.periodic(cron="*/30 * * * *", periodic_id="ashby_fan_out")
@procrastinate_app.task(
    queue="ashby_fetch",
    name="enqueue_ashby_fan_out",
    retry=RetryStrategy(max_attempts=3, exponential_wait=2),
)
async def enqueue_ashby_fan_out(timestamp: int) -> int: ...
```

**Queueing lock format**

`queueing_lock=f"ashby:{company_id}"` — applied at `defer_async` site (both the periodic fan-out and the admin trigger endpoint). Per-company isolation; never global. Greenhouse uses `greenhouse:{company_id}` — the two ATSes never share locks.

**`Company.sourceAts` field shape (frontend `Company` type)**

```ts
// Unit 7 introduces the field, narrow Ashby-only union:
sourceAts?: 'ashby';

// Unit 9 widens the union to include Greenhouse:
sourceAts?: 'ashby' | 'greenhouse';
```

The field is optional throughout. Only Greenhouse/Ashby `backend-scraper` rows carry it. Google/Apple/Microsoft `backend-scraper` rows do NOT carry it (they remain in "Custom Web Scrapers" on the Why page).

---

## Work Units

10 sequential units. Order is load-bearing. Each unit is independently committable.

### Unit 1 — `SourceId.ASHBY` constant

**Status:** TODO

**Why 1st:** Single shared constant every other unit imports. Tiny, fast, low-risk. Verifies the constants file is the right shape before the larger units depend on it.

**Prerequisites:** None.

**Owned files:**
- `scripts/shared/constants.py` (edit) — add `ASHBY` to `SourceId`

**Shared-file edits:**
- (none)

**Changes:**
- `scripts/shared/constants.py`: add `ASHBY: Final[str] = "ashby_api"` to `SourceId`.

**Tests:**
- Smoke-test import in an existing constants test (if present) or rely on `pytest -q` collection to load the module.

**Done when:**
- `cd src/backend && pytest -q` passes.
- `python -c "from scripts.shared.constants import SourceId; print(SourceId.ASHBY)"` prints `ashby_api`.
- Commit message: `Unit 1: add SourceId.ASHBY constant`.

---

### Unit 2 — Seed Ashby companies (Alembic data migration)

**Status:** TODO

**Why 2nd:** The fan-out task needs row source.

**Prerequisites:** Unit 1.

**Owned files:**
- `src/backend/alembic/versions/<ts>_seed_ashby_companies.py` (new, hand-written data migration)

**Shared-file edits:**
- `src/backend/api/tests/test_migration_companies.py` — extend with Ashby seed coverage (mirror the Greenhouse cases already in the file)

**Changes:**
- Hand-written Alembic data migration `<ts>_seed_ashby_companies.py` mirroring `20260516_001452_939331c99a23_seed_greenhouse_companies.py`.
- `down_revision` chains to the most recent migration on `main` (`ebb479b7eed5`).
- `upgrade()`: `op.bulk_insert(...)` of 47 rows transcribed from `src/frontend/src/config/companies.ts` lines 280–410. Each row: `(id, display_name, ats='ashby', board_token=<jobBoardName>, enabled=true)`. Use `ON CONFLICT DO NOTHING` for idempotency on re-runs against pre-existing data.
- `downgrade()`: `DELETE FROM companies WHERE ats='ashby' AND id IN (...)`.

**Tests:**
- `upgrade head` seeds 47 rows where `ats='ashby'`.
- Round-trip `upgrade head → downgrade -1 → upgrade head` is idempotent.

**Done when:**
- `cd src/backend && pytest api/tests/test_migration_companies.py -v` is green.
- `SELECT count(*) FROM companies WHERE ats='ashby';` returns 47 after `alembic upgrade head` (local manual check is optional).
- Commit message: `Unit 2: seed 47 Ashby companies via Alembic data migration`.

---

### Unit 3 — Ashby fetch helper (pure module)

**Status:** TODO

**Why 3rd:** Isolate HTTP + transform layer for unit testing without queue plumbing.

**Prerequisites:** Unit 1.

**Owned files:**
- `src/backend/api/services/ashby_client.py` (new)
- `src/backend/api/tests/test_ashby_client.py` (new)

**Shared-file edits:**
- (none)

**Changes:**
- New `src/backend/api/services/ashby_client.py`. Mirror `greenhouse_client.py` structure exactly:
  - `SOURCE_ID = SourceId.ASHBY`
  - `ASHBY_BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"`
  - `DEFAULT_TIMEOUT_SECONDS = 30.0`
  - `async def fetch_jobs(board_token: str, http: httpx.AsyncClient) -> list[dict]`: GET `{ASHBY_BASE_URL}/{board_token}?includeCompensation=true`. Raises on non-2xx and on missing/non-list `"jobs"` key.
  - `def transform_to_job_listings(company_id: str, raw_jobs: list[dict]) -> list[JobListing]`: maps each raw Ashby job to a `JobListing`. `id = str(raw["id"])`. Populates `details`:
    ```python
    {
        "department": raw.get("department"),
        "team": raw.get("team"),
        "secondary_locations": [s.get("location") for s in raw.get("secondaryLocations", []) if isinstance(s, dict)],
        "employment_type": raw.get("employmentType"),
        "is_remote_eligible": bool(raw.get("isRemote")),
        "compensation_summary": (raw.get("compensation") or {}).get("compensationTierSummary"),
        "published_at": raw.get("publishedAt"),
        "description_html": raw.get("descriptionHtml"),
        "experience_level": None,
    }
    ```
  - `posted_on` parsed from `raw["publishedAt"]` via a local `_normalize_iso8601` helper (duplicate the Greenhouse helper, ~10 lines).
  - `url = raw["jobUrl"]`, `location = raw["location"]`.

**Tests:**
- Happy path with a fixture from a real Ashby response (e.g. `notion`).
- `fetch_jobs` raises `ValueError` on missing `jobs` key, non-list `jobs`.
- `fetch_jobs` raises `httpx.HTTPStatusError` on 5xx.
- `transform_to_job_listings`: id format, `posted_on` UTC normalization, `is_remote_eligible` truthy on `isRemote=true`, all `details` keys present, compensation summary extracted, `experience_level` always `None`.

**Done when:**
- `cd src/backend && pytest api/tests/test_ashby_client.py -v` is green.
- Commit message: `Unit 3: add Ashby fetch + transform client`.

---

### Unit 4 — `fetch_ashby_company` task

**Status:** TODO

**Why 4th:** The per-company worker. Depends on Units 1, 2, 3.

**Prerequisites:** Units 1, 2, 3.

**Owned files:**
- `src/backend/api/tasks/fetch_ashby_company.py` (new)
- `src/backend/api/tests/test_fetch_ashby_company.py` (new)

**Shared-file edits:**
- (none)

**Changes:**
- New `src/backend/api/tasks/fetch_ashby_company.py`. **Structurally copy `fetch_greenhouse_company.py`**, substituting:
  - Imports from `..services.ashby_client` instead of `..services.greenhouse_client`.
  - `@procrastinate_app.task(queue="ashby_fetch", name="fetch_ashby_company", retry=RetryStrategy(max_attempts=5, exponential_wait=2))`
  - Function name: `async def fetch_ashby_company(company_id: str, board_token: str) -> None`.
  - Everything else identical: same `asyncio.to_thread` wrapping, same `asyncio.shield` for connection acquisition, same `SAFETY_GUARD_RATIO` guard, same 5-step DB sequence (upsert → update_last_seen → increment_consecutive_misses → mark_jobs_closed → record_scrape_run), same fallback-connection logic for `record_scrape_run`, same narrow-exception handling (`httpx.HTTPError`, `ValueError`, `psycopg2.Error` only).

**Tests:**
- Happy path: 3 raw jobs → 3 upserted, scrape_run recorded.
- Re-run with existing job missing → `consecutive_misses=1` → re-run → `consecutive_misses=2` → marked CLOSED.
- Safety guard: 0 jobs returned with 100 active → no writes, run logged with `error_count=1`.
- HTTPX 5xx → task raises → Procrastinate retries.
- Fallback connection path on `record_scrape_run` primary failure.
- Programmer error (AttributeError) propagates without being caught.

**Done when:**
- `cd src/backend && pytest api/tests/test_fetch_ashby_company.py -v` is green.
- Commit message: `Unit 4: add fetch_ashby_company Procrastinate task`.

---

### Unit 5 — Periodic fan-out + worker queue expansion

**Status:** TODO

**Why 5th:** Connects the cron to the per-company worker. Last backend change before the frontend cutover.

**Prerequisites:** Units 1, 2, 3, 4.

**Owned files:**
- `src/backend/api/tasks/enqueue_ashby_fan_out.py` (new)
- `src/backend/api/tasks/__init__.py` (edit — side-effect import for `enqueue_ashby_fan_out` and `fetch_ashby_company`)
- `src/backend/api/tests/test_enqueue_ashby_fan_out.py` (new)

**Shared-file edits:**
- `src/backend/api/main.py` — line 146: change `queues=["greenhouse_fetch"]` → `queues=["greenhouse_fetch", "ashby_fetch"]`. Update the info log on line 151 accordingly.

**Changes:**
- New `src/backend/api/tasks/enqueue_ashby_fan_out.py`. Structurally copy `enqueue_greenhouse_fan_out.py`, substituting:
  - `@procrastinate_app.periodic(cron="*/30 * * * *", periodic_id="ashby_fan_out")`
  - `@procrastinate_app.task(queue="ashby_fetch", name="enqueue_ashby_fan_out", retry=RetryStrategy(max_attempts=3, exponential_wait=2))`
  - `db.list_enabled_companies(conn, "ashby")`
  - Defers `fetch_ashby_company.configure(queueing_lock=f"ashby:{c['id']}").defer_async(...)`.
  - Same per-company error isolation: catch `AlreadyEnqueued`, `ConnectorException`, `psycopg2.Error`; let programmer errors propagate.
- `src/backend/api/main.py` line 146: change `queues=["greenhouse_fetch"]` → `queues=["greenhouse_fetch", "ashby_fetch"]`. Update the info log on line 151 accordingly.
- `src/backend/api/tasks/__init__.py` (if it explicitly imports task modules): add side-effect imports for `enqueue_ashby_fan_out` and `fetch_ashby_company`. Verify the existing import pattern for Greenhouse and mirror it.

**Tests:**
- Defers one job per enabled Ashby company; skips disabled.
- Re-run within window: `AlreadyEnqueued` raised per company, loop continues.
- Per-company connector error: loop isolation (next company still gets deferred).
- Programmer error (AttributeError) propagates.

**Done when:**
- `cd src/backend && pytest api/tests/test_enqueue_ashby_fan_out.py -v` is green.
- Manual smoke: start backend, log line shows `queues=['greenhouse_fetch', 'ashby_fetch']`.
- Commit message: `Unit 5: add Ashby periodic fan-out and expand worker queues`.

---

### Unit 6 — Admin trigger endpoints

**Status:** TODO

**Why 6th:** QA + emergency tooling. Mirrors Greenhouse trigger endpoints. Required by DEPLOY.md's "trigger fan-out manually right after deploy" step.

**Prerequisites:** Units 1, 2, 3, 4, 5.

**Owned files:**
- (none new — extends existing router)

**Shared-file edits:**
- `src/backend/api/routers/jobs_qa.py` — add `POST /trigger-ashby-fetch` and `POST /trigger-ashby-fan-out`.
- `src/backend/api/tests/test_jobs_qa_router.py` — extend with the four Ashby cases below.
- (conditional) `src/frontend/src/pages/QAPage/QAPage.tsx` — only if QAPage has dedicated Greenhouse trigger UI; mirror it for Ashby.

**Changes:**
- Extend `src/backend/api/routers/jobs_qa.py`:
  - `POST /api/jobs-qa/trigger-ashby-fetch?company_id=<id>` — admin-only (`Depends(require_admin)`). Verifies company exists with `ats='ashby'`. 404 if missing. Defers `fetch_ashby_company` with `queueing_lock=f"ashby:{company_id}"`. Returns 202 with `{enqueued, already_enqueued}`.
  - `POST /api/jobs-qa/trigger-ashby-fan-out` — admin-only. Defers `enqueue_ashby_fan_out` directly. Returns 202.
- If QAPage has dedicated Greenhouse trigger UI (inspect during this unit), add Ashby equivalents. If Greenhouse is API-only on QAPage, leave UI alone.

**Tests:**
- 401/403 without admin token.
- 404 for unknown company.
- 202 + `enqueued=true` happy path.
- 202 + `already_enqueued=true` on second call with same lock.

**Done when:**
- `cd src/backend && pytest api/tests/test_jobs_qa_router.py -v` is green.
- `curl -X POST -H "Authorization: Bearer <admin>" http://localhost:8000/api/jobs-qa/trigger-ashby-fetch?company_id=notion` → 202.
- Commit message: `Unit 6: add Ashby admin trigger endpoints`.

---

### Unit 7 — Frontend cutover (no Why-page changes yet)

**Status:** TODO

**Why 7th:** Backend now serves Ashby data. Point the UI at it and delete the old code paths. Why-page split lives in Unit 8 so this commit stays focused on the data-plane swap.

**Prerequisites:** Units 1, 2, 3, 4, 5, 6.

**Owned files (delete):**
- `src/frontend/src/api/clients/ashbyClient.ts` (delete)
- `src/frontend/src/api/transformers/ashbyTransformer.ts` (delete)
- `src/frontend/src/__tests__/api/transformers/ashbyTransformer.test.ts` (delete)
- `src/frontend/src/__tests__/api/serverless/ashby.serverless.test.ts` (delete)
- `api/ashby.ts` (delete)
- Optionally `src/frontend/src/api/clients/cursorJobUrl.ts` + its tests (delete iff Ashby was the only caller — grep `src/frontend/src/` during this unit)

**Shared-file edits:**
- `src/frontend/src/config/companies.ts` — flip 47 Ashby entries to `createBackendScraperCompany(..., { ..., sourceAts: 'ashby' })`
- `src/frontend/src/types/index.ts` — add optional `sourceAts?: 'ashby'` to `Company` type and to the `createBackendScraperCompany` factory's options parameter; remove `AshbyConfig` interface; remove `'ashby'` from `ATSProvider` union; remove `AshbyConfig` from `Company.config` discriminated union
- `src/frontend/src/api/types.ts` — remove `AshbyJobResponse`, `AshbyAPIResponse`; remove `ATSConstants.Ashby` (if it exists); remove `'ashby'` from `APIError.atsProvider` union
- `src/frontend/src/api/clients/baseClient.ts` — remove `AshbyConfig` from `ATSCompanyConfig` union and from APIError construction
- `src/frontend/src/features/app/appSlice.ts` — if default `selectedATS` was `Ashby`, change to `BackendScraper`
- `vercel.json` / `vercel.ts` — remove the Ashby route definition
- `CLAUDE.md` (root) — remove Ashby from "ATS APIs (Lever, Ashby, Workday, Gem, Eightfold)"; update Vercel function list (remove `api/ashby.ts`)
- `src/frontend/CLAUDE.md` — remove Ashby from frontend client list; remove `createAshbyCompany()` from the factory list; update Vercel functions section

**Changes:**

**Companies config (`src/frontend/src/config/companies.ts`):**
- For every `createAshbyCompany(id, name, opts)` (47 entries, lines 280–410), replace with `createBackendScraperCompany(id, name, <jobsUrl>, { ...<other-options>, sourceAts: 'ashby' })`.
  - `<jobsUrl>`: keep `opts.jobsUrl` if it was set (cursor, saronic, plaid); otherwise default to `https://careers.ashbyhq.com/${jobBoardName}` (matching what `createAshbyCompany` previously produced).
  - Drop `jobBoardName` (now stored in DB as `board_token`).
  - Preserve every other option (e.g. `recruiterLinkedInUrl`).

**`sourceAts` type plumbing (locked in this Unit, not Unit 8):**
- Add optional `sourceAts?: 'ashby'` field to the `Company` type in `src/frontend/src/types/index.ts`.
- Add matching optional parameter to `createBackendScraperCompany` factory so the 47 cutover entries can pass `sourceAts: 'ashby'` and type-check.
- Unit 8 builds the Why-page consumers of this field. Unit 9 widens the union to `'ashby' | 'greenhouse'`.

**Remove Ashby dead code:**
- Delete `src/frontend/src/api/clients/ashbyClient.ts`.
- Delete `src/frontend/src/api/transformers/ashbyTransformer.ts`.
- Delete `src/frontend/src/__tests__/api/transformers/ashbyTransformer.test.ts`.
- Delete `src/frontend/src/__tests__/api/serverless/ashby.serverless.test.ts`.
- Edit `src/frontend/src/types/index.ts`: remove `AshbyConfig` interface; remove `'ashby'` from `ATSProvider` union; remove `AshbyConfig` from `Company.config` discriminated union.
- Edit `src/frontend/src/api/types.ts`: remove `AshbyJobResponse`, `AshbyAPIResponse`; remove `ATSConstants.Ashby` (if it exists); remove `'ashby'` from `APIError.atsProvider` union.
- Edit `src/frontend/src/api/clients/baseClient.ts`: remove `AshbyConfig` from `ATSCompanyConfig` union and from APIError construction. The implementation agent picks a remaining factory-based ATS (Lever / Workday / Gem) for any test fixtures.
- Edit `src/frontend/src/features/app/appSlice.ts`: if default `selectedATS` was `Ashby`, change to `BackendScraper`.
- Search-and-replace any remaining `'ashby'` / `AshbyConfig` references in `src/frontend/src/`.
- Grep for callers of `rewriteCursorJobUrls` (in `src/frontend/src/api/clients/cursorJobUrl.ts`). If Ashby was the only caller, delete that utility and its tests too.

**Delete Vercel proxy:**
- Delete `api/ashby.ts`.
- Update `vercel.json` (and/or `vercel.ts`) to remove the Ashby route definition.

**Doc updates:**
- Update root `CLAUDE.md`: remove Ashby from "ATS APIs (Lever, Ashby, Workday, Gem, Eightfold)"; update Vercel function list (remove `api/ashby.ts`).
- Update `src/frontend/CLAUDE.md`: remove Ashby from frontend client list; remove `createAshbyCompany()` from the factory list; update Vercel functions section.

**Tests:**
- `npm run type-check` clean across `src/frontend/`.
- `npm test` passes for all existing suites (Ashby-specific suites are deleted; other suites should be unaffected by the dead-code removal).
- Manual verification: render Ashby companies (Notion, OpenAI, Ramp, Cursor) via `npm run dev:vercel -w src/frontend` and confirm jobs come from `/api/jobs?company=<id>`.

**Done when:**
- `npm run type-check` clean.
- `npm test` passes.
- `npm run dev:vercel -w src/frontend` — Ashby companies (Notion, OpenAI, Ramp, Cursor) render. Network tab shows `/api/jobs?company=<id>`, zero `/api/ashby/*` requests.
- `grep -rE "AshbyConfig|ashbyClient|ashbyTransformer|createAshbyCompany|'ashby'\b" src/frontend/src/` returns zero matches (excluding any new `sourceAts: 'ashby'` lines, which are intentional).
- Commit message: `Unit 7: cut Ashby companies over to backend-scraper, delete legacy client/proxy`.

---

### Unit 8 — Why page Ashby split

**Status:** TODO

**Why 8th:** Bake in the equivalent of commit `168701a` so we don't ship a follow-up cosmetic PR for Ashby.

**Prerequisites:** Units 1, 2, 3, 4, 5, 6, 7.

**Owned files:**
- (none new)

**Shared-file edits:**
- `src/frontend/src/pages/WhyPage/atsGrouping.ts` — add `'ashby'` to `ATSGroupKey`, `getATSGroupKey` checks `sourceAts === 'ashby'` first; add `ashby: 'Ashby'` display name; add `'ashby'` to `NON_CAPITALIZED_GROUPS`
- `src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx` — new Ashby column tests

**Changes:**
- Edit `src/frontend/src/pages/WhyPage/atsGrouping.ts`:
  - Update `ATSGroupKey` to include `'ashby'`: `type ATSGroupKey = Company['ats'] | 'greenhouse' | 'ashby'`.
  - Update `getATSGroupKey`:
    ```ts
    export function getATSGroupKey(company: Company): ATSGroupKey {
      if (company.ats === 'backend-scraper' && company.sourceAts === 'ashby') return 'ashby';
      if (company.ats === 'backend-scraper' && company.jobsUrl?.startsWith(GREENHOUSE_BOARD_URL_PREFIX)) return 'greenhouse';
      return company.ats;
    }
    ```
    (The Greenhouse URL-prefix branch is removed in Unit 9 once the retrofit lands.)
  - Update `ATS_DISPLAY_NAMES`: add `ashby: 'Ashby'` (capitalized, matching Greenhouse's display style).
  - Update `NON_CAPITALIZED_GROUPS`: add `'ashby'` (display name is already cased, don't `textTransform: capitalize` it).
- Update WhyPage tests (`src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx`):
  - Add: "renders a dedicated Ashby group containing only companies whose `sourceAts === 'ashby'`".
  - Add: "Custom Web Scrapers group excludes Ashby companies (true custom scrapers only)".
  - Verify existing "renders one ATS group header per distinct non-empty ATS group" passes with the expanded `ATSGroupKey`.
  - Verify the test helper `groupCompaniesByATS` includes the Ashby key.

**Tests:**
- "renders a dedicated Ashby group containing only companies whose `sourceAts === 'ashby'`".
- "Custom Web Scrapers group excludes Ashby companies (true custom scrapers only)".
- Existing "renders one ATS group header per distinct non-empty ATS group" still passes with the expanded `ATSGroupKey`.

**Done when:**
- `npm test -- WhyPage` passes.
- `npm run dev:vercel -w src/frontend` → navigate to `/why` → "Ashby (47)" column renders with all 47 companies. "Custom Web Scrapers" column contains only Google/Apple/Microsoft. Greenhouse column still renders (via URL prefix, until Unit 9 retrofits it).
- Commit message: `Unit 8: split Ashby into its own Why-page column`.

---

### Unit 9 — Greenhouse retrofit to `sourceAts`

**Status:** TODO

**Why 9th:** End the two-mechanism state in `atsGrouping.ts`. After this unit, `getATSGroupKey` only checks `sourceAts` — URL-prefix detection is removed.

**Prerequisites:** Units 1, 2, 3, 4, 5, 6, 7, 8.

**Owned files:**
- (none new)

**Shared-file edits:**
- `src/frontend/src/config/companies.ts` — add `sourceAts: 'greenhouse'` to ~45 existing Greenhouse `createBackendScraperCompany` entries
- `src/frontend/src/types/index.ts` — widen `sourceAts` to `sourceAts?: 'ashby' | 'greenhouse'`
- `src/frontend/src/pages/WhyPage/atsGrouping.ts` — remove `GREENHOUSE_BOARD_URL_PREFIX` constant; simplify `getATSGroupKey`
- `src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx` — update the Greenhouse-grouping test to assert against `sourceAts === 'greenhouse'` instead of URL prefix

**Changes:**
- `src/frontend/src/config/companies.ts`: for every existing `createBackendScraperCompany(...)` call that points at a Greenhouse board (URL prefix `https://boards.greenhouse.io/`), add `sourceAts: 'greenhouse'` to the options object. ~45 single-line edits. Google/Apple/Microsoft entries (also `createBackendScraperCompany`) do NOT get `sourceAts` — they remain in "Custom Web Scrapers".
- Update `src/frontend/src/types/index.ts`: expand `sourceAts` field type to `sourceAts?: 'ashby' | 'greenhouse'`.
- Update `src/frontend/src/pages/WhyPage/atsGrouping.ts`:
  - Remove `GREENHOUSE_BOARD_URL_PREFIX` constant.
  - Simplify `getATSGroupKey`:
    ```ts
    export function getATSGroupKey(company: Company): ATSGroupKey {
      if (company.ats === 'backend-scraper' && company.sourceAts) return company.sourceAts;
      return company.ats;
    }
    ```
- Update `src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx`:
  - Update the "renders a dedicated Greenhouse group" test to assert against `sourceAts === 'greenhouse'` rather than URL prefix.
  - The Custom-Web-Scrapers exclusion test continues to pass (Greenhouse entries now have `sourceAts !== undefined`).

**Tests:**
- "renders a dedicated Greenhouse group" passes with the new assertion against `sourceAts === 'greenhouse'`.
- Custom-Web-Scrapers exclusion still passes.
- `grep -n "GREENHOUSE_BOARD_URL_PREFIX" src/frontend/src/` returns no matches.

**Done when:**
- `npm run type-check` clean.
- `npm test` passes.
- Why page renders the same three columns (Greenhouse, Ashby, Custom Web Scrapers) with the same counts as before Unit 9.
- `grep -n "GREENHOUSE_BOARD_URL_PREFIX" src/frontend/src/` returns no matches.
- Commit message: `Unit 9: retrofit Greenhouse companies to sourceAts, remove URL-prefix detection`.

---

### Unit 10 — Deploy runbook + DEPLOY.md

**Status:** TODO

**Why 10th:** Document the operator steps. No code changes.

**Prerequisites:** Units 1, 2, 3, 4, 5, 6, 7, 8, 9.

**Owned files:**
- `docs/implementations/ashbyBackendMigration/DEPLOY.md` (new)

**Shared-file edits:**
- (none)

**Changes:**
- New `docs/implementations/ashbyBackendMigration/DEPLOY.md` parallel to `docs/implementations/greenhouseBackendMigration/DEPLOY.md`. Sections:
  - **Merge order**: single PR, all 10 commits land at once. Railway auto-deploys backend; Vercel auto-deploys frontend.
  - **Pre-merge check (local)**: `cd src/backend && pytest`, `npm run type-check`, `npm test`.
  - **Post-merge operator action** (the critical step): right after Railway shows "deploy succeeded" on commit-9's SHA, hit `POST /api/jobs-qa/trigger-ashby-fan-out` (curl example with admin Bearer token). This populates `job_listings` within ~30s instead of waiting up to 30 min for the next cron tick. Without this step, anyone who navigates to an Ashby company page during the gap window sees an empty list.
  - **Monitoring queries**:
    - `SELECT count(*) FROM companies WHERE ats='ashby';` → 47.
    - 30 min post-deploy: `SELECT count(*) FROM scrape_runs WHERE company IN (SELECT id FROM companies WHERE ats='ashby') AND started_at > now() - interval '1 hour';` ≈ 47.
    - 2 hours post-deploy: `SELECT count(*) FROM job_listings WHERE source_id='ashby_api' AND company='notion';` ≥ Ashby API count for Notion.
    - Worker health: `SELECT status, count(*) FROM procrastinate_jobs WHERE queue_name='ashby_fetch' GROUP BY status;`
  - **Rollback**: revert the merge commit. Frontend goes back to direct Ashby API calls (briefly broken since `api/ashby.ts` was deleted in the merge — note this asymmetry in the runbook so operators know rollback also needs to revert that file). Backend continues to fetch Ashby harmlessly until a code revert lands.

**Tests:**
- N/A (docs only).

**Done when:**
- `docs/implementations/ashbyBackendMigration/DEPLOY.md` exists and matches the Greenhouse DEPLOY.md structure.
- Commit message: `Unit 10: add DEPLOY.md runbook for Ashby backend migration`.

---

## Critical files

| File | Action | Unit |
|---|---|---|
| `scripts/shared/constants.py` | edit | 1 |
| `src/backend/alembic/versions/<ts>_seed_ashby_companies.py` | new (hand-written data migration) | 2 |
| `src/backend/api/services/ashby_client.py` | new | 3 |
| `src/backend/api/tasks/fetch_ashby_company.py` | new | 4 |
| `src/backend/api/tasks/enqueue_ashby_fan_out.py` | new | 5 |
| `src/backend/api/tasks/__init__.py` | edit (side-effect import) | 5 |
| `src/backend/api/main.py` | edit (queues list + log) | 5 |
| `src/backend/api/routers/jobs_qa.py` | edit (trigger endpoints) | 6 |
| `src/frontend/src/config/companies.ts` | edit (flip 47 Ashby entries) | 7 |
| `src/frontend/src/types/index.ts` | edit (add `sourceAts`, drop `AshbyConfig`) | 7 |
| `src/frontend/src/api/clients/ashbyClient.ts` | **delete** | 7 |
| `src/frontend/src/api/transformers/ashbyTransformer.ts` | **delete** | 7 |
| `src/frontend/src/__tests__/api/transformers/ashbyTransformer.test.ts` | **delete** | 7 |
| `src/frontend/src/__tests__/api/serverless/ashby.serverless.test.ts` | **delete** | 7 |
| `src/frontend/src/api/types.ts` | edit (drop Ashby types) | 7 |
| `src/frontend/src/api/clients/baseClient.ts` | edit (drop `AshbyConfig` union member) | 7 |
| `api/ashby.ts` | **delete** | 7 |
| `vercel.json` / `vercel.ts` | edit (route cleanup) | 7 |
| `CLAUDE.md`, `src/frontend/CLAUDE.md` | edit (docs) | 7 |
| `src/frontend/src/pages/WhyPage/atsGrouping.ts` | edit (add ashby key + display name) | 8 |
| `src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx` | edit (new Ashby column tests) | 8 |
| `src/frontend/src/config/companies.ts` | edit (add `sourceAts: 'greenhouse'` to 45 entries) | 9 |
| `src/frontend/src/pages/WhyPage/atsGrouping.ts` | edit (remove URL-prefix detection) | 9 |
| `docs/implementations/ashbyBackendMigration/DEPLOY.md` | new | 10 |

---

## Existing utilities reused

- `scripts/shared/database.py`: `count_active_jobs`, `get_active_job_ids`, `upsert_jobs_batch`, `update_last_seen`, `increment_consecutive_misses`, `mark_jobs_closed`, `get_jobs_exceeding_miss_threshold`, `list_enabled_companies`, `record_scrape_run`, `get_connection`.
- `scripts/shared/incremental.py`: `MISSED_RUN_THRESHOLD`, `SAFETY_GUARD_RATIO`.
- `scripts/shared/models.py`: `JobListing`, `ScrapeRun`.
- `scripts/shared/utils.py`: `get_iso_timestamp`.
- `src/backend/api/tasks/procrastinate_app.py`: `procrastinate_app` singleton (no changes).
- `src/backend/api/routers/jobs.py`: `/api/jobs` endpoint (no changes — already serves anything in `companies`).
- `src/frontend/src/api/clients/backendScraperClient.ts`: per-company + batched fetch (no changes).
- `src/frontend/src/api/transformers/backendScraperTransformer.ts`: reads `details.experience_level` + `details.is_remote_eligible` (no changes — Ashby populates `is_remote_eligible`; `experience_level` stays null).

---

## End-to-End Verification (after all 10 units, before review passes)

1. Local: `docker compose up -d postgres`; backend startup applies migrations + seed; worker log shows `queues=['greenhouse_fetch', 'ashby_fetch']`.
2. `curl -X POST -H "Authorization: Bearer <admin>" 'http://localhost:8000/api/jobs-qa/trigger-ashby-fan-out'` → 202.
3. Within ~30s: `psql -c "SELECT company, count(*) FROM job_listings WHERE source_id='ashby_api' GROUP BY company ORDER BY 2 DESC LIMIT 10;"` shows seeded Ashby companies populated.
4. Frontend: `npm run dev:vercel -w src/frontend`. Open `/companies` → select Notion, OpenAI, Ramp, Cursor → jobs render from `/api/jobs`. Network tab: zero `/api/ashby/*` requests.
5. Open `/why` → "Ashby (47)" column visible; "Greenhouse (45)" column visible; "Custom Web Scrapers (3)" column contains only Google/Apple/Microsoft.
6. Wait one cron interval (30 min). `SELECT count(*) FROM scrape_runs WHERE started_at > now() - interval '1 hour' AND company IN (SELECT id FROM companies WHERE ats='ashby');` ≈ 47.
7. Simulate disappearance: monkeypatch a fetch response to drop one Ashby job → after 2 cron cycles, that job's `status='CLOSED'`.
8. `cd src/backend && pytest` all green; coverage ≥ existing baseline.
9. `npm run type-check && npm test` clean.
10. `grep -rE "'ashby'|AshbyConfig|createAshbyCompany|GREENHOUSE_BOARD_URL_PREFIX" src/frontend/src/ api/ vercel.json vercel.ts` returns zero matches (excluding intentional `sourceAts: 'ashby'` lines in companies.ts).

---

## Three Review Passes (handled by `/e2eimplementation`)

Each pass dispatches in parallel:

- `pr-review-toolkit:code-reviewer` (always)
- `pr-review-toolkit:silent-failure-hunter` (always)
- `pr-review-toolkit:pr-test-analyzer` (always)
- `pr-review-toolkit:type-design-analyzer` (Unit 7+9 modify types — yes)
- `pr-review-toolkit:comment-analyzer` (only if comments added/changed; tasks units add comments)
- `vercel-prod-verifier` (Unit 7 deletes `api/ashby.ts` + edits `vercel.json` — yes)
- `postgres-prod-verifier` (Unit 2 ships a migration; Units 3–5 add ORM queries — yes)
- `railway-prod-verifier` (Units 1–6 ship backend code — yes)

Findings consolidated in `docs/implementations/ashbyBackendMigration/REVIEW_AUDIT.md`. Fix agent runs between passes for Critical/Important items. Three passes regardless of pass-1 cleanliness.

---

## Non-goals

- **Migrating Lever / Workday / Gem / Eightfold to backend.** Each is a near-copy of this plan (own queue, own client, own task, own fan-out, own atsGrouping key + display name + `sourceAts` value).
- **Per-company observability dashboard.** `procrastinate_jobs` + `scrape_runs` are already queryable.
- **Removing `googleScraper` / `appleScraper` / `microsoftScraper` from the "Custom Web Scrapers" group.** They legitimately belong there since they're truly bespoke.
- **Renaming queues to a single shared `backend_fetch`.** Doable but renaming live queues mid-flight isn't free.
