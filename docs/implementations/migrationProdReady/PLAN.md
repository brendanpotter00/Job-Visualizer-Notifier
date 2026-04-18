# Migration Production-Readiness Plan

## Context

PR `feature/migration` (1 commit ahead of `main`) introduces a custom Python migration runner at `scripts/shared/migrations/runner.py` and four baseline/forward migrations, then uses that runner to convert `job_listings.posted_on`, `created_at`, `closed_on`, `first_seen_at`, `last_seen_at` from TEXT to TIMESTAMPTZ. `init_schema` now delegates to `migrate_up`, so Railway picks up new migrations on first boot of each deploy — no separate migration step.

The code paths most affected in production:
- **Backend lifespan** (`src/backend/api/main.py`) calls `init_schema` on startup; if this hangs or fails, the pool still initializes but serves against whatever state the DB is left in.
- **Pydantic response model** (`src/backend/api/models.py` — `JobListingResponse`) switched five fields from `str` to `datetime`. Pydantic serializes datetime to ISO 8601 with microseconds and a UTC offset.
- **Scraper writes** still pass ISO 8601 strings via `shared/database.py`; psycopg2 implicit-casts these into `timestamptz`. Verified by `test_inserting_iso_string_works`.
- **Frontend** (`src/frontend/src/api/types.ts` `BackendJobListing`) expects ISO 8601 strings; `transformBackendJob` passes them to `new Date()`, which tolerates microseconds and offsets.

The existing tests cover discovery, advisory lock key stability, env validation, forward/rollback cycles, NOT NULL preservation on ALTER, and the critical ISO-string-to-timestamptz implicit-cast path. Logs use `logger.info` on apply, `logger.exception` on failure, and tracking-table `INSERT` is committed per migration.

What is still missing for production confidence:

