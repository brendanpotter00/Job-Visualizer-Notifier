# Move Gem to Backend Cron + Queue

## Context

Gem is currently fetched statelessly from the browser: the frontend calls `api.gem.com/job_board/v0/{vanityUrlPath}/job_posts/` through the `api/gem.ts` Vercel CORS proxy, runs `gemTransformer.ts` client-side, and never persists anything. This is the same shape Greenhouse had before commit `92bfdf6` ("Move Greenhouse to Backend Cron + Queue") and the same shape Ashby had before PR #120 ("Move Ashby to Backend Cron + Queue"). We mirror the Ashby migration exactly — it is the closest exemplar (also a JSON-only ATS with a single companies-table row per board).

The Greenhouse + Ashby migrations established the canonical pattern for JSON-only ATS providers:

- Per-company Procrastinate task with retries and queueing locks
- 30-minute periodic fan-out driven by Procrastinate's built-in `@app.periodic` cron
- Existing `companies` table holds `(id, display_name, ats, board_token, enabled)` — Gem just adds 3 more rows
- Existing `job_listings` composite PK `(source_id, id)` already supports multi-source coexistence
- Frontend cutover flips Gem entries from `createGemCompany(...)` to `createBackendScraperCompany(...)` and reads them through `/api/jobs?company=<id>` (already serving Greenhouse, Ashby, and Google/Apple/Microsoft)

**Outcome:** Gem jobs land in `job_listings` with `source_id = 'gem_api'`. The 3 Gem entries in `companies.ts` are flipped to `backend-scraper` carrying `sourceAts: 'gem'`. The Why page renders Gem in its own column (not lumped into the "gem" ATS group of pre-cutover frontend behavior). `api/gem.ts`, `gemClient.ts`, `gemTransformer.ts`, their tests, and all references to `'gem'` / `GemConfig` in the frontend client-selection logic are removed.

---

## Decisions Locked

| Decision | Choice |
|---|---|
| Scope | Gem only. Lever / Workday / Eightfold stay frontend-stateless. |
| Source ID | `"gem_api"` (added to `SourceId` in `scripts/shared/constants.py`). |
| Procrastinate queue | New queue `"gem_fetch"` (separate from `"greenhouse_fetch"` / `"ashby_fetch"`). |
| Worker hosting | In-process; expand `main.py` worker to `queues=["greenhouse_fetch", "ashby_fetch", "gem_fetch"]`, concurrency stays at **5**. |
| Cron frequency | `*/30 * * * *` (matches Greenhouse / Ashby, no stagger). |
| Overlap policy | `queueing_lock=f"gem:{company_id}"` per per-company task. |
| ID format | Raw Gem job id as string (`str(raw["id"])`) — no prefixing. Composite PK on `(source_id, id)` handles cross-source uniqueness. Gem ids are observed to be numeric strings (e.g. `"4123456"`); cast defensively. |
| `details` JSONB shape | Greenhouse/Ashby-style keys where they overlap, Gem-specific where unique. Keys: `experience_level: None` (Gem doesn't expose), `is_remote_eligible: bool(raw.get("location_type") == "remote")`, `employment_type` (normalized to display casing — `Full-time`, `Part-time`, `Contract`, `Internship`, `Temporary`), `department` (first entry of `raw.departments[]` if present), `office` (first entry of `raw.offices[]` if present), `secondary_offices` (`raw.offices[1:]` names), `published_at` (`raw.first_published_at` if present else `raw.created_at`), `content_html: raw.content` (Gem returns HTML in `content`; the field name matches the Ashby `description_html` slot semantically — but we keep Gem's column name to match its API). |
| `posted_on` source | `raw.first_published_at or raw.created_at`. Parsed by `_normalize_iso8601` helper (duplicated from `ashby_client.py`, ~10 lines). |
| Seed migration | Hand-written Alembic data migration `seed_gem_companies.py` (one acceptable hand-write — data migrations are not autogenerable). 3 rows `(id, display_name, ats='gem', board_token=<id>, enabled=true)`. All three companies (nominal / retool / gem) use board_token == id — the frontend never overrides `vanityUrlPath`. |
| Schema extension | **None.** Gem only needs `board_token` per company (the vanity URL slug). The existing `companies` table already supports that. No new columns. |
| Frontend cutover | Each `createGemCompany(id, name)` → `createBackendScraperCompany(id, name, jobsUrl, { sourceAts: 'gem' })`. Default `jobsUrl` for Gem was `https://jobs.gem.com/${vanityUrlPath}` — preserve per company. |
| Gem grouping on Why page | Widen `sourceAts` union to `'ashby' \| 'greenhouse' \| 'gem'`. `getATSGroupKey` already prefers `sourceAts` (post-Ashby Unit 9 retrofit). Add `gem: 'Gem'` to `ATS_DISPLAY_NAMES` and `'gem'` to `ATSGroupKey`. |
| Vercel proxy deletion | Delete `api/gem.ts` + its test file (if it exists) at the end of the frontend cutover unit. Once all 3 Gem entries are backend-scraper, the proxy is dead code. |
| Frontend dead-code deletion | Delete `gemClient.ts`, `gemTransformer.ts`, their test files. Remove `GemConfig`/`GemJobResponse`/`GemOptions` from `types/index.ts` and `api/types.ts`. Remove `'gem'` from `ATSProvider`, `ATSConstants`, and from `ATSCompanyConfig`/`JobAPIClient` unions. Remove `createGemCompany` factory. Remove Gem MSW handler from the frontend test mock setup (if present). |
| QAPage UI | Match what Greenhouse/Ashby have. The implementation agent inspects QAPage during Unit 6 and adds Gem trigger UI iff Greenhouse/Ashby have dedicated UI. |
| Deploy gap mitigation | One PR (Units 1–10). DEPLOY.md instructs the operator to hit `POST /api/jobs-qa/trigger-gem-fan-out` immediately after Railway finishes deploying Units 1–6 so the first batch lands within ~30s instead of waiting up to 30 min for the cron. |
| Feature directory slug | `gemBackendMigration` (matches `greenhouseBackendMigration` / `ashbyBackendMigration` siblings). |
| Default ATS in appSlice | Inspect during Unit 7. If Gem was the default `selectedATS`, change to `BackendScraper`. |

