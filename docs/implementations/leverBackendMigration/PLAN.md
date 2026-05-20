# Move Lever to Backend Cron + Queue

## Context

Lever is currently fetched statelessly from the browser: the frontend calls `https://api.lever.co/v0/postings/{company}` through the `api/lever.ts` Vercel CORS proxy, runs `leverTransformer.ts` client-side, and never persists anything. This is the same shape Greenhouse had before commit `92bfdf6` and Ashby had before commit `1d0d95a` (PR #120). The Ashby migration is the canonical exemplar — Lever is a near-copy of that plan substituting `'lever'` everywhere.

The Ashby/Greenhouse migrations established the pattern for JSON-only ATS providers:

- Per-company Procrastinate task with retries and queueing locks
- 30-minute periodic fan-out driven by Procrastinate's built-in `@app.periodic` cron
- Existing `companies` table holds `(id, display_name, ats, board_token, enabled)` — Lever just adds 3 more rows
- Existing `job_listings` composite PK `(source_id, id)` already supports multi-source coexistence
- Frontend cutover flips Lever entries from `createLeverCompany(...)` to `createBackendScraperCompany(...)` carrying a new `sourceAts: 'lever'` marker
- `atsGrouping.ts` already supports `sourceAts` (Ashby migration introduced it; Greenhouse retrofit removed URL-prefix detection in Unit 9 of that plan). Widening the union to `'ashby' | 'greenhouse' | 'lever'` and adding the display row is all the Why-page work needed.

**Outcome:** Lever jobs land in `job_listings` with `source_id = 'lever_api'`. The 3 Lever entries in `companies.ts` are flipped to `backend-scraper` carrying `sourceAts: 'lever'`. The Why page renders Lever in its own column. `api/lever.ts`, `leverClient.ts`, `leverTransformer.ts`, their tests, and all references to `'lever'` / `LeverConfig` in the frontend client-selection logic are removed.

---

## Decisions Locked

| Decision | Choice |
|---|---|
| Scope | Lever only. Workday/Gem/Eightfold stay frontend-stateless. |
| Source ID | `"lever_api"` (added to `SourceId` in `scripts/shared/constants.py`). |
| Procrastinate queue | New queue `"lever_fetch"` (separate from `"greenhouse_fetch"` and `"ashby_fetch"`). |
| Worker hosting | In-process; expand `main.py` worker to `queues=["greenhouse_fetch", "ashby_fetch", "lever_fetch"]`, concurrency stays at **5**. |
| Cron frequency | `*/30 * * * *` (matches Greenhouse/Ashby, no stagger). |
| Overlap policy | `queueing_lock=f"lever:{company_id}"` per per-company task. |
| ID format | Raw Lever id as string (`str(raw["id"])`) — no prefixing. Composite PK on `(source_id, id)` handles cross-source uniqueness. |
| `details` JSONB shape | Backend-scraper-frontend-compatible keys. Keys: `experience_level: None` (Lever doesn't expose), `is_remote_eligible: raw.get("workplaceType") == "remote"`, `employment_type: raw["categories"].get("commitment")`, `department: raw["categories"].get("department")`, `team: raw["categories"].get("team")`, `secondary_locations: []` (Lever doesn't expose), `compensation_summary: None` (Lever doesn't expose at this endpoint), `description_html: raw.get("descriptionPlain") or raw.get("description")`, `published_at: <ISO-from-ms>(raw.createdAt)`, `tags: sanitize_tags(raw.get("tags") or [])` (tags array can contain mixed types — flatten / coerce to strings). |
| `posted_on` source | `raw["createdAt"]` (Unix milliseconds) → ISO 8601 UTC string. Local helper `_ms_to_iso8601` (~10 lines) — distinct from Ashby's `_normalize_iso8601` because Lever ships epoch-ms, not an ISO string. |
| Seed migration | Hand-written Alembic data migration `seed_lever_companies.py` (one acceptable hand-write — data migrations are not autogenerable). 3 rows `(id, display_name, ats='lever', board_token=<lever-slug>, enabled=true)`. |
| Frontend cutover | Each `createLeverCompany(id, name, opts)` → `createBackendScraperCompany(id, name, jobsUrl, { ..., sourceAts: 'lever' })`. Default `jobsUrl` for Lever was `https://jobs.lever.co/${id}` — preserve verbatim per company. Preserve `recruiterLinkedInUrl`. |
| Lever grouping on Why page | Widen `sourceAts` union in `Company` type to include `'lever'`. `atsGrouping.ts` adds `'lever'` to `ATSGroupKey`, `ATS_DISPLAY_NAMES`, and `NON_CAPITALIZED_GROUPS`. `getATSGroupKey` already prefers `sourceAts` (since Ashby Unit 9) — no logic changes there. |
| Vercel proxy deletion | Delete `api/lever.ts` + any test files at the end of the frontend cutover unit. Once all 3 Lever entries are backend-scraper, the proxy is dead code. |
| Frontend dead-code deletion | Delete `leverClient.ts`, `leverTransformer.ts`, their test files. Remove `LeverConfig`/`LeverJobResponse`/`ATSConstants.Lever` from `types/index.ts` and `api/types.ts`. Remove `'lever'` from `ATSProvider` and from `ATSCompanyConfig` unions in `baseClient.ts`. If `appSlice.ts` defaults `selectedATS` to `Lever`, change to `BackendScraper`. |
| QAPage UI | Match what Greenhouse + Ashby have. The implementation agent inspects QAPage during Unit 6 and adds Lever trigger UI iff Greenhouse/Ashby have their own. |
| Tags handling | Lever's `tags` field is `(string | string[] | null)[]` — frontend uses `sanitizeTags(raw.tags)` helper. Backend transformer must mirror that flatten-and-coerce behavior so `details.tags` is always `list[str]`. Implementation agent ports `sanitizeTags` logic into a private `_sanitize_tags` helper in `lever_client.py`. |
| Skipped unit (Unit 9 in Ashby plan) | Ashby's Unit 9 retrofitted Greenhouse to `sourceAts`. Lever has no analogous predecessor to retrofit — Greenhouse + Ashby already use `sourceAts`. **Lever PLAN has 9 units, not 10.** Renumber accordingly: Ashby's Unit 10 (DEPLOY.md) is Lever's Unit 9. |
| Deploy gap mitigation | One PR (all 9 units). DEPLOY.md instructs the operator to hit `POST /api/jobs-qa/trigger-lever-fan-out` immediately after Railway finishes deploying the backend units so the first batch lands within ~30s instead of waiting up to 30 min for the cron. |
| Feature directory slug | `leverBackendMigration` (matches `ashbyBackendMigration` and `greenhouseBackendMigration` siblings). |
| Default ATS in appSlice | Inspect during Unit 7. If Lever was the default, change to `BackendScraper`. |

---

## Repo Constraints (must follow)

- **Alembic autogenerate only.** Edit `src/backend/api/db_models.py` → `alembic revision --autogenerate` → review. Never hand-write migration files. Exception: data migrations (the seed in Unit 2). Memory: `feedback_use_alembic_migrations.md`.
- **No full-table rewrites.** This plan doesn't add columns to `job_listings` or `companies`. Only INSERTs.
- **Bare table names.** `companies` and `job_listings` are env-agnostic.
- **Correctness over "don't crash"**: narrow exception handling in tasks (catch only `httpx.HTTPError`, `ValueError`, `psycopg2.Error`); programmer errors propagate. Memory: `feedback_correctness_over_dont_crash.md`.
- **Stay inside owned files per unit.** Each unit's "Owned files" / "Shared-file edits" lists are the boundary. Touching unlisted files is a stop-and-ask trigger.
- **Async endpoints must use `Depends(get_db)` and `asyncio.to_thread`** for any sync DB calls — caught in the Greenhouse PR Pass 1 review. Trigger endpoints in Unit 6 must follow this.
- **Admin gating**: every new trigger endpoint uses `Depends(require_admin)` — caught in Greenhouse PR Pass 2.

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
│                queues=["greenhouse_fetch", "ashby_fetch", "lever_fetch"],        │
│                concurrency=5))                                                   │
│                                                                                  │
│   New tasks (import-side-effect registered on procrastinate_app):                │
│     @app.periodic(cron="*/30 * * * *", periodic_id="lever_fan_out")              │
│     @app.task(queue="lever_fetch", retry=RetryStrategy(3, 2))                    │
│     async def enqueue_lever_fan_out(timestamp: int) -> int:                      │
│         companies = db.list_enabled_companies(conn, "lever")                     │
│         for c in companies:                                                      │
│             await fetch_lever_company.configure(                                 │
│                 queueing_lock=f"lever:{c['id']}"                                 │
│             ).defer_async(company_id=c['id'], board_token=c['board_token'])      │
│                                                                                  │
│     @app.task(queue="lever_fetch", retry=RetryStrategy(5, 2))                    │
│     async def fetch_lever_company(company_id, board_token):                      │
│         # Identical 5-phase shape to fetch_ashby_company:                        │
│         # to_thread(get_connection) → fetch_jobs → transform → safety_guard      │
│         # → upsert → update_last_seen → increment_consecutive_misses             │
│         # → mark_jobs_closed → record_scrape_run                                 │
└──────────────────────────────────────────────────────────────────────────────────┘

