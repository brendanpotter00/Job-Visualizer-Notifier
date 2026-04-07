# onesecondswe

A job board that pulls software engineering postings directly from company ATS systems — Greenhouse, Lever, Ashby, Gem, and Workday — plus custom scrapers for Google, Apple, and Microsoft.

## Prerequisites

- Node.js 18+
- [Vercel CLI](https://vercel.com/docs/cli): `npm i -g vercel`
- Python 3.13+ (full stack only)
- Docker (full stack only — runs PostgreSQL)

## Quick Start (frontend only)

```bash
npm install
npm run dev:vercel
```

Opens at `http://localhost:3000`. You must use `dev:vercel` — it runs Vercel Dev which serves the API proxy functions in `api/`. Plain `npm run dev` skips the proxies and most companies won't load.

## Full Stack (frontend + backend + scrapers)

```bash
# 1. Start PostgreSQL
docker compose up -d postgres

# 2. Set up Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r src/backend/api/requirements.txt
pip install -r scripts/requirements.txt
.venv/bin/playwright install chromium

# 3. Start the backend
PYTHONPATH=. uvicorn src.backend.api.main:app --host 0.0.0.0 --port 8000 --reload

# 4. In another terminal, start the frontend
npm run dev:vercel
```

Backend API docs: `http://localhost:8000/docs`

## Commands

| Command | Description |
| --- | --- |
| `npm run dev:vercel` | Start frontend with API proxies |
| `npm run build` | Production build |
| `npm test` | Run tests |
| `npm run type-check` | TypeScript type checking |
| `npm run lint` | ESLint |
| `npm run format` | Prettier |

## Repo Structure

```
src/frontend/      React SPA (TypeScript, Redux Toolkit, MUI, Recharts)
src/backend/api/   FastAPI backend (Python, PostgreSQL)
scripts/           Python scrapers (Playwright)
api/               Vercel serverless functions (ATS API proxies)
```

See `CLAUDE.md` for architecture details.
