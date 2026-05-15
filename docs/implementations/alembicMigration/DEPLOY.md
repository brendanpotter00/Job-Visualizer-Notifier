# Alembic Migration Deployment Runbook

> **Superseded in part by `docs/implementations/envAgnosticTables/DEPLOY.md`.**
> References below to `alembic_version_<env>`, `alembic_version_prod`, and `SCRAPER_ENVIRONMENT` are historical. After the envAgnosticTables PR the live tracker is the default `alembic_version`, Alembic's `env.py` no longer passes `version_table=`, and `apply_alembic_migrations` takes a single `database_url` argument. The body below is preserved unchanged as the historical record of the Alembic introduction; do not follow its stamp/env-var instructions against today's codebase.

Companion to `PLAN.md`. Covers the one-time prod stamp before the first post-Alembic deploy, the ongoing deploy loop, rollback, the schema-change workflow, and failure modes.

## Why this runbook exists

Until this PR, schema was managed by a hand-rolled numbered-migration runner in `scripts/shared/migrations/`. Prod has versions 1–5 applied. This PR replaces that runner with Alembic and ships an empty baseline revision (`91337142414f`). The baseline has `upgrade() = pass` and `downgrade() = pass` — its only job is to anchor the revision graph at prod's current state without re-running any of the 1–5 DDL.

The handoff is: after merge, an operator runs `alembic stamp 91337142414f` once against prod. That writes one row to `alembic_version_prod` declaring "prod is at the baseline." The next Railway deploy's lifespan hook runs `alembic upgrade head`, sees prod is already at head, and does nothing. Future schema changes are Alembic revisions on top of the baseline.

See the incident postmortem at `docs/incidents/2026-04-18-migration-filled-postgres-volume/` for the 45-minute outage on 2026-04-19 that motivates the combined-ALTER-TABLE rule documented below.

## One-time prod stamp sequence

Run **before** merging this PR. If the PR merges without the stamp, the first deploy's lifespan hook will try to apply the baseline (a no-op) and succeed, but any subsequent non-empty revision will attempt to apply from `base` and could collide with prod's actual state.

### 1. Verify the legacy tracker on prod is at version 5

```
mcp__postgres-prod__query "SELECT version FROM schema_migrations_prod ORDER BY version"
```

Expected: 5 rows, versions 1 through 5. If fewer rows are present, stop — prod is not in the state this baseline assumes.

### 2. Stamp prod at the baseline

From an operator workstation (not Railway, not CI — this is a human action) with prod credentials in the environment:

```
export DATABASE_URL=<prod Postgres URL from Railway>
export SCRAPER_ENVIRONMENT=prod
cd src/backend
alembic stamp 91337142414f
```

Expected output: `INFO  [alembic.runtime.migration] Will assume transactional DDL.` followed by `INFO  [alembic.runtime.migration] Running stamp_revision  -> 91337142414f`.

Do **not** run `alembic upgrade head` in this step. Stamp only writes to the version tracker; upgrade would attempt to apply the revision body (which is empty, so harmless — but the contract is "stamp the tracker, leave everything else alone").

### 3. Verify the stamp landed

```
mcp__postgres-prod__query "SELECT version_num FROM alembic_version_prod"
```

Expected: one row containing `91337142414f`.

### 4. Merge the PR

Only after step 3 succeeds. The first Railway deploy runs `apply_alembic_migrations` in the lifespan hook; Alembic sees `alembic_version_prod.version_num = 91337142414f` and `script_location` head is also `91337142414f`, so `upgrade head` is a no-op.

## Deploy sequence (ongoing)

Railway auto-deploys from `main` via the Dockerfile at `src/backend/Dockerfile`. On each deploy:

1. Container starts, FastAPI lifespan opens.
2. `apply_alembic_migrations(settings.database_url, settings.scraper_environment)` runs from `src/backend/api/main.py`.
3. Alembic loads `/app/alembic.ini`, resolves `script_location` to `/app/alembic/`, reads `SCRAPER_ENVIRONMENT=prod` via `env.py`, targets `alembic_version_prod`.
4. Runs `upgrade head`. On a deploy with no new revisions, Alembic logs `Context impl PostgresqlImpl.` → `Will assume transactional DDL.` and exits immediately. Expect one line in the Railway logs: `Applying database migrations...` followed by a no-op.

No operator action required per deploy.

> **Rollout safety caveat — read this before relying on automatic rollback.** The Railway service currently has `healthcheckPath: null`. That means Railway does **not** evaluate a health check before promoting a new deployment, and it does **not** automatically retain the prior deployment on lifespan failure. Instead, the `ON_FAILURE` restart policy retries the broken container up to 10 times and then leaves the service degraded. **Recovery from a lifespan failure today requires a manual re-pin via Railway's UI** to the previous image (see Rollback below). If the service later configures a `healthcheckPath`, this language can be relaxed.

## Rollback

Two independent levers:

1. **Container rollback (manual, single-image-back only):** pin the backend image to the pre-Alembic tag in Railway's UI. This is the recommended response to any Alembic-related lifespan failure on prod. **Important constraint:** this is only safe if the rollback target image **already had migrations 1–5 applied during its own production lifetime** — i.e., it runs against a database that the legacy runner has already advanced past version 5. The legacy runner reads `schema_migrations_prod`, sees 1–5 already applied, and does nothing in that case. Do **not** rollback to a pre-migration-5 image (or any image that predates the schema's current state) without operator review and a manual schema check first; the legacy runner there might attempt to apply migrations 1–5 against a schema that already has them, with unpredictable results.
2. **Revision downgrade:** `alembic downgrade base` is a no-op against the empty baseline (the baseline's `downgrade()` is `pass`). For a future non-empty revision that needs to be reverted: from an operator workstation, `cd src/backend && alembic downgrade -1`. Always take a Railway manual backup first and confirm the `downgrade()` body actually inverts the `upgrade()` body — autogenerate does not guarantee a symmetric downgrade.

## Adding a schema change

The steady-state workflow for future changes:

1. **Edit `src/backend/api/db_models.py`** — add/modify the column/index/constraint in the SQLAlchemy declarative model. This is the source of truth.

2. **Autogenerate a revision locally:**

   ```
   docker compose up -d postgres
   cd src/backend
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/jobscraper SCRAPER_ENVIRONMENT=local alembic revision --autogenerate -m "short description"
   ```

   Autogenerate diffs `db_models.Base.metadata` against the current local DB and writes a revision file under `src/backend/alembic/versions/`.

3. **Inspect the generated file and collapse per-table ALTERs.** This is the incident-driven rule:
   - Open `src/backend/alembic/versions/<new_rev>_<message>.py`.
   - If the file contains multiple `op.alter_column(...)` calls on the **same table**, wrap them in a single `op.batch_alter_table("table_name") as batch_op:` block and call `batch_op.alter_column(...)` for each. This forces Postgres into one table rewrite rather than N rewrites — the pattern that filled the prod volume on 2026-04-19.
   - Alembic's autogenerate tends to emit split statements. You must hand-collapse them. Review every revision file before committing.

4. **Estimate disk cost.** Cross-reference `docs/incidents/2026-04-18-migration-filled-postgres-volume/volume-downgrade-playbook.md` — Rule 2's rewrite-size estimate (rows × avg row width × 2 for the temp copy). If the estimate exceeds 25% of Railway's provisioned volume, schedule a volume upgrade before the deploy and take a manual Railway backup immediately before merging.

5. **Test locally:**

   ```
   cd src/backend
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/jobscraper SCRAPER_ENVIRONMENT=local alembic upgrade head
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/jobscraper SCRAPER_ENVIRONMENT=local alembic downgrade -1
   DATABASE_URL=postgresql://postgres:postgres@localhost:5432/jobscraper SCRAPER_ENVIRONMENT=local alembic upgrade head
   ```

   Downgrade-then-upgrade verifies the revision is reversible. If downgrade fails, fix `downgrade()` before committing.

6. **Run the parity test:** `cd scripts && pytest tests/integration/test_alembic_parity.py` — confirms `db_models.Base.metadata.create_all` and Alembic autogenerate remain in agreement after your edit.

7. **Commit the revision file with the model change** in the same commit. PR, review, merge. Railway's next deploy applies it via the lifespan hook.

## Failure modes

- **`alembic upgrade head` fails during lifespan:** the lifespan exception propagates and the container exits. Because the Railway service currently has `healthcheckPath: null` and an `ON_FAILURE` restart policy, Railway will retry the broken container up to 10 times before leaving the service in a degraded state — **it will not automatically retain the prior deployment**. Read the Railway logs for the specific revision failure, fix the revision file, commit, redeploy. If the service is hard-down and a fix isn't ready, manually re-pin the previous image in Railway's UI per the Rollback section. **Fail-forward by default** — don't chase a broken deploy with manual SQL on prod.
- **Long-running migration blocks lifespan:** Alembic has no built-in lock-timeout analog to the old runner's `SET LOCAL lock_timeout`. A revision that rewrites a large table can hold the FastAPI startup open until Postgres finishes. Railway's default health-check timeout will eventually kill the container. Mitigate at the revision level: use `op.batch_alter_table` to combine ALTERs (Rule 2), avoid `ALTER TABLE ... SET NOT NULL` on unbacked columns, and size the volume for the rewrite temp copy.
- **Two Railway replicas deploy simultaneously:** the current Railway rollout is single-pod, so two replicas running `alembic upgrade head` against the same DB is not a failure mode today. If the service scales to multiple replicas, Alembic's `alembic_version` row-level lock provides basic mutual exclusion — one replica wins, the others see head and exit. This is weaker than the old runner's `pg_advisory_lock` and should be revisited if we move to multi-instance hot deploy.
- **`alembic_version_prod` drift:** if the row goes missing (e.g. a DB restore from before the stamp), re-run step 2 of the prod stamp sequence. Do not run `alembic upgrade head` first — upgrade from `base` will try to apply every revision including future non-empty ones.

## Legacy artifact: `schema_migrations_prod`

The tracking table from the old runner remains on prod with its 5 rows of history. It is no longer written to. It is preserved as historical evidence. A separate cleanup PR may drop it after the Alembic era has stabilized; until then, ignore it. No application code reads it.
