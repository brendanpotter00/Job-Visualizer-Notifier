# Env-Agnostic Tables Deployment Runbook

Companion to `PLAN.md`. Covers the one-time prod rename, the post-merge Railway env-var cleanup, the ongoing deploy loop, rollback with an explicit env, and the one-time local stale-artifact cleanup.

## Why this runbook exists

Before this PR, tables carried an `_{env}` suffix (`job_listings_prod`, `users_local`, …) driven by `SCRAPER_ENVIRONMENT`. The suffix is gone after this PR — every environment uses the bare names `job_listings`, `scrape_runs`, `users`, `user_enabled_companies`. Alembic's tracker becomes the default `alembic_version`.

The cutover is `ALTER TABLE … RENAME` only. No rows are rewritten. The 2026-04-18 incident (`docs/incidents/2026-04-18-migration-filled-postgres-volume/`) showed what a full-table rewrite on 138 MB of prod data does to a 5 GB volume; the rename migration avoids it by design.

After this PR merges, the live tracker on prod is `alembic_version` (not `alembic_version_prod`), `SCRAPER_ENVIRONMENT` is dead config, and the Alembic PLAN-era downgrade path requires `-x env=prod` because there's no ambient env var to infer from.

## 1. One-time prod rename (pre-merge, operator)

Run before merging this PR. The rename migration must land against prod's `_prod`-suffixed tables; merging first would deploy code that expects bare names against a DB that still has suffixed names and break the lifespan startup.

### 1.1. Take a Railway manual Postgres backup

Mandatory. `ALTER TABLE … RENAME` is catalog-only, but there is no in-place rollback path if the rename crashes mid-way and the downgrade step is also missed. The backup is the safety net.

### 1.2. Snapshot pre-rename row counts

```
mcp__postgres-prod__query "
  SELECT 'job_listings_prod' AS t, COUNT(*) FROM job_listings_prod
  UNION ALL SELECT 'scrape_runs_prod', COUNT(*) FROM scrape_runs_prod
  UNION ALL SELECT 'users_prod', COUNT(*) FROM users_prod
  UNION ALL SELECT 'user_enabled_companies_prod', COUNT(*) FROM user_enabled_companies_prod"
```

Copy the four counts somewhere you can compare against after the rename.

### 1.3. Run the rename migration against prod

From an operator workstation (not Railway, not CI) with the envAgnosticTables branch checked out locally and prod credentials exported:

```
export DATABASE_URL=<prod Postgres URL from Railway>
cd src/backend
alembic upgrade head
```

Do NOT set `SCRAPER_ENVIRONMENT` — the branch's `env.py` no longer reads it. Setting it has no effect (Pydantic `Settings` is `extra="ignore"`), just make sure the deploy checklist doesn't carry it over from the old runbook.

Expected sequence:

- Alembic opens the DB, sees no `alembic_version` table (only the legacy `alembic_version_prod`), and creates a fresh `alembic_version` under Alembic's default name. Applies the empty baseline `91337142414f` (no-op), then applies `e1974f8f8eee`, then `f4008c4fb790`.
- Inside `e1974f8f8eee`:
  - Narrows `search_path` to the current schema so `ALTER TABLE IF EXISTS` cannot fall through to `public.*` under any future test-schema invocation.
  - Drops the pre-Alembic `schema_migrations_local` and `schema_migrations_prod` trackers (idempotent; `schema_migrations_local` no-ops on prod).
  - Renames the four `*_prod` tables to their bare names. Postgres auto-renames the implicit PK index and sequence with the table.
  - Renames six named indexes (`idx_job_listings_prod_*`, `idx_users_prod_*`, `idx_user_enabled_companies_prod_*`) to their bare forms via `ALTER INDEX IF EXISTS`.
  - Renames the `users_prod_email_key` UNIQUE constraint to `users_email_key` inside a `DO $$ … EXCEPTION WHEN undefined_object OR undefined_table THEN NULL; END $$` guard so the absent-variant no-ops.
  - Drops the legacy `alembic_version_local` and `alembic_version_prod` trackers. The new `alembic_version` (created by Alembic at the start of the run) holds the active head revision.
- Inside `f4008c4fb790` (constraint-name cleanup):
  - Same `search_path` narrowing.
  - Renames six auto-generated constraint names from `_{env}`-suffixed forms to bare names (both `_local` and `_prod` variants via `IF EXISTS`-style DO/EXCEPTION guards): `job_listings_pkey`, `scrape_runs_pkey`, `users_pkey`, `users_auth0_id_key`, `user_enabled_companies_pkey`, `user_enabled_companies_user_id_fkey`. Catalog-only — no index rebuilds.

Expected output ends with `INFO  [alembic.runtime.migration] Running upgrade … -> f4008c4fb790, rename env-suffixed pk/fk constraints`.

### 1.4. Verify post-rename state

```
mcp__postgres-prod__query "
  SELECT tablename FROM pg_tables
  WHERE schemaname = 'public' ORDER BY tablename"
```

Expect exactly: `alembic_version`, `job_listings`, `scrape_runs`, `user_enabled_companies`, `users`. No `*_local`, no `*_prod`, no `alembic_version_prod`.

```
mcp__postgres-prod__query "
  SELECT 'job_listings' AS t, COUNT(*) FROM job_listings
  UNION ALL SELECT 'scrape_runs', COUNT(*) FROM scrape_runs
  UNION ALL SELECT 'users', COUNT(*) FROM users
  UNION ALL SELECT 'user_enabled_companies', COUNT(*) FROM user_enabled_companies"
```

All four counts MUST equal the snapshot from 1.2. A mismatch means the rename lost data — stop, restore from 1.1's backup, investigate before continuing.

