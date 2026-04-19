# Migrate from Custom Migration Runner to Alembic

## Context

On 2026-04-19, migrations 0003 and 0004 — shipped by the hand-rolled runner at `scripts/shared/migrations/runner.py` — ran four separate `ALTER TABLE ... ALTER COLUMN TYPE TIMESTAMPTZ` statements in a Python loop against `job_listings_prod`, triggering four full-table rewrites + four WAL streams on a 5 GB Hobby-tier Postgres volume. The volume filled mid-migration; Postgres crashlooped for ~45 minutes until the volume was upgraded (see `docs/incidents/2026-04-18-migration-filled-postgres-volume/README.md`). The fix in `0004_job_timestamps_timestamptz.py` collapsed the loop into a single combined `ALTER TABLE` with multiple `ALTER COLUMN` clauses — one rewrite, one WAL stream.

That single-statement property is **load-bearing** for this repo. Alembic's autogenerate emits a combined `ALTER TABLE` with multiple `ALTER COLUMN` clauses by default, which is exactly what the incident postmortem prescribes. Going forward, all schema changes flow through Alembic. The custom runner is frozen at versions 0001–0005 and will be deleted.

**Current state.** `scripts/shared/migrations/runner.py` is invoked from the FastAPI lifespan, from a CLI, and from tests. Prod already has versions 1–5 applied (verified against `schema_migrations_prod` via `mcp__postgres-prod__query`; applied timestamps between `2026-04-19T00:13:08Z` and `2026-04-19T00:54:27Z`). Migrations 0003 and 0004 performed destructive data rewrites and **must not run again** on prod.

**Target state.** `alembic upgrade head` replaces `migrate_up`. One empty baseline revision represents the post-0005 schema. The lifespan hook calls Alembic programmatically via `alembic.config.Config` + `command.upgrade` (no shelling out). New schema changes are authored with `alembic revision --autogenerate -m "..."` against SQLAlchemy models in `src/backend/api/db_models.py` that mirror the post-0005 prod schema.

**Call sites of the old runner that must be rewritten or removed:**
- `src/backend/api/main.py:14` — `from scripts.shared.database import init_schema, get_connection`
- `src/backend/api/main.py:34` — `init_schema(temp_conn, settings.scraper_environment)` (lifespan startup)
- `scripts/shared/database.py:137–157` — `init_schema()` whose body is `from .migrations.runner import migrate_up; migrate_up(conn, env)`
- `scripts/migrate.py:26–31` — imports `discover_migrations`, `get_applied_versions`, `migrate_down`, `migrate_up`
- `scripts/run_scraper.py` — calls `db.init_schema(conn, env)` before scraping
- `scripts/tests/conftest.py` — calls `db.init_schema(conn, env=test_env)` and cleans up `schema_migrations_{test_env}`
- `scripts/tests/unit/test_migration_runner.py` — tests the runner directly
- `scripts/tests/unit/test_migrate_cli.py` — tests `scripts/migrate.py`
- `scripts/tests/integration/test_migrations.py` — integration tests of the runner
- `scripts/tests/integration/test_database.py` — uses `db.init_schema` (and possibly `runner`)
- `src/backend/api/tests/conftest.py` — `from scripts.shared.database import init_schema, _get_table_name`; calls `init_schema(conn, test_env)`; cleans up `schema_migrations_{test_env}`
- `scripts/ARCHITECTURE.md` — documents the custom runner

**Environment-suffix reality.** Tables are named `job_listings_{env}`, `scrape_runs_{env}`, `users_{env}`, `user_enabled_companies_{env}`, `schema_migrations_{env}` with `env ∈ {local, qa, prod, test_<hex>}`. Each running process has exactly one `SCRAPER_ENVIRONMENT` (prod is a single Railway service with `SCRAPER_ENVIRONMENT=prod`), so Alembic's `env.py` reads that env var at runtime, composes table names, and uses `version_table=f"alembic_version_{env}"` in both `context.configure` calls so local/qa/prod never collide if someone shares a DB. There is no cross-env Alembic — each process sees one logical schema.

## Shared Contracts

Frozen for all units below. Do not edit these in one unit and change them in another.

**Target post-0005 schema** (source of truth for `db_models.py` in Unit 1; derived by reading `scripts/shared/migrations/0001_initial_schema.py` through `0005_add_user_enabled_companies.py`):

