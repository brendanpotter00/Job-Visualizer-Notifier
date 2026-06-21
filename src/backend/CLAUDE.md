# Backend API (FastAPI)

Python FastAPI web API that serves job data from PostgreSQL and runs automated scrapers.

## Commands

```bash
# From project root
docker compose up -d postgres                    # Start PostgreSQL
source .venv/bin/activate
PYTHONPATH=. uvicorn src.backend.api.main:app --host 0.0.0.0 --port 8000 --reload  # Start API (dev)

# Dependencies
pip install -r src/backend/api/requirements.txt  # Install API dependencies

# Testing (from src/backend/)
cd src/backend && pytest                                 # Run all backend tests
cd src/backend && pytest -v                              # Verbose output
cd src/backend && pytest api/tests/test_jobs_router.py   # Single file

# Type checking (from src/backend/) — run before committing; CI gates on it
cd src/backend && mypy                                   # Static type check (config in pyproject.toml)
```

## Type checking

Static type checking is enforced by **mypy** (config in `src/backend/pyproject.toml`)
and runs in CI ahead of `pytest` — a type error fails the build, so `mypy` must be
clean before committing (mirrors the frontend's "Zero TypeScript Errors Required").

- **Baseline** (over `api/`): `disallow_untyped_defs` + `disallow_incomplete_defs` +
  `check_untyped_defs` + `warn_return_any` + `warn_redundant_casts` +
  `warn_unused_ignores` + `no_implicit_optional`. Every function in the production code
  has typed params and a return type; DB rows that cross into routers are carried as `TypedDict`
  (e.g. `UserRow`) via `typing.cast(...)` so a `db_models` column rename surfaces as a
  mypy error at the read site, not a runtime `KeyError`.
- **psycopg2 is intentionally untyped** (`ignore_missing_imports`): the code uses
  `RealDictCursor` (dict rows) and the published tuple-row stubs would fight that. The
  `conn: Connection` annotations are convention; data-shape safety lives in the
  Pydantic models / `TypedDict`s, not the driver.
- **Ratchet (not yet checked, tighten later)**: `api/tests/` and `api/eval/` are
  excluded (see the `exclude` in `[tool.mypy]`). Enable them module-by-module in a
  follow-up. New production code under `api/` is checked from day one.

## Prerequisites

- PostgreSQL running on localhost:5432 (use `docker compose up -d postgres` from project root)
- Database: `jobscraper` with bare-named tables `job_listings`, `scrape_runs`, `users`, `user_enabled_companies`, `admins`, `features`, `feature_upvotes` (created on first lifespan/migration run)
- Python 3.13+ with dependencies from `src/backend/api/requirements.txt`

## Configuration

All configuration via environment variables:

| Env Var | Description | Default |
|---------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection URL | `postgresql://postgres:postgres@localhost:5432/jobscraper` |
| `SCRAPER_INTERVAL_HOURS` | Hours between auto-scrape cycles | `1` |
| `SCRAPER_COMPANIES` | Comma-separated company list | `apple,google,microsoft` |
| `SCRAPER_DETAIL_SCRAPE` | Fetch job detail pages | `true` |
| `SCRAPER_TIMEOUT_MINUTES` | Max time per scrape | `90` |
| `SCRAPER_SCRIPTS_PATH` | Path to Python scripts | `../../scripts` (local) / `/app/scripts` (Docker) |
| `SCRAPER_PYTHON_PATH` | Python interpreter path | `python3` |
| `DB_POOL_MIN` | Minimum database connections in pool | `1` |
| `DB_POOL_MAX` | Maximum database connections in pool | `15` |
| `PORT` | Server port | `8080` |
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:3000,http://localhost:5173,http://localhost:8000` |
| `AUTH0_DOMAIN` | Auth0 tenant domain (e.g., `myapp.us.auth0.com`) | *(required for auth)* |
| `AUTH0_AUDIENCE` | Auth0 API audience identifier | *(required for auth)* |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID for One Tap validation | *(optional)* |

**Table names are env-agnostic.** All environments share bare names (`job_listings`, `scrape_runs`, `users`, `user_enabled_companies`). Test isolation uses per-worker Postgres **schemas** via `PYTEST_SCHEMA=test_<hex>` + `SET search_path`; inside the schema the table names are the same as prod. See `docs/implementations/envAgnosticTables/PLAN.md`.

## API Endpoints

**Jobs Router (`/api/jobs`):**
- `GET /api/jobs` - List jobs (params: company, status, limit, offset)
- `GET /api/jobs/{id}` - Get single job by ID

**QA Router (`/api/jobs-qa`):**
- `GET /api/jobs-qa/stats` - Job statistics (params: company; returns total, open, closed, by company)
- `GET /api/jobs-qa/scrape-runs` - Scrape run history (params: company, limit)
- `POST /api/jobs-qa/trigger-scrape` - Manually trigger scraper (params: company; default: google)

**Users Router (`/api/users`):**
- `GET /api/users` - Get or create authenticated user's profile (requires Bearer token)
- `PUT /api/users` - Update display name (requires Bearer token)
- `GET /api/users/enabled-companies` - List user's enabled companies (requires Bearer token)
- `PUT /api/users/enabled-companies` - Update user's enabled companies (requires Bearer token)

**Admin Router (`/api/admin`):**
- `GET /api/admin/users` - List all users with admin flag (requires admin)
- `GET /api/admin/users/stats` - User statistics (requires admin)
- `POST /api/admin/users/{user_id}/admin` - Grant admin to user (requires admin)
- `DELETE /api/admin/users/{user_id}/admin` - Revoke admin from user (requires admin)

**Features Router (`/api/features`):**
- `GET /api/features` - List all features with upvote counts and current user's vote state (optional auth)
- `POST /api/features/{feature_id}/upvote` - Add upvote for a feature (requires Bearer token)
- `DELETE /api/features/{feature_id}/upvote` - Remove upvote for a feature (requires Bearer token)

**Health:**
- `GET /health` - Health check (returns "OK" 200, or "UNAVAILABLE" 503 if pool is down)
- `GET /health/worker` - Procrastinate worker liveness probe; checks `procrastinate_events` and `worker_heartbeats` freshness windows; returns 200 OK or 503; used as Railway's `healthcheckPath`

## Key Files

```
src/backend/api/
├── main.py              # FastAPI app, lifespan, health check
├── config.py            # Pydantic BaseSettings (env vars)
├── dependencies.py      # Connection pool + get_db FastAPI dependency
├── models.py            # Response models with camelCase aliases
├── requirements.txt     # Python dependencies
├── auth/
│   ├── dependencies.py  # FastAPI auth dependencies (get_current_user, get_optional_user)
│   ├── jwt.py           # JWT validation dispatcher (Auth0 + Google issuer routing)
│   └── google_jwt.py    # Google One Tap token validation via Google JWKS
├── routers/
│   ├── jobs.py          # Jobs list and detail endpoints
│   ├── jobs_qa.py       # Stats, scrape runs, trigger scrape
│   ├── users.py         # User profile + enabled-companies endpoints (auth required)
│   ├── features.py      # Feature voting endpoints (list, upvote, remove upvote)
│   └── admin.py         # Admin-only user management endpoints
├── services/
│   ├── database.py      # API query functions (reuses scripts/shared/database.py)
│   ├── user_service.py  # User CRUD operations (get_or_create, update)
│   ├── user_preferences_service.py  # Enabled-companies CRUD
│   ├── admin_service.py # Admin grant/revoke and is_admin check
│   ├── features_service.py  # Feature list and upvote logic
│   ├── features_seed.py # Seed initial feature rows
│   ├── scraper_lock.py  # asyncio.Lock singleton shared by runner + auto-scraper
│   ├── scraper_runner.py # Async subprocess runner for scrapers
│   ├── auto_scraper.py  # Background scheduled scraping (Google/Apple/Microsoft)
│   ├── ashby_client.py      # Ashby ATS HTTP client
│   ├── eightfold_client.py  # Eightfold ATS HTTP client (SSRF allowlist lives here)
│   ├── gem_client.py        # Gem ATS HTTP client
│   ├── greenhouse_client.py # Greenhouse ATS HTTP client
│   ├── lever_client.py      # Lever ATS HTTP client
│   └── workday_client.py    # Workday ATS HTTP client
└── tasks/
    ├── procrastinate_app.py         # Procrastinate App instance + schema setup
    ├── heartbeat.py                 # Heartbeat task (liveness probe for /health/worker)
    ├── enqueue_*_fan_out.py (×6)    # Fan-out tasks: enqueue per-company fetch for each ATS
    └── fetch_*_company.py (×6)      # Leaf tasks: fetch + upsert one company's jobs
```

## Evals

`api/eval/` holds an **on-demand, human-run, never-CI** golden-set eval that scores
the **real** Claude Haiku output of Tier-2 location normalization against a curated
+ prod-sampled set — it catches *quality* regressions that the (LLM-mocking) unit
tests cannot. It needs `ANTHROPIC_API_KEY` and spends real money (~a few cents/run).

```bash
# from repo root (so .env.local is auto-loaded)
PYTHONPATH=. python -m src.backend.api.eval.eval_locations --set all
```

Run it before merging any change to the location-normalization logic (prompt,
model, schema, `CanonicalLocation`/`LocationSpec`, the `anthropic` SDK pin) and
before a `re-normalize-all` backfill. The **pure scorer** (`api/eval/scoring.py`)
is unit-tested in the normal suite (`api/tests/test_eval_scoring.py`). Full how/when:
**`api/eval/README.md`**.

A read-only, on-demand **prod monitor** (`api/eval/monitor_prod.py`) verifies the
*live* normalization pipeline (deployment, backlog drain, integrity invariants,
queue health) — run it with a read-only `MONITOR_DATABASE_URL` (no Anthropic key
needed); full runbook in **`src/backend/docs/location-normalization-monitoring.md`**.

## Architecture

- **Database**: Connection pool managed by `dependencies.py`; table naming reused from `scripts/shared/database.py`
- **Response serialization**: Pydantic models with `alias_generator=to_camel` produce camelCase JSON matching frontend expectations
- **Background workers**: Two workers run in the FastAPI lifespan context:
  1. **Procrastinate worker** (`tasks/procrastinate_app.py`) — drains the Procrastinate job queue; handles Greenhouse, Ashby, Lever, Gem, Eightfold, and Workday ATS companies via fan-out + per-company fetch tasks. Supervised with auto-restart on crash.
  2. **Auto-scraper loop** (`services/auto_scraper.py`) — asyncio task that periodically spawns subprocesses for Google, Apple, and Microsoft scrapers.
- **Scraper subprocess**: Runs `scripts/run_scraper.py` via `asyncio.create_subprocess_exec`

### Schema migrations

Schema is managed by **Alembic** (not the old `scripts/shared/migrations/` runner, which was removed in the Alembic migration PR). Source of truth is `src/backend/api/db_models.py` (SQLAlchemy declarative models). Revision files live in `src/backend/alembic/versions/`, one per schema change, anchored by the empty baseline revision `91337142414f`.

For a human-readable overview of every table — an ER diagram plus per-column notes and conventions — see **`src/backend/docs/database-schema.md`** (point-in-time snapshot of `db_models.py`; refresh it when the schema changes).

- FastAPI's lifespan hook runs `apply_alembic_migrations(settings.database_url)` from `src/backend/api/migrations.py` on every startup. Dev and prod use the same code path. `SCRAPER_ENVIRONMENT` is not read anywhere.
- Tables are bare across all envs (`job_listings`, `scrape_runs`, `users`, `user_enabled_companies`). The Alembic tracker is the default `alembic_version`; `src/backend/alembic/env.py` does NOT pass `version_table=`.
- To add a schema change: edit `db_models.py`, then `alembic revision --autogenerate`, then review the generated file per the combined-ALTER-TABLE rule in `docs/implementations/alembicMigration/DEPLOY.md`. Never hand-write a revision file — always autogenerate.
- Tests bootstrap the schema via `Base.metadata.create_all` + `apply_alembic_migrations(db_url)` inside a per-worker Postgres schema (`PYTEST_SCHEMA=test_<hex>` + `SET search_path`). See `src/backend/api/tests/conftest.py::db_conn` and `scripts/tests/conftest.py::postgres_db`. Teardown is `DROP SCHEMA … CASCADE`; no per-table cleanup.

See `docs/implementations/envAgnosticTables/DEPLOY.md` for the env-suffix removal runbook (rename migration, Railway env-var cleanup, rollback with `-x env=prod`). The prior `docs/implementations/alembicMigration/DEPLOY.md` is historical — its `alembic_version_<env>` and `SCRAPER_ENVIRONMENT` references no longer match the live code. See `docs/incidents/2026-04-18-migration-filled-postgres-volume/` for why combined ALTER TABLE is load-bearing.

## Deployment

Production backend is deployed on **Railway** (auto-deploys from GitHub). Railway uses the Dockerfile at `src/backend/Dockerfile`.

Key production env vars to set in Railway:
- `DATABASE_URL` — PostgreSQL connection string (provided by Railway if using their Postgres plugin)
- `CORS_ORIGINS` — must include the production frontend domain

## Docker

```bash
# Build (from project root)
docker build -f src/backend/Dockerfile -t jobs-api .

# Run
docker run -p 8080:8080 -e DATABASE_URL=postgresql://... jobs-api
```

Single-stage Python 3.13-slim image with Playwright browser dependencies.
