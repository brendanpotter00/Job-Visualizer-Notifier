---
name: run
description: |
  Launch and drive this project's app to see a change working. Use when asked to
  run, start, or screenshot the app, or to confirm a change works in the real
  app (not just tests). Covers all three modes: frontend-only (fastest), full
  stack (frontend + backend + Postgres), and scraper-only. A zero-context agent
  should be able to follow this without reading anything else.
trigger_phrases:
  - run the app
  - start the app
  - start the dev server
  - run the project
  - run locally
  - start locally
  - launch the frontend
  - start the backend
  - run the backend
  - run the full stack
required_tools:
  - Bash
mode: read-write
---

# Run This Project Locally

## Quick orientation

Monorepo: TypeScript + React frontend (`src/frontend/`) + Python FastAPI backend
(`src/backend/`) + Python scrapers (`scripts/`). The frontend visualizes job
posting activity; the backend fetches jobs from ATS boards via Procrastinate
workers; scrapers handle Google / Apple / Microsoft.

**Ports:**
- Frontend: `http://localhost:3000` (Vercel Dev) or `http://localhost:5173` (plain Vite)
- Backend: `http://localhost:8000` — API docs at `http://localhost:8000/docs`
- Postgres: `localhost:5432`

---

## Mode 1 — Frontend only (fastest, no backend required)

The frontend points at the **production Railway backend** when run via Vercel Dev.
This is the right mode for UI-only changes.

```bash
# From project root
npm install          # first time only
npm run dev:vercel -w src/frontend
# → http://localhost:3000
```

> **MUST use `dev:vercel`, not `npm run dev`.**
> `dev:vercel` runs `vercel dev` from the project root, which executes the
> serverless functions in `api/` as local proxies. Plain `npm run dev` starts
> Vite only — the `api/` proxies never run and almost all company data fails
> to load (CORS / auth errors from direct ATS calls).

### Vercel CLI requirement

`vercel dev` must be installed:

```bash
npm i -g vercel   # if 'vercel: command not found'
```

If Vercel CLI prompts for project linking on first run, link to the existing
`job-visualizer-notifier` project (not a new one).

---

## Mode 2 — Full stack (frontend + backend + Postgres)

Use this for backend changes, scraper changes, or when you need a local DB.

### Step 1 — Start Postgres

```bash
docker compose up -d postgres
# Postgres: localhost:5432, user/pass/db all = "postgres"/"postgres"/"jobscraper"
```

