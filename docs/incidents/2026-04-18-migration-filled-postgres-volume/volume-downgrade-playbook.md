# Playbook: Downsize the Railway Postgres Volume Back to 5 GB

**Context:** During the 2026-04-19 incident ([README.md](./README.md)), the Railway Postgres volume was emergency-upgraded from 5 GB → 20 GB → 40 GB to let WAL replay finish and the DB come back. Railway volumes are one-way — they can only grow, not shrink — so getting back to a 5 GB plan means moving the data to a new Postgres service with a smaller volume and decommissioning the old one.

The actual database is tiny (~251 MB live, 12,590 job rows, no extensions beyond `plpgsql`), so this is a cheap move for a side project. Steps below are the concrete path.

---

## Part 1 — Right-size the volume now (40 GB → 5 GB)

### What you're doing

`pg_dump` the current Postgres service, provision a new Postgres service in the same Railway project at the default (5 GB) volume, `pg_restore` into it, point `DATABASE_URL` at the new service, verify, then delete the old service. Both services live in the same project so the move can stay on Railway's private network.

**Expected downtime:** ~30–60 seconds while `DATABASE_URL` swaps and the backend service redeploys. For a hobby-scale app that's fine to do in the middle of the day; do it when the scraper isn't mid-cycle if you want to be tidy.

### Prerequisites

- `pg_dump` / `pg_restore` on your laptop (`brew install postgresql@16`).
- Railway CLI logged in: `railway whoami` should show your account.
- ~5 minutes of active attention.

### Step-by-step

**1. Snapshot the old DB as insurance.**
In the Railway dashboard → old Postgres service → Backups → **Create Backup**. Keep it until step 8 finishes cleanly. Railway caps manual backups at 50% of volume size; at 40 GB allocated this is more than enough for a 251 MB DB.

**2. Provision a new Postgres service in the same project.**
Railway dashboard → **+ Create** → **Database** → **PostgreSQL**. Put it in the same environment (`production`). Do **not** grow the volume — leave it at the default (5 GB). Wait for it to go green.

**3. Grab both connection strings.**
Both services expose a public proxy URL that works from your laptop. From the Railway dashboard variables tab on each Postgres service, copy the `DATABASE_PUBLIC_URL` (or equivalent external URL — not the `*.railway.internal` one; that only resolves inside Railway).

```bash
OLD_DB="postgresql://postgres:…@<old-public-host>:<port>/railway"
NEW_DB="postgresql://postgres:…@<new-public-host>:<port>/railway"
```

**4. Dump + restore in one pipe.**

```bash
pg_dump -Fc --no-owner --no-acl --verbose "$OLD_DB" \
  | pg_restore --no-owner --no-acl --verbose -d "$NEW_DB"
```

`-Fc` = custom (compressed binary) format; `--no-owner --no-acl` strips ownership / GRANT statements since the new cluster's default `postgres` role will own everything by default. At ~251 MB this completes in well under a minute over a typical home connection.

**5. Verify the new DB contents.**
Use the Postgres MCP or `psql "$NEW_DB"`:

```sql
-- Same five migrations should show as applied (no re-run needed).
SELECT version, name, applied_at FROM schema_migrations_prod ORDER BY version;

-- Row counts should match the old DB exactly.
SELECT count(*) FROM job_listings_prod;   -- expect 12,590 (or current production count)
SELECT count(*) FROM users_prod;
SELECT count(*) FROM user_enabled_companies_prod;
SELECT count(*) FROM scrape_runs_prod;

-- Timestamp columns are still TIMESTAMPTZ.
SELECT column_name, data_type FROM information_schema.columns
 WHERE table_name = 'job_listings_prod'
   AND column_name IN ('posted_on','created_at','closed_on','first_seen_at','last_seen_at');
```

Also run `ANALYZE;` on the new DB so the planner has fresh stats (pg_restore does not update them):

```bash
psql "$NEW_DB" -c "ANALYZE;"
```