---

## Repo Constraints (must follow)

- **Alembic autogenerate only.** Edit `src/backend/api/db_models.py` → `alembic revision --autogenerate` → review. Never hand-write migration files. Exception: data migrations (the seed in Unit 2). Memory: `feedback_use_alembic_migrations.md`.
- **No full-table rewrites.** This plan doesn't add columns to `job_listings` or `companies`. Only INSERTs.
- **Bare table names.** `companies` and `job_listings` are env-agnostic.
- **Correctness over "don't crash":** narrow exception handling in tasks (catch only `httpx.HTTPError`, `ValueError`, `psycopg2.Error`); programmer errors propagate. Memory: `feedback_correctness_over_dont_crash.md`.
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
│                queues=["greenhouse_fetch", "ashby_fetch", "gem_fetch"],          │
│                concurrency=5))                                                   │
│                                                                                  │
│   New tasks (import-side-effect registered on procrastinate_app):                │
│     @app.periodic(cron="*/30 * * * *", periodic_id="gem_fan_out")                │
│     @app.task(queue="gem_fetch", retry=RetryStrategy(3, 2))                      │
│     async def enqueue_gem_fan_out(timestamp: int) -> int:                        │
│         companies = db.list_enabled_companies(conn, "gem")                       │
│         for c in companies:                                                      │
│             await fetch_gem_company.configure(                                   │
│                 queueing_lock=f"gem:{c['id']}"                                   │
│             ).defer_async(company_id=c['id'], board_token=c['board_token'])      │
│                                                                                  │
│     @app.task(queue="gem_fetch", retry=RetryStrategy(5, 2))                      │
│     async def fetch_gem_company(company_id, board_token):                        │
│         # Identical 5-phase shape to fetch_ashby_company:                        │
│         # to_thread(get_connection) → fetch_jobs → transform → safety_guard      │
│         # → upsert → update_last_seen → increment_consecutive_misses             │
│         # → mark_jobs_closed → record_scrape_run                                 │
└──────────────────────────────────────────────────────────────────────────────────┘

Frontend cutover (Unit 7): companies.ts entries flip gem → backend-scraper, each carrying sourceAts: 'gem'.
Frontend calls `/api/jobs?company=nominal` — same endpoint already used for Greenhouse, Ashby, Google/Apple/Microsoft.
api/gem.ts is deleted in Unit 7.

Why page split (Unit 8): widens sourceAts to include 'gem', adds gem display name + ATSGroupKey entry.
```

---

## Race Condition / Deadlock Audit

Each risk and how it's neutralized (identical to Ashby — see `docs/implementations/ashbyBackendMigration/PLAN.md` for the full table). Summary:

- Worker dedup: `SELECT … FOR UPDATE SKIP LOCKED` on `procrastinate_jobs`.
- Cron-vs-running dedup: `queueing_lock=f"gem:{company_id}"`.
- Multi-replica periodic dedup: Procrastinate's Postgres advisory lock.
- Concurrent upserts: `ON CONFLICT (source_id, id) DO UPDATE`. Composite PK keeps Gem and Ashby/Greenhouse rows separate even if raw ids ever overlap.
- Partial fetch (e.g. Gem returns 5 of 500 jobs) closes everything: `SAFETY_GUARD_RATIO = 0.1` in `incremental.py` — port the check into the new task.
- Migration startup race (2 replicas booting): Alembic's Postgres advisory lock.
- Worker dies mid-task: Procrastinate retry; task is idempotent via `upsert_jobs_batch` + `ON CONFLICT`.

No deadlocks possible — single-row UPSERT or per-row UPDATE on `job_listings` keyed by `(source_id, id)`.

---

## Schema (no DDL changes)

The `companies` table from the Greenhouse migration already supports Gem — `ats` is a free-form `Text` column. The only schema-touching migration in this plan is the data-migration seed of the 3 Gem company rows.

`job_listings` is unchanged: composite PK `(source_id, id)`, `consecutive_misses`, `status`, `closed_on`, `last_seen_at` all exist. The `details` JSONB column accepts arbitrary shape.

---

## Shared Contracts

The following contracts are frozen for the duration of this plan. Every Unit reads them; no Unit changes them without first changing this section.

**HTTP — Gem Job Board fetch**

```
GET https://api.gem.com/job_board/v0/{board_token}/job_posts/
Accept: application/json
Timeout: 30s
Response: list[dict]   # Flat array (NOT wrapped in {jobs: [...]})
```

`fetch_jobs(board_token, http)` raises `httpx.HTTPStatusError` on non-2xx and `ValueError` if the JSON is not a list. The caller treats both as a failed run and lets Procrastinate retry.

**`details` JSONB shape (written by `transform_to_job_listings`, consumed by `backendScraperTransformer.ts`)**

```python
{
    "department": raw["departments"][0]["name"] if raw.get("departments") else None,
    "office": raw["offices"][0]["name"] if raw.get("offices") else None,
    "secondary_offices": [o["name"] for o in raw.get("offices", [])[1:] if isinstance(o, dict) and o.get("name")],
    "employment_type": _normalize_employment_type(raw.get("employment_type")),
    "is_remote_eligible": bool(raw.get("location_type") == "remote"),
    "published_at": raw.get("first_published_at") or raw.get("created_at"),
    "content_html": raw.get("content"),
    "experience_level": None,
}
```

`_normalize_employment_type` maps Gem's snake_case (`full_time`, `part_time`, `contract`, `intern`, `temporary`) to display casing (`Full-time`, `Part-time`, `Contract`, `Internship`, `Temporary`). Unrecognized values pass through unchanged. `None` returns `None`. This mirrors the frontend `normalizeEmploymentType` in the now-deleted `gemTransformer.ts`.

**`JobListing` row shape (per-row written to `job_listings`)**

| Field | Source |
|---|---|
| `source_id` | `SourceId.GEM` = `"gem_api"` |
| `id` | `str(raw["id"])` (raw Gem id, no prefix) |
| `company` | `company_id` (Gem `companies.id`) |
| `title` | `raw["title"]` |
| `url` | `raw["absolute_url"]` |
| `location` | `raw["offices"][0]["name"]` if present, else `raw.get("location", {}).get("name")` |
| `posted_on` | `_normalize_iso8601(raw["first_published_at"] or raw["created_at"])` |
| `details` | JSONB shape above |
| `status` | (managed by `upsert_jobs_batch` / `mark_jobs_closed`) |
| `last_seen_at` | (managed by `update_last_seen`) |
| `consecutive_misses` | (managed by `increment_consecutive_misses`) |

**Procrastinate task signatures**

```python
@procrastinate_app.task(
    queue="gem_fetch",
    name="fetch_gem_company",
    retry=RetryStrategy(max_attempts=5, exponential_wait=2),
)
async def fetch_gem_company(company_id: str, board_token: str) -> None: ...

