# Local Development Setup

Monorepo with a React frontend, FastAPI backend, Python scrapers, and Vercel serverless API proxies backed by PostgreSQL. The full stack runs across 3-4 terminal windows.

---

## Quick Start (Daily Commands)

Once everything is installed, these are the only commands you need. For a one-page daily cheat sheet (start/stop + common gotchas), see **[RUNNING-DEV.md](./RUNNING-DEV.md)**.

**Terminal 1 -- Database:**

```bash
docker compose up -d postgres
```

**Terminal 2 -- FastAPI Backend:**

```bash
source .venv/bin/activate
PYTHONPATH=. uvicorn src.backend.api.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 3 -- Frontend + API Proxies:**

```bash
npm run dev:vercel -w src/frontend
```

> **Important:** Use `npm run dev:vercel -w src/frontend`, not `npm run dev`. The `-w src/frontend` flag is required: `dev:vercel` is defined in `src/frontend/package.json`, **not** the root `package.json` (running it from root fails with `Missing script: "dev:vercel"`). The plain `dev` command starts Vite only -- the serverless functions in `api/` that proxy ATS APIs and backend requests won't be available.

**Terminal 4 (optional) -- Run a Scraper:**

```bash
source .venv/bin/activate
python scripts/run_scraper.py --company google --max-jobs 10
```

**URLs after startup:**

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| FastAPI Swagger | http://localhost:8000/docs |
| Health Check | http://localhost:8000/health |

---

## Prerequisites

| Tool | Minimum Version | Install |
|------|----------------|---------|
| Node.js | 18+ | https://nodejs.org or `nvm install 18` |
| npm | 9+ | Bundled with Node.js |
| Python | 3.13+ | https://python.org or `pyenv install 3.13` |
| Docker | Any recent | https://docker.com/get-started |
| Vercel CLI | Latest | `npm i -g vercel` |

---

## One-Time Setup

All commands run from the project root.

### 1. Clone and Enter the Repo

```bash
git clone https://github.com/brendanpotter00/Job-Visualizer-Notifier.git
cd Job-Visualizer-Notifier
```

### 2. Install Node Dependencies

```bash
npm install
```

This uses npm workspaces to install both root and `src/frontend` dependencies.

### 3. Create a Python Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install Python Dependencies

```bash
pip install -r src/backend/api/requirements.txt
pip install -r scripts/requirements.txt
pip install -r scripts/requirements-dev.txt
```

The backend and scrapers share `psycopg2-binary` and `pydantic` but have separate requirements files.

### 5. Install Playwright Browser

```bash
playwright install chromium
```

Required for the Google, Apple, and Microsoft scrapers. The browser binary is separate from the Python package.

### 6. Link to Vercel

```bash
npm i -g vercel    # if not already installed
vercel link
```

Follow the prompts to link to the existing Vercel project. This creates a `.vercel/` directory and pulls environment variables.

### 7. Create `.env.local` (if not created by `vercel link`)

```bash
echo 'BACKEND_API_URL="http://localhost:8000"' > .env.local
```

> **Gotcha — remove `INTERNAL_API_KEY` from `.env.local` for local dev.** `vercel link`
> / `vercel env pull` populates `.env.local` with the project's cloud variables,
> **including `INTERNAL_API_KEY`** (the shared secret the production backend requires on
> every request). Locally the FastAPI internal-key gate is meant to be **open** — it
> only opens when `INTERNAL_API_KEY` is unset. If `.env.local` carries a real
> `INTERNAL_API_KEY`, the backend enforces it but `vercel dev` doesn't send a matching
> header, so **every `/api/*` request returns 401** — the UI shows "Admin status
> unavailable" and no data loads. Comment it out or delete the line:
>
> ```bash
> # INTERNAL_API_KEY=...   # leave unset locally so the backend gate stays open
> ```

### 8. Start PostgreSQL

```bash
docker compose up -d postgres
```

Verify it's running:

```bash
docker compose ps
```

You should see `jobscraper-postgres` with status `healthy`.

**Bootstrap the schema (first time, or any brand-new/empty database):**

The Alembic chain is baselined on a pre-existing schema, so simply starting the backend against an empty database **fails** (`relation "users" does not exist`) instead of creating tables. Materialize the full schema from the ORM models and stamp Alembic at head once — this mirrors what the test suite does:

```bash
source .venv/bin/activate            # if not already active
cd src/backend && python - <<'PY'
import os
from sqlalchemy import create_engine
from api.db_models import Base
from api.migrations import stamp_alembic_head
url = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/jobscraper")
Base.metadata.create_all(create_engine(url))
stamp_alembic_head(url)
print("Schema bootstrapped and stamped at Alembic head.")
PY
cd ../..
```

On every later boot the backend keeps the schema current automatically (`alembic upgrade head` in its lifespan) — you only run this once per fresh database. If a branch switch later stamps your DB at a revision that doesn't exist on the current branch, see *"Backend exits on startup with `Can't locate revision`"* in Troubleshooting.

**Seed the `companies` table (required for any scraped data):**

The bootstrap above stamps Alembic at head *without running migration bodies*, so the `seed_*` company migrations never fire — your `companies` table is **empty**, which means the scraper fan-out has nothing to scrape and `job_listings` stays empty. Apply the idempotent seed (a snapshot of prod's company set, `ON CONFLICT DO NOTHING`):

```bash
docker exec -i jobscraper-postgres psql -U postgres -d jobscraper \
  -v ON_ERROR_STOP=1 -f - < src/backend/seed/companies_seed.sql
```

Safe to re-run any time. Prod is the source of truth — see the header of `src/backend/seed/companies_seed.sql` for the one-line query to refresh the snapshot when companies are added. Once seeded, the in-process Procrastinate worker fans out per-company fetches every 30 min (or trigger immediately via the `/api/jobs-qa/trigger-*-fan-out` admin endpoints) and `job_listings` fills in.

### 9. Verify

Start each service per the Quick Start section above and confirm the frontend loads at http://localhost:3000.

### 10. (Optional) Grant yourself admin -- for `/admin` pages

Admin pages (e.g. the **Location Normalization Monitor** at `/admin/location-normalization`, plus user management) are gated on a row in the `admins` table. There is no seeding -- grant yourself once:

1. Sign in at http://localhost:3000 (Google or Auth0). This creates your `users` row.
2. Insert an `admins` row keyed to your email:

   ```bash
   docker exec jobscraper-postgres psql -U postgres -d jobscraper \
     -c "INSERT INTO admins (user_id) SELECT id FROM users WHERE email='you@example.com' ON CONFLICT (user_id) DO NOTHING;"
   ```

3. Reload the app -- the admin navigation items appear.

---

## Component Details

### Frontend (React SPA)

| | |
|---|---|
| Location | `src/frontend/` |
| Dev command | `npm run dev:vercel -w src/frontend` (from project root) |
| Build | `npm run build` |
| Tests | `npm test` (768+ Vitest tests, >85% coverage) |
| Type check | `npm run type-check` |
| Lint | `npm run lint` |
| Format | `npm run format` |

- Uses npm workspaces -- root `package.json` delegates most scripts to `src/frontend`, **but `dev:vercel` exists only in `src/frontend/package.json`**, so it must be invoked with `-w src/frontend` (or from inside `src/frontend/`)
- `dev:vercel` runs `vercel dev` from the project root, which serves both the Vite frontend and the serverless functions in `api/`
- Vite serves on port 3000

### FastAPI Backend

| | |
|---|---|
| Location | `src/backend/api/` |
| Entry point | `src/backend/api/main.py` |
| Run | `PYTHONPATH=. uvicorn src.backend.api.main:app --host 0.0.0.0 --port 8000 --reload` |
| Dependencies | `src/backend/api/requirements.txt` |
| Docs | `src/backend/CLAUDE.md` |

**Why `PYTHONPATH=.`?** The FastAPI app uses relative imports for its own package (`from .config import settings`, `from ..models import ...`) but also imports from the scrapers package via absolute imports (`from scripts.shared.database import get_connection`). Without `PYTHONPATH=.` set from the project root, the `scripts.*` imports fail.

**Endpoints:**
- `GET /api/jobs` -- List jobs (params: company, status, limit, offset)
- `GET /api/jobs/{id}` -- Get single job
- `GET /api/jobs-qa/stats` -- Job statistics
- `GET /api/jobs-qa/scrape-runs` -- Scrape run history
- `POST /api/jobs-qa/trigger-scrape` -- Manually trigger a scraper
- `GET /health` -- Health check

**Auto-scraper:** The backend starts a background task that runs scrapers on a configurable interval (default: 1 hour). It logs errors but won't crash the server if Playwright isn't available.

### Python Scrapers

| | |
|---|---|
| Location | `scripts/` |
| Entry point | `scripts/run_scraper.py` |
| Dependencies | `scripts/requirements.txt` |
| Dev dependencies | `scripts/requirements-dev.txt` |
| Docs | `scripts/CLAUDE.md` |

**Companies:** google, apple, microsoft, or `all`

**JSON mode** (default -- outputs to `scripts/output/`):

```bash
python scripts/run_scraper.py --company google
python scripts/run_scraper.py --company apple --detail-scrape
python scripts/run_scraper.py --company all --max-jobs 10
```

**Database mode** (writes to PostgreSQL):

```bash
python scripts/run_scraper.py --company google \
  --db-url "postgresql://postgres:postgres@localhost:5432/jobscraper"
```

**Tests:**

```bash
cd scripts && pytest              # all tests
cd scripts && pytest tests/unit   # unit only
```

### Vercel Serverless Functions (API Proxies)

| | |
|---|---|
| Location | `api/` |
| Served by | `vercel dev` (via `npm run dev:vercel -w src/frontend`) |

These TypeScript functions proxy external ATS API calls to avoid browser CORS restrictions:

| Function | Proxies to |
|----------|-----------|
| `api/greenhouse.ts` | `https://boards-api.greenhouse.io` |
| `api/lever.ts` | `https://api.lever.co` |
| `api/ashby.ts` | `https://api.ashbyhq.com` |
| `api/workday.ts` | Workday (dynamic tenant URL) |
| `api/jobs.ts` | FastAPI backend `/api/jobs` |
| `api/jobs-qa.ts` | FastAPI backend `/api/jobs-qa` |

Backend URL resolution (`api/utils/backendUrl.ts`): uses `http://localhost:8000` for local dev, `BACKEND_API_URL` env var in production.

### PostgreSQL Database

| | |
|---|---|
| Image | PostgreSQL 15 |
| Port | 5432 |
| Credentials | postgres / postgres |
| Database | jobscraper |
| Connection URL | `postgresql://postgres:postgres@localhost:5432/jobscraper` |

Schema is managed by **Alembic** (source of truth: `src/backend/api/db_models.py`). On a database that already holds the baselined schema, the FastAPI lifespan's `alembic upgrade head` keeps it current on every boot. A brand-new/empty database must be bootstrapped once -- see One-Time Setup step 8 -- because the Alembic chain is baselined on a pre-existing schema and can't build from scratch. Core tables include:
- `job_listings` -- job postings
- `scrape_runs` -- scrape execution history
- `users` -- authenticated user profiles
- `user_enabled_companies` -- per-user company preferences

Table names are the same across every environment (local, prod, per-worker test schemas). Test isolation uses per-worker Postgres schemas via `PYTEST_SCHEMA` + `SET search_path`, not table-name suffixing. Data persists in a Docker volume (`postgres_data`).

---

## Environment Variables

All variables have defaults that work for local development. Override via `.env` file or shell environment.

### FastAPI Backend (`src/backend/api/config.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/jobscraper` | PostgreSQL connection URL |
| `SCRAPER_INTERVAL_HOURS` | `1` | Hours between auto-scrape cycles |
| `SCRAPER_COMPANIES` | `apple,google,microsoft` | Comma-separated company list |
| `SCRAPER_DETAIL_SCRAPE` | `true` | Fetch job detail pages |
| `SCRAPER_TIMEOUT_MINUTES` | `90` | Max time per scrape run |
| `SCRAPER_SCRIPTS_PATH` | `../../scripts` | Path to Python scraper scripts |
| `SCRAPER_PYTHON_PATH` | `python3` | Python interpreter path |
| `PORT` | `8080` | Server port (production) |
| `INTERNAL_API_KEY` | *(unset)* | Shared-secret gate. **Leave unset locally** (gate open). Production-only — if `vercel link` pulled it into `.env.local`, comment it out (see step 7). |

### Vercel Functions (`.env.local`)

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_API_URL` | `http://localhost:8000` | FastAPI backend URL for serverless function proxies |

---

## JetBrains IDE Setup

These instructions work for IntelliJ IDEA Ultimate, PyCharm, and WebStorm. Open the project root (`Job-Visualizer-Notifier/`) as your project.

### Run Configuration: Frontend Dev Server

1. **Run > Edit Configurations > + > npm**
2. Configure:
   - **Name:** Frontend (Vercel Dev)
   - **Command:** `run`
   - **Scripts:** `dev:vercel`
   - **Package.json:** `<project-root>/src/frontend/package.json`
   - **Node interpreter:** Project default
3. Click **Apply**

### Run Configuration: FastAPI Backend

1. **Run > Edit Configurations > + > Python**
2. Configure:
   - **Name:** FastAPI Backend
   - **Module name:** `uvicorn` (select "Module name" instead of "Script path")
   - **Parameters:** `src.backend.api.main:app --host 0.0.0.0 --port 8000 --reload`
   - **Working directory:** `<project-root>` (e.g., `/Users/you/Job-Visualizer-Notifier`)
   - **Environment variables:** `PYTHONPATH=.`
   - **Python interpreter:** `.venv/bin/python`
3. Click **Apply**

> The `PYTHONPATH=.` and working directory settings are critical. Without them, the `scripts.shared.*` absolute imports will fail with `ModuleNotFoundError`. The backend's own imports use relative paths (`from .config`, `from ..models`) so they resolve correctly regardless of PYTHONPATH.

### Run Configuration: Python Scrapers

1. **Run > Edit Configurations > + > Python**
2. Configure:
   - **Name:** Scraper (Google)
   - **Script path:** `<project-root>/scripts/run_scraper.py`
   - **Parameters:** `--company google --max-jobs 10`
   - **Working directory:** `<project-root>`
   - **Python interpreter:** `.venv/bin/python`
3. Click **Apply**

For database mode, change Parameters to:
```
--company google --db-url "postgresql://postgres:postgres@localhost:5432/jobscraper"
```

### Run Configuration: Frontend Tests (Vitest)

1. **Run > Edit Configurations > + > Vitest**
2. Configure:
   - **Name:** Frontend Tests
   - **Vitest package:** `<project-root>/node_modules/vitest`
   - **Working directory:** `<project-root>`
   - **Configuration file:** `<project-root>/src/frontend/vitest.config.ts`
3. Click **Apply**

### Run Configuration: Scraper Tests (pytest)

1. **Run > Edit Configurations > + > Python tests > pytest**
2. Configure:
   - **Name:** Scraper Tests
   - **Target:** Custom
   - **Additional arguments:** `tests/`
   - **Working directory:** `<project-root>/scripts`
   - **Python interpreter:** `.venv/bin/python`
3. Click **Apply**

### Database Data Source (PostgreSQL)

1. **View > Tool Windows > Database**
2. **+ > Data Source > PostgreSQL**
3. Configure:
   - **Host:** `localhost`
   - **Port:** `5432`
   - **User:** `postgres`
   - **Password:** `postgres`
   - **Database:** `jobscraper`
4. Click **Test Connection**, then **Apply**

After the one-time schema bootstrap (One-Time Setup step 8), the tables `job_listings`, `scrape_runs`, `users`, `admins`, and the rest will appear.

---

## Troubleshooting

**`ModuleNotFoundError` when starting FastAPI**
`PYTHONPATH=.` is missing or the working directory isn't the project root. The backend uses relative imports for its own package but needs the project root on the Python path for `scripts.shared.*` imports.

**API calls fail in the frontend (CORS errors or 404s)**
You're running `npm run dev` instead of `npm run dev:vercel -w src/frontend`. The serverless functions in `api/` are only served by `vercel dev`.

**"Admin status unavailable" and every `/api/*` request returns 401**
`.env.local` has a non-empty `INTERNAL_API_KEY` (pulled in by `vercel link` / `vercel env pull`). The backend's internal-key gate then enforces it, but local `vercel dev` doesn't send a matching header, so all non-`/health` requests are rejected. Comment out or remove the `INTERNAL_API_KEY` line in `.env.local` and restart the backend — locally the gate must stay open (unset). See step 7 above.

**Backend exits on startup with `Can't locate revision identified by '<hash>'` (or `relation "users" does not exist`)**
Your local Postgres is shared across branches and its `alembic_version` is stamped at a revision that doesn't exist on the current branch -- usually a migration from another unmerged feature branch. The lifespan runs `alembic upgrade head` on boot and can't compute a path from an unknown revision, so startup fails. Fixes:
- **Keep your data (tables already exist):** repoint the version tracker to this branch's head without touching tables -- `alembic stamp head` (run from the repo root with the venv active).
- **Start clean (empty DB):** `docker compose down -v && docker compose up -d postgres`, then re-run the schema bootstrap from One-Time Setup step 8. (`stamp` alone on an empty DB would leave you with no tables -- the Alembic chain can't build an empty DB from scratch.)

This recurs whenever you switch between branches whose migrations have diverged.

**`vercel dev` fails with "not linked"**
Run `vercel link` first to create the `.vercel/` directory.

**Playwright browser not found**
Run `playwright install chromium` after pip installing the requirements. The browser binary is downloaded separately from the Python package.

**PostgreSQL connection refused**
The Docker container isn't running. Run `docker compose up -d postgres` and check with `docker compose ps`.

**Tables don't exist in PostgreSQL**
Tables are created dynamically on first connection. Run the backend or a scraper with `--db-url` at least once to create them.

**Port 8000 already in use**
Another process is using port 8000. Kill it with `lsof -ti:8000 | xargs kill -9`, or run the backend on a different port and update `BACKEND_API_URL` in `.env.local` to match.

**Port 3000 already in use**
Kill the existing process:
```bash
lsof -ti:3000 | xargs kill -9
```

**Backend auto-scraper fails on startup**
The background scraper task logs errors if Playwright isn't installed or configured, but the API endpoints still work normally.

**Scraper is very slow**
Detail scraping (`--detail-scrape`) fetches individual pages for each job. Expect 15-30 minutes for 500+ jobs. Use `--max-jobs 10` for testing.