1. **No concurrency test** for the advisory lock under real multi-instance startup. Claimed behavior is "serialize across processes/instances", but no integration test opens two connections and proves the second waits.
2. **No statement/lock timeout** on the advisory lock: a stuck `ACCESS EXCLUSIVE` lock on `job_listings_prod` during `ALTER COLUMN TYPE` could freeze the deploy indefinitely with no log line after "Applying migration 0003_…".
3. **Idempotency of 0003/0004** on an already-`timestamptz` column is untested. PostgreSQL's `ALTER COLUMN … TYPE TIMESTAMPTZ USING x::timestamptz` on a column that's already timestamptz succeeds as a no-op, but we have no assertion guarding that. A prod DB where someone ran the migration manually before the auto-apply commit landed would re-enter this path on every deploy.
4. **No pre-check for unparseable strings** in prod `job_listings.posted_on` before the ALTER. If a single row has a malformed ISO string, 0003 aborts mid-transaction and the deploy boots with the schema change partially applied.
5. **Scraper end-to-end against timestamptz** never exercised in CI. Integration test inserts a raw SQL row but doesn't call `upsert_job` / `upsert_jobs_batch` with a `JobListing` Pydantic instance through the real code path.
6. **Frontend regression** not verified: `transformBackendJob` hands `raw.postedOn` (now produced by Pydantic as `"2026-01-08T19:04:30.284000+00:00"` rather than the scraper's original `"2026-01-08T19:04:30.284+00:00"`) to `new Date()` — works — and to downstream `new Date(job.createdAt).getTime()` call sites. All work with `new Date()`, but `npm run type-check` and `npm test` have not been run against a backend response shape.
7. **No PR description** and no deploy/rollback runbook.

Scope of this plan: close the concrete gaps above without re-architecting. Preserve every already-committed file behavior.

## Shared Contracts

Frozen for all units below. Do not edit these in one unit and change them in another.

**Migration runner API** (`scripts/shared/migrations/runner.py`)
- `discover_migrations() -> List[Migration]`
- `migrate_up(conn, env) -> List[int]` — idempotent, advisory-locked, per-migration commit
- `migrate_down(conn, env, target_version=0) -> List[int]` — advisory-locked
- `get_applied_versions(conn, env) -> Set[int]`
- `_advisory_lock(conn, env)` context manager
- Env validation rules: `local`, `qa`, `prod`, or `test_[a-f0-9]{8}`

**`job_listings_{env}` schema after all migrations**
- `posted_on TIMESTAMPTZ NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `closed_on TIMESTAMPTZ NULL`
- `first_seen_at TIMESTAMPTZ NOT NULL`
- `last_seen_at TIMESTAMPTZ NOT NULL` (indexed)

**Pydantic response shape** (`src/backend/api/models.py` — `JobListingResponse`)
- `created_at: datetime`, `posted_on: datetime | None`, `closed_on: datetime | None`, `first_seen_at: datetime`, `last_seen_at: datetime`
- Serialized via default Pydantic v2 JSON encoder → ISO 8601 with microseconds and `+00:00` offset

**Frontend contract** (`src/frontend/src/api/types.ts` — `BackendJobListing`)
- All five fields typed `string` (ISO 8601). Consumed only by `transformBackendJob` (`raw.postedOn || raw.firstSeenAt`) and by `new Date(...)` on the output.

**Scraper-side `JobListing`** (`scripts/shared/models.py`)
- Timestamp fields remain `str`. psycopg2 implicit-casts to timestamptz.
- NOT changed by this PR. Must remain unchanged.

## Work Units

### Unit 1 — Harden the migration runner for production deploys

**Status:** DONE

**Prerequisites:** none

**Owned files:**
- `scripts/shared/migrations/runner.py`

**Shared-file edits:**
- `scripts/tests/unit/test_migration_runner.py` — add a `caplog`-based test that `Acquired`/`Released` log lines are emitted around migrate_up.

**Done when:**
- `pytest scripts/tests/unit/test_migration_runner.py scripts/tests/integration/test_migrations.py` passes.
- Reading `scripts/shared/migrations/runner.py` shows:
  - A `lock_timeout` set before `pg_advisory_lock` (bounded so a blocked call doesn't freeze the deploy).
  - A `statement_timeout` (e.g. 300s) set before each `migration.upgrade(conn, env)` call.
  - On acquire: `logger.info("Acquired migration advisory lock env=%s key=%s", env, key)`. On release: `logger.info("Released migration advisory lock env=%s", env)`.
  - `migrate_up` logs the full planned list before starting: `logger.info("Pending migrations: %s", [...])`.

**Body:**

The current advisory lock blocks indefinitely. On Railway, a deploy hang with no log after "Connecting to database" is indistinguishable from a legitimately slow migration. Add:

1. In `_advisory_lock`: set `SET LOCAL lock_timeout = '30s'` before `pg_advisory_lock`. Log intent to wait, the key, and the env. On release log the release. Keep this inside a transaction if needed — `SET LOCAL` requires a transaction.
2. In `migrate_up`'s per-migration block: set `SET LOCAL statement_timeout = '300s'` inside the transaction before calling `migration.upgrade`. On timeout, `logger.exception` surfaces which migration hung.
3. Log the full pending plan once before applying so a Railway log reader sees "Pending migrations: [3, 4]" even if migration 3 then hangs.
4. Add a unit test (`test_migration_runner.py`) asserting that after `migrate_up` completes, the logger emitted both "Acquired" and "Released" messages at INFO for the test env (use `caplog`).

Do NOT change public function signatures. Do NOT introduce async. Do NOT change the tracking table schema.

---

### Unit 2 — Guarantee 0003/0004 idempotency and add a pre-flight row scan

**Status:** DONE

**Prerequisites:** Unit 1

**Owned files:**
- `scripts/shared/migrations/0003_posted_on_timestamptz.py`
- `scripts/shared/migrations/0004_job_timestamps_timestamptz.py`

**Shared-file edits:**
- `scripts/tests/integration/test_migrations.py` — add classes `TestPostedOnIdempotent` and `TestJobTimestampIdempotent`, plus a malformed-row guard test.

**Done when:**
- `pytest scripts/tests/integration/test_migrations.py` passes.
- A new integration test re-runs the upgrade function of 0003 against a table whose `posted_on` column is already `timestamptz`, and asserts it does not raise and the column remains `timestamptz`. Same for 0004 across all four columns.
- A new integration test seeds a row with a malformed `posted_on` (e.g., `"not-a-date"`) into the 0001-baseline `TEXT` column, then calls `migrate_up` and asserts:
  - The migration raises a clear error message naming `job_listings_{env}.posted_on` (and sample ids or row count).
  - The `posted_on` column type is still `TEXT` (migration 0003 did not complete).
  - The tracking table does NOT have version 3.
  - `get_applied_versions` returns `{1, 2}`.

**Body:**

PostgreSQL's `ALTER COLUMN ... TYPE TIMESTAMPTZ USING x::timestamptz` is a no-op when the column is already `timestamptz` (the cast is identity), so the migrations are de facto idempotent once applied. Document that with assertions so the behavior doesn't silently regress if someone later rewrites these migrations.

Pre-flight scan (0003 and 0004): before the `ALTER`, run a query that finds rows whose value doesn't look like an ISO 8601 timestamp (conservative prefix filter, e.g. `<col>::text !~ '^\d{4}-\d{2}-\d{2}T'`), and if any rows are found, `LIMIT 10`, raise a `RuntimeError` naming the table, column, and sample ids. This converts the opaque "invalid input syntax for type timestamp" error into a clear, actionable deploy-log line.

Keep `downgrade` untouched.

---

### Unit 3 — Exercise the full scraper-write-through-API path end-to-end against timestamptz

**Status:** DONE

**Prerequisites:** Unit 2

**Owned files:**
- `scripts/tests/integration/test_database.py` — add a test `test_upsert_job_writes_iso_strings_to_timestamptz` (create if missing).
- `src/backend/api/tests/test_jobs_router.py` — add a test `test_get_jobs_returns_iso8601_datetime_strings` (create if missing).

**Shared-file edits:** none

**Done when:**
- `pytest scripts/tests/integration/test_database.py` passes with the new test.
- `cd src/backend && pytest api/tests` passes with the new test.
- The new scraper test calls `db.upsert_job(conn, JobListing(..., created_at="2026-04-18T12:00:00Z", first_seen_at=..., last_seen_at=...), env=test_env)`, then `SELECT created_at, pg_typeof(created_at) FROM ...` and asserts (a) the returned Python value is a `datetime` with `tzinfo`, (b) `pg_typeof` is `timestamp with time zone`.
- The new API test inserts a row (via `_insert_job` from `conftest.py`), calls `GET /api/jobs`, and asserts the JSON response field `createdAt` matches a strict ISO 8601 regex and that `datetime.fromisoformat` round-trips successfully.

**Body:**

Today the ISO-string cast is tested via raw SQL (`test_inserting_iso_string_works`), and the response shape is asserted only by the Pydantic model's type annotation. Neither side proves the full scrape → insert → select → serialize → JSON chain against the new column types. Add the two tests above. Do not add new fixtures; reuse `postgres_db` / `db_conn`.

---

### Unit 4 — Frontend regression verification pass

**Status:** DONE

**Prerequisites:** Unit 3

**Owned files:** none (verification gate)

**Shared-file edits:** none

**Done when:**
- `npm run type-check` passes (zero TypeScript errors).
- `npm test` passes (zero test regressions).
- A manual probe confirms `new Date("2026-01-08T19:04:30.284000+00:00").getTime()` returns a finite number in the repo's Node test runner (Vitest/V8). This can be a one-line assertion in an existing test file or documented in the PR body — either is fine.
- No new assertions, code, or tests are added in this unit unless driven by a test failure. It is purely a verification gate. If any test fails, diagnose and either (a) fix forward with a minimal edit under this unit's ownership, explicitly noted; or (b) stop and escalate before proceeding to Unit 5.

**Body:**

`BackendJobListing` still types the five timestamps as `string`, which matches Pydantic's serialized output. `transformBackendJob` only reads `raw.postedOn || raw.firstSeenAt` and passes to `new Date(...)`, which tolerates microsecond-precision ISO 8601 with `+00:00`. No code path does string equality or prefix matching on these timestamps — verify by reading `lib/timeBucketing.ts`, `lib/date.ts`, `features/filters/selectors/recentJobsSelectors.ts`, `components/companies-page/MetricsDashboard/hooks/useTimeBasedJobCounts.ts`, `components/recent-jobs-page/RecentJobsMetrics/hooks/useRecentJobsTimeBasedCounts.ts` during this unit.

This unit is a gate, not a code change. Run the commands, read the consumers of those five fields, confirm no surprises.

---

### Unit 5 — Deploy runbook, rollback doc, and PR description

**Status:** TODO

**Prerequisites:** Unit 4

**Owned files:**
- `docs/implementations/migrationProdReady/DEPLOY.md` — new file.

**Shared-file edits:** none

**Done when:**
- `docs/implementations/migrationProdReady/DEPLOY.md` exists and contains:
  - "Deploy sequence" — Railway auto-runs migrations in lifespan, what to look for in logs, expected log lines (`"Pending migrations: [...]"`, `"Acquired migration advisory lock"`, `"Applied N migration(s)"`).
  - "Rollback procedure" — `python scripts/migrate.py down --to <N> --env prod --db-url "$DATABASE_URL"`, then redeploy a commit before the offending migration.
  - "Pre-deploy check" — `python scripts/migrate.py status --env prod --db-url "$DATABASE_URL"` and inspect pending count.
  - "Failure modes" — hung advisory lock (symptom: no "Acquired" log within 30s of boot → `lock_timeout` will fire and pod will crashloop, safe to redeploy); malformed ISO row (symptom: Unit 2 pre-flight error message → run scan query documented here, fix rows, redeploy).
- PR description (set via `gh pr edit` or at `gh pr create` time): summarizes the change in 2 sentences, explicitly states "Backend auto-applies migrations on lifespan startup on Railway", links to `DEPLOY.md`, lists the five converted columns, and notes that `users_{env}` and `scrape_runs_{env}` timestamp columns are intentionally out of scope.

**Body:**

The user said "production ready". Even with all the code hardening above, a deploy without a written procedure means the first time something goes wrong at 2am, the operator has to re-derive the runbook from the source. Write it once, now, from the information already in the PR.

Do not add tests for the doc. Do not change any code in this unit.

## Critical files

| File | Role | Units touching |
|------|------|----------------|
| `scripts/shared/migrations/runner.py` | Migration execution, advisory lock, logging | Unit 1 |
| `scripts/tests/unit/test_migration_runner.py` | Unit tests for runner, including new log-assertion test | Unit 1 |
| `scripts/shared/migrations/0003_posted_on_timestamptz.py` | `posted_on` → timestamptz + pre-flight scan | Unit 2 |
| `scripts/shared/migrations/0004_job_timestamps_timestamptz.py` | Four remaining timestamps → timestamptz + pre-flight scan | Unit 2 |
| `scripts/tests/integration/test_migrations.py` | Integration tests for idempotency and malformed-row guard | Unit 2 |
| `scripts/tests/integration/test_database.py` | End-to-end scraper write path against timestamptz | Unit 3 |
| `src/backend/api/tests/test_jobs_router.py` | End-to-end API response shape assertion | Unit 3 |
| `docs/implementations/migrationProdReady/DEPLOY.md` | Deploy/rollback runbook | Unit 5 |

## Non-goals

- **Conversion of `users_{env}.created_at` / `users_{env}.updated_at`.** These remain `TEXT`. The user's "one field" framing refers to `job_listings` timestamps; user timestamps are a separate change.
- **Conversion of `scrape_runs_{env}.started_at` / `scrape_runs_{env}.completed_at`.** Same reasoning; also `ScrapeRunResponse` in `models.py` still uses `str`, which is intentional for this PR.
- **Rewriting the custom runner to Alembic.** The user said "alembic" colloquially. The in-tree runner is what ships.
- **Any frontend feature changes.** `BackendJobListing` keeps `string` types; `transformBackendJob` stays byte-identical. No new UI for timestamps.
- **Changes to `JobListing` (scraper Pydantic model) timestamp types.** It stays `str` so psycopg2 implicit-cast continues to work.
- **Adding a separate migration CLI step to the Railway deploy pipeline.** Auto-apply on lifespan is the chosen architecture.
- **Backfilling or re-normalizing existing timestamp values in prod.** All existing values are ISO 8601 with explicit UTC offset; the pre-flight scan in Unit 2 is a safety net, not a migration.