@procrastinate_app.periodic(cron="*/30 * * * *", periodic_id="gem_fan_out")
@procrastinate_app.task(
    queue="gem_fetch",
    name="enqueue_gem_fan_out",
    retry=RetryStrategy(max_attempts=3, exponential_wait=2),
)
async def enqueue_gem_fan_out(timestamp: int) -> int: ...
```

**Queueing lock format**

`queueing_lock=f"gem:{company_id}"` — applied at `defer_async` site (both the periodic fan-out and the admin trigger endpoint). Per-company isolation; never global. Greenhouse uses `greenhouse:{company_id}`, Ashby uses `ashby:{company_id}` — the three ATSes never share locks.

**`Company.sourceAts` field shape (frontend `Company` type)**

```ts
// Pre-PR (post-Ashby migration):
sourceAts?: 'ashby' | 'greenhouse';

// Unit 8 widens the union to include Gem:
sourceAts?: 'ashby' | 'greenhouse' | 'gem';
```

The field is optional throughout. Only Greenhouse / Ashby / Gem `backend-scraper` rows carry it. Google/Apple/Microsoft `backend-scraper` rows do NOT carry it (they remain in "Custom Web Scrapers" on the Why page).

---

## Work Units

10 sequential units. Order is load-bearing. Each unit is independently committable.

### Unit 1 — `SourceId.GEM` constant

**Status:** DONE

**Why 1st:** Single shared constant every other unit imports. Tiny, fast, low-risk. Verifies the constants file is the right shape before the larger units depend on it.

**Prerequisites:** None.

**Owned files:**
- `scripts/shared/constants.py` (edit) — add `GEM` to `SourceId`

**Shared-file edits:**
- (none)

**Changes:**
- `scripts/shared/constants.py`: add `GEM: Final[str] = "gem_api"` to `SourceId`.

**Tests:**
- Smoke-test import in an existing constants test (if present) or rely on `pytest -q` collection to load the module.

**Done when:**
- `cd src/backend && pytest -q` passes.
- `python -c "from scripts.shared.constants import SourceId; print(SourceId.GEM)"` prints `gem_api`.
- Commit message: `Unit 1: add SourceId.GEM constant`.

---

### Unit 2 — Seed Gem companies (Alembic data migration)

**Status:** DONE

**Why 2nd:** The fan-out task needs row source.

**Prerequisites:** Unit 1.

**Owned files:**
- `src/backend/alembic/versions/<ts>_seed_gem_companies.py` (new, hand-written data migration)

**Shared-file edits:**
- `src/backend/api/tests/test_migration_companies.py` — extend with Gem seed coverage (mirror the existing Ashby/Greenhouse cases)

**Changes:**
- Hand-written Alembic data migration `<ts>_seed_gem_companies.py` mirroring `20260517_220000_a17b7c0ffee500_seed_ashby_companies.py`.
- `down_revision` chains to the most recent migration on the current branch (`a17b7c0ffee500`).
- `upgrade()`: `op.bulk_insert(...)` (or per-row INSERT with `ON CONFLICT DO NOTHING`) of 3 rows transcribed from `src/frontend/src/config/companies.ts` lines 526–529. Each row: `(id, display_name, ats='gem', board_token=<id>, enabled=true)`.
  - `nominal | Nominal | gem | nominal | true`
  - `retool | Retool | gem | retool | true`
  - `gem | Gem | gem | gem | true`
- `downgrade()`: `DELETE FROM companies WHERE ats='gem' AND id IN ('nominal', 'retool', 'gem')`.

**Tests:**
- `upgrade head` seeds 3 rows where `ats='gem'`.
- Round-trip `upgrade head → downgrade -1 → upgrade head` is idempotent.
- Existing Ashby and Greenhouse seed rows are untouched by the downgrade.

**Done when:**
- `cd src/backend && pytest api/tests/test_migration_companies.py -v` is green.
- `SELECT count(*) FROM companies WHERE ats='gem';` returns 3 after `alembic upgrade head` (local manual check is optional).
- Commit message: `Unit 2: seed 3 Gem companies via Alembic data migration`.

---

### Unit 3 — Gem fetch helper (pure module)

**Status:** DONE

**Why 3rd:** Isolate HTTP + transform layer for unit testing without queue plumbing.

**Prerequisites:** Unit 1.

**Owned files:**
- `src/backend/api/services/gem_client.py` (new)
- `src/backend/api/tests/test_gem_client.py` (new)

**Shared-file edits:**
- (none)

**Changes:**
- New `src/backend/api/services/gem_client.py`. Mirror `ashby_client.py` structure exactly:
  - `SOURCE_ID = SourceId.GEM`
  - `GEM_BASE_URL = "https://api.gem.com/job_board/v0"`
  - `DEFAULT_TIMEOUT_SECONDS = 30.0`
  - `async def fetch_jobs(board_token: str, http: httpx.AsyncClient) -> list[dict]`: GET `{GEM_BASE_URL}/{board_token}/job_posts/`. Raises on non-2xx and on non-list response.
  - `def transform_to_job_listings(company_id: str, raw_jobs: list[dict]) -> list[JobListing]`: maps each raw Gem job to a `JobListing`. `id = str(raw["id"])`. Populates `details` per the Shared Contracts shape above.
  - `posted_on` parsed from `raw["first_published_at"] or raw["created_at"]` via a local `_normalize_iso8601` helper (duplicate the Ashby helper, ~10 lines).
  - `url = raw["absolute_url"]`. `location` = `raw["offices"][0]["name"]` if present, else `raw.get("location", {}).get("name")` (Gem can return either, mirroring frontend transformer).
  - `_normalize_employment_type` private helper that maps `full_time/part_time/contract/intern/temporary` to `Full-time/Part-time/Contract/Internship/Temporary`. Unknown values pass through. `None` returns `None`.

**Tests:**
- Happy path with a fixture from a real Gem response (e.g. `retool`).
- `fetch_jobs` raises `ValueError` on non-list JSON.
- `fetch_jobs` raises `httpx.HTTPStatusError` on 5xx.
- `transform_to_job_listings`:
  - id format (always string, even if numeric in source).
  - `posted_on` UTC normalization.
  - `is_remote_eligible` truthy when `location_type == "remote"`, falsy otherwise.
  - all `details` keys present.
  - `employment_type` normalization covers all 5 known mappings + pass-through + None.
  - `experience_level` always `None`.
  - location falls back from offices[0].name → location.name.
  - posted_on falls back from first_published_at → created_at.

**Done when:**
- `cd src/backend && pytest api/tests/test_gem_client.py -v` is green.
- Commit message: `Unit 3: add Gem fetch + transform client`.

---

### Unit 4 — `fetch_gem_company` task

**Status:** DONE

**Why 4th:** The per-company worker. Depends on Units 1, 2, 3.

**Prerequisites:** Units 1, 2, 3.

**Owned files:**
- `src/backend/api/tasks/fetch_gem_company.py` (new)
- `src/backend/api/tests/test_fetch_gem_company.py` (new)

**Shared-file edits:**
- (none)

**Changes:**
- New `src/backend/api/tasks/fetch_gem_company.py`. **Structurally copy `fetch_ashby_company.py`**, substituting:
  - Imports from `..services.gem_client` instead of `..services.ashby_client`.
  - `@procrastinate_app.task(queue="gem_fetch", name="fetch_gem_company", retry=RetryStrategy(max_attempts=5, exponential_wait=2))`
  - Function name: `async def fetch_gem_company(company_id: str, board_token: str) -> None`.
  - Everything else identical: same `asyncio.to_thread` wrapping, same `asyncio.shield` for connection acquisition, same `SAFETY_GUARD_RATIO` guard, same 5-step DB sequence (upsert → update_last_seen → increment_consecutive_misses → mark_jobs_closed → record_scrape_run), same fallback-connection logic for `record_scrape_run`, same narrow-exception handling (`httpx.HTTPError`, `ValueError`, `psycopg2.Error` only).

**Tests:**
- Happy path: 3 raw jobs → 3 upserted, scrape_run recorded.
- Re-run with existing job missing → `consecutive_misses=1` → re-run → `consecutive_misses=2` → marked CLOSED.
- Safety guard: 0 jobs returned with 100 active → no writes, run logged with `error_count=1`.
- HTTPX 5xx → task raises → Procrastinate retries.
- Fallback connection path on `record_scrape_run` primary failure.
- Programmer error (AttributeError) propagates without being caught.

**Done when:**
- `cd src/backend && pytest api/tests/test_fetch_gem_company.py -v` is green.
- Commit message: `Unit 4: add fetch_gem_company Procrastinate task`.

---

### Unit 5 — Periodic fan-out + worker queue expansion

**Status:** DONE

**Why 5th:** Connects the cron to the per-company worker. Last backend change before the frontend cutover.

**Prerequisites:** Units 1, 2, 3, 4.

**Owned files:**
- `src/backend/api/tasks/enqueue_gem_fan_out.py` (new)
- `src/backend/api/tasks/__init__.py` (edit — side-effect import for `enqueue_gem_fan_out` and `fetch_gem_company`)
- `src/backend/api/tests/test_enqueue_gem_fan_out.py` (new)

**Shared-file edits:**
- `src/backend/api/main.py` — line 146: change `queues=["greenhouse_fetch", "ashby_fetch"]` → `queues=["greenhouse_fetch", "ashby_fetch", "gem_fetch"]`. Update the info log on line 151 accordingly.

**Changes:**
- New `src/backend/api/tasks/enqueue_gem_fan_out.py`. Structurally copy `enqueue_ashby_fan_out.py`, substituting:
  - `@procrastinate_app.periodic(cron="*/30 * * * *", periodic_id="gem_fan_out")`
  - `@procrastinate_app.task(queue="gem_fetch", name="enqueue_gem_fan_out", retry=RetryStrategy(max_attempts=3, exponential_wait=2))`
  - `db.list_enabled_companies(conn, "gem")`
  - Defers `fetch_gem_company.configure(queueing_lock=f"gem:{c['id']}").defer_async(...)`.
  - Same per-company error isolation: catch `AlreadyEnqueued`, `ConnectorException`, `psycopg2.Error`; let programmer errors propagate.
- `src/backend/api/main.py` line 146: change `queues=["greenhouse_fetch", "ashby_fetch"]` → `queues=["greenhouse_fetch", "ashby_fetch", "gem_fetch"]`. Update the info log on line 151 accordingly.
- `src/backend/api/tasks/__init__.py`: add side-effect imports for `enqueue_gem_fan_out` and `fetch_gem_company`, mirroring the existing Ashby pattern.

**Tests:**
- Defers one job per enabled Gem company; skips disabled.
- Re-run within window: `AlreadyEnqueued` raised per company, loop continues.
- Per-company connector error: loop isolation (next company still gets deferred).
- Programmer error (AttributeError) propagates.

**Done when:**
- `cd src/backend && pytest api/tests/test_enqueue_gem_fan_out.py -v` is green.
- Manual smoke: start backend, log line shows `queues=['greenhouse_fetch', 'ashby_fetch', 'gem_fetch']`.
- Commit message: `Unit 5: add Gem periodic fan-out and expand worker queues`.

---

### Unit 6 — Admin trigger endpoints

**Status:** DONE

**Why 6th:** QA + emergency tooling. Mirrors Greenhouse/Ashby trigger endpoints. Required by DEPLOY.md's "trigger fan-out manually right after deploy" step.

**Prerequisites:** Units 1, 2, 3, 4, 5.

**Owned files:**
- (none new — extends existing router)

**Shared-file edits:**
- `src/backend/api/routers/jobs_qa.py` — add `POST /trigger-gem-fetch` and `POST /trigger-gem-fan-out`.
- `src/backend/api/tests/test_jobs_qa_router.py` — extend with the four Gem cases below.
- (conditional) `src/frontend/src/pages/QAPage/QAPage.tsx` — only if QAPage has dedicated Greenhouse/Ashby trigger UI; mirror it for Gem.

**Changes:**
- Extend `src/backend/api/routers/jobs_qa.py`:
  - `POST /api/jobs-qa/trigger-gem-fetch?company_id=<id>` — admin-only (`Depends(require_admin)`). Verifies company exists with `ats='gem'`. 404 if missing. Defers `fetch_gem_company` with `queueing_lock=f"gem:{company_id}"`. Returns 202 with `{enqueued, already_enqueued}`.
  - `POST /api/jobs-qa/trigger-gem-fan-out` — admin-only. Defers `enqueue_gem_fan_out` directly. Returns 202.
- If QAPage has dedicated Greenhouse/Ashby trigger UI (inspect during this unit), add Gem equivalents. If those are API-only on QAPage, leave UI alone.

**Tests:**
- 401/403 without admin token.
- 404 for unknown company.
- 202 + `enqueued=true` happy path.
- 202 + `already_enqueued=true` on second call with same lock.

**Done when:**
- `cd src/backend && pytest api/tests/test_jobs_qa_router.py -v` is green.
- `curl -X POST -H "Authorization: Bearer <admin>" http://localhost:8000/api/jobs-qa/trigger-gem-fetch?company_id=retool` → 202.
- Commit message: `Unit 6: add Gem admin trigger endpoints`.

