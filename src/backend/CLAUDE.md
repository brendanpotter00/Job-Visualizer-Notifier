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
```

## Prerequisites

- PostgreSQL running on localhost:5432 (use `docker compose up -d postgres` from project root)
- Database: `jobscraper` with tables `job_listings_local` and `scrape_runs_local`
- Python 3.13+ with dependencies from `src/backend/api/requirements.txt`

## Configuration

All configuration via environment variables:

| Env Var | Description | Default |
|---------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection URL | `postgresql://postgres:postgres@localhost:5432/jobscraper` |
| `SCRAPER_ENVIRONMENT` | Table name suffix (local/qa/prod) | `local` |
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

**Environment-based table naming:**
- `SCRAPER_ENVIRONMENT=local` → `job_listings_local`, `scrape_runs_local`
- `SCRAPER_ENVIRONMENT=prod` → `job_listings_prod`, `scrape_runs_prod`

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

**Health:**
- `GET /health` - Health check (returns "OK" 200, or "UNAVAILABLE" 503 if pool is down)

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
│   └── users.py         # User profile endpoints (auth required)
└── services/
    ├── database.py      # API query functions (reuses scripts/shared/database.py)
    ├── user_service.py  # User CRUD operations (get_or_create, update)
    ├── scraper_runner.py # Async subprocess runner for scrapers
    └── auto_scraper.py  # Background scheduled scraping
```

## Architecture

- **Database**: Connection pool managed by `dependencies.py`; table naming reused from `scripts/shared/database.py`
- **Response serialization**: Pydantic models with `alias_generator=to_camel` produce camelCase JSON matching frontend expectations
- **Background scraper**: asyncio task launched in FastAPI lifespan context
- **Scraper subprocess**: Runs `scripts/run_scraper.py` via `asyncio.create_subprocess_exec`

### Schema migrations

Schema is managed by **Alembic** (not the old `scripts/shared/migrations/` runner, which was removed in the Alembic migration PR). Source of truth is `src/backend/api/db_models.py` (SQLAlchemy declarative models). Revision files live in `src/backend/alembic/versions/`, one per schema change, anchored by the empty baseline revision `91337142414f`.

- FastAPI's lifespan hook runs `apply_alembic_migrations(...)` from `src/backend/api/migrations.py` on every startup. Dev and prod use the same code path.
- `SCRAPER_ENVIRONMENT` is still read by scraper/app config but no longer drives table names — tables are bare across all envs (see `docs/implementations/envAgnosticTables/PLAN.md`). The Alembic tracker is the default `alembic_version`; `src/backend/alembic/env.py` no longer sets `version_table=`.
- To add a schema change: edit `db_models.py`, then `alembic revision --autogenerate`, then review the generated file per the combined-ALTER-TABLE rule in `docs/implementations/alembicMigration/DEPLOY.md`. Never hand-write a revision file — always autogenerate.
- Tests bootstrap the schema via `Base.metadata.create_all` + `apply_alembic_migrations` (to populate `alembic_version_<env>`); see `src/backend/api/tests/conftest.py::db_conn` and `scripts/tests/conftest.py::postgres_db`.

See `docs/implementations/alembicMigration/DEPLOY.md` for the full deploy/rollback/schema-change runbook and `docs/incidents/2026-04-18-migration-filled-postgres-volume/` for why combined ALTER TABLE is load-bearing.

## Deployment

Production backend is deployed on **Railway** (auto-deploys from GitHub). Railway uses the Dockerfile at `src/backend/Dockerfile`.

Key production env vars to set in Railway:
- `DATABASE_URL` — PostgreSQL connection string (provided by Railway if using their Postgres plugin)
- `SCRAPER_ENVIRONMENT=prod`
- `CORS_ORIGINS` — must include the production frontend domain

## Docker

```bash
# Build (from project root)
docker build -f src/backend/Dockerfile -t jobs-api .

# Run
docker run -p 8080:8080 -e DATABASE_URL=postgresql://... jobs-api
```

Single-stage Python 3.13-slim image with Playwright browser dependencies.