**6. Cut the backend over.**
Railway dashboard → `Job-Visualizer-Notifier` service → Variables. Change `DATABASE_URL` to the **new** Postgres's private URL (`postgresql://…@<new>.railway.internal:5432/railway`). Railway will stage the change; click **Deploy** to apply. The backend will redeploy in 20–40 s. During FastAPI lifespan the migration runner will see all five migrations already in `schema_migrations_prod` and do nothing — expected log line: `Pending migrations env=prod: []`.

If the scraper runs as a separate Railway service/cron, update its `DATABASE_URL` the same way. (Check `railway variables --service <name>` per service to see which one reads it.)

**7. Smoke-test.**
- Hit `/api/jobs?company=apple` — expect a populated response.
- Open the frontend → companies page should render the usual chart.
- Watch backend deploy logs for the next ~2 minutes for unexpected errors.
- If the scraper is on an hourly cron, wait for the next cycle to confirm writes land in the new DB (check `last_seen_at` on a freshly scraped row).

**8. Delete the old service.**
Only after at least one scrape cycle has written cleanly to the new DB and the frontend has been healthy for an hour or two. Railway dashboard → old Postgres service → Settings → **Delete Service**. Confirm the name. This also deletes the manual backup from step 1, so keep a `pg_dump` tarball locally if you want belt-and-suspenders:

```bash
pg_dump -Fc --no-owner --no-acl "$OLD_DB" > job-visualizer-prod-backup-$(date +%Y%m%d).dump
```

**9. Confirm the 5 GB bill.**
Railway dashboard → new Postgres service → Usage. Volume should cap at 5 GB and actual usage should sit around 250–400 MB (pg_restore can produce slightly different on-disk size than the original due to fresh heap packing).

---

## Part 2 — Rules to stay on a small volume going forward

The reason this incident happened: migration 0004 rewrote `job_listings_prod` four times in a row inside a single transaction, and the WAL+rewrite churn filled the 5 GB volume. The fix in PR #72 made that specific migration cheap, but **a new schema change could recreate the same failure** if the rules below aren't followed. Each rule is here because skipping it is what cost the 45-minute outage.

### Rule 1: Use Alembic for all new schema changes

The hand-rolled runner in `scripts/shared/migrations/` is frozen at the 0001–0005 set. It stays in the repo only to replay those five migrations on a fresh environment.

Every new schema change (new column, type change, new table, new index, constraint) goes through Alembic:

1. Edit the SQLAlchemy model.
2. `alembic revision --autogenerate -m "<description>"`
3. **Review the generated migration** — specifically, if multiple columns on the same table are changing type, confirm Alembic emitted a single `op.batch_alter_table(...)` block (its default) or a single `op.alter_column` per table-rewrite pass. If autogenerate produced N separate `op.alter_column` calls on the same table, collapse them before committing.
4. Apply locally against a Postgres copy, check the table rewrites happen once (see Rule 3's verification snippet), commit.

Alembic is not set up in this repo yet; setting it up is the natural follow-up to this playbook. The scaffolding is: `alembic.ini` at repo root, `src/backend/alembic/env.py` configured to import the existing SQLAlchemy models, and a baseline revision that captures the 0001–0005 end-state so Alembic's history starts from today's prod schema.

### Rule 2: Estimate disk cost before merging any rewrite migration

"Rewrite migration" = any DDL that forces Postgres to copy the heap. The common cases:

- `ALTER COLUMN … TYPE …` with an incompatible `USING` (e.g. `TEXT → TIMESTAMPTZ`, `INT → TEXT`, varchar length changes that reduce the limit).
- `ALTER TABLE … SET TABLESPACE`.
- `CLUSTER` / `VACUUM FULL` / `pg_repack` on a table.
- Adding a `NOT NULL` column with a volatile default (Postgres 11+ avoids the rewrite for immutable defaults, but volatile ones still rewrite).

Cost model: a rewrite temporarily consumes **~2× the table's total size** (old heap visible to concurrent txns + new heap being written) plus **~1× in WAL**. So free volume during the migration needs to be ≥ 3× `pg_total_relation_size('<table>')`.

Quick check before merging, run against prod:

```sql
SELECT
  pg_size_pretty(pg_total_relation_size('job_listings_prod')) AS table_size,
  pg_size_pretty(pg_database_size(current_database()))         AS db_size;
```

Compare to the volume's free space in the Railway dashboard → Postgres service → Metrics. If the ratio is <3×, either grow the volume preemptively or restructure the migration (see Rule 3).

Put this estimate directly in the PR description for any rewrite migration, not just a correctness argument.

### Rule 3: Batch ALTER COLUMNs on the same table into one statement

One `ALTER TABLE` with multiple `ALTER COLUMN` clauses = one heap rewrite + one WAL stream. N separate `ALTER TABLE` statements = N of each.

✅ Right:
```sql
ALTER TABLE job_listings_prod
  ALTER COLUMN created_at    TYPE TIMESTAMPTZ USING created_at::timestamptz,
  ALTER COLUMN closed_on     TYPE TIMESTAMPTZ USING closed_on::timestamptz,
  ALTER COLUMN first_seen_at TYPE TIMESTAMPTZ USING first_seen_at::timestamptz,
  ALTER COLUMN last_seen_at  TYPE TIMESTAMPTZ USING last_seen_at::timestamptz;
```

❌ Wrong (what 0004 originally did):
```python
for col in (...):
    cursor.execute(f"ALTER TABLE ... ALTER COLUMN {col} TYPE TIMESTAMPTZ USING ...")
```

Alembic's `op.batch_alter_table` emits the combined form by default. This is the single biggest reason the incident was recoverable in 23 s (with the fix) rather than filling 40 GB of volume again.

Verify locally before merging:

```bash
# In a psql session against a dev copy, wrap the migration in EXPLAIN-style timing:
\timing on
BEGIN;
-- run the migration
SELECT pg_size_pretty(pg_database_size(current_database()));  -- size snapshot
COMMIT;
SELECT pg_size_pretty(pg_database_size(current_database()));  -- final size
```

If the "during migration" size spikes to many multiples of table size, you're not batched.

### Rule 4: Take a Railway manual backup right before merging a schema change

Dashboard → Postgres → Backups → **Create Backup**. Takes ~10 seconds. Delete it a day after the migration has been stable. Cost of making it: nothing. Cost of not having it when a rewrite gets wedged: the 2026-04-19 incident.

### Rule 5: Volume sizing heuristic

For a DB currently at `X` GB, target volume ≥ `max(2 GB, 3 × X)`. With the current DB at ~0.25 GB, the default 5 GB plan has ~20× headroom, which is enough to absorb any single table rewrite.

If the DB grows past ~1.6 GB, bump the volume preemptively — don't wait for a deploy to push against the ceiling.

### Rule 6: Pre-deploy disk check in CI (future, nice-to-have)

Worth building once Alembic is in place: a CI check that (a) detects pending migrations via `alembic upgrade --sql`, (b) identifies any `ALTER COLUMN TYPE` / rewrite-heavy DDL in the generated SQL, (c) compares estimated cost to current prod volume free space, and (d) fails the PR if headroom is <3×. Not urgent for a side project — Rules 1–4 catch 99% of the risk manually — but it's the eventual automated version of Rule 2.

---

## Quick-reference checklist for future schema PRs

- [ ] Migration is an Alembic revision, not a hand-rolled file under `scripts/shared/migrations/`.
- [ ] Autogenerated migration reviewed; multi-column type changes on one table use `batch_alter_table` / single combined `ALTER TABLE`.
- [ ] Disk cost estimated: `pg_total_relation_size('<table>') × 3 ≤ volume free space`. Estimate pasted in PR description.
- [ ] Manual Railway backup taken on the Postgres service right before merge.
- [ ] DEPLOY.md (or equivalent runbook) updated if new operator steps are needed.
- [ ] Post-deploy: watch volume usage in Railway metrics for 10 min, confirm it returns to baseline after WAL checkpoint.

---

## References

- [Incident README](./README.md)
- [PR #72 — combined-ALTER fix](https://github.com/brendanpotter00/Job-Visualizer-Notifier/pull/72)
- [Railway Volumes docs — downsizing unsupported](https://docs.railway.com/volumes/reference)
- [Railway Backups docs](https://docs.railway.com/volumes/backups)
- Repo memory: *"Use Alembic for schema migrations, not hand-rolled SQL"*