---

### Unit 7 — Frontend cutover

**Status:** DONE

**Note (deviation from plan):** Unit 7 widened `sourceAts` to `'ashby' | 'greenhouse' | 'gem'` **and** updated `atsGrouping.ts` (adding `'gem'` to `ATSGroupKey`, the `gem: 'Gem'` display name, and `'gem'` to `NON_CAPITALIZED_GROUPS`) in the same commit. The PLAN originally deferred those `atsGrouping` changes to Unit 8, but the `ATS_DISPLAY_NAMES` `Record<ATSGroupKey, string>` constraint forces the issue: removing `'gem'` from `ATSProvider` in Unit 7 made the pre-existing `gem: 'gem'` Record entry an extra-key type error against `ATSGroupKey`. The cleanest fix was to fold the atsGrouping changes into Unit 7 so the type system stays green. Unit 8 narrows to WhyPage test additions only.

**Why 7th:** Backend now serves Gem data. Point the UI at it and delete the old code paths. Why-page split lives in Unit 8 so this commit stays focused on the data-plane swap.

**Prerequisites:** Units 1, 2, 3, 4, 5, 6.

**Owned files (delete):**
- `src/frontend/src/api/clients/gemClient.ts` (delete)
- `src/frontend/src/api/transformers/gemTransformer.ts` (delete)
- `src/frontend/src/__tests__/api/clients/gemClient.test.ts` (delete iff present)
- `src/frontend/src/__tests__/api/transformers/gemTransformer.test.ts` (delete iff present)
- `src/frontend/src/__tests__/api/serverless/gem.serverless.test.ts` (delete iff present)
- `api/gem.ts` (delete)
- `api/__tests__/gem.test.ts` (delete iff present)