`job_listings_{env}`:
- `id TEXT PRIMARY KEY`
- `title TEXT NOT NULL`
- `company TEXT NOT NULL`
- `location TEXT NULL`
- `url TEXT NOT NULL`
- `source_id TEXT NOT NULL`
- `details JSONB DEFAULT '{}'::jsonb`
- `posted_on TIMESTAMPTZ NULL` *(converted from TEXT in 0003)*
- `created_at TIMESTAMPTZ NOT NULL` *(converted from TEXT in 0004)*
- `closed_on TIMESTAMPTZ NULL` *(converted from TEXT in 0004)*
- `status TEXT NOT NULL DEFAULT 'OPEN'`
- `has_matched BOOLEAN DEFAULT FALSE`
- `ai_metadata JSONB DEFAULT '{}'::jsonb`
- `first_seen_at TIMESTAMPTZ NOT NULL` *(converted in 0004)*
- `last_seen_at TIMESTAMPTZ NOT NULL` *(converted in 0004)*
- `consecutive_misses INTEGER DEFAULT 0`
- `details_scraped BOOLEAN DEFAULT FALSE`
- Indexes: `idx_{table}_status(status)`, `idx_{table}_company(company)`, `idx_{table}_last_seen(last_seen_at)`

`scrape_runs_{env}`:
- `run_id TEXT PRIMARY KEY`
- `company TEXT NOT NULL`
- `started_at TEXT NOT NULL` *(still TEXT — intentionally out of scope of 0003/0004)*
- `completed_at TEXT NULL`
- `mode TEXT NOT NULL`
- `jobs_seen INTEGER DEFAULT 0`, `new_jobs INTEGER DEFAULT 0`, `closed_jobs INTEGER DEFAULT 0`, `details_fetched INTEGER DEFAULT 0`, `error_count INTEGER DEFAULT 0`

`users_{env}`:
- `id TEXT PRIMARY KEY`
- `auth0_id TEXT NOT NULL UNIQUE`
- `email TEXT NOT NULL` with a separate named `UNIQUE` constraint `users_{env}_email_key` *(added by 0002)*
- `display_name TEXT NULL`, `given_name TEXT NULL`, `family_name TEXT NULL`, `picture_url TEXT NULL`
- `created_at TEXT NOT NULL`, `updated_at TEXT NOT NULL` *(still TEXT)*
- Indexes: `idx_{table}_auth0_id(auth0_id)`, `idx_{table}_email(email)`