Frontend cutover (Unit 7): companies.ts entries flip lever → backend-scraper, each carrying sourceAts: 'lever'.
Frontend calls `/api/jobs?company=palantir` — same endpoint already used for Greenhouse + Ashby + Google/Apple/Microsoft.
api/lever.ts is deleted in Unit 7.

Why page split (Unit 8): widens sourceAts to 'ashby' | 'greenhouse' | 'lever', adds Lever section to atsGrouping.ts.
```

---

## Race Condition / Deadlock Audit

Identical analysis to the Ashby plan — repeating here for self-containedness:

| Risk | Mitigation |
|---|---|
| Two workers pick the same task | Procrastinate uses `SELECT … FOR UPDATE SKIP LOCKED` on `procrastinate_jobs`. Impossible by design. |
| Cron fires while prior batch still draining | `queueing_lock=f"lever:{company_id}"` per-task. Procrastinate refuses to enqueue a second task with the same lock while one is pending/running. |
| Periodic task itself fires twice (e.g. two FastAPI replicas) | Procrastinate's periodic scheduler holds a Postgres advisory lock; only one replica's worker takes a given periodic firing. |
| Concurrent upserts to same `job_listings (source_id, id)` | `ON CONFLICT (source_id, id) DO UPDATE` in `upsert_jobs_batch`. Composite PK keeps Lever and other ATSes from colliding even if raw IDs overlap. |
| Manual trigger races with cron | Both go through `fetch_lever_company.configure(queueing_lock=...).defer_async(...)`. Lock dedupes. |
| Partial fetch (e.g. Lever returns 0 of 500 jobs) closes everything | `SAFETY_GUARD_RATIO = 0.1` in `incremental.py` — port the check into the new task. If scraped count < 10% of active, skip close phase, mark run as failed, no destructive writes. |
| Migration startup race (2 replicas booting) | Alembic uses a Postgres advisory lock; second replica's `apply_alembic_migrations()` is a no-op. Procrastinate's `app.open_async()` is also idempotent. |
| Worker dies mid-task | Procrastinate's task state goes back to `todo` after a heartbeat timeout. `RetryStrategy(max_attempts=5)` handles it. Task is idempotent: `upsert_jobs_batch` + `ON CONFLICT` means a re-run sees the same end state. |
| Three ATS fan-outs fire at the same `*/30 * * * *` tick → pile onto 5 worker slots | Worker concurrency=5 + per-company `queueing_lock` means up to 5 companies fetch in parallel, the rest queue. Each per-company task is fast (~1s of HTTP + ~200ms of DB writes). Empirically drains in ~1 minute. No deadlock: every task acquires the same connection-pool resource without inter-task lock ordering. |

No deadlocks possible — there's no multi-row locking ordered differently between tasks.

---

## Schema (no DDL changes)

The `companies` table already supports Lever — `ats` is a free-form `Text` column. The only schema-touching migration in this plan is the data-migration seed of the 3 Lever company rows.

`job_listings` is unchanged: composite PK `(source_id, id)`, `consecutive_misses`, `status`, `closed_on`, `last_seen_at` all exist. The `details` JSONB column accepts arbitrary shape.

---

## Shared Contracts

The following contracts are frozen for the duration of this plan. Every Unit reads them; no Unit changes them without first changing this section.

**HTTP — Lever Postings fetch**

```
GET https://api.lever.co/v0/postings/{board_token}?mode=json
Timeout: 30s
Response: list[dict] (Lever returns a top-level JSON array, NOT wrapped in an object)
```

`fetch_jobs(board_token, http)` raises `httpx.HTTPStatusError` on non-2xx and `ValueError` on non-list response root.

**`details` JSONB shape (written by `transform_to_job_listings`, consumed by `backendScraperTransformer.ts`)**

```python
{
    "department": (raw.get("categories") or {}).get("department"),
    "team": (raw.get("categories") or {}).get("team"),
    "secondary_locations": [],  # Lever doesn't expose
    "employment_type": (raw.get("categories") or {}).get("commitment"),
    "is_remote_eligible": raw.get("workplaceType") == "remote",
    "compensation_summary": None,  # Lever doesn't expose at postings endpoint
    "published_at": _ms_to_iso8601(raw.get("createdAt")),
    "description_html": raw.get("descriptionPlain") or raw.get("description"),
    "experience_level": None,
    "tags": _sanitize_tags(raw.get("tags") or []),
}
```

**`JobListing` row shape (per-row written to `job_listings`)**

| Field | Source |
|---|---|
| `source_id` | `SourceId.LEVER` = `"lever_api"` |
| `id` | `str(raw["id"])` (raw Lever id, no prefix) |
| `company` | `company_id` (Lever `companies.id`) |
| `title` | `raw["text"]` |
| `url` | `raw["hostedUrl"]` |
| `location` | `(raw.get("categories") or {}).get("location")` |
| `posted_on` | `_ms_to_iso8601(raw["createdAt"])` (epoch ms → ISO 8601 UTC) |
| `details` | JSONB shape above |
| `status` | (managed by `upsert_jobs_batch` / `mark_jobs_closed`) |
| `last_seen_at` | (managed by `update_last_seen`) |
| `consecutive_misses` | (managed by `increment_consecutive_misses`) |

**Procrastinate task signatures**

```python
@procrastinate_app.task(
    queue="lever_fetch",
    name="fetch_lever_company",
    retry=RetryStrategy(max_attempts=5, exponential_wait=2),
)
async def fetch_lever_company(company_id: str, board_token: str) -> None: ...