**Shared-file edits:**
- `src/frontend/src/config/companies.ts` — flip 3 Gem entries to `createBackendScraperCompany(..., { sourceAts: 'gem' })`; remove `createGemCompany` factory and its options interface (`GemOptions`)
- `src/frontend/src/types/index.ts` — remove `GemConfig` interface; remove `'gem'` from `ATSProvider` union; remove `GemConfig` from `Company.config` discriminated union; **do not** widen `sourceAts` here (Unit 8 widens it)
- `src/frontend/src/api/types.ts` — remove `GemJobResponse`; remove `ATSConstants.Gem`; remove `'gem'` from `APIError.atsProvider` union; remove `GemConfig` from `JobAPIClient.fetchJobs` config union
- `src/frontend/src/api/clients/baseClient.ts` — remove `GemConfig` from `ATSCompanyConfig` union and from APIError construction
- `src/frontend/src/features/app/appSlice.ts` — if default `selectedATS` was `Gem`, change to `BackendScraper`
- Wherever `gemClient` is registered in the client-selection logic (likely `jobsApi.ts` or a similar dispatch module) — remove the `gem` branch
- MSW handler in `src/frontend/src/__tests__/mocks/handlers.ts` (or equivalent) — remove the Gem handler if present
- `vercel.json` / `vercel.ts` — remove the Gem route definition
- `CLAUDE.md` (root) — remove Gem from "ATS APIs (Lever, Workday, Gem, Eightfold)"; update Vercel function list (remove `api/gem.ts`); add Gem to the backend-scraper section
- `src/frontend/CLAUDE.md` — remove Gem from frontend client list; remove `createGemCompany()` from the factory list; update Vercel functions section
- `scripts/CLAUDE.md` — no edits expected (Gem is not a scripts/ scraper)