`user_enabled_companies_{env}` *(from 0005)*:
- `user_id TEXT NOT NULL REFERENCES users_{env}(id) ON DELETE CASCADE`
- `company_id TEXT NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
- `PRIMARY KEY (user_id, company_id)`
- Index: `idx_{table}_user_id(user_id)`

**Alembic layout:**
- `alembic.ini` at repo root. `sqlalchemy.url` left empty — `env.py` injects at runtime.
- `src/backend/alembic/` package (next to `src/backend/api/`).
- `src/backend/alembic/env.py` — reads `DATABASE_URL` and `SCRAPER_ENVIRONMENT` through `src/backend/api/config.Settings` so local/prod share one config surface; passes `version_table=f"alembic_version_{env}"` into both `context.configure()` calls (online and offline); imports `Base` from `src/backend/api/db_models.py` and passes `target_metadata=Base.metadata`; enables `compare_type=True` and `compare_server_default=True` so future autogens catch type regressions.
- `src/backend/alembic/versions/` — revision files live here.
- `src/backend/alembic/script.py.mako` — default template, unchanged.

**`version_table` name:** `alembic_version_{env}`. This differs from Alembic's default `alembic_version` so local/qa/prod tracking tables never collide in a shared DB, matching the repo's existing `schema_migrations_{env}` pattern.

**Command surface after this PR:**
- `cd src/backend && alembic upgrade head` — apply pending migrations (replaces `python scripts/migrate.py up`).
- `cd src/backend && alembic revision --autogenerate -m "short description"` — generate next revision from `db_models.py`.
- `cd src/backend && alembic current` — show applied head (replaces `python scripts/migrate.py status`).
- `cd src/backend && alembic downgrade -1` — roll back one step.
- `cd src/backend && alembic stamp <rev>` — declare a DB already at a given revision (used once on prod; see Unit 7 runbook).

**Env wiring contract:** `env.py` reads `os.environ["DATABASE_URL"]` (falling back to the same default as `src/backend/api/config.py`) and `os.environ["SCRAPER_ENVIRONMENT"]` (default `"local"`). The app and the CLI share one source of truth via `src/backend/api/config.Settings`.

**Incident-driven invariant (load-bearing, never relax):** every revision file that Alembic autogenerates must be reviewed before merge to confirm multi-column type changes on a single table are emitted as one combined `op.batch_alter_table(...)` block or a single `op.alter_column` call — never N separate `op.alter_column` calls on the same table. See `docs/incidents/2026-04-18-migration-filled-postgres-volume/volume-downgrade-playbook.md` Rule 3. This PR ships no new DDL so no enforcement is exercised here, but DEPLOY.md documents the rule for every future Alembic revision.

## Work Units

### Unit 1 — Install Alembic + scaffold SQLAlchemy models mirroring post-0005 schema

**Status:** DONE

**Prerequisites:** none

**Owned files:**
- `src/backend/api/requirements.txt` — add `alembic>=1.13.0` and `sqlalchemy>=2.0.0`.
- `src/backend/api/db_models.py` — NEW. Declarative `Base`, plus `JobListing`, `ScrapeRun`, `User`, `UserEnabledCompany` classes whose `__tablename__` is set at module-import time from `SCRAPER_ENVIRONMENT` (mirroring `scripts/shared/database._get_table_name`).
- `src/backend/api/tests/test_db_models.py` — NEW. Asserts that `Base.metadata.tables` contains `job_listings_local`, `scrape_runs_local`, `users_local`, `user_enabled_companies_local`, and that the TIMESTAMPTZ / NOT NULL / index shapes match the post-0005 contract.

**Shared-file edits:** none

**Done when:**
- `pip install -r src/backend/api/requirements.txt` succeeds and imports `alembic` and `sqlalchemy`.
- `cd src/backend && pytest api/tests/test_db_models.py` passes.
- `SCRAPER_ENVIRONMENT=local python -c "from api.db_models import Base; print(sorted(Base.metadata.tables))"` prints the four expected tables with `_local` suffix.

**Body:**

This unit is pure Python — no DB contact, no Alembic yet. The output is a declarative metadata object that Unit 2's `env.py` will point `target_metadata` at.

`db_models.py` structure:

1. Import `sqlalchemy` (`Column`, `Text`, `Integer`, `Boolean`, `TIMESTAMP`, `ForeignKey`, `Index`, `UniqueConstraint`, `PrimaryKeyConstraint`, `func`, `text`) and `declarative_base`. Import `JSONB` from `sqlalchemy.dialects.postgresql`.
2. Read `env = os.environ.get("SCRAPER_ENVIRONMENT", "local")`. Validate against the same allow-list as `scripts/shared/database._is_valid_env` (reuse by importing if import cycles permit; otherwise duplicate the regex `^test_[a-f0-9]{8}$`).
3. `Base = declarative_base()`.
4. `class JobListing(Base)`:
   - `__tablename__ = f"job_listings_{env}"`
   - Columns exactly matching the Shared Contracts schema. Use `TIMESTAMP(timezone=True)` for `posted_on` (nullable), `created_at` (NOT NULL), `closed_on` (nullable), `first_seen_at` (NOT NULL), `last_seen_at` (NOT NULL).
   - Server defaults: `status` → `text("'OPEN'")`, `has_matched` → `text("false")`, `consecutive_misses` → `text("0")`, `details_scraped` → `text("false")`, `details`/`ai_metadata` → `text("'{}'::jsonb")`.
   - `__table_args__`: `Index(f"idx_{__tablename__}_status", "status")`, `Index(f"idx_{__tablename__}_company", "company")`, `Index(f"idx_{__tablename__}_last_seen", "last_seen_at")`.
5. `class ScrapeRun(Base)` — all-TEXT timestamp columns, matching the explicit non-goal of converting scrape_runs timestamps.
6. `class User(Base)`:
   - `auth0_id` has `unique=True` (produces the exact same constraint 0001 creates).
   - Named `UniqueConstraint("email", name=f"users_{env}_email_key")` in `__table_args__` so autogen output matches the name migration 0002 produced.
   - Indexes `idx_{table}_auth0_id` and `idx_{table}_email`.
7. `class UserEnabledCompany(Base)`:
   - Composite PK via `PrimaryKeyConstraint("user_id", "company_id")`.
   - `user_id` has `ForeignKey(f"users_{env}.id", ondelete="CASCADE")`.
   - `created_at` is `TIMESTAMP(timezone=True)` with `server_default=func.now()`.
   - Index `idx_{table}_user_id`.

Unit test asserts:
- Every table name starts with the expected prefix and ends in `_local`.
- For `job_listings_local`, the five timestamptz columns are `DateTime(timezone=True)` and their nullability matches the contract.
- The `users_local_email_key` constraint is present.
- `user_enabled_companies_local` has the FK with `ondelete='CASCADE'`.

**Hard constraint:** Do not edit or run `scripts/shared/migrations/000[1-5]_*.py` in this unit. `db_models.py` is authored by reading them, not by running them. Discrepancies are resolved in Unit 3 by fixing `db_models.py`, not the migrations.

---

### Unit 2 — Initialize Alembic skeleton and commit an empty baseline revision

**Status:** DONE

**Prerequisites:** Unit 1

**Owned files:**
- `alembic.ini` — NEW at repo root. Standard layout with `script_location = src/backend/alembic`, `sqlalchemy.url =` (empty — env.py provides). Keep `[loggers]`/`[handlers]`/`[formatters]` sections at Alembic's defaults.
- `src/backend/alembic/env.py` — NEW.
- `src/backend/alembic/script.py.mako` — NEW. Default Alembic template verbatim.
- `src/backend/alembic/versions/<rev>_baseline.py` — NEW. `upgrade()` = `pass`, `downgrade()` = `pass`. Generated by running `cd src/backend && alembic revision -m "baseline"` (empty, not autogenerate).
- `src/backend/alembic/README` — NEW, one-paragraph orientation pointing to `db_models.py` and the DEPLOY.md runbook.

**Shared-file edits:** none in this unit. No changes to main.py, database.py, migrate.py, or any test.

**Done when:**
- `cd src/backend && alembic current` connects, and prints `<baseline_rev> (head)` against a DB that has been stamped with the baseline (or nothing against a fresh DB).
- `cd src/backend && alembic history` lists exactly one revision.
- `cat src/backend/alembic/versions/*_baseline.py` shows `upgrade()` and `downgrade()` bodies are literally `pass` (no autogen output, no SQL).
- Running `cd src/backend && alembic upgrade head` against a database already created by the old runner (post-0005) **creates** `alembic_version_local` but does not alter any existing table.
- Backend still boots against prod (no call-site changes yet — lifespan still uses old runner).

**Body:**

`env.py` structure (standard Alembic template with three additions):

1. At top, prepend `sys.path` with the repo root and `src/backend` so `from api.db_models import Base` and `from api.config import Settings` resolve. Alembic runs from `src/backend/` as cwd.
2. `settings = Settings()` — reuses the Pydantic env-loading the app uses. `database_url = settings.database_url`, `env_suffix = settings.scraper_environment`.
3. `config.set_main_option("sqlalchemy.url", database_url)`.
4. `target_metadata = Base.metadata`.
5. In both `run_migrations_offline()` and `run_migrations_online()`, pass `version_table=f"alembic_version_{env_suffix}"` and `compare_type=True`, `compare_server_default=True` to `context.configure(...)`.
6. For `run_migrations_online`, use `engine_from_config` with `poolclass=pool.NullPool` (matches Alembic template).

Baseline revision file: generated via `alembic revision -m "baseline"` (NOT `--autogenerate`). The file's `upgrade()` and `downgrade()` bodies are `pass`. Rename the file to `<rev>_baseline.py` and set `revision = "<short hex>"`, `down_revision = None`. The purpose of this revision is solely to give `alembic stamp` a target that matches the post-0005 prod state.

**Hard constraint:** `alembic.ini` must NOT contain `sqlalchemy.url = postgresql://...`. Leave it empty or unset. `env.py` is the only place credentials/URL are read, and it reads them from environment variables at runtime.

---

### Unit 3 — Verify autogen against a fresh DB produces an empty diff

**Status:** DONE

**Prerequisites:** Unit 2

**Owned files:**
- `scripts/tests/integration/test_alembic_parity.py` — NEW. Integration test that spins up a test-env schema via the old runner, stamps Alembic to baseline, runs `alembic revision --autogenerate`, and asserts the generated upgrade body has no `op.*` calls.

**Shared-file edits:** none

**Done when:**
- `pytest scripts/tests/integration/test_alembic_parity.py` passes.
- Running the test against a fresh Docker Postgres (`docker compose up -d postgres`) produces a temporary revision file whose `upgrade()` body, stripped of comments/whitespace, equals `pass`.
- If the test fails: the generated file's body reveals the drift between `db_models.py` and the real post-0005 schema (nullability, default, index name, type precision, constraint name). Fix by editing `db_models.py` in Unit 1, not the baseline in Unit 2.

**Body:**

This is the correctness gate that proves `db_models.py` is a faithful mirror of the schema the old runner produces. Without it, the first real autogenerate migration in production would silently include DDL intended to reconcile a model drift — exactly the class of bug Alembic is supposed to prevent.

Test outline:

1. In a unique `test_<hex>` env, open a psycopg2 connection and call the old runner's `migrate_up(conn, env)` to create the post-0005 schema.
2. Invoke Alembic programmatically with `SCRAPER_ENVIRONMENT=<test_env>` and `DATABASE_URL=<test_db_url>`: `from alembic.config import Config; from alembic import command; cfg = Config("alembic.ini"); command.stamp(cfg, "head")`. This inserts the baseline revision into `alembic_version_<test_env>`.
3. Invoke `command.revision(cfg, autogenerate=True, message="parity_check")`.
4. Read the newly-created revision file under `src/backend/alembic/versions/*parity_check*.py`. Parse with `ast` — extract the `upgrade` function body. Assert every top-level statement is either `pass`, a `#` comment, or a docstring. Any `op.*` call fails the test with the full file contents in the assertion message.
5. Cleanup: delete the generated revision file; drop the test env's tables and `alembic_version_<test_env>`.

Non-goal: this unit does not edit `db_models.py` or the baseline. It is a fail-loud canary for Unit 1's faithfulness. If it fails, the fix is in Unit 1's `db_models.py` definition, re-run Unit 3 until empty.

**Hard constraint:** The test must run against a local Docker Postgres, never prod. The test's `DATABASE_URL` comes from `TEST_DATABASE_URL` env var (same pattern as `scripts/tests/conftest.py`), defaulting to `postgresql://postgres:postgres@localhost:5432/jobscraper`.

---

### Unit 4 — Swap the FastAPI lifespan hook to Alembic

**Status:** DONE

**Prerequisites:** Unit 3

**Owned files:**
- `src/backend/api/migrations.py` — NEW. `def apply_alembic_migrations(database_url: str, env: str) -> None` that calls `alembic.config.Config` + `command.upgrade(cfg, "head")` in-process. Preserves `logger.exception("Failed to apply migrations during startup (env=%s)", env)` semantics on failure.
- `src/backend/api/main.py` — replace the `init_schema(temp_conn, settings.scraper_environment)` call (lines 33–40) with `apply_alembic_migrations(settings.database_url, settings.scraper_environment)`. Remove the `from scripts.shared.database import init_schema, get_connection` import; keep `get_connection` import only if still needed elsewhere (it is not after this change — the temp_conn pattern goes away). Remove the temp_conn acquire/close block entirely since Alembic manages its own engine.
- `src/backend/api/tests/conftest.py` — replace `from scripts.shared.database import init_schema, _get_table_name` + `init_schema(conn, test_env)` with `from api.migrations import apply_alembic_migrations` + `apply_alembic_migrations(TEST_DB_URL, test_env)`. Update the drop-tables cleanup block: replace `schema_migrations_{test_env}` with `alembic_version_{test_env}`.

**Shared-file edits:**
- `scripts/shared/database.py` — delete the `init_schema` function body (lines 137–157). If no backend call site remains (Unit 5 removes the scraper call site), delete the function entirely. If `scripts/run_scraper.py` still depends on it at the start of Unit 4, leave `init_schema` defined as a no-op that raises `RuntimeError("init_schema removed; use alembic upgrade head")` — Unit 5 removes the last caller.

**Done when:**
- `cd src/backend && pytest api/tests` passes.
- Lifespan startup log line changes from `Applied N migration(s) for env=prod: [...]` to Alembic's log lines (`Running upgrade ... -> ...` or `Context impl PostgresqlImpl.` + `Will assume transactional DDL.`). Note the new log shape in `DEPLOY.md` (Unit 7).
- `grep -rn "init_schema" src/backend/` returns nothing.
- The lifespan startup time against an already-stamped prod DB is ≤ 1s (Alembic's `upgrade head` is a no-op when `alembic_version_prod` already matches head).

**Body:**

`apply_alembic_migrations` implementation sketch:

```python
from alembic import command
from alembic.config import Config
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def apply_alembic_migrations(database_url: str, env: str) -> None:
    repo_root = Path(__file__).resolve().parents[3]  # src/backend/api -> repo root
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    # env.py also reads SCRAPER_ENVIRONMENT; setting it on cfg via
    # cfg.set_main_option is an option, but we rely on the process env var
    # that main.py has already set via Settings().
    try:
        command.upgrade(cfg, "head")
    except Exception:
        logger.exception("Failed to apply Alembic migrations (env=%s)", env)
        raise
```

Note: `env.py` already reads `SCRAPER_ENVIRONMENT` from `os.environ`, so setting it as a main option is unnecessary — the process env matches what `Settings()` resolved in `main.py`.

The lifespan block in `main.py` simplifies to:

```python
logger.info("Applying database migrations...")
try:
    apply_alembic_migrations(settings.database_url, settings.scraper_environment)
except Exception:
    logger.exception(
        "Failed to apply migrations during startup (env=%s)",
        settings.scraper_environment,
    )
    raise
```

The previous `temp_conn = get_connection(...)` block is deleted — Alembic manages its own engine and pool via `env.py`.

**Hard constraint:** Do not delete the old runner in this unit. Unit 6 owns that. This unit only redirects callers; the runner still exists on disk so migrate.py (Unit 5) and run_scraper.py (Unit 5) can still be edited without breaking imports mid-branch.

---

### Unit 5 — Delete `scripts/migrate.py`, update `scripts/run_scraper.py`, and make Alembic deploy-safe

**Status:** IN PROGRESS

**Prerequisites:** Unit 4

**Owned files:**
- `scripts/migrate.py` — DELETE. The `alembic` binary covers `status` (→ `alembic current`), `up` (→ `alembic upgrade head`), and `down` (→ `alembic downgrade <target>`).
- `scripts/tests/unit/test_migrate_cli.py` — DELETE. Tests a deleted CLI.

**Shared-file edits:**
- `scripts/run_scraper.py` — replace `db.init_schema(conn, env)` with a call to `apply_alembic_migrations` imported from `src.backend.api.migrations`. Because `run_scraper.py` runs with `PYTHONPATH=<repo root>`, the import `from src.backend.api.migrations import apply_alembic_migrations` resolves. In the Docker image, the layout is `/app/api/` + `/app/scripts/`, so inside the container the import becomes `from api.migrations import apply_alembic_migrations`. Implementation agent verifies both paths resolve before committing.
- `scripts/tests/conftest.py` — change `db.init_schema(conn, env=test_env)` to call `apply_alembic_migrations(TEST_DB_URL, test_env)`. Drop-table cleanup changes `schema_migrations_{test_env}` to `alembic_version_{test_env}`.
- `scripts/tests/integration/test_database.py` — any reference to `init_schema` is redirected to `apply_alembic_migrations`. Grep during implementation to confirm.

**Done when:**
- `ls scripts/migrate.py` returns not-found.
- `pytest scripts/tests/unit` passes (minus the deleted CLI test).
- `pytest scripts/tests/integration/test_database.py` passes.
- `python scripts/run_scraper.py --env local --db-url postgresql://...` boots, runs migrations via Alembic, and proceeds to scrape.
- `grep -rn "scripts/migrate.py\|shared.migrations.runner\|migrate_up\|migrate_down\|discover_migrations\|get_applied_versions" .` returns only matches inside `scripts/shared/migrations/` (to be deleted in Unit 6) and inside docs being rewritten in Unit 7.

**Body:**

The old CLI's three subcommands map 1:1 to Alembic commands, so the CLI has no unique value — keeping it would require rewriting it as a wrapper around `subprocess.run(["alembic", ...])`, which adds complexity and fragility for no benefit. Delete it and document the replacements in `DEPLOY.md` (Unit 7):

| Old | New |
|-----|-----|
| `python scripts/migrate.py status --env prod --db-url ...` | `DATABASE_URL=... SCRAPER_ENVIRONMENT=prod alembic current` |
| `python scripts/migrate.py up --env prod --db-url ...` | `DATABASE_URL=... SCRAPER_ENVIRONMENT=prod alembic upgrade head` |
| `python scripts/migrate.py down --to N --env prod --db-url ...` | `DATABASE_URL=... SCRAPER_ENVIRONMENT=prod alembic downgrade <rev>` |

**Hard constraint:** `scripts/shared/migrations/` still exists at end of Unit 5. Unit 6 deletes it. Any test not yet rewired against Alembic must be updated in Unit 5 (tests own callers, not the runner itself).

---

### Unit 6 — Delete the old runner and its migrations

**Status:** TODO

**Prerequisites:** Unit 5

**Owned files:**
- `scripts/shared/migrations/` — DELETE the entire directory. Includes `runner.py`, `0001_initial_schema.py`, `0002_add_users_email_unique.py`, `0003_posted_on_timestamptz.py`, `0004_job_timestamps_timestamptz.py`, `0005_add_user_enabled_companies.py`, `__init__.py`.
- `scripts/tests/unit/test_migration_runner.py` — DELETE.
- `scripts/tests/integration/test_migrations.py` — DELETE.
- `scripts/tests/integration/test_alembic_parity.py` (Unit 3) — EDIT to drop its dependency on the old runner. After Unit 6 the parity test must bootstrap the schema a different way: change the parity test to use `Base.metadata.create_all(engine)` as the schema source + `alembic stamp head` + `alembic revision --autogenerate`, then assert empty diff. This is a stronger invariant anyway — "autogenerate is stable against its own source" — and doesn't need the old runner.

**Shared-file edits:** none (Unit 5 already rewired the tests and call sites).

**Done when:**
- `ls scripts/shared/migrations/` returns not-found.
- `grep -rn "scripts.shared.migrations\|migrations.runner\|0001_initial_schema\|0002_add_users_email_unique\|0003_posted_on_timestamptz\|0004_job_timestamps_timestamptz\|0005_add_user_enabled_companies" .` returns no matches outside of `docs/incidents/`, `docs/implementations/migrationProdReady/`, and `docs/implementations/alembicMigration/` (historical docs are preserved).
- `pytest scripts/tests/` passes.
- `cd src/backend && pytest api/tests` passes.
- `pytest scripts/tests/integration/test_alembic_parity.py` passes under the new `create_all` formulation.

**Body:**

This is the blast-radius unit — nothing upstream should still depend on the runner, or the build breaks. The prerequisite gate is that Units 4–5 leave no importer standing. Confirm with a full-repo grep before starting Unit 6.

Why delete (not archive): the user explicitly requested deletion. The incident postmortem and the prior PLAN.md remain in `docs/` as the historical record; the code itself is dead.

**Hard constraint:** Prod already has versions 1–5 applied and `schema_migrations_prod` row history — **do not drop `schema_migrations_prod` in this unit**. The tracking table remains on prod as historical evidence (it's a single 5-row table) until a separate cleanup PR. Unit 7's DEPLOY.md documents this explicitly; the runbook's `alembic stamp` step does not touch `schema_migrations_prod`.

---

### Unit 7 — Docs and prod-stamp runbook

**Status:** TODO

**Prerequisites:** Unit 6

**Owned files:**
- `docs/implementations/alembicMigration/DEPLOY.md` — NEW.
- `CLAUDE.md` — update the "Key Files" or "Commands" section to reference `alembic upgrade head` instead of migration runner references.
- `src/backend/CLAUDE.md` — replace any migration-runner language with Alembic. Add a "Schema migrations" subsection pointing at `src/backend/alembic/` and `db_models.py`.
- `scripts/CLAUDE.md` — remove the migration-runner references from the script docs (this file mostly describes scrapers, minor edits expected).
- `scripts/ARCHITECTURE.md` — remove sections describing the custom runner; replace with a one-paragraph "Schema is managed by Alembic; see src/backend/alembic/" pointer.

**Shared-file edits:** none

**Done when:**
- `DEPLOY.md` exists and contains:
  - **Prod stamp sequence** (one-time, before the first post-Alembic deploy):
    1. Verify `schema_migrations_prod` has versions 1–5 applied: `mcp__postgres-prod__query "SELECT version FROM schema_migrations_prod ORDER BY version"`.
    2. From the operator's workstation with `DATABASE_URL=<prod URL>` and `SCRAPER_ENVIRONMENT=prod` exported: `cd src/backend && alembic stamp <baseline_rev>`.
    3. Confirm `alembic_version_prod` exists and contains exactly one row with the baseline revision: `mcp__postgres-prod__query "SELECT version_num FROM alembic_version_prod"`.
    4. Only after step 3 succeeds, merge the PR — the first deploy's lifespan hook will see `alembic upgrade head` as a no-op.
  - **Deploy sequence:** Railway auto-runs the lifespan hook on each deploy. Expected log lines: `"Applying database migrations..."` → `"Context impl PostgresqlImpl."` → `"Will assume transactional DDL."` → (no revisions to apply since baseline is head).
  - **Rollback:** pin the backend Docker image to the pre-Alembic tag; `alembic downgrade base` is a no-op against the baseline (no DDL), so no data action needed. If a future non-empty revision is rolled back, use `alembic downgrade -1`.
  - **Adding a schema change:** (1) edit `src/backend/api/db_models.py`; (2) `cd src/backend && DATABASE_URL=<local> SCRAPER_ENVIRONMENT=local alembic revision --autogenerate -m "short message"`; (3) open the generated file under `src/backend/alembic/versions/` and **verify all ALTER COLUMN calls on the same table are combined into one `op.batch_alter_table(...)` block or one `op.alter_column` followed by zero others on the same table** — this is the incident-driven rule; split-statement autogens must be manually collapsed; (4) take a Railway manual backup and estimate disk cost per Rule 2 of `docs/incidents/2026-04-18-migration-filled-postgres-volume/volume-downgrade-playbook.md`; (5) test locally with `alembic upgrade head`; (6) commit and PR.
  - **Failure modes:** `alembic upgrade head` times out → check Railway logs for the specific revision; fail-forward by fixing the revision and redeploying. Alembic does not have a lock-timeout equivalent of the old runner's `pg_advisory_lock` / `SET LOCAL lock_timeout` — multi-instance deploy safety relies on Railway deploying one pod at a time during rollout, plus Alembic's own version-table row-level lock. Call this out as a known limitation.
  - **schema_migrations_prod note:** the legacy tracking table is preserved as historical evidence and is no longer written to; ignore it.
- Root `CLAUDE.md`, `src/backend/CLAUDE.md`, `scripts/CLAUDE.md`, and `scripts/ARCHITECTURE.md` have no references to `scripts.shared.migrations`, `migrate_up`, `migrate_down`, or `python scripts/migrate.py`.

**Body:**

The stamp step is the one destructive-looking action in the rollout. Document it precisely. Include the exact `DATABASE_URL`/`SCRAPER_ENVIRONMENT` export lines; do not commit values. Cross-link to the incident postmortem so future reviewers see why this migration matters.

**Hard constraint:** Do not run `alembic stamp` against prod as part of this PR's implementation. The stamp is a human operator action that happens between PR merge and first deploy. Implementation agents only write the runbook.

## Critical files

| File | Role | Units touching |
|------|------|----------------|
| `src/backend/api/requirements.txt` | Add alembic + sqlalchemy | Unit 1 |
| `src/backend/api/db_models.py` | SQLAlchemy declarative models, source of truth for autogenerate | Unit 1, (fixed in Unit 3) |
| `alembic.ini` | Alembic config pointing at `src/backend/alembic/` | Unit 2 |
| `src/backend/alembic/env.py` | Reads DATABASE_URL + SCRAPER_ENVIRONMENT, sets version_table | Unit 2 |
| `src/backend/alembic/versions/<rev>_baseline.py` | Empty baseline revision | Unit 2 |
| `src/backend/api/migrations.py` | `apply_alembic_migrations` helper for lifespan | Unit 4, imported by Unit 5 |
| `src/backend/api/main.py` | Lifespan hook — swap init_schema to apply_alembic_migrations | Unit 4 |
| `src/backend/api/tests/conftest.py` | Test fixture init — swap to apply_alembic_migrations | Unit 4 |
| `scripts/tests/conftest.py` | Scraper test fixture init — swap to apply_alembic_migrations | Unit 5 |
| `scripts/run_scraper.py` | Scraper entry — swap init_schema to apply_alembic_migrations | Unit 5 |
| `scripts/migrate.py` | Deleted | Unit 5 |
| `scripts/tests/unit/test_migrate_cli.py` | Deleted | Unit 5 |
| `scripts/shared/migrations/` | Deleted directory (runner + 5 migrations + __init__) | Unit 6 |
| `scripts/tests/unit/test_migration_runner.py` | Deleted | Unit 6 |
| `scripts/tests/integration/test_migrations.py` | Deleted | Unit 6 |
| `scripts/tests/integration/test_alembic_parity.py` | Parity canary — created Unit 3, rewired Unit 6 | Unit 3, Unit 6 |
| `scripts/shared/database.py` | Remove init_schema (lines 137–157) | Unit 4 |
| `docs/implementations/alembicMigration/DEPLOY.md` | Prod stamp + deploy runbook | Unit 7 |
| `CLAUDE.md`, `src/backend/CLAUDE.md`, `scripts/CLAUDE.md`, `scripts/ARCHITECTURE.md` | Doc refresh | Unit 7 |

## Non-goals

- **Any new schema change.** This PR ships no DDL other than Alembic's internal `alembic_version_{env}` tracking table. No column additions, no type changes, no renames, no index changes. The baseline is empty by construction.
- **Running Alembic against the prod DB during implementation.** Validation is local (Docker Postgres) only. The one prod-touching command — `alembic stamp <baseline_rev>` — is a post-merge operator action documented in Unit 7's DEPLOY.md, not executed by implementation agents.
- **Reworking the env-suffix table naming scheme.** `job_listings_{env}` stays. `db_models.py` resolves `env` at import time from `SCRAPER_ENVIRONMENT`. Each running process has one env. There is no cross-env Alembic.
- **Dropping `schema_migrations_prod` on prod.** It remains as historical evidence. A separate cleanup PR can drop it after the Alembic-era has stabilized.
- **CI checks for rewrite-heavy DDL.** The "one combined ALTER TABLE per table per revision" rule from the incident playbook is enforced by reviewer discipline in this PR and documented in DEPLOY.md. Automating the check (parse revision file, count `op.alter_column` per table) is a separate follow-up PR.
- **Converting `scrape_runs_{env}` and `users_{env}` TEXT timestamps to TIMESTAMPTZ.** These remain TEXT (carried over from the existing non-goal in `docs/implementations/migrationProdReady/PLAN.md`). If a future PR converts them, it goes through Alembic.
- **Removing `psycopg2-binary` in favor of SQLAlchemy for application queries.** The app's data-access code in `scripts/shared/database.py` continues to use raw psycopg2. SQLAlchemy is pulled in solely to express the schema for autogenerate's `target_metadata`.
- **Replacing the old runner's `pg_advisory_lock` + `SET LOCAL lock_timeout` behavior in Alembic.** Alembic relies on the version-table row lock + Railway single-pod rollout. If a future multi-instance hot deploy becomes a requirement, that's a separate hardening PR.