@procrastinate_app.periodic(cron="*/30 * * * *", periodic_id="lever_fan_out")
@procrastinate_app.task(
    queue="lever_fetch",
    name="enqueue_lever_fan_out",
    retry=RetryStrategy(max_attempts=3, exponential_wait=2),
)
async def enqueue_lever_fan_out(timestamp: int) -> int: ...
```

**Queueing lock format**

`queueing_lock=f"lever:{company_id}"` — applied at `defer_async` site (both the periodic fan-out and the admin trigger endpoint). Per-company isolation; never global. Greenhouse uses `greenhouse:{company_id}`, Ashby uses `ashby:{company_id}` — the three ATSes never share locks.

**`Company.sourceAts` field shape (frontend `Company` type)**

```ts
// Before this PR (current state after Ashby PR #120):
sourceAts?: 'ashby' | 'greenhouse';

// Unit 7 widens the union to include Lever:
sourceAts?: 'ashby' | 'greenhouse' | 'lever';
```

The field is optional throughout. Only Greenhouse/Ashby/Lever `backend-scraper` rows carry it. Google/Apple/Microsoft `backend-scraper` rows do NOT carry it (they remain in "Custom Web Scrapers" on the Why page).

---

## Work Units

9 sequential units. Order is load-bearing. Each unit is independently committable.

### Unit 1 — `SourceId.LEVER` constant

**Status:** DONE

**Why 1st:** Single shared constant every other unit imports. Tiny, fast, low-risk. Verifies the constants file is the right shape before the larger units depend on it.

**Prerequisites:** None.

**Owned files:**
- `scripts/shared/constants.py` (edit) — add `LEVER` to `SourceId`

**Shared-file edits:**
- (none)

**Changes:**
- `scripts/shared/constants.py`: add `LEVER: Final[str] = "lever_api"` to `SourceId`.

**Tests:**
- Smoke-test import in an existing constants test (if present) or rely on `pytest -q` collection to load the module.

**Done when:**
- `cd src/backend && pytest -q` passes.
- `python -c "from scripts.shared.constants import SourceId; print(SourceId.LEVER)"` prints `lever_api`.
- Commit message: `Unit 1: add SourceId.LEVER constant`.

---

### Unit 2 — Seed Lever companies (Alembic data migration)

**Status:** DONE

**Why 2nd:** The fan-out task needs row source.

**Prerequisites:** Unit 1.

**Owned files:**
- `src/backend/alembic/versions/<ts>_seed_lever_companies.py` (new, hand-written data migration)

**Shared-file edits:**
- `src/backend/api/tests/test_migration_companies.py` — extend with Lever seed coverage (mirror the Greenhouse + Ashby cases already in the file)

**Changes:**
- Hand-written Alembic data migration `<ts>_seed_lever_companies.py` mirroring `20260517_220000_a17b7c0ffee500_seed_ashby_companies.py`.
- `down_revision` chains to the most recent migration on `main` (`a17b7c0ffee500` — verify with `alembic heads` during implementation).
- `upgrade()`: `op.execute(insert_sql, row)` of 3 rows transcribed from `src/frontend/src/config/companies.ts` lines 350–362. Each row: `(id, display_name, ats='lever', board_token=<lever-slug>)`. Use `ON CONFLICT (id) DO NOTHING` for idempotency on re-runs against pre-existing data. `enabled` omitted (server_default=true).
  - Rows: `('palantir', 'Palantir', 'lever', 'palantir')`, `('spotify', 'Spotify', 'lever', 'spotify')`, `('zoox', 'Zoox', 'lever', 'zoox')`.
- `downgrade()`: `DELETE FROM companies WHERE ats='lever'`.

**Tests:**
- `upgrade head` seeds 3 rows where `ats='lever'`.
- Round-trip `upgrade head → downgrade -1 → upgrade head` is idempotent.

**Done when:**
- `cd src/backend && pytest api/tests/test_migration_companies.py -v` is green.
- `SELECT count(*) FROM companies WHERE ats='lever';` returns 3 after `alembic upgrade head`.
- Commit message: `Unit 2: seed 3 Lever companies via Alembic data migration`.

---

### Unit 3 — Lever fetch helper (pure module)

**Status:** DONE

**Why 3rd:** Isolate HTTP + transform layer for unit testing without queue plumbing.

**Prerequisites:** Unit 1.

**Owned files:**
- `src/backend/api/services/lever_client.py` (new)
- `src/backend/api/tests/test_lever_client.py` (new)

**Shared-file edits:**
- (none)

**Changes:**
- New `src/backend/api/services/lever_client.py`. Mirror `ashby_client.py` structure exactly:
  - `SOURCE_ID = SourceId.LEVER`
  - `LEVER_BASE_URL = "https://api.lever.co/v0/postings"`
  - `DEFAULT_TIMEOUT_SECONDS = 30.0`
  - `async def fetch_jobs(board_token: str, http: httpx.AsyncClient) -> list[dict]`: GET `{LEVER_BASE_URL}/{board_token}?mode=json`. Raises on non-2xx. **Lever returns a top-level JSON array** (not a `{"jobs": [...]}` wrapper) — validate `isinstance(payload, list)`, raise `ValueError` if not.
  - `def transform_to_job_listings(company_id: str, raw_jobs: list[dict]) -> list[JobListing]`: maps each raw Lever job to a `JobListing`. `id = str(raw["id"])`. Populates `details`:
    ```python
    cats = raw.get("categories") or {}
    {
        "department": cats.get("department"),
        "team": cats.get("team"),
        "secondary_locations": [],
        "employment_type": cats.get("commitment"),
        "is_remote_eligible": raw.get("workplaceType") == "remote",
        "compensation_summary": None,
        "published_at": _ms_to_iso8601(raw.get("createdAt")),
        "description_html": raw.get("descriptionPlain") or raw.get("description"),
        "experience_level": None,
        "tags": _sanitize_tags(raw.get("tags") or []),
    }
    ```
  - `posted_on` parsed from `raw["createdAt"]` (Unix milliseconds) via local `_ms_to_iso8601` helper (~10 lines, distinct from Ashby's `_normalize_iso8601`).
  - `url = raw["hostedUrl"]`, `title = raw["text"]`, `location = cats.get("location")`.
  - Private helpers:
    - `_ms_to_iso8601(value: int | None) -> Optional[str]`: takes epoch ms, returns ISO 8601 UTC string. Returns `None` on `None` or non-int input. Uses `datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat()`.
    - `_sanitize_tags(raw_tags: list) -> list[str]`: flattens `(string | string[] | null)[]` to `list[str]`. Mirrors frontend `sanitizeTags`. Drop `None`/empty strings, coerce to str, dedupe while preserving order.

**Tests:**
- Happy path with a fixture from a real Lever response (e.g. `palantir`).
- `fetch_jobs` raises `ValueError` on non-list root response.
- `fetch_jobs` raises `httpx.HTTPStatusError` on 5xx.
- `transform_to_job_listings`: id format (always string even if int), `posted_on` UTC normalization from epoch-ms, `is_remote_eligible` truthy on `workplaceType='remote'`, falsy on `workplaceType='onsite'` and missing/unspecified, all `details` keys present, `description_html` falls back to `description` when `descriptionPlain` missing, `experience_level` always `None`.
- `_sanitize_tags`: flattens `["a", ["b", "c"], null, ""]` → `["a", "b", "c"]`; preserves order; deduplicates.
- `_ms_to_iso8601`: 1714857600000 → `"2024-05-04T20:00:00+00:00"` (or equivalent); `None` → `None`; non-int → `None`.

**Done when:**
- `cd src/backend && pytest api/tests/test_lever_client.py -v` is green.
- Commit message: `Unit 3: add Lever fetch + transform client`.

---

### Unit 4 — `fetch_lever_company` task

**Status:** DONE

**Why 4th:** The per-company worker. Depends on Units 1, 2, 3.

**Prerequisites:** Units 1, 2, 3.

**Owned files:**
- `src/backend/api/tasks/fetch_lever_company.py` (new)
- `src/backend/api/tests/test_fetch_lever_company.py` (new)

**Shared-file edits:**
- (none)

**Changes:**
- New `src/backend/api/tasks/fetch_lever_company.py`. **Structurally copy `fetch_ashby_company.py`**, substituting:
  - Imports from `..services.lever_client` instead of `..services.ashby_client`.
  - `@procrastinate_app.task(queue="lever_fetch", name="fetch_lever_company", retry=RetryStrategy(max_attempts=5, exponential_wait=2))`
  - Function name: `async def fetch_lever_company(company_id: str, board_token: str) -> None`.
  - Log prefix: `fetch_lever_company`.
  - Everything else identical: same `asyncio.to_thread` wrapping, same `asyncio.shield` for connection acquisition, same `SAFETY_GUARD_RATIO` guard, same 5-step DB sequence (upsert → update_last_seen → increment_consecutive_misses → mark_jobs_closed → record_scrape_run), same fallback-connection logic for `record_scrape_run`, same narrow-exception handling (`httpx.HTTPError`, `ValueError`, `psycopg2.Error` only — programmer errors propagate).

**Tests:**
- Happy path: 3 raw jobs → 3 upserted, scrape_run recorded.
- Re-run with existing job missing → `consecutive_misses=1` → re-run → `consecutive_misses=2` → marked CLOSED.
- Safety guard: 0 jobs returned with 100 active → no writes, run logged with `error_count=1`.
- HTTPX 5xx → task raises → Procrastinate retries.
- Fallback connection path on `record_scrape_run` primary failure.
- Programmer error (AttributeError) propagates without being caught.

**Done when:**
- `cd src/backend && pytest api/tests/test_fetch_lever_company.py -v` is green.
- Commit message: `Unit 4: add fetch_lever_company Procrastinate task`.

---

### Unit 5 — Periodic fan-out + worker queue expansion

**Status:** DONE

**Why 5th:** Connects the cron to the per-company worker. Last backend change before the frontend cutover.

**Prerequisites:** Units 1, 2, 3, 4.

**Owned files:**
- `src/backend/api/tasks/enqueue_lever_fan_out.py` (new)
- `src/backend/api/tests/test_enqueue_lever_fan_out.py` (new)

**Shared-file edits:**
- `src/backend/api/tasks/__init__.py` — side-effect import for `enqueue_lever_fan_out` and `fetch_lever_company` (mirror existing Ashby import pattern)
- `src/backend/api/main.py` line 146: change `queues=["greenhouse_fetch", "ashby_fetch"]` → `queues=["greenhouse_fetch", "ashby_fetch", "lever_fetch"]`. Update info log on line 151 accordingly.

**Changes:**
- New `src/backend/api/tasks/enqueue_lever_fan_out.py`. Structurally copy `enqueue_ashby_fan_out.py`, substituting:
  - `@procrastinate_app.periodic(cron="*/30 * * * *", periodic_id="lever_fan_out")`
  - `@procrastinate_app.task(queue="lever_fetch", name="enqueue_lever_fan_out", retry=RetryStrategy(max_attempts=3, exponential_wait=2))`
  - `db.list_enabled_companies(conn, "lever")`
  - Defers `fetch_lever_company.configure(queueing_lock=f"lever:{c['id']}").defer_async(...)`.
  - Same per-company error isolation: catch `AlreadyEnqueued`, `ConnectorException`, `psycopg2.Error`; let programmer errors propagate.
- `src/backend/api/main.py` line 146: change queues list as noted above. Update info log on line 151 accordingly.
- `src/backend/api/tasks/__init__.py`: add side-effect imports for `enqueue_lever_fan_out` and `fetch_lever_company`. Verify the existing import pattern for Ashby and mirror it.

**Tests:**
- Defers one job per enabled Lever company; skips disabled.
- Re-run within window: `AlreadyEnqueued` raised per company, loop continues.
- Per-company connector error: loop isolation (next company still gets deferred).
- Programmer error (AttributeError) propagates.

**Done when:**
- `cd src/backend && pytest api/tests/test_enqueue_lever_fan_out.py -v` is green.
- Manual smoke: start backend, log line shows `queues=['greenhouse_fetch', 'ashby_fetch', 'lever_fetch']`.
- Commit message: `Unit 5: add Lever periodic fan-out and expand worker queues`.

---

### Unit 6 — Admin trigger endpoints

**Status:** DONE

**Why 6th:** QA + emergency tooling. Mirrors Ashby trigger endpoints. Required by DEPLOY.md's "trigger fan-out manually right after deploy" step.

**Prerequisites:** Units 1, 2, 3, 4, 5.

**Owned files:**
- (none new — extends existing router)

**Shared-file edits:**
- `src/backend/api/routers/jobs_qa.py` — add `POST /trigger-lever-fetch` and `POST /trigger-lever-fan-out`.
- `src/backend/api/tests/test_jobs_qa_router.py` — extend with the four Lever cases below.
- (conditional) `src/frontend/src/pages/QAPage/QAPage.tsx` — only if QAPage has dedicated Greenhouse/Ashby trigger UI; mirror it for Lever.

**Changes:**
- Extend `src/backend/api/routers/jobs_qa.py`:
  - `POST /api/jobs-qa/trigger-lever-fetch?company_id=<id>` — admin-only (`Depends(require_admin)`). Verifies company exists with `ats='lever'`. 404 if missing. Defers `fetch_lever_company` with `queueing_lock=f"lever:{company_id}"`. Returns 202 with `{enqueued, already_enqueued}`. Uses `Depends(get_db)` for any sync DB check, wrapped in `asyncio.to_thread`.
  - `POST /api/jobs-qa/trigger-lever-fan-out` — admin-only. Defers `enqueue_lever_fan_out` directly. Returns 202.
- If QAPage has dedicated Greenhouse/Ashby trigger UI (inspect during this unit), add Lever equivalents. If those are API-only on QAPage, leave UI alone.

**Tests:**
- 401/403 without admin token.
- 404 for unknown company.
- 202 + `enqueued=true` happy path.
- 202 + `already_enqueued=true` on second call with same lock.

**Done when:**
- `cd src/backend && pytest api/tests/test_jobs_qa_router.py -v` is green.
- `curl -X POST -H "Authorization: Bearer <admin>" http://localhost:8000/api/jobs-qa/trigger-lever-fetch?company_id=palantir` → 202.
- Commit message: `Unit 6: add Lever admin trigger endpoints`.