**Changes:**

**Companies config (`src/frontend/src/config/companies.ts`):**
- For every `createGemCompany(id, name)` call (3 entries, lines 527–529), replace with `createBackendScraperCompany(id, name, 'https://jobs.gem.com/<vanityUrlPath>', { sourceAts: 'gem' })`.
  - `<vanityUrlPath>` defaults to the company id for all 3 entries (none pass an override).
  - Preserve any other options (none currently set, but defensive).
- Remove the `createGemCompany` factory function definition and the `GemOptions` interface.
- Remove the `GemConfig` import at the top.
- Replace the `// Gem companies` comment block header with `// Gem (backend-scraper)` and keep the 3 entries grouped together.

**Remove Gem dead code:**
- Delete `src/frontend/src/api/clients/gemClient.ts`.
- Delete `src/frontend/src/api/transformers/gemTransformer.ts`.
- Delete any `__tests__` files specifically for Gem (grep `gem` under `__tests__/`).
- Edit `src/frontend/src/types/index.ts`: remove `GemConfig` interface; remove `'gem'` from `ATSProvider` union; remove `GemConfig` from `Company.config` discriminated union.
- Edit `src/frontend/src/api/types.ts`: remove `GemJobResponse`; remove `ATSConstants.Gem`; remove `'gem'` from `APIError.atsProvider` union; remove `GemConfig` from `JobAPIClient.fetchJobs`.
- Edit `src/frontend/src/api/clients/baseClient.ts`: remove `GemConfig` from `ATSCompanyConfig` union and from APIError construction.
- Edit `src/frontend/src/features/app/appSlice.ts`: if default `selectedATS` was `Gem`, change to `BackendScraper`.
- Find and remove the `gem` branch in whatever module routes companies to a client (RTK Query `getJobsForCompany` endpoint or similar — likely `src/frontend/src/features/jobs/jobsApi.ts`).
- Remove the Gem MSW handler (search `src/frontend/src/__tests__/mocks/` for `gem` matches).
- Search-and-replace any remaining `'gem'` references in `src/frontend/src/` excluding intentional `sourceAts: 'gem'` lines and the Gem company display name `'Gem'`.

**Delete Vercel proxy:**
- Delete `api/gem.ts`.
- Update `vercel.json` (and/or `vercel.ts`) to remove the Gem rewrite/route definition.

**Doc updates:**
- Update root `CLAUDE.md`: remove Gem from "ATS APIs (Lever, Workday, Gem, Eightfold)"; update Vercel function list (remove `api/gem.ts`); add Gem to the backend-scraper provider list alongside Greenhouse/Ashby.
- Update `src/frontend/CLAUDE.md`: remove Gem from frontend client list; remove `createGemCompany()` from the factory list; update Vercel functions section; add Gem to the backend-scraper provider list.

**Tests:**
- `npm run type-check` clean across `src/frontend/`.
- `npm test` passes for all existing suites (Gem-specific suites are deleted; other suites should be unaffected by the dead-code removal).
- Manual verification: render Gem companies (Nominal, Retool, Gem) via `npm run dev:vercel -w src/frontend` and confirm jobs come from `/api/jobs?company=<id>`.

**Done when:**
- `npm run type-check` clean.
- `npm test` passes.
- `npm run dev:vercel -w src/frontend` — Gem companies (Nominal, Retool, Gem) render. Network tab shows `/api/jobs?company=<id>`, zero `/api/gem/*` requests.
- `grep -rE "GemConfig|gemClient|gemTransformer|createGemCompany|GemJobResponse" src/frontend/src/` returns zero matches (excluding any new `sourceAts: 'gem'` lines, which are intentional).
- `grep -n "api/gem" vercel.json vercel.ts 2>/dev/null` returns zero matches.
- Commit message: `Unit 7: cut Gem companies over to backend-scraper, delete legacy client/proxy`.

---

### Unit 8 — Why page Gem split

**Status:** DONE

**Note:** The atsGrouping.ts and types/index.ts changes the PLAN scoped to Unit 8 were folded into Unit 7 (see Unit 7 note for rationale). Unit 8 narrowed to WhyPage test additions only.

**Why 8th:** Bake in the equivalent of the Ashby Unit 8 split so we don't ship a follow-up cosmetic PR for Gem.

**Prerequisites:** Units 1, 2, 3, 4, 5, 6, 7.

**Owned files:**
- (none new)

**Shared-file edits:**
- `src/frontend/src/types/index.ts` — widen `sourceAts` from `'ashby' | 'greenhouse'` to `'ashby' | 'greenhouse' | 'gem'`
- `src/frontend/src/pages/WhyPage/atsGrouping.ts` — add `'gem'` to `ATSGroupKey`; add `gem: 'Gem'` display name; add `'gem'` to `NON_CAPITALIZED_GROUPS` if applicable (inspect during the unit)
- `src/frontend/src/config/companies.ts` — update the factory's `sourceAts` parameter type to `'ashby' | 'greenhouse' | 'gem'`
- `src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx` — new Gem column tests

**Changes:**
- Edit `src/frontend/src/types/index.ts`:
  - Widen `sourceAts?: 'ashby' | 'greenhouse'` to `sourceAts?: 'ashby' | 'greenhouse' | 'gem'`.
- Edit `src/frontend/src/config/companies.ts`:
  - Widen the `createBackendScraperCompany` options type for `sourceAts` accordingly.