Also confirm the tracker row:

```
mcp__postgres-prod__query "SELECT version_num FROM alembic_version"
```

Expect one row: `f4008c4fb790` (the constraint-cleanup revision that chains from `e1974f8f8eee`).

And confirm no `_prod`-suffixed constraint names remain on the bare tables:

```
mcp__postgres-prod__query "
  SELECT conname FROM pg_constraint
  WHERE connamespace = 'public'::regnamespace
    AND conname LIKE '%_prod_%'
    AND conrelid::regclass::text IN
        ('job_listings','scrape_runs','users','user_enabled_companies')
  ORDER BY conname"
```

Expect zero rows.

### 1.5. Merge the PR

Only after 1.4 succeeds. The first Railway deploy's lifespan runs `apply_alembic_migrations(settings.database_url)`, Alembic sees the tracker already at head, and does nothing.

## 2. Post-merge Railway env-var cleanup (operator)

Delete the `SCRAPER_ENVIRONMENT=prod` variable in Railway's dashboard (Service → Variables). The code no longer reads it, so leaving it is harmless — this step is cleanliness, not correctness. Doing it now prevents confusion when a future engineer greps Railway vars looking for unused config.

No redeploy needed; the delete is silent.

## 3. Deploy loop (ongoing)

Railway auto-deploys from `main` via `src/backend/Dockerfile`. On each deploy:

1. Container starts, FastAPI lifespan opens.
2. `apply_alembic_migrations(settings.database_url)` runs from `src/backend/api/main.py`. Signature is one-arg after this PR.
3. Alembic loads `/app/alembic.ini`, reads `script_location=/app/alembic`, targets the default `alembic_version` tracker.
4. Runs `upgrade head`. With no new revisions, Alembic logs `Context impl PostgresqlImpl.` → `Will assume transactional DDL.` and exits immediately.

No operator action required per deploy. Same rollout-safety caveat as the Alembic PLAN applies: the Railway service has `healthcheckPath: null`, so a lifespan failure leaves the service degraded rather than auto-retaining the prior deployment — recovery is a manual image re-pin via Railway's UI.

## 4. Rollback

Two independent levers:

1. **Container rollback (manual, single-image-back):** pin the backend image to the pre-envAgnosticTables tag in Railway's UI. Safe only if the rollback target image was already running against `_prod`-suffixed tables at the time. Since this PR's deploy is the cutover, the immediately-previous image IS such an image — but pair this with step 4.2 below to put the schema back to `_prod`-suffixed names, otherwise the rolled-back image will look for tables that no longer exist under those names.

2. **Revision downgrade (explicit env required):** from an operator workstation:

   ```
   export DATABASE_URL=<prod Postgres URL from Railway>
   cd src/backend
   alembic -x env=prod downgrade -1
   ```

   The `-x env=prod` is mandatory. Without it the migration raises `RuntimeError("downgrade requires -x env=local|prod …")` loudly — there's no ambient `SCRAPER_ENVIRONMENT` in the post-merge world, so the downgrade can't infer which suffix to restore. Running it as `alembic -x env=local downgrade -1` against prod would scramble prod to local-suffix naming; the explicit flag is what prevents that.

   **What downgrade does NOT restore:** the pre-Alembic `schema_migrations_prod` tracker. `upgrade()` DROPs it; `downgrade()` does not recreate it. If a full rollback to the pre-Alembic era is needed, use the Railway backup from step 1.1.

Always take a Railway manual backup before running downgrade on prod.

## 5. One-time local stale-artifact cleanup

The local Postgres `public` schema in dev machines accumulated ~23 stale `user_enabled_companies_test_*` and `alembic_version_test_*` tables from interrupted pytest runs under the old env-suffix scheme. After this PR, nothing references or drops them — they are orphans.

Each developer runs this ONCE against their local DB after pulling `main`:

```
mcp__postgres__query "
  DO \$\$
  DECLARE r record;
  BEGIN
    FOR r IN SELECT tablename FROM pg_tables
             WHERE schemaname = 'public' AND tablename LIKE 'user_enabled_companies_test_%'
    LOOP EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename); END LOOP;
    FOR r IN SELECT tablename FROM pg_tables
             WHERE schemaname = 'public' AND tablename LIKE 'alembic_version_test_%'
    LOOP EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename); END LOOP;
  END \$\$"
```

Or equivalently from a `psql` shell:

```
psql postgresql://postgres:postgres@localhost:5432/jobscraper -c "
  DO \$\$
  DECLARE r record;
  BEGIN
    FOR r IN SELECT tablename FROM pg_tables
             WHERE schemaname = 'public' AND tablename LIKE 'user_enabled_companies_test_%'
    LOOP EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename); END LOOP;
    FOR r IN SELECT tablename FROM pg_tables
             WHERE schemaname = 'public' AND tablename LIKE 'alembic_version_test_%'
    LOOP EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename); END LOOP;
  END \$\$;"
```

Production was verified clean via `mcp__postgres-prod__query` at the time of this PR — no `*_test_*` tables existed there.

The test fixtures under this PR use per-worker Postgres **schemas** (`PYTEST_SCHEMA=test_<hex>` + `SET search_path`) with `DROP SCHEMA … CASCADE` at teardown, so this class of leak cannot recur.

## See also

- `PLAN.md` — the unit-by-unit plan for this PR.
- `docs/incidents/2026-04-18-migration-filled-postgres-volume/README.md` — the incident that motivates the RENAME-only migration.
- `docs/implementations/alembicMigration/DEPLOY.md` — the prior runbook. Its `alembic_version_<env>` and `SCRAPER_ENVIRONMENT` references are historical after this PR; the live tracker is `alembic_version`.