---

### Unit 7 — Frontend cutover

**Status:** DONE

**Why 7th:** Backend now serves Lever data. Point the UI at it and delete the old code paths.

**Prerequisites:** Units 1, 2, 3, 4, 5, 6.

**Owned files (delete):**
- `src/frontend/src/api/clients/leverClient.ts` (delete)
- `src/frontend/src/api/transformers/leverTransformer.ts` (delete)
- `src/frontend/src/__tests__/api/transformers/leverTransformer.test.ts` (delete iff exists)
- `src/frontend/src/__tests__/api/clients/leverClient.test.ts` (delete iff exists)
- `src/frontend/src/__tests__/api/serverless/lever.serverless.test.ts` (delete iff exists)
- `api/lever.ts` (delete)

**Shared-file edits:**
- `src/frontend/src/config/companies.ts` — flip 3 Lever entries to `createBackendScraperCompany(..., { ..., sourceAts: 'lever' })`; remove `createLeverCompany` factory function (lines ~21–44)
- `src/frontend/src/types/index.ts` — widen `sourceAts` union to `'ashby' | 'greenhouse' | 'lever'`; remove `LeverConfig` interface; remove `'lever'` from `ATSProvider` union; remove `LeverConfig` from `Company.config` discriminated union
- `src/frontend/src/api/types.ts` — remove `LeverJobResponse`; remove `ATSConstants.Lever` if it exists; remove `'lever'` from `APIError.atsProvider` union
- `src/frontend/src/api/clients/baseClient.ts` — remove `LeverConfig` from `ATSCompanyConfig` union and from APIError construction
- `src/frontend/src/features/app/appSlice.ts` — if default `selectedATS` was `Lever`, change to `BackendScraper`
- `vercel.json` / `vercel.ts` — remove the Lever route definition (if present)
- `CLAUDE.md` (root) — remove Lever from "ATS APIs (Lever, Workday, Gem, Eightfold)" list; update Vercel function list (remove `api/lever.ts`)
- `src/frontend/CLAUDE.md` — remove Lever from frontend client list; remove `createLeverCompany()` from the factory list; update Vercel functions section