- Edit `src/frontend/src/pages/WhyPage/atsGrouping.ts`:
  - Update `ATSGroupKey` to include `'gem'`.
  - Update `ATS_DISPLAY_NAMES`: add `gem: 'Gem'`.
  - Update `NON_CAPITALIZED_GROUPS` if it contains `ashby`/`greenhouse`: add `'gem'`.
  - `getATSGroupKey` already prefers `sourceAts` (post-Ashby Unit 9 retrofit) — no change needed to that function.
- Update WhyPage tests (`src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx`):
  - Add: "renders a dedicated Gem group containing only companies whose `sourceAts === 'gem'`".
  - Verify "Custom Web Scrapers group excludes Gem companies".
  - Verify existing "renders one ATS group header per distinct non-empty ATS group" passes with the expanded `ATSGroupKey`.

**Tests:**
- "renders a dedicated Gem group containing only companies whose `sourceAts === 'gem'`".
- "Custom Web Scrapers group excludes Gem companies (true custom scrapers only)".
- Existing "renders one ATS group header per distinct non-empty ATS group" still passes with the expanded `ATSGroupKey`.

**Done when:**
- `npm test -- WhyPage` passes.
- `npm run dev:vercel -w src/frontend` → navigate to `/why` → "Gem (3)" column renders with all 3 companies. "Custom Web Scrapers" column still contains only Google/Apple/Microsoft. Greenhouse + Ashby columns continue to render.
- Commit message: `Unit 8: split Gem into its own Why-page column`.

---

### Unit 9 — Reserved (no-op)

**Status:** TODO

**Why 9th:** Reserved slot for symmetry with the Ashby PLAN (Unit 9 there was the Greenhouse retrofit, which has already shipped). For the Gem migration, there is no equivalent retrofit needed — the `sourceAts` mechanism is already in place and Unit 8 widened the union. **This unit is a no-op marker:** mark DONE immediately with no commit. Keeps PLAN numbering aligned with Ashby for reviewer ergonomics.

**Prerequisites:** Units 1, 2, 3, 4, 5, 6, 7, 8.

**Owned files:**
- (none)

**Shared-file edits:**
- (none)

**Changes:**
- None. This unit exists for numbering parity with the Ashby PLAN. No code changes, no commit produced.

**Done when:**
- PLAN.md is updated to mark this unit `**Status:** DONE` with a brief note: "Skipped — no Greenhouse-style retrofit needed for Gem (sourceAts mechanism already in place from prior Ashby PR)."
- No commit is created for this unit. The next implementation unit picks up at Unit 10.

---

### Unit 10 — Deploy runbook + DEPLOY.md

**Status:** TODO

**Why 10th:** Document the operator steps. No code changes.

**Prerequisites:** Units 1, 2, 3, 4, 5, 6, 7, 8.

**Owned files:**
- `docs/implementations/gemBackendMigration/DEPLOY.md` (new)

**Shared-file edits:**
- (none)

