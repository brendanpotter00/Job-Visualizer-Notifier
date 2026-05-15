# Env-agnostic Postgres table names

## Context

Today every Postgres table in this project carries an `_{env}` suffix (`job_listings_prod`, `users_local`, `scrape_runs_local`, `user_enabled_companies_test_0a5bd6ed`, …). The suffix was originally a safety valve so local, qa, prod, and per-test schemas could coexist in one shared Postgres instance. In practice there is no shared-instance scenario anymore: local has its own Docker Postgres, prod is a Railway Postgres with one Railway service (`SCRAPER_ENVIRONMENT=prod`), and test isolation is handled case-by-case via `test_<hex>` envs that leak tables when the process dies. The suffix now adds complexity for no benefit — every SQL statement in `scripts/shared/database.py` is an f-string, every SQLAlchemy `__tablename__` is computed at import time, every test fixture reloads modules to rebind the suffix, and there are 23 stale `user_enabled_companies_test_*` tables in local from interrupted runs.

**Goal.** Remove the suffix everywhere. After this change, every environment uses bare table names: `job_listings`, `scrape_runs`, `users`, `user_enabled_companies`. Alembic's tracker becomes the default `alembic_version`. The `SCRAPER_ENVIRONMENT` env var, the `--env` CLI flag, the `env` parameter threaded through `scripts/shared/database.py`, and the `ALLOWED_ENVS` / `_TEST_ENV_PATTERN` helpers are deleted. Test isolation switches from per-test table-suffix to per-pytest-worker Postgres **schema** (`SET search_path TO <schema>` on connect; bare table names inside).

**Why RENAME-only.** The 2026-04-18 production incident (`docs/incidents/2026-04-18-migration-filled-postgres-volume/`) filled Railway's 5 GB volume when migrations 0003/0004 triggered four full-table rewrites on a 138 MB `job_listings_prod`. The combined-ALTER fix in 0004 is load-bearing repo memory. `ALTER TABLE … RENAME TO …` is a catalog-only change — no row rewrites, no WAL bloat, no temp copies. The migration for this feature MUST use `op.rename_table`, `ALTER INDEX … RENAME`, `ALTER TABLE … RENAME CONSTRAINT …`, and `DROP TABLE IF EXISTS schema_migrations_{env}` exclusively. No create-new-and-copy. No data migration. No dual-write period.