**Changes:**

**Companies config (`src/frontend/src/config/companies.ts`):**
- For each of the 3 `createLeverCompany(id, name, opts)` entries (lines ~350–362), replace with `createBackendScraperCompany(id, name, 'https://jobs.lever.co/<id>', { sourceAts: 'lever', recruiterLinkedInUrl: <opts.recruiterLinkedInUrl> })`.
- Remove the `createLeverCompany` factory function definition (lines ~21–44) entirely.
- Remove `LeverConfig` import.

**`sourceAts` union widening:**
- Edit `src/frontend/src/types/index.ts`: change `sourceAts?: 'ashby' | 'greenhouse'` to `sourceAts?: 'ashby' | 'greenhouse' | 'lever'`.

**Remove Lever dead code:**
- Delete `src/frontend/src/api/clients/leverClient.ts`.
- Delete `src/frontend/src/api/transformers/leverTransformer.ts`.
- Delete `src/frontend/src/__tests__/api/transformers/leverTransformer.test.ts` (if it exists).
- Delete `src/frontend/src/__tests__/api/clients/leverClient.test.ts` (if it exists).
- Delete `src/frontend/src/__tests__/api/serverless/lever.serverless.test.ts` (if it exists).
- Edit `src/frontend/src/types/index.ts`: remove `LeverConfig` interface; remove `'lever'` from `ATSProvider` union; remove `LeverConfig` from `Company.config` discriminated union.
- Edit `src/frontend/src/api/types.ts`: remove `LeverJobResponse`; remove `ATSConstants.Lever` (if it exists); remove `'lever'` from `APIError.atsProvider` union.
- Edit `src/frontend/src/api/clients/baseClient.ts`: remove `LeverConfig` from `ATSCompanyConfig` union and from APIError construction.
- Edit `src/frontend/src/features/app/appSlice.ts`: if default `selectedATS` was `Lever`, change to `BackendScraper`.
- Search-and-replace any remaining `'lever'` / `LeverConfig` references in `src/frontend/src/` (excluding new `sourceAts: 'lever'` lines which are intentional).

