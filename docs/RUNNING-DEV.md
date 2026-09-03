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

## Re-testing the add-a-company flow (local only)

The add flow only runs its real code path **once per board**: after that,
`POST /api/users/companies` answers *"you already track this"* / *"we already
publish this"*, and the 20-per-month add quota has spent a slot. To test it again
you have to put the database back to before the board was added.

**Turn it on** — `.env.local`, then restart the backend:

```bash
DEV_RESET_ENABLED=true
```

Two ways to use it, both doing exactly the same thing (one service, one delete order):

| | |
|---|---|
| **Button** | `/qa` → **Danger zone — local development only**. Pick a scope, click *Clear custom companies*, confirm. It prints the per-table counts it deleted and the published rows it left alone. The panel does not render unless the backend says the reset is available. |
| **CLI** | `python scripts/one_off/dev_reset_custom_companies.py --email you@example.com` — **dry run** by default (runs the real deletes, prints the real counts, then rolls back). Add `--apply` to commit, `--all` instead of `--email` for every user, `--yes` to skip the prompt. |

**What it clears:** the `visibility='user'` `companies` rows, their `user_companies`
ownership rows, `company_add_attempts` (which is the quota counter — so your adds
come back), `company_scripts`, discovery progress (it lives in the company row's
`provider_config`), `company_harvests`, `scrape_runs`, and every `custom:<id>` job
with its freshness / location / tag / enrichment sidecars.

**What it never touches:** published companies and their jobs. Every delete is
scoped to `visibility='user'`.

**Why it cannot escape your laptop:** with `DEV_RESET_ENABLED` off the route is not
registered at all (404, not 403). With it *on*, the endpoint still refuses unless
`DATABASE_URL` parses to a loopback host — checked on every call, independently of
the flag. And it is deliberately **not** in any `api/*.ts` proxy allowlist, so the
button calls `http://localhost:8000` directly rather than going through a Vercel
function. If your backend is not on `:8000` (per-worktree ports), set
`VITE_DEV_RESET_BACKEND_URL` in `src/frontend/.env.local` to match.

## Daily gotchas

- **`-w src/frontend` is required.** `dev:vercel` is defined only in `src/frontend/package.json`; `npm run dev:vercel` from the root fails with `Missing script: "dev:vercel"`.

- **Backend won't boot — `Can't locate revision identified by '<hash>'`.** You switched to a branch whose migrations don't include your DB's stamped revision (one shared local Postgres across branches). Repoint it without touching tables:
  ```bash
  alembic stamp head        # repo root, venv active
  ```
  If your DB is actually empty (e.g. after `docker compose down -v`), don't stamp — re-run the schema **bootstrap** from [LOCAL-SETUP.md](./LOCAL-SETUP.md) step 8 instead (the Alembic chain can't build an empty DB from scratch), **then re-seed companies** (the bootstrap skips migration data, so the `companies` table comes up empty and nothing scrapes):
  ```bash
  docker exec -i jobscraper-postgres psql -U postgres -d jobscraper \
    -v ON_ERROR_STOP=1 -f - < src/backend/seed/companies_seed.sql
  ```

- **UI loads but no companies / no jobs.** The `companies` table is empty (fresh DB after a bootstrap, which skips the `seed_*` migration data). Re-seed with the idempotent snapshot above; the worker fans out and fills `job_listings` within 30 min (or hit `/api/jobs-qa/trigger-*-fan-out` to start now).

- **Every `/api/*` returns 401 / UI shows "Admin status unavailable".** `.env.local` carries a real `INTERNAL_API_KEY` (pulled in by `vercel link`). Comment it out — locally the backend's internal-key gate must stay **open** (unset).

- **Port already in use.** `lsof -ti:8000 | xargs kill -9` (or `:3000`).

- **Admin pages blank / redirect to home.** Grant yourself admin once, after signing in at http://localhost:3000:
  ```bash
  docker exec jobscraper-postgres psql -U postgres -d jobscraper \
    -c "INSERT INTO admins (user_id) SELECT id FROM users WHERE email='you@example.com' ON CONFLICT (user_id) DO NOTHING;"
  ```

- **`scraper[apple] … exit code 1` in the backend log is non-fatal.** The Playwright auto-scrapers (Google/Apple/Microsoft/Amazon) log errors but the API keeps serving. Only matters if you need those companies' data locally.