### Step 2 — Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r src/backend/api/requirements.txt
pip install -r scripts/requirements.txt          # only needed for scrapers
.venv/bin/playwright install chromium             # only needed for scrapers
```

### Step 3 — Start the backend (new terminal)

```bash
source .venv/bin/activate
PYTHONPATH=. uvicorn src.backend.api.main:app --host 0.0.0.0 --port 8000 --reload
# → http://localhost:8000/docs
```

On startup the backend:
- Runs Alembic migrations automatically
- Seeds company rows and features
- Starts Procrastinate worker queues (`greenhouse_fetch`, `ashby_fetch`, etc.)

### Step 4 — Start the frontend (another terminal)

```bash
npm run dev:vercel -w src/frontend
# → http://localhost:3000
```

Vercel Dev detects `localhost` in the Host header and routes `/api/*` calls to
your local backend on port 8000 instead of the production Railway backend.
(See `api/utils/backendUrl.ts` for the routing logic.)

---

## Mode 3 — Scrapers only

```bash
source .venv/bin/activate

# Google jobs
python scripts/run_scraper.py

# Apple or Microsoft
python scripts/run_scraper.py --company apple
python scripts/run_scraper.py --company microsoft

# All script-based companies
python scripts/run_scraper.py --company all

# Dry run (no DB writes)
python scripts/run_scraper.py --dry-run
```

Scrapers require Postgres running and the `.venv` active.

---

## Key commands reference

| Task | Command (from project root) |
|------|-----------------------------|
| Dev server (frontend-only) | `npm run dev:vercel -w src/frontend` |
| Dev server (plain Vite, no proxies) | `npm run dev` |
| Production build | `npm run build` |
| TypeScript check | `npm run type-check` |
| All frontend tests | `npm test` |
| Tests with coverage | `npm run test:coverage -w src/frontend` |
| Tests (watch mode) | `npm run test:watch -w src/frontend` |
| Lint | `npm run lint` |
| Format | `npm run format` |
| Backend start | `PYTHONPATH=. uvicorn src.backend.api.main:app --host 0.0.0.0 --port 8000 --reload` |
| Postgres start | `docker compose up -d postgres` |
| Postgres stop | `docker compose down` |

---

## Environment variables

**Frontend (`src/frontend/.env.local`, NOT project root `.env.local`):**

The frontend has no required env vars for local dev — Vercel Dev injects them
from the linked Vercel project. If you need to override:

```
VITE_API_URL=http://localhost:8000   # force local backend
```

**Backend (set in shell or `.env` at project root):**

| Var | Default | Notes |
|-----|---------|-------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/jobscraper` | Must match docker-compose |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173,http://localhost:8000` | Add your port if different |
| `ANTHROPIC_API_KEY` | *(none)* | Only needed for location normalization |
| `AUTH0_DOMAIN` | *(none)* | Only needed if testing auth flows |
| `AUTH0_AUDIENCE` | *(none)* | Only needed if testing auth flows |
| `INTERNAL_API_KEY` | *(none)* | Shared secret for Vercel → backend proxy calls |

All other config lives in `src/backend/api/config.py` (Pydantic BaseSettings).

---

## Critical gotchas

1. **`dev:vercel` not `dev`** — Plain `npm run dev` skips the `api/` serverless
   proxy functions. Every company's data goes through those proxies. Without them
   you get CORS errors or broken auth on almost every ATS board.

2. **Env files must be in `src/frontend/`** — Vite reads `src/frontend/.env.local`,
   not `<root>/.env.local`. A `.env.local` at the project root is silently ignored
   by Vite.

3. **Vercel cloud env vars override local `.env`** — When `vercel dev` is running,
   env vars pulled from the linked Vercel project take precedence over local
   `.env` files for the serverless functions. Backend URL routing uses the Host
   header (`localhost` → local backend) to avoid this for the backend URL.

4. **macOS port 5000 is AirPlay** — Never configure the backend or any service on
   port 5000 on macOS. Use 8000.

5. **Stale Vite dep-optimization → page stuck on "Loading…"** — If the app loads
   but RTK Query calls are pending forever despite 200 responses, it's stale Vite
   cache (module dedup). Fix: `rm -rf src/frontend/node_modules/.vite` then
   restart `dev:vercel`.

6. **Zero TypeScript errors required before commit** — Run `npm run type-check`
   before committing. The CI pipeline rejects TypeScript errors.

7. **Test coverage must stay >80%** — Run `npm run test:coverage -w src/frontend`
   to check. There are 1300+ tests; all must pass.

---

## Health checks

```bash
# Backend alive?
curl http://localhost:8000/health

# Procrastinate worker alive?
curl http://localhost:8000/health/worker

# API docs
open http://localhost:8000/docs
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `vercel: command not found` | Vercel CLI not installed | `npm i -g vercel` |
| Frontend loads but all company data fails | Running plain `npm run dev` | Switch to `npm run dev:vercel -w src/frontend` |
| Backend `relation "X" does not exist` | Migrations not applied or local DB drift | Stop backend, `alembic downgrade base`, `alembic upgrade head`, restart |
| Page stuck on "Loading…" (RTK calls never resolve) | Stale Vite dep cache | `rm -rf src/frontend/node_modules/.vite` + restart |
| `connection refused` on port 5432 | Postgres not running | `docker compose up -d postgres` |
| Procrastinate worker not processing jobs | Worker queues not started | Restart the backend — worker starts automatically on startup |