**Delete Vercel proxy:**
- Delete `api/lever.ts`.
- Update `vercel.json` (and/or `vercel.ts`) to remove the Lever route definition if present.

**MSW handlers:**
- Grep for Lever MSW handlers under `src/frontend/src/__tests__/` (commonly in a `handlers.ts` or `mocks/` file). Remove any handlers targeting `api.lever.co` or `/api/lever/*`.

**Doc updates:**
- Update root `CLAUDE.md`: remove Lever from "ATS APIs (Lever, Workday, Gem, Eightfold)" list; update Vercel function list (remove `api/lever.ts`).
- Update `src/frontend/CLAUDE.md`: remove Lever from frontend client list; remove `createLeverCompany()` from the factory list; update Vercel functions section.

**Tests:**
- `npm run type-check` clean across `src/frontend/`.
- `npm test` passes for all existing suites.
- Manual verification: render Lever companies (Palantir, Spotify, Zoox) via `npm run dev:vercel -w src/frontend` and confirm jobs come from `/api/jobs?company=<id>`.

**Done when:**
- `npm run type-check` clean.
- `npm test` passes.
- `npm run dev:vercel -w src/frontend` — Lever companies (Palantir, Spotify, Zoox) render. Network tab shows `/api/jobs?company=<id>`, zero `/api/lever/*` requests.
- `grep -rE "LeverConfig|leverClient|leverTransformer|createLeverCompany|'lever'\b" src/frontend/src/` returns zero matches (excluding intentional `sourceAts: 'lever'` lines, which are expected).
- Commit message: `Unit 7: cut Lever companies over to backend-scraper, delete legacy client/proxy`.