**Changes:**
- New `docs/implementations/gemBackendMigration/DEPLOY.md` parallel to `docs/implementations/ashbyBackendMigration/DEPLOY.md`. Sections:
  - **Critical: Implicit Deploy Ordering** — backend (Railway) lands Units 1–6 BEFORE frontend (Vercel) flips to backend-scraper Units 7–8. Same asymmetry as Ashby.
  - **Pre-Merge Checklist** — env vars unchanged (Gem's public API requires no auth), migrations round-trip clean, backend pytest green, frontend type-check + tests green, no lingering Gem legacy references (grep list), `api/gem.ts` deleted, 3 Gem `sourceAts: 'gem'` tags counted.
  - **Deploy Sequence** — merge PR, watch Railway build logs (look for `queues=['greenhouse_fetch', 'ashby_fetch', 'gem_fetch']`), once Railway healthy hit `POST /api/jobs-qa/trigger-gem-fan-out` (curl example with admin Bearer token), then per-company `POST /api/jobs-qa/trigger-gem-fetch?company_id=retool`. Watch Vercel deploy.
  - **Post-Deploy Monitoring**:
    - `SELECT count(*) FROM companies WHERE ats='gem';` → 3.
    - `SELECT * FROM procrastinate_periodic_defers WHERE task_name='enqueue_gem_fan_out' ORDER BY defer_timestamp DESC LIMIT 5;`
    - `SELECT status, count(*) FROM procrastinate_jobs WHERE queue_name='gem_fetch' GROUP BY status;`
    - `SELECT count(*) FROM scrape_runs WHERE company IN (SELECT id FROM companies WHERE ats='gem') AND started_at > now() - interval '5 minutes';`
    - `SELECT company, count(*) FROM job_listings WHERE source_id='gem_api' GROUP BY company;`
  - **2-hour cross-reference**: `curl -s 'https://api.gem.com/job_board/v0/retool/job_posts/' | jq 'length'` vs `SELECT count(*) FROM job_listings WHERE source_id='gem_api' AND company='retool' AND status='OPEN';`
  - **Frontend smoke**: open `/companies`, switch to Nominal/Retool/Gem; network tab shows `/api/jobs?company=<id>`, zero `/api/gem/*` requests. Open `/why` → four columns: Ashby, Greenhouse, Gem, Custom Web Scrapers.
  - **Rollback**: revert the merge commit. Frontend goes back to direct Gem API calls (briefly broken since `api/gem.ts` was deleted in the merge — note this asymmetry in the runbook so operators know rollback also needs to restore that file).

**Tests:**
- N/A (docs only).

**Done when:**
- `docs/implementations/gemBackendMigration/DEPLOY.md` exists and matches the Ashby DEPLOY.md structure.
- Commit message: `Unit 10: add DEPLOY.md runbook for Gem backend migration`.

---

## Critical files

| File | Action | Unit |
|---|---|---|
| `scripts/shared/constants.py` | edit | 1 |
| `src/backend/alembic/versions/<ts>_seed_gem_companies.py` | new (hand-written data migration) | 2 |
| `src/backend/api/services/gem_client.py` | new | 3 |
| `src/backend/api/tasks/fetch_gem_company.py` | new | 4 |
| `src/backend/api/tasks/enqueue_gem_fan_out.py` | new | 5 |
| `src/backend/api/tasks/__init__.py` | edit (side-effect import) | 5 |
| `src/backend/api/main.py` | edit (queues list + log) | 5 |
| `src/backend/api/routers/jobs_qa.py` | edit (trigger endpoints) | 6 |
| `src/frontend/src/config/companies.ts` | edit (flip 3 Gem entries, drop factory) | 7 |
| `src/frontend/src/types/index.ts` | edit (drop `GemConfig`) | 7 |
| `src/frontend/src/api/clients/gemClient.ts` | **delete** | 7 |
| `src/frontend/src/api/transformers/gemTransformer.ts` | **delete** | 7 |
| `src/frontend/src/api/types.ts` | edit (drop Gem types) | 7 |
| `src/frontend/src/api/clients/baseClient.ts` | edit (drop `GemConfig` union member) | 7 |
| `api/gem.ts` | **delete** | 7 |
| `vercel.json` / `vercel.ts` | edit (route cleanup) | 7 |
| `CLAUDE.md`, `src/frontend/CLAUDE.md` | edit (docs) | 7 |
| `src/frontend/src/types/index.ts` | edit (widen `sourceAts`) | 8 |
| `src/frontend/src/pages/WhyPage/atsGrouping.ts` | edit (add `gem` key + display name) | 8 |
| `src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx` | edit (new Gem column tests) | 8 |
| `docs/implementations/gemBackendMigration/DEPLOY.md` | new | 10 |

---

## Existing utilities reused

- `scripts/shared/database.py`: `count_active_jobs`, `get_active_job_ids`, `upsert_jobs_batch`, `update_last_seen`, `increment_consecutive_misses`, `mark_jobs_closed`, `get_jobs_exceeding_miss_threshold`, `list_enabled_companies`, `record_scrape_run`, `get_connection`.
- `scripts/shared/incremental.py`: `MISSED_RUN_THRESHOLD`, `SAFETY_GUARD_RATIO`.
- `scripts/shared/models.py`: `JobListing`, `ScrapeRun`.
- `scripts/shared/utils.py`: `get_iso_timestamp`.
- `src/backend/api/tasks/procrastinate_app.py`: `procrastinate_app` singleton (no changes).
- `src/backend/api/routers/jobs.py`: `/api/jobs` endpoint (no changes — already serves anything in `companies`).
- `src/frontend/src/api/clients/backendScraperClient.ts`: per-company + batched fetch (no changes).
- `src/frontend/src/api/transformers/backendScraperTransformer.ts`: reads `details.experience_level` + `details.is_remote_eligible` (no changes — Gem populates `is_remote_eligible`; `experience_level` stays null).

---

## End-to-End Verification (after all 10 units, before review passes)

1. Local: `docker compose up -d postgres`; backend startup applies migrations + seed; worker log shows `queues=['greenhouse_fetch', 'ashby_fetch', 'gem_fetch']`.
2. `curl -X POST -H "Authorization: Bearer <admin>" 'http://localhost:8000/api/jobs-qa/trigger-gem-fan-out'` → 202.
3. Within ~30s: `psql -c "SELECT company, count(*) FROM job_listings WHERE source_id='gem_api' GROUP BY company ORDER BY 2 DESC;"` shows seeded Gem companies populated.
4. Frontend: `npm run dev:vercel -w src/frontend`. Open `/companies` → select Nominal, Retool, Gem → jobs render from `/api/jobs`. Network tab: zero `/api/gem/*` requests.
5. Open `/why` → "Gem (3)" column visible alongside Ashby, Greenhouse, Custom Web Scrapers.
6. Wait one cron interval (30 min). `SELECT count(*) FROM scrape_runs WHERE started_at > now() - interval '1 hour' AND company IN (SELECT id FROM companies WHERE ats='gem');` ≈ 3.
7. Simulate disappearance: monkeypatch a fetch response to drop one Gem job → after 2 cron cycles, that job's `status='CLOSED'`.
8. `cd src/backend && pytest` all green; coverage ≥ existing baseline.
9. `npm run type-check && npm test` clean.
10. `grep -rE "'gem'|GemConfig|createGemCompany|gemClient|gemTransformer|GemJobResponse" src/frontend/src/ api/ vercel.json vercel.ts` returns zero matches (excluding intentional `sourceAts: 'gem'` lines in companies.ts and the company display name `'Gem'`).

---

## Three Review Passes (handled by `/e2eimplementation`)

Each pass dispatches in parallel:

- `pr-review-toolkit:code-reviewer` (always)
- `pr-review-toolkit:silent-failure-hunter` (always)
- `pr-review-toolkit:pr-test-analyzer` (always)
- `pr-review-toolkit:type-design-analyzer` (Units 7+8 modify types — yes)
- `pr-review-toolkit:comment-analyzer` (only if comments added/changed; tasks units add comments)
- `vercel-prod-verifier` (Unit 7 deletes `api/gem.ts` + edits `vercel.json` — yes)
- `postgres-prod-verifier` (Unit 2 ships a migration; Units 3–5 add ORM queries — yes)
- `railway-prod-verifier` (Units 1–6 ship backend code — yes)

Findings consolidated in `docs/implementations/gemBackendMigration/REVIEW_AUDIT.md`. Fix agent runs between passes for Critical/Important items. Three passes regardless of pass-1 cleanliness.

---

## Non-goals

- **Migrating Lever / Workday / Eightfold to backend.** Each is a near-copy of this plan (own queue, own client, own task, own fan-out, own atsGrouping key + display name + `sourceAts` value).
- **Per-company observability dashboard.** `procrastinate_jobs` + `scrape_runs` are already queryable.
- **Removing `googleScraper` / `appleScraper` / `microsoftScraper` from the "Custom Web Scrapers" group.** They legitimately belong there since they're truly bespoke.
- **Renaming queues to a single shared `backend_fetch`.** Doable but renaming live queues mid-flight isn't free.
