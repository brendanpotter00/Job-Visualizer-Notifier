# Running Dev (Daily)

The short version: start three processes and go. For first-time install -- Node/Python deps, Playwright, `vercel link`, `.env.local`, and the **one-time database schema bootstrap** -- see **[LOCAL-SETUP.md](./LOCAL-SETUP.md)**.

## Start the stack

Three terminals, all from the repo root:

```bash
# 1 — Postgres
docker compose up -d postgres

# 2 — Backend (FastAPI)
source .venv/bin/activate
PYTHONPATH=. uvicorn src.backend.api.main:app --host 0.0.0.0 --port 8000 --reload

# 3 — Frontend + API proxies   (the -w flag is required, see gotchas)
npm run dev:vercel -w src/frontend
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend / Swagger | http://localhost:8000/docs |
| Health | http://localhost:8000/health |

Smoke test (gate open + DB reachable):

```bash
curl -s localhost:8000/health              # OK
curl -s "localhost:8000/api/jobs?limit=1"   # HTTP 200, [] or jobs
```

## Stop the stack

Ctrl-C terminals 2 and 3, then:

```bash
docker compose stop postgres    # or `docker compose down` to remove the container (the postgres_data volume is kept)
```

## Daily gotchas

- **`-w src/frontend` is required.** `dev:vercel` is defined only in `src/frontend/package.json`; `npm run dev:vercel` from the root fails with `Missing script: "dev:vercel"`.

- **Backend won't boot — `Can't locate revision identified by '<hash>'`.** You switched to a branch whose migrations don't include your DB's stamped revision (one shared local Postgres across branches). Repoint it without touching tables:
  ```bash
  alembic stamp head        # repo root, venv active
  ```
  If your DB is actually empty (e.g. after `docker compose down -v`), don't stamp — re-run the schema **bootstrap** from [LOCAL-SETUP.md](./LOCAL-SETUP.md) step 8 instead (the Alembic chain can't build an empty DB from scratch).

- **Every `/api/*` returns 401 / UI shows "Admin status unavailable".** `.env.local` carries a real `INTERNAL_API_KEY` (pulled in by `vercel link`). Comment it out — locally the backend's internal-key gate must stay **open** (unset).

- **Port already in use.** `lsof -ti:8000 | xargs kill -9` (or `:3000`).

- **Admin pages blank / redirect to home.** Grant yourself admin once, after signing in at http://localhost:3000:
  ```bash
  docker exec jobscraper-postgres psql -U postgres -d jobscraper \
    -c "INSERT INTO admins (user_id) SELECT id FROM users WHERE email='you@example.com' ON CONFLICT (user_id) DO NOTHING;"
  ```

- **`scraper[apple] … exit code 1` in the backend log is non-fatal.** The Playwright auto-scrapers (Google/Apple/Microsoft) log errors but the API keeps serving. Only matters if you need those companies' data locally.
