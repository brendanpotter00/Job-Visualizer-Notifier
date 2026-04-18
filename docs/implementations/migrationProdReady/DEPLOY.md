# Migration Prod-Ready — Deploy Runbook

This PR converts five `job_listings_{env}` columns from `TEXT` to `TIMESTAMPTZ`:
`posted_on`, `created_at`, `closed_on`, `first_seen_at`, `last_seen_at`. Migrations
`0003` and `0004` apply the ALTER; migrations `0001`/`0002` are baseline and
already applied in prod. The backend auto-applies migrations during FastAPI
lifespan on each Railway boot.

## Pre-deploy check

Before merging, confirm the pending migration list against prod:

```bash
python scripts/migrate.py status --env prod --db-url "$DATABASE_URL"
```

Expect (on the first deploy of this PR):

```
Environment: prod
Applied: 0 / 4

  [ ] 0001_initial_schema
  [ ] 0002_add_users_email_unique
  [ ] 0003_posted_on_timestamptz
  [ ] 0004_job_timestamps_timestamptz
```

This PR introduces the `schema_migrations_prod` tracking table, so the first
run reports `0/4` — the runner creates the tracking table during the advisory-
lock dance and then applies every migration. The baseline migrations are safe
to replay against the existing prod schema: `0001` uses `CREATE TABLE IF NOT
EXISTS` for every object it owns, and `0002` probes `pg_constraint` before
adding the unique constraint.

On subsequent deploys expect `Applied: 4 / 4` — the tracking table is
populated and `migrate_up` is a no-op.

## Deploy sequence

1. Merge PR to `main`. Railway auto-deploys from `main`.
2. Watch the Railway deploy logs for the backend service. In order, expect:

   ```
   Waiting for migration advisory lock env=prod key=<int>
   Acquired migration advisory lock env=prod key=<int>
   Pending migrations env=prod: [3, 4]
   Applying migration 0003_posted_on_timestamptz (env=prod)
   Applying migration 0004_job_timestamps_timestamptz (env=prod)
   Released migration advisory lock env=prod
   Applied 2 migration(s) for env=prod: [3, 4]
   ```

3. Once the service reports healthy, smoke-test `GET /api/jobs` and confirm
   `createdAt` / `firstSeenAt` / `lastSeenAt` come back as ISO 8601 strings
   (with `+00:00` offset — microsecond precision is fine).
4. Spot-check the frontend: company page loads, graph renders, recent jobs
   list has plausible timestamps. No visual regression expected.

## Rollback procedure

If either migration lands cleanly but a downstream consumer breaks:

1. Roll the DB back to before the broken migration:

   ```bash
   python scripts/migrate.py down --to 2 --env prod --db-url "$DATABASE_URL"
   ```

   `--to N` keeps migrations 1..N applied and rolls back everything above N
   (i.e., N is kept, anything greater than N is reverted). So `--to 2` leaves
   `0001` and `0002` applied and reverts `0003` and `0004`. Use `--to 3` if
   only `0004` is at fault. Use `--to 0` only in an emergency — it drops
   everything and will require re-seeding.

2. Redeploy a git commit from before this PR so the running backend code
   matches the rolled-back schema. Revert this PR via `gh pr revert` or
   deploy an earlier tag.

The `downgrade()` in both `0003` and `0004` converts columns back to `TEXT`
via `USING col::text`. Data is preserved; the column type flips back.

## Failure modes

### Hung advisory lock

**Symptom:** No `Acquired migration advisory lock` log line within ~30s of pod
boot. Instead, the pod exits with `psycopg2.errors.LockNotAvailable` (SQLSTATE
`55P03`). In the Railway deploy log, grep for the underlying Postgres message
`canceling statement due to lock timeout` — that's the string the operator
will actually see once the exception is formatted.

**Cause:** Another process is holding `pg_advisory_lock(<key>)` for this env.
Usually a prior pod that was killed before releasing, or a concurrent deploy.

**Fix:** Railway will restart the pod. The `lock_timeout = 30s` in
`runner._advisory_lock` bounds the wait so a stuck peer surfaces as a
crashloop instead of an indefinite hang. If it doesn't clear within a few
retries, connect via `psql` and run:

```sql
SELECT pid, state, query
FROM pg_stat_activity
WHERE query ILIKE '%pg_advisory_lock%';
```

Then `SELECT pg_terminate_backend(<pid>)` on the stuck session. Redeploying
after that will succeed.

### Malformed ISO 8601 row

**Symptom:** Deploy log shows the pre-flight scanner raising:

```
RuntimeError: Cannot convert job_listings_prod.posted_on to TIMESTAMPTZ:
N row(s) have non-ISO-8601 values. Sample ids: [...]
```

**Cause:** A scraper wrote a non-ISO string into a timestamp column. This is
expected to be impossible given current scraper code (all writers go through
`shared/utils.get_iso_timestamp` or equivalent), but the pre-flight is a
safety net for human-written rows or imports.

**Fix:** Connect via `psql` and inspect the offending rows using the scan
query (substitute the column named in the error):

```sql
SELECT id, posted_on
FROM job_listings_prod
WHERE posted_on IS NOT NULL
  AND posted_on::text !~ '^\d{4}-\d{2}-\d{2}T'
LIMIT 10;
```

Repair or null out the bad values, then redeploy. The migration is idempotent
— it will re-run against the now-clean data on the next boot.

### Migration exceeds 300s statement timeout

**Symptom:** `canceling statement due to statement timeout` during
`0003`/`0004`.

**Cause:** `ALTER COLUMN TYPE` rewrites the table. On `job_listings_prod` at
current size this completes in seconds. If row count grows ~100x, the 300s
ceiling (`_MIGRATION_STATEMENT_TIMEOUT` in `runner.py`) may become tight.

**Fix:** Raise `_MIGRATION_STATEMENT_TIMEOUT` in a follow-up PR; do not
manually run the ALTER in a psql session against prod without coordinating,
as Railway will try to re-apply the migration on the next boot.