---

### Unit 8 — Why page Lever split

**Status:** DONE

**Why 8th:** Add Lever to the Why-page provider grouping so Lever companies appear in their own column instead of "Custom Web Scrapers".

**Prerequisites:** Units 1, 2, 3, 4, 5, 6, 7.

**Owned files:**
- (none new)

**Shared-file edits:**
- `src/frontend/src/pages/WhyPage/atsGrouping.ts` — add `'lever'` to `ATSGroupKey`, `ATS_DISPLAY_NAMES` (`lever: 'Lever'`), `NON_CAPITALIZED_GROUPS`
- `src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx` — new Lever column tests

**Changes:**
- Edit `src/frontend/src/pages/WhyPage/atsGrouping.ts`:
  - Update `ATSGroupKey` to include `'lever'`: `type ATSGroupKey = Company['ats'] | 'greenhouse' | 'ashby' | 'lever'`.
  - `getATSGroupKey` already prefers `sourceAts` (Ashby migration Unit 9 — `if (company.ats === 'backend-scraper' && company.sourceAts) return company.sourceAts`). No logic change needed.
  - Update `ATS_DISPLAY_NAMES`: add `lever: 'Lever'`.
  - Update `NON_CAPITALIZED_GROUPS`: add `'lever'` (display name is already cased, don't `textTransform: capitalize` it).
- Update WhyPage tests (`src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx`):
  - Add: "renders a dedicated Lever group containing only companies whose `sourceAts === 'lever'`".
  - Add: "Custom Web Scrapers group excludes Lever companies (true custom scrapers only)".
  - Verify existing "renders one ATS group header per distinct non-empty ATS group" passes with the expanded `ATSGroupKey`.

**Tests:**
- "renders a dedicated Lever group containing only companies whose `sourceAts === 'lever'`".
- "Custom Web Scrapers group excludes Lever companies (true custom scrapers only)".
- Existing "renders one ATS group header per distinct non-empty ATS group" still passes.

**Done when:**
- `npm test -- WhyPage` passes.
- `npm run dev:vercel -w src/frontend` → navigate to `/why` → "Lever (3)" column renders with Palantir, Spotify, Zoox. "Custom Web Scrapers" column unchanged (Google/Apple/Microsoft).
- Commit message: `Unit 8: split Lever into its own Why-page column`.

---

### Unit 9 — Deploy runbook + DEPLOY.md

**Status:** DONE

**Why 9th:** Document the operator steps. No code changes.

**Prerequisites:** Units 1, 2, 3, 4, 5, 6, 7, 8.

**Owned files:**
- `docs/implementations/leverBackendMigration/DEPLOY.md` (new)

**Shared-file edits:**
- (none)

**Changes:**
- New `docs/implementations/leverBackendMigration/DEPLOY.md` parallel to `docs/implementations/ashbyBackendMigration/DEPLOY.md`. Sections:
  - **Merge order**: single PR, all 9 commits land at once. Railway auto-deploys backend; Vercel auto-deploys frontend.
  - **Pre-merge check (local)**: `cd src/backend && pytest`, `npm run type-check`, `npm test`.
  - **Post-merge operator action** (the critical step): right after Railway shows "deploy succeeded" on the merge commit's SHA, hit `POST /api/jobs-qa/trigger-lever-fan-out` (curl example with admin Bearer token). This populates `job_listings` within ~30s instead of waiting up to 30 min for the next cron tick. Without this step, anyone who navigates to a Lever company page (Palantir, Spotify, Zoox) during the gap window sees an empty list.
  - **Monitoring queries**:
    - `SELECT count(*) FROM companies WHERE ats='lever';` → 3.
    - 30 min post-deploy: `SELECT count(*) FROM scrape_runs WHERE company IN (SELECT id FROM companies WHERE ats='lever') AND started_at > now() - interval '1 hour';` ≈ 3.
    - 2 hours post-deploy: `SELECT count(*) FROM job_listings WHERE source_id='lever_api' AND company='palantir';` ≥ Lever API count for Palantir.
    - Worker health: `SELECT status, count(*) FROM procrastinate_jobs WHERE queue_name='lever_fetch' GROUP BY status;`
  - **Rollback**: revert the merge commit. Frontend goes back to direct Lever API calls (briefly broken since `api/lever.ts` was deleted in the merge — note this asymmetry in the runbook so operators know rollback also needs to revert that file). Backend continues to fetch Lever harmlessly until a code revert lands.

**Tests:**
- N/A (docs only).

**Done when:**
- `docs/implementations/leverBackendMigration/DEPLOY.md` exists and matches the Ashby DEPLOY.md structure.
- Commit message: `Unit 9: add DEPLOY.md runbook for Lever backend migration`.

---

## Critical files

| File | Action | Unit |
|---|---|---|
| `scripts/shared/constants.py` | edit | 1 |
| `src/backend/alembic/versions/<ts>_seed_lever_companies.py` | new (hand-written data migration) | 2 |
| `src/backend/api/services/lever_client.py` | new | 3 |
| `src/backend/api/tasks/fetch_lever_company.py` | new | 4 |
| `src/backend/api/tasks/enqueue_lever_fan_out.py` | new | 5 |
| `src/backend/api/tasks/__init__.py` | edit (side-effect import) | 5 |
| `src/backend/api/main.py` | edit (queues list + log) | 5 |
| `src/backend/api/routers/jobs_qa.py` | edit (trigger endpoints) | 6 |
| `src/frontend/src/config/companies.ts` | edit (flip 3 Lever entries; remove `createLeverCompany`) | 7 |
| `src/frontend/src/types/index.ts` | edit (widen `sourceAts`, drop `LeverConfig`) | 7 |
| `src/frontend/src/api/clients/leverClient.ts` | **delete** | 7 |
| `src/frontend/src/api/transformers/leverTransformer.ts` | **delete** | 7 |
| `src/frontend/src/__tests__/api/transformers/leverTransformer.test.ts` | **delete** (if exists) | 7 |
| `src/frontend/src/__tests__/api/clients/leverClient.test.ts` | **delete** (if exists) | 7 |
| `src/frontend/src/api/types.ts` | edit (drop Lever types) | 7 |
| `src/frontend/src/api/clients/baseClient.ts` | edit (drop `LeverConfig` union member) | 7 |
| `api/lever.ts` | **delete** | 7 |
| `vercel.json` / `vercel.ts` | edit (route cleanup if present) | 7 |
| `CLAUDE.md`, `src/frontend/CLAUDE.md` | edit (docs) | 7 |
| `src/frontend/src/pages/WhyPage/atsGrouping.ts` | edit (add lever key + display name) | 8 |
| `src/frontend/src/__tests__/pages/WhyPage/WhyPage.test.tsx` | edit (new Lever column tests) | 8 |
| `docs/implementations/leverBackendMigration/DEPLOY.md` | new | 9 |

---

## Existing utilities reused

- `scripts/shared/database.py`: `count_active_jobs`, `get_active_job_ids`, `upsert_jobs_batch`, `update_last_seen`, `increment_consecutive_misses`, `mark_jobs_closed`, `get_jobs_exceeding_miss_threshold`, `list_enabled_companies`, `record_scrape_run`, `get_connection`.
- `scripts/shared/incremental.py`: `MISSED_RUN_THRESHOLD`, `SAFETY_GUARD_RATIO`.
- `scripts/shared/models.py`: `JobListing`, `ScrapeRun`.
- `scripts/shared/utils.py`: `get_iso_timestamp`.
- `src/backend/api/tasks/procrastinate_app.py`: `procrastinate_app` singleton (no changes).
- `src/backend/api/routers/jobs.py`: `/api/jobs` endpoint (no changes — already serves anything in `companies`).
- `src/frontend/src/api/clients/backendScraperClient.ts`: per-company + batched fetch (no changes).
- `src/frontend/src/api/transformers/backendScraperTransformer.ts`: reads `details.experience_level` + `details.is_remote_eligible` + `details.tags` (no changes — Lever populates `is_remote_eligible` and `tags`; `experience_level` stays null).
- `src/frontend/src/pages/WhyPage/atsGrouping.ts`: `getATSGroupKey` already prefers `sourceAts` (since Ashby Unit 9 retrofit). Unit 8 of this plan only adds the display name + group key — no logic changes.

---

## End-to-End Verification (after all 9 units, before review passes)

1. Local: `docker compose up -d postgres`; backend startup applies migrations + seed; worker log shows `queues=['greenhouse_fetch', 'ashby_fetch', 'lever_fetch']`.
2. `curl -X POST -H "Authorization: Bearer <admin>" 'http://localhost:8000/api/jobs-qa/trigger-lever-fan-out'` → 202.
3. Within ~30s: `psql -c "SELECT company, count(*) FROM job_listings WHERE source_id='lever_api' GROUP BY company ORDER BY 2 DESC;"` shows palantir, spotify, zoox populated.
4. Frontend: `npm run dev:vercel -w src/frontend`. Open `/companies` → select Palantir, Spotify, Zoox → jobs render from `/api/jobs`. Network tab: zero `/api/lever/*` requests.
5. Open `/why` → "Lever (3)" column visible; "Ashby (46)" and "Greenhouse (45)" columns unchanged; "Custom Web Scrapers (3)" column still contains Google/Apple/Microsoft.
6. Wait one cron interval (30 min). `SELECT count(*) FROM scrape_runs WHERE started_at > now() - interval '1 hour' AND company IN (SELECT id FROM companies WHERE ats='lever');` ≈ 3.
7. Simulate disappearance: monkeypatch a fetch response to drop one Lever job → after 2 cron cycles, that job's `status='CLOSED'`.
8. `cd src/backend && pytest` all green; coverage ≥ existing baseline.
9. `npm run type-check && npm test` clean.
10. `grep -rE "'lever'|LeverConfig|createLeverCompany" src/frontend/src/ api/ vercel.json vercel.ts` returns zero matches (excluding intentional `sourceAts: 'lever'` lines in companies.ts).

---

## Three Review Passes (handled by `/e2eimplementation`)

Each pass dispatches in parallel:

- `pr-review-toolkit:code-reviewer` (always)
- `pr-review-toolkit:silent-failure-hunter` (always)
- `pr-review-toolkit:pr-test-analyzer` (always)
- `pr-review-toolkit:type-design-analyzer` (Unit 7 modifies types — yes)
- `pr-review-toolkit:comment-analyzer` (only if comments added/changed; tasks units add comments)
- `vercel-prod-verifier` (Unit 7 deletes `api/lever.ts` + edits `vercel.json` — yes)
- `postgres-prod-verifier` (Unit 2 ships a migration; Units 3–5 add ORM queries — yes)
- `railway-prod-verifier` (Units 1–6 ship backend code — yes)

Findings consolidated in `docs/implementations/leverBackendMigration/REVIEW_AUDIT.md`. Fix agent runs between passes for Critical/Important items. Three passes regardless of pass-1 cleanliness.

---

## Non-goals

- **Migrating Workday / Gem / Eightfold to backend.** Each is a near-copy of this plan.
- **Per-company observability dashboard.** `procrastinate_jobs` + `scrape_runs` are already queryable.
- **Removing `googleScraper` / `appleScraper` / `microsoftScraper` from the "Custom Web Scrapers" group.** They legitimately belong there since they're truly bespoke.
- **Renaming queues to a single shared `backend_fetch`.** Doable but renaming live queues mid-flight isn't free.