**Out of scope.** No column changes, no type changes, no new indexes, no data transformations. Frontend and Vercel serverless proxies are untouched (they don't talk to Postgres directly). We preserve no `SCRAPER_ENVIRONMENT` backcompat shim — it's deleted cleanly. Downgrade is explicit: the downgrade function takes the target env name via `alembic -x env=<name>` because there's no ambient env var to read post-change.

## Shared Contracts

Frozen for every unit. Any drift is a blocker.

**Final table names (all envs):**
- `job_listings`
- `scrape_runs`
- `users`
- `user_enabled_companies`

**Final Alembic tracker:** `alembic_version` (Alembic's default). `src/backend/alembic/env.py` MUST NOT pass `version_table=` to either `context.configure` call.

**Final index / constraint names (all envs):**
- `job_listings`: `idx_job_listings_status`, `idx_job_listings_company`, `idx_job_listings_last_seen`
- `users`: UNIQUE constraint `users_email_key`, `idx_users_auth0_id`, `idx_users_email`, plus the autogen-created unique index backing `auth0_id UNIQUE` (Postgres names it `users_auth0_id_key` — preserved via rename).
- `user_enabled_companies`: `idx_user_enabled_companies_user_id`; composite PK stays unnamed (PostgreSQL default `user_enabled_companies_pkey`).
- `scrape_runs`: no secondary indexes; PK stays `scrape_runs_pkey`.

**Allowed migration ops (exhaustive list):**
- `op.rename_table(old, new)` — one per user table.
- `op.execute("ALTER INDEX <old> RENAME TO <new>")` — one per index, including the PK's implicit index (`job_listings_{env}_pkey` → `job_listings_pkey`, etc.) only if Postgres didn't auto-rename it with the table (verify locally — Postgres auto-renames the PK index with the table in most cases, so the explicit ALTER INDEX may be unneeded; the implementer confirms empirically).
- `op.execute("ALTER TABLE <table> RENAME CONSTRAINT <old> TO <new>")` — for `users_<env>_email_key` → `users_email_key`.
- `op.execute("DROP TABLE IF EXISTS schema_migrations_local")` and `op.execute("DROP TABLE IF EXISTS schema_migrations_prod")` — the pre-Alembic tracker from PR #76.
- `op.execute("ALTER TABLE alembic_version_<env> RENAME TO alembic_version")`, guarded by `to_regclass('alembic_version_<env>')` so running against a DB that never had the suffixed tracker (e.g. a fresh local) is a no-op.
- **Forbidden:** `op.create_table`, `op.drop_table` (other than `schema_migrations_*`), `op.add_column`, `op.drop_column`, `op.alter_column`, `op.create_index`, `op.drop_index`, `op.execute("CREATE TABLE …")`, `INSERT INTO … SELECT …`. Any of these in the revision file is a blocker.

**Alembic version-table bootstrap.** The migration itself runs against a DB where the tracker is `alembic_version_<env>` (env.py still reads `settings.scraper_environment` at the moment the migration starts). During `upgrade()`, we rename that tracker to `alembic_version` as the LAST statement. In the same commit, `env.py` stops passing `version_table=`. The next startup will look for `alembic_version` (Alembic default) and find the renamed table — bootstrap is correct. The `to_regclass` guard makes the rename idempotent so re-running `upgrade` on an already-renamed DB is safe.

**Test schema isolation contract.**
- Each pytest worker (including single-worker runs) generates `test_<hex>` once per session.
- Fixture `CREATE SCHEMA IF NOT EXISTS "test_<hex>"` once before any migration, `DROP SCHEMA "test_<hex>" CASCADE` at session teardown (schema-scoped DROP cascades to every contained table — no per-table loop).
- New env var `PYTEST_SCHEMA` carries the schema name. Both `src/backend/alembic/env.py` and `scripts/shared/database.get_connection` check for it and run `SET search_path TO "<schema>", public` after connecting. Application queries do NOT hardcode the schema — they rely on `search_path`.
- When `PYTEST_SCHEMA` is unset (prod, local dev, scraper runs), `search_path` is untouched (Postgres default `public`), tables live in `public`, behavior is identical to not having the feature.
- Inside the test schema, tables are UNSUFFIXED: `job_listings`, `users`, etc. — same names as prod.

**No `SCRAPER_ENVIRONMENT` anywhere.** Any unit that leaves a runtime reference to `SCRAPER_ENVIRONMENT`, `scraper_environment`, or `--env` is a blocker. Grep for all three at the end of every unit.

**Rollout order.** Local → Prod. The one-time prod rename is a pre-deploy operator step (see Unit 5 runbook), mirroring the alembic stamp pattern in `docs/implementations/alembicMigration/DEPLOY.md`.

## Work Units

### Unit 1 — Schema-aware test isolation foundation

**Status:** DONE (commit `6d8f216`)

**Findings for downstream units:**
- Baseline Alembic revision `91337142414f` is empty; user tables come from `Base.metadata.create_all` in fixtures, not from Alembic. Unit 3's rename migration is still correct (it operates on the live `_local`/`_prod` tables that `create_all` or prior hand-rolled DDL produced), but the implementer should NOT expect `alembic upgrade head` on a fresh DB to produce `job_listings_local` — only `alembic_version_local`.
- `Base.metadata.create_all(checkfirst=False)` is load-bearing inside fixtures: SQLAlchemy's default existence probe sees `public.job_listings_local` on shared dev DBs and skips creation, leaving the test schema empty. Unit 2's conftest edits must preserve this `checkfirst=False`.
- `connection.commit()` required after `CREATE SCHEMA IF NOT EXISTS` in `alembic/env.py` under SQLAlchemy 2.x; without it the implicit transaction rolls back and the schema vanishes.
- Teardown order: close the test's psycopg2 connection BEFORE `DROP SCHEMA … CASCADE`, else the open session reference deadlocks the drop.

**Prerequisites:** none

**Owned files** (may be created/edited exclusively in this unit):
- none (this unit is shared-file edits only; no new files)

**Shared-file edits** (appends only; prior lines must not move):
- `src/backend/alembic/env.py` — add a `_PYTEST_SCHEMA = os.environ.get("PYTEST_SCHEMA")` block BEFORE the existing `_version_table` computation. In `run_migrations_online`, after `connectable.connect() as connection` and BEFORE `context.configure(...)`, run `if _PYTEST_SCHEMA: connection.execute(text('CREATE SCHEMA IF NOT EXISTS "' + _PYTEST_SCHEMA + '"')); connection.execute(text('SET search_path TO "' + _PYTEST_SCHEMA + '", public'))`. In `run_migrations_offline`, do the same via raw `context.execute` injected into the migration stream (or simply skip — offline mode is only used by operators in this repo).
- `scripts/shared/database.py::get_connection` — after `psycopg2.connect(...)`, read `os.environ.get("PYTEST_SCHEMA")` and if set, run one cursor.execute `SET search_path TO "<schema>", public`. The setting is per-connection — no pool concerns because this function opens a fresh connection each call.
- `src/backend/api/dependencies.py` (connection pool factory) — same treatment: if `PYTEST_SCHEMA` is set, run `SET search_path TO ...` as each pooled connection is returned to the caller. Confirm the pool uses `psycopg2.pool.ThreadedConnectionPool` or similar and hook the `getconn` path.
- `src/backend/api/tests/conftest.py::db_conn` — rewrite: remove the `_make_test_env()` + ALLOWED_ENVIRONMENTS widening dance. Instead, generate `test_<hex>` once per module, set `os.environ["PYTEST_SCHEMA"] = schema`, open a psycopg2 connection, `CREATE SCHEMA IF NOT EXISTS "<schema>"`, `SET search_path`, then call `apply_alembic_migrations(TEST_DB_URL, <unused>)`. Tables are now bare-named inside the schema. Teardown: `DROP SCHEMA "<schema>" CASCADE`; pop `PYTEST_SCHEMA`.
- `scripts/tests/conftest.py::postgres_db` — mirror the same rewrite. Drop the `importlib.reload(_db_models)` dance entirely — tables are no longer env-suffixed, so there's no need to rebind suffixes across test modules.
- `src/backend/api/tests/test_db_models.py` — update expected table names from `job_listings_local` → `job_listings` (single edit pass; keep test structure).

**What to do:**
- Introduce `PYTEST_SCHEMA` as the one contract both test-fixture layers and the runtime DB layer honor.
- Keep `SCRAPER_ENVIRONMENT` alive for this unit — the point of Unit 1 is landing the isolation plumbing before Unit 2 starts ripping out the env-suffix system. Tables are STILL `_local` in the live code at end of Unit 1; only the test fixtures now carve out a per-worker schema and populate it.
- Verify by running the full test suite twice in parallel (`pytest -n 2`) against a single local Postgres and confirming no cross-worker table collisions.

**Done when:**
- `cd src/backend && pytest api/tests -v` passes.
- `cd scripts && pytest tests -v` passes.
- `PYTEST_SCHEMA=test_deadbeef cd src/backend && alembic upgrade head` (against a fresh local Postgres) creates the schema and populates `alembic_version_local` inside `test_deadbeef` (NOT in `public`).
- `grep -rn "SCRAPER_ENVIRONMENT" src/backend/ scripts/` still has hits — unit does NOT remove them yet.

---

### Unit 2 — Strip env suffix from db_models.py and Alembic env.py defaults

**Status:** DONE (commit `239eed5`)

**Findings for downstream units:**
- 4 SQL f-strings bypassed `_get_table_name` and had to be spot-fixed: `src/backend/api/services/user_preferences_service.py::_table`, `src/backend/api/tests/conftest.py::_clear_tables`, and raw SQL in `scripts/tests/integration/test_database.py` + `test_incremental.py`. All are now bare-named.
- `src/backend/api/tests/test_migrations_env_guard.py` was deleted here (was scheduled for Unit 4). The guard it tested was removed from `migrations.py` and the test file covered the removed guard — couldn't stay.
- Parity test currently XPASSes (strict=False, still exit 0) — unexpected but benign. It xpasses because the parity DB is seeded from `create_all` (bare names), so there's no drift to detect. Unit 3 removes the xfail once the migration applies.

**Prerequisites:** Unit 1

**Owned files:**
- `src/backend/api/db_models.py` — rewrite without any env resolution. Drop `_ALLOWED_ENVS`, `_TEST_ENV_PATTERN`, `_resolve_env`, `_ENV`. Every `__tablename__` becomes the bare name. Every `Index(...)`, `UniqueConstraint(...)`, and `ForeignKey(...)` reference uses the bare name.

**Shared-file edits:**
- `src/backend/alembic/env.py` — delete `_env_suffix = settings.scraper_environment` and `_version_table = f"alembic_version_{_env_suffix}"`. Remove `version_table=_version_table` from BOTH `context.configure` calls in `run_migrations_offline` and `run_migrations_online` (Alembic defaults to `alembic_version`). Leave `compare_type=True, compare_server_default=True`. Leave the `PYTEST_SCHEMA` block from Unit 1.
- `scripts/shared/database.py::_get_table_name` — **scope revision during implementation (2026-04-19):** The helper must return BARE table names (`"job_listings"`, `"scrape_runs"`, `"users"`) regardless of the `env` argument. Without this change, Unit 2 would leave `scripts/shared/database.py` emitting `_local`-suffixed SQL while fixtures create bare-named tables inside the `PYTEST_SCHEMA` — `search_path` would fall back to `public.job_listings_local` and silently corrupt the shared dev DB. Keep the `env: str` parameter (Unit 4 strips it). Keep `_is_valid_env(env)` validation so bogus envs still error. Everything else in `scripts/shared/database.py` (ALLOWED_ENVS, public function signatures) remains untouched for Unit 4.
- `src/backend/api/tests/test_db_models.py` — update every assertion from `*_local` to bare names (e.g. `idx_users_local_email` → `idx_users_email`, `users_local_email_key` → `users_email_key`). Delete any `db_models_module` reload fixture.
- `src/backend/api/migrations.py` — remove the `scraper_environment mismatch` guard in `apply_alembic_migrations`. The guard exists because env.py read `settings.scraper_environment`; env.py no longer does that. The function signature remains `apply_alembic_migrations(database_url, env)` for now (Unit 4 deletes the `env` arg entirely), but the body only uses `database_url`.

**What to do:**
- At end of this unit, `db_models.py` declares tables as `job_listings`, `scrape_runs`, `users`, `user_enabled_companies` with bare index/constraint names.
- The parity test at `scripts/tests/integration/test_alembic_parity.py` will begin reporting drift between `db_models.py` and the live `_local`-suffixed schema. That failure is expected — Unit 3's rename migration resolves it. Mark the parity test with `@pytest.mark.xfail(reason="Drift expected until rename migration lands; see envAgnosticTables Unit 3")` in THIS unit so CI stays green between commits. Unit 3 removes the xfail.

**Done when:**
- `python -c "from api.db_models import Base; print(sorted(Base.metadata.tables))"` prints `['job_listings', 'scrape_runs', 'user_enabled_companies', 'users']`.
- `cd src/backend && pytest api/tests/test_db_models.py -v` passes against the new expected names.
- `grep -n "SCRAPER_ENVIRONMENT\|_ENV\|_resolve_env\|version_table" src/backend/api/db_models.py src/backend/alembic/env.py` returns NO matches (version_table references allowed only inside comments).
- `cd scripts && pytest tests/integration/test_alembic_parity.py` is xfailing (not erroring), with the reason message Unit 3 will key off.

---

### Unit 3 — Author the rename migration (combined ALTERs, downgrade via -x env=)

**Status:** DONE (commit `ee5fe7f`)

**Findings for downstream units:**
- Revision ID `e1974f8f8eee` chains from baseline `91337142414f`. Round-trip verified locally: bare (3781/2/0/0) → downgrade `-x env=local` → `_local` (3781/2/0/0) → upgrade head → bare (3781/2/0/0). Row counts preserved exactly.
- Three bugs in the original runbook's revision body were caught during implementation:
  1. `SET LOCAL search_path TO current_schema()` is invalid Postgres syntax — `SET LOCAL` accepts identifiers/string-literals, not function calls. Replaced with `SELECT set_config('search_path', current_schema(), true)` which is the transaction-scoped equivalent.
  2. `op.get_context().get_x_argument(...)` fails with `AttributeError` — `get_x_argument` lives on `EnvironmentContext` (`alembic.context`), not `MigrationContext` (`op.get_context()`). Downgrade now imports `from alembic import context, op` and calls `context.get_x_argument(as_dictionary=True)`.
  3. `ALTER TABLE IF EXISTS ... RENAME CONSTRAINT` guards only the TABLE, not the constraint. Under local, the `users_prod_email_key` rename attempt errored with `UndefinedObject`. Wrapped in `DO $$ BEGIN ... EXCEPTION WHEN undefined_object OR undefined_table THEN NULL; END $$` so absent variants no-op.
- The xfail decorator from `scripts/tests/integration/test_alembic_parity.py` is removed; parity test passes unconditionally.
- Prod state verified unchanged via read-only `mcp__postgres-prod__query` — all 4 tables still `_prod`-suffixed. Unit 5 owns the prod rename DEPLOY step.

**Prerequisites:** Unit 2

**Owned files:**
- `src/backend/alembic/versions/<new_rev>_remove_env_suffix_from_tables.py` — NEW. Created via `cd src/backend && DATABASE_URL=<local-url> SCRAPER_ENVIRONMENT=local alembic revision --autogenerate -m "remove env suffix from tables"`, then the autogenerated DROP/CREATE body is **hand-replaced** with the rename ops enumerated below. Down-revision chains from `91337142414f` (the existing baseline).

**Shared-file edits:**
- `scripts/tests/integration/test_alembic_parity.py` — remove the xfail added in Unit 2. After the migration applies, db_models.py and the live schema should match exactly (both are unsuffixed).
- `src/backend/api/tests/test_db_models.py` — if any index/constraint-name assertions still embed `_local`, update to bare names.

**What to do:**

1. Run autogenerate to get the scaffold and revision ID:
   ```
   cd src/backend && DATABASE_URL=postgresql://postgres:postgres@localhost:5432/jobscraper \
     SCRAPER_ENVIRONMENT=local alembic revision --autogenerate -m "remove env suffix from tables"
   ```
2. Open the generated file. Autogenerate will emit something catastrophic — likely `op.drop_table("job_listings_local")` + `op.create_table("job_listings", ...)`. **DELETE the autogenerated body entirely.** Replace `upgrade()` with exactly this sequence (the order matters: rename child tables before parents so FK implicit constraints follow the rename cleanly):

   ```python
   def upgrade() -> None:
       # Drop the pre-Alembic legacy tracker. Idempotent; harmless on fresh envs.
       op.execute("DROP TABLE IF EXISTS schema_migrations_local")
       op.execute("DROP TABLE IF EXISTS schema_migrations_prod")

       # Rename the four user tables. Postgres auto-renames the implicit
       # PK index and sequence with the table; we do NOT need ALTER INDEX
       # for *_pkey. Verify with `\d+ job_listings` locally after running.
       op.execute("ALTER TABLE IF EXISTS job_listings_local RENAME TO job_listings")
       op.execute("ALTER TABLE IF EXISTS job_listings_prod  RENAME TO job_listings")
       op.execute("ALTER TABLE IF EXISTS scrape_runs_local  RENAME TO scrape_runs")
       op.execute("ALTER TABLE IF EXISTS scrape_runs_prod   RENAME TO scrape_runs")
       op.execute("ALTER TABLE IF EXISTS user_enabled_companies_local RENAME TO user_enabled_companies")
       op.execute("ALTER TABLE IF EXISTS user_enabled_companies_prod  RENAME TO user_enabled_companies")
       op.execute("ALTER TABLE IF EXISTS users_local RENAME TO users")
       op.execute("ALTER TABLE IF EXISTS users_prod  RENAME TO users")

       # Rename named indexes (Postgres does NOT auto-rename these with the table).
       for old, new in [
           ("idx_job_listings_local_status",  "idx_job_listings_status"),
           ("idx_job_listings_local_company", "idx_job_listings_company"),
           ("idx_job_listings_local_last_seen","idx_job_listings_last_seen"),
           ("idx_job_listings_prod_status",   "idx_job_listings_status"),
           ("idx_job_listings_prod_company",  "idx_job_listings_company"),
           ("idx_job_listings_prod_last_seen","idx_job_listings_last_seen"),
           ("idx_users_local_auth0_id", "idx_users_auth0_id"),
           ("idx_users_local_email",    "idx_users_email"),
           ("idx_users_prod_auth0_id",  "idx_users_auth0_id"),
           ("idx_users_prod_email",     "idx_users_email"),
           ("idx_user_enabled_companies_local_user_id", "idx_user_enabled_companies_user_id"),
           ("idx_user_enabled_companies_prod_user_id",  "idx_user_enabled_companies_user_id"),
       ]:
           op.execute(f"ALTER INDEX IF EXISTS {old} RENAME TO {new}")

       # Rename the named UNIQUE constraint on users.email.
       op.execute("ALTER TABLE IF EXISTS users RENAME CONSTRAINT users_local_email_key TO users_email_key")
       op.execute("ALTER TABLE IF EXISTS users RENAME CONSTRAINT users_prod_email_key  TO users_email_key")

       # Bootstrap: the Alembic tracker itself must be renamed. At the moment
       # this migration runs, env.py still targets alembic_version_<env>.
       # In the SAME commit Unit 2 removed version_table=, so the NEXT startup
       # will look for alembic_version. The to_regclass guard makes this safe
       # against fresh envs that never had the suffixed tracker.
       op.execute("""
           DO $$
           BEGIN
               IF to_regclass('alembic_version_local') IS NOT NULL THEN
                   EXECUTE 'ALTER TABLE alembic_version_local RENAME TO alembic_version';
               ELSIF to_regclass('alembic_version_prod') IS NOT NULL THEN
                   EXECUTE 'ALTER TABLE alembic_version_prod RENAME TO alembic_version';
               END IF;
           END $$;
       """)
   ```

3. Write `downgrade()`. Because there's no ambient `SCRAPER_ENVIRONMENT` after this change, downgrade must be explicit. Accept the target env via `-x env=<name>`:

   ```python
   def downgrade() -> None:
       ctx = op.get_context()
       x = ctx.get_x_argument(as_dictionary=True)
       env = x.get("env")
       if env not in ("local", "prod"):
           raise RuntimeError(
               "downgrade requires -x env=local|prod (no ambient SCRAPER_ENVIRONMENT "
               "after envAgnosticTables). Run: alembic -x env=<env> downgrade -1"
           )
       suffix = f"_{env}"

       op.execute(f"ALTER TABLE IF EXISTS alembic_version RENAME TO alembic_version{suffix}")
       op.execute(f"ALTER TABLE IF EXISTS users RENAME CONSTRAINT users_email_key TO users{suffix}_email_key")
       for new, old in [
           ("idx_job_listings_status",       f"idx_job_listings{suffix}_status"),
           ("idx_job_listings_company",      f"idx_job_listings{suffix}_company"),
           ("idx_job_listings_last_seen",    f"idx_job_listings{suffix}_last_seen"),
           ("idx_users_auth0_id",            f"idx_users{suffix}_auth0_id"),
           ("idx_users_email",               f"idx_users{suffix}_email"),
           ("idx_user_enabled_companies_user_id", f"idx_user_enabled_companies{suffix}_user_id"),
       ]:
           op.execute(f"ALTER INDEX IF EXISTS {new} RENAME TO {old}")
       for t in ("job_listings", "scrape_runs", "users", "user_enabled_companies"):
           op.execute(f"ALTER TABLE IF EXISTS {t} RENAME TO {t}{suffix}")
       # `schema_migrations_{env}` was DROP'd in upgrade; downgrade does NOT
       # recreate it. Document in the docstring that this is one-way.
   ```

   Docstring at the top of the file MUST state: "Downgrade is single-env: pass `-x env=local` or `-x env=prod`. `schema_migrations_{env}` is not recreated."

4. Verify locally:
   - `cd src/backend && alembic upgrade head` — renames `*_local` tables to bare names.
   - `cd src/backend && alembic -x env=local downgrade -1` — reverses to `*_local` names.
   - `cd src/backend && alembic upgrade head` — re-renames. Must produce an empty diff against `db_models.py` (parity test).

5. Clean up stale local test artifacts (one-time, NOT part of the migration). The Unit 5 DEPLOY.md snippet documents:
   ```sql
   -- Run once against local Postgres after merging this PR. Removes 23 stale
   -- user_enabled_companies_test_* tables from interrupted pytest runs.
   DO $$
   DECLARE r record;
   BEGIN
     FOR r IN SELECT tablename FROM pg_tables
              WHERE schemaname = 'public' AND tablename LIKE 'user_enabled_companies_test_%'
     LOOP EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename); END LOOP;
     FOR r IN SELECT tablename FROM pg_tables
              WHERE schemaname = 'public' AND tablename LIKE 'alembic_version_test_%'
     LOOP EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', r.tablename); END LOOP;
   END $$;
   ```

**Done when:**
- `cd src/backend && alembic upgrade head` against a fresh `_local` schema (simulated by stamping the baseline and creating `_local` tables manually, or more simply against the operator's real local DB) produces the renamed tables with ZERO row-count change on any table. Verify with `SELECT COUNT(*) FROM job_listings;` equals the pre-rename `SELECT COUNT(*) FROM job_listings_local;`.
- `cd scripts && pytest tests/integration/test_alembic_parity.py` passes (no xfail, clean diff).
- `cd src/backend && alembic -x env=local downgrade -1` followed by `alembic upgrade head` is idempotent.
- The revision file contains ZERO `op.create_table`, `op.drop_table` (other than the two `schema_migrations_*` drops), `op.add_column`, or `op.alter_column` calls. Confirm via `grep -E "op\.(create|drop|add|alter_column)" src/backend/alembic/versions/<new_rev>_*.py`.

---

### Unit 4 — Delete SCRAPER_ENVIRONMENT and --env plumbing

**Status:** DONE (commit `9bf8950`)

**Findings for downstream units:**
- Grep gates are clean outside `docs/`: `SCRAPER_ENVIRONMENT`, `scraper_environment`, `--env`, `_get_table_name`, `ALLOWED_ENVS`, `_TEST_ENV_PATTERN`, `_is_valid_env` have zero matches in `src/` and `scripts/` (excluding `.claude/worktrees/`, `.venv/`, and historical `docs/` prose). The one remaining `--env` hit inside code (`test_scraper_runner.py:66: assert "--env" not in args`) is a negative assertion pinning the subprocess contract — intentional, not a leak.
- Backend suite: 176 tests pass. Scripts suite (excluding `test_alembic_parity.py` which needs a fresh Postgres DB) 365 tests pass. Parity still works when run against a local Postgres.
- `src/backend/api/migrations.py` signature is now `apply_alembic_migrations(database_url: str)` — single-arg. The env-mismatch guard is gone.
- `BatchWriter(conn, scraper)` no longer takes an `env` positional. Callers throughout `scripts/shared/incremental.py` were updated in lockstep.
- `app.state.env` is not set or read anywhere — confirmed via grep.
- Railway `SCRAPER_ENVIRONMENT=prod` variable is still live in the dashboard; deletion is a Unit 5 post-merge manual step because the code no longer reads it (harmless dead config).

**Prerequisites:** Unit 3

**Owned files:**
- `src/backend/api/tests/test_migrations_env_guard.py` — DELETE. The guard was premised on env-mismatch between settings and caller; there are no envs anymore.

**Shared-file edits:**
- `src/backend/api/config.py` — remove `scraper_environment` field, `ALLOWED_ENVIRONMENTS`, and the `validate_environment` validator. Keep everything else untouched.
- `src/backend/api/main.py` — delete the `settings.scraper_environment` references (lines 28, 32, 45). `apply_alembic_migrations(settings.database_url)` (drop second arg). Delete `app.state.env = settings.scraper_environment` — nothing reads `app.state.env` after this unit (verify via grep).
- `src/backend/api/migrations.py` — change signature from `apply_alembic_migrations(database_url: str, env: str)` to `apply_alembic_migrations(database_url: str)`. Delete the env-mismatch guard entirely.
- `src/backend/api/services/scraper_runner.py:52` — remove `"--env", config.scraper_environment,` from the argv list.
- `src/backend/api/dependencies.py` — if there's anything reading `settings.scraper_environment` or passing `env=` to `get_connection`, strip it.
- `scripts/shared/database.py` — remove `ALLOWED_ENVS`, `_TEST_ENV_PATTERN`, `_is_valid_env`, `_get_table_name`. Every function signature loses the `env: str = "local"` parameter. Every f-string like `f"SELECT id FROM {jobs_table}"` becomes `"SELECT id FROM job_listings"`. The JSON column list `_JOB_COLUMNS` and the `_UPSERT_ON_CONFLICT` body are unchanged. This is a large but mechanical diff.
- `scripts/shared/incremental.py` — remove `env` parameter from `run_incremental_scrape` and any helper. Every call site into `database.py` loses the `env` kwarg.
- `scripts/shared/batch_writer.py` — remove `env` from `BatchWriter.__init__` and all method signatures that take it.
- `scripts/shared/base_scraper.py` — if it stores/uses `env`, remove.
- `scripts/run_scraper.py` — delete the `--env` argparse flag. Delete `env = args.env` and every downstream use. Call `apply_alembic_migrations(db_url)` (one-arg). Change exit code comment to reflect.
- `scripts/tests/integration/test_database.py`, `scripts/tests/integration/test_incremental.py`, `scripts/tests/integration/test_scraper_transform.py`, etc. — every call site that passes `env=test_env` loses the kwarg. Fixtures keep `test_env` for the schema-name generator, not for table-name suffixing.
- `src/backend/api/tests/conftest.py` — remove references to `_get_table_name` (import + usage). `_insert_job`, `_insert_scrape_run`, `_insert_user` hardcode table names (`job_listings`, `scrape_runs`, `users`, `user_enabled_companies`). `_clear_tables` hardcodes the four table names in its `TRUNCATE`.
- `src/backend/api/tests/test_main_lifespan.py` — update any references to `SCRAPER_ENVIRONMENT`.
- `docker-compose.yml` — remove any `SCRAPER_ENVIRONMENT: local` from the api service env (grep confirmed no hits in top-level file, but worktrees have them — verify the live file).
- `src/backend/Dockerfile` — remove any `ENV SCRAPER_ENVIRONMENT=prod` line (grep confirmed none in live Dockerfile; verify).
- `.env.local` and `.env.development.local` — remove `SCRAPER_ENVIRONMENT=` lines if present.
- Railway env var — NOT edited in this PR; documented in Unit 5 DEPLOY runbook as a post-merge manual action.

**What to do:**
- After this unit, `grep -rn "SCRAPER_ENVIRONMENT\|scraper_environment\|--env" src/ scripts/ --exclude-dir=.claude --exclude-dir=.venv` MUST return zero matches outside of `docs/` and `docs/incidents/` historical writings.
- `scripts/shared/database.py` becomes substantially shorter — it's the largest single-file diff in the PR. The function contract for every public function (`get_connection`, `insert_job`, `upsert_jobs_batch`, `get_active_job_ids`, …) loses its `env` parameter. Update every caller in lockstep; do NOT leave an env-accepting shim.
- Verify no `app.state.env` readers remain. If the jobs_qa router or a test was reading it, rewrite that code path (likely irrelevant after removing `--env`).

**Done when:**
- `grep -rn "SCRAPER_ENVIRONMENT\|scraper_environment" src/ scripts/ | grep -v docs/ | grep -v .claude/` returns zero matches.
- `grep -rn "\-\-env\|args\.env\|env=env\|env=test_env\|env=\"local\"\|env='local'" src/ scripts/ | grep -v .claude/` returns zero matches.
- `grep -rn "_get_table_name\|ALLOWED_ENVS\|_TEST_ENV_PATTERN\|_is_valid_env" src/ scripts/ | grep -v .claude/` returns zero matches.
- `cd src/backend && pytest api/tests -v` passes.
- `cd scripts && pytest tests -v` passes.
- `python scripts/run_scraper.py --help` does not list `--env`.
- `python scripts/run_scraper.py --company google --db-url postgresql://postgres:postgres@localhost:5432/jobscraper --max-jobs 3` completes a scrape end-to-end against a local DB that has already had the Unit 3 migration applied.

---

### Unit 5 — Docs, DEPLOY runbook, stale-artifact cleanup SQL

**Status:** DONE

**Prerequisites:** Unit 4

**Owned files:**
- `docs/implementations/envAgnosticTables/DEPLOY.md` — NEW. Contents outlined below.

**Shared-file edits:**
- `docs/implementations/alembicMigration/DEPLOY.md` — add a "Superseded by envAgnosticTables" callout at the top: references to `alembic_version_<env>` and `SCRAPER_ENVIRONMENT` in this file are historical; the live tracker is now `alembic_version`. Do NOT rewrite the body — it remains correct as a historical record of the Alembic migration.
- `src/backend/CLAUDE.md` — rewrite the `Environment-based table naming` bullets and the `SCRAPER_ENVIRONMENT` row of the env-var table (delete the row). Under `Schema migrations`, change `alembic_version_<env>` → `alembic_version`, delete the "`SCRAPER_ENVIRONMENT` drives table suffix resolution" bullet, and update the test-isolation bullet to mention `PYTEST_SCHEMA` / per-worker schemas.
- `scripts/CLAUDE.md` — delete `--env` from the CLI options table and from every example. Delete the "Environment Flag Affects Tables" gotcha. Change "Jobs stored in `job_listings_{env}` table" → "Jobs stored in `job_listings` table". Delete the "`job_listings_{env}`" reference in the data flow section.
- `CLAUDE.md` (root) — grep confirmed no current matches; if the file gains a reference during another PR between merging Unit 2 and Unit 5, strip it.
- `docs/LOCAL-SETUP.md` — delete the `SCRAPER_ENVIRONMENT` row (line 261) and the prose at line 248 describing `_local`.

**What to do:**
- `DEPLOY.md` must cover five things in order:
  1. **Prod rename sequence** (human-run, pre-merge):
     - Take a Railway manual Postgres backup. Mandatory — rename is catalog-only but there's no going back without a restore if downgrade is missed.
     - From the operator workstation with prod `DATABASE_URL` exported: `cd src/backend && SCRAPER_ENVIRONMENT=prod alembic upgrade head`. Expected output: renames eight `*_prod` tables and their indexes/constraints, drops `schema_migrations_prod`, renames `alembic_version_prod` to `alembic_version`.
     - Verify with `mcp__postgres-prod__query "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"` — expect `alembic_version`, `job_listings`, `scrape_runs`, `user_enabled_companies`, `users`.
     - Verify row counts match the pre-rename snapshot.
  2. **Post-merge Railway action:** DELETE the `SCRAPER_ENVIRONMENT=prod` variable in Railway's dashboard. The code no longer reads it; leaving it is harmless but confusing. Call this out as the one manual env-var step.
  3. **Deploy loop:** Railway auto-deploys from main. First post-merge deploy's lifespan runs `alembic upgrade head`, sees head matches, no-op.
  4. **Rollback:** operator runs `cd src/backend && alembic -x env=prod downgrade -1` (explicit env required — no ambient). Document that the legacy `schema_migrations_prod` is NOT restored by downgrade; if a full rollback to pre-Alembic is needed, use the Railway Postgres backup restore.
  5. **Local stale-artifact cleanup:** the DO block from Unit 3 for removing 23 stale `user_enabled_companies_test_*` tables. Operator runs it once against local Postgres after pulling main. Include exact `mcp__postgres__query` invocation.

- Add a note in DEPLOY.md explaining why downgrade requires `-x env=`: because there's no `SCRAPER_ENVIRONMENT` in the post-merge world, the migration can't infer which suffix to restore. Operators pass it explicitly.

**Done when:**
- `docs/implementations/envAgnosticTables/DEPLOY.md` exists, covers the five points above, and cross-links to `docs/incidents/2026-04-18-migration-filled-postgres-volume/README.md`.
- `grep -rn "SCRAPER_ENVIRONMENT\|_local\|_prod\b" CLAUDE.md src/backend/CLAUDE.md scripts/CLAUDE.md docs/LOCAL-SETUP.md` returns only hits inside historical/incident prose or inside the new DEPLOY.md runbook steps.
- `grep -n "\-\-env" scripts/CLAUDE.md` returns zero matches.
- Root CLAUDE.md renders without referencing env-suffix tables.

---

## Critical files

| Path | Why critical | Change type |
|------|--------------|-------------|
| `src/backend/alembic/env.py` | Drops `version_table=`; adds `PYTEST_SCHEMA` search_path hook | Shared-edit (Units 1, 2) |
| `src/backend/api/db_models.py` | Bare table + index + constraint names; `_ENV` removed | Owned (Unit 2) |
| `src/backend/alembic/versions/<new>_remove_env_suffix_from_tables.py` | The RENAME-only migration file; downgrade takes `-x env=` | Owned-new (Unit 3) |
| `src/backend/api/config.py` | `scraper_environment` field deleted | Shared-edit (Unit 4) |
| `src/backend/api/main.py` | Lifespan no longer passes env; no `app.state.env` | Shared-edit (Unit 4) |
| `src/backend/api/migrations.py` | `apply_alembic_migrations(database_url)` one-arg; guard removed | Shared-edit (Units 2, 4) |
| `src/backend/api/services/scraper_runner.py` | Drops `--env` from subprocess argv | Shared-edit (Unit 4) |
| `src/backend/api/dependencies.py` | Honor `PYTEST_SCHEMA` on pooled connections | Shared-edit (Unit 1) |
| `src/backend/api/tests/conftest.py` | Schema-based isolation; bare table names | Shared-edit (Units 1, 4) |
| `src/backend/api/tests/test_db_models.py` | Expect unsuffixed names | Shared-edit (Units 1, 2) |
| `src/backend/api/tests/test_migrations_env_guard.py` | Obsolete; delete | Owned-delete (Unit 4) |
| `src/backend/api/tests/test_main_lifespan.py` | Drop env-arg assertions | Shared-edit (Unit 4) |
| `scripts/shared/database.py` | Remove `env` from every signature; `_get_table_name` gone; hardcoded bare names | Shared-edit (Units 1, 4) |
| `scripts/shared/incremental.py` | Thread-through `env` removed | Shared-edit (Unit 4) |
| `scripts/shared/batch_writer.py` | Thread-through `env` removed | Shared-edit (Unit 4) |
| `scripts/shared/base_scraper.py` | Thread-through `env` removed (verify) | Shared-edit (Unit 4) |
| `scripts/run_scraper.py` | `--env` flag deleted; `apply_alembic_migrations(db_url)` one-arg | Shared-edit (Unit 4) |
| `scripts/tests/conftest.py` | Schema-based isolation; no `_get_table_name` | Shared-edit (Units 1, 4) |
| `scripts/tests/integration/test_alembic_parity.py` | Xfail in Unit 2, remove xfail in Unit 3 | Shared-edit (Units 2, 3) |
| `scripts/tests/integration/test_database.py` | Drop `env=` kwargs | Shared-edit (Unit 4) |
| `scripts/tests/integration/test_incremental.py` | Drop `env=` kwargs | Shared-edit (Unit 4) |
| `scripts/tests/integration/test_scraper_transform.py` | Drop `env=` kwargs | Shared-edit (Unit 4) |
| `docker-compose.yml` | Remove `SCRAPER_ENVIRONMENT` if present | Shared-edit (Unit 4) |
| `src/backend/Dockerfile` | Remove `ENV SCRAPER_ENVIRONMENT` if present | Shared-edit (Unit 4) |
| `.env.local`, `.env.development.local` | Remove `SCRAPER_ENVIRONMENT` lines | Shared-edit (Unit 4) |
| `docs/implementations/envAgnosticTables/DEPLOY.md` | Operator runbook | Owned-new (Unit 5) |
| `docs/implementations/alembicMigration/DEPLOY.md` | Supersession callout | Shared-edit (Unit 5) |
| `src/backend/CLAUDE.md` | Env-var table + Schema migrations subsection | Shared-edit (Unit 5) |
| `scripts/CLAUDE.md` | CLI options, examples, data flow | Shared-edit (Unit 5) |
| `CLAUDE.md` (root) | Verify no env-suffix references | Shared-edit (Unit 5) |
| `docs/LOCAL-SETUP.md` | Delete `SCRAPER_ENVIRONMENT` row + `_local` prose | Shared-edit (Unit 5) |

## Non-goals

- **No data migration.** Zero rows are rewritten. `ALTER TABLE … RENAME` only.
- **No dual-write / backcompat period.** After Unit 4 merges, `_local`/`_prod` table names do not exist in code. The rename migration is the single cutover.
- **No logging-only `SCRAPER_ENVIRONMENT`.** The variable is deleted entirely; we don't keep it as a tag for log lines.
- **No frontend changes.** `src/frontend/` is untouched.
- **No Vercel serverless API proxy changes.** `api/users.ts` and siblings are pass-throughs; they don't read `SCRAPER_ENVIRONMENT`.
- **No schema changes** (no new columns, no type changes, no new indexes). The only DDL is `ALTER TABLE … RENAME`, `ALTER INDEX … RENAME`, `ALTER TABLE … RENAME CONSTRAINT`, `DROP TABLE IF EXISTS schema_migrations_*`.
- **No automated stale-artifact cleanup.** The 23 stale `user_enabled_companies_test_*` tables in local are one-time operator SQL, documented in DEPLOY.md, NOT a migration.
- **No multi-env Alembic.** One env, one `alembic_version`.

## Risks and mitigations

- **Autogenerate emits DROP/CREATE for renames** — the primary implementation pitfall. Alembic cannot distinguish a rename from a drop-and-create. Mitigation: Unit 3's procedure explicitly runs autogenerate *only* to get the filename scaffold, then hand-replaces the body with the rename ops enumerated in Shared Contracts. The Done-when checks grep the revision file for forbidden op calls.
- **Alembic version-table bootstrap** — env.py changes in the same commit that renames the tracker. If the rename step fails mid-migration, the DB is left with the old `alembic_version_<env>` tracker while env.py expects `alembic_version`. Mitigation: the DO-block with `to_regclass` makes the rename idempotent — re-running `alembic upgrade head` catches up cleanly. The migration is the last statement, so everything before it is already committed within the same transaction.
- **Test isolation regression** — Unit 1 lands the schema-per-worker switch before any table renames. A test suite failure here is contained to test infra and rolls back cleanly because no production code is affected. Mitigation: running the full test suite twice in Unit 1's Done-when catches the common pitfall (pooled connections that were opened before `SET search_path` returned to the caller).
- **Railway env-var drift** — operators may forget to delete `SCRAPER_ENVIRONMENT=prod` in Railway's dashboard after merge. Mitigation: the code no longer reads it, so the leftover value is harmless. The PR body + DEPLOY.md both call it out as a manual post-merge step so it gets done for cleanliness, not correctness.
- **Stale test tables in local** — 23 pre-existing `user_enabled_companies_test_*` tables live in the local Postgres `public` schema. After this PR those are orphans (nothing references or drops them). Mitigation: Unit 3's DO-block cleanup SQL, run by each developer once against their local DB, documented in DEPLOY.md. Production has none (verified via `postgres-prod` MCP).
- **Downgrade on prod in a hurry** — the operator must remember `-x env=prod`. If they run `alembic downgrade -1` without the flag, the migration raises `RuntimeError("downgrade requires -x env=")` loudly. Mitigation: the error message tells the operator exactly what to add. A silent-default to `local` would be worse — running a downgrade against prod with a local-suffix target would scramble prod.
