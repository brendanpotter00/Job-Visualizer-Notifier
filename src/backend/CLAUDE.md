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
- Database: `jobscraper` (created on first lifespan/migration run). Key tables include `job_listings`, `scrape_runs`, `users`, `user_enabled_companies`, `user_saved_filters`, `user_keyword_lists`, `admins`, `features`, `feature_upvotes`, `companies`, `locations`, `job_locations`, `job_enrichment`, `feedback`, `worker_heartbeats`, and others — see `src/backend/docs/database-schema.md` for the full schema.
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
| `DB_POOL_TIMEOUT` | Database pool connection timeout (seconds) | `5` |
| `PORT` | Server port | `8080` |
| `CORS_ORIGINS` | Comma-separated allowed origins | `http://localhost:3000,http://localhost:5173,http://localhost:8000` |
| `AUTH0_DOMAIN` | Auth0 tenant domain (e.g., `myapp.us.auth0.com`) | *(required for auth)* |
| `AUTH0_AUDIENCE` | Auth0 API audience identifier | *(required for auth)* |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID for One Tap validation | *(optional)* |
| `INTERNAL_API_KEY` | Shared secret for X-Internal-Key middleware (server-to-server auth); unset = allow all requests, log warning | *(optional)* |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude Haiku Tier-2 location normalization and eval runs | *(required for normalization)* |
| `ENRICHMENT_USE_EXTERNAL` | Master flag enabling external enrichment pull integration (gates `GET /pending`) | `false` |
| `ENRICHMENT_CLAIM_TTL_MINUTES` | Stale-claim reclaim window in minutes (must exceed a full enricher tick round-trip) | `240` |
| `ENRICHMENT_REQUIRE_JUDGE_PASS` | If true, hold judge-flagged rows as `needs_human` instead of publishing `done` | `false` |
| `ENRICHMENT_CLAIM_WITHOUT_DESCRIPTION` | If true, allow claiming description-less rows (e.g. Workday/Eightfold) | `false` |
| `POSTHOG_PROJECT_TOKEN` | PostHog analytics API key — if unset, all analytics is disabled (`get_posthog()` returns `None`) | *(optional)* |
| `POSTHOG_HOST` | PostHog ingestion host (US cloud endpoint) | `https://us.i.posthog.com` |
| `FEEDBACK_RATE_LIMIT_MAX` | Max feedback submissions per client IP per window | `5` |
| `FEEDBACK_RATE_LIMIT_WINDOW_SECONDS` | Rate-limit sliding window duration (seconds) | `60` |

**Table names are env-agnostic.** All environments share bare names (`job_listings`, `scrape_runs`, `users`, `user_enabled_companies`). Test isolation uses per-worker Postgres **schemas** via `PYTEST_SCHEMA=test_<hex>` + `SET search_path`; inside the schema the table names are the same as prod. See `docs/implementations/envAgnosticTables/PLAN.md`.

## API Endpoints

**Jobs Router (`/api/jobs`):**
- `GET /api/jobs` - List jobs (params: company, companies, status, category, level, limit, offset, **since**, **cursor**)
- `GET /api/jobs/{id}` - Get single job by ID

**Keyset pagination on `GET /api/jobs`** (ticket 1.3; closes the 2026-05-17 postmortem's
"push the time/recency filter into SQL so the result set bounds itself"):

- **Two modes, selected by parameter presence.** Passing **neither** `since` nor `cursor`
  is byte-identical to the pre-keyset behaviour — same SQL, `ORDER BY f.last_seen_at DESC`,
  same bare-array body, **no** `X-Next-Cursor` header. Passing **either** switches to
  `ORDER BY first_seen_at DESC, source_id DESC, id DESC` with a row-value boundary
  predicate. Locked by `api/tests/test_jobs_keyset_pagination.py`.
- **`?since=`** — ISO-8601 **with a UTC offset** (`Z` or `±HH:MM`); naive values are a 422,
  never assumed-UTC. **Inclusive**: `first_seen_at >= since`. No server default; the 90-day
  default is the frontend's business.
- **`?cursor=`** — opaque `base64url("<first_seen_at ISO-8601 UTC>|<source_id>|<id>")`,
  minted by the server, echoed back verbatim by the client. Codec + validation live in
  `api/pagination.py`. Malformed input is a **422 with a specific reason** — never a
  silently-ignored parameter, which would restart the walk at page 1 with no signal.
- **`X-Next-Cursor` response header** — the next page's token. Present **iff** the page came
  back full (`len(page) == limit`); its **absence is the only end-of-walk signal**. The body
  stays a bare JSON array in both modes, so cursor support is purely additive for every
  existing consumer. A trailing exactly-full page costs one extra round trip returning `[]`.
- **Sort key rationale:** `first_seen_at` is IMMUTABLE (unlike `last_seen_at`, re-stamped on
  every OPEN row every scrape cycle), and `(source_id, id)` is the composite PK, so the tuple
  is unique. Both properties are load-bearing — without the first, a concurrent scrape
  reshuffles the ordering mid-walk; without the second, rows sharing a `first_seen_at` page
  non-deterministically. Matches the UI's own `selectRecentJobsSorted` (firstSeenAt DESC).
- **Header delivery is THREE hops, all wired here:** `api/jobs.ts` (the Vercel proxy)
  re-emits it explicitly — `forwardResponse` copies status + body only — `CORSMiddleware`
  in `main.py` lists it in `expose_headers` for callers hitting the backend directly, and
  `vercel.json`'s `/api/(.*)` block adds `Access-Control-Expose-Headers: X-Next-Cursor` for
  cross-origin callers of the proxy. Adding a response header to this endpoint without doing
  all three means it silently never reaches the client. Note `api/jobs.ts` forwards
  `since`/`cursor` on **presence** (`!== undefined`), not truthiness — dropping an empty
  `?cursor=` would turn the backend's 422 into a silent page-1 restart.
- **`offset` is a 422 in keyset mode.** Both answer "where does this page start?", and
  `get_jobs` applies both — the cursor seeks to the boundary and `OFFSET n` then discards
  the first `n` rows past it, a 200 with silent row loss. `offset=0` is fine (default,
  no-op); the legacy path still supports `offset` normally.
- **A cursor is only meaningful under the filter set it was minted with.** Changing
  `companies`/`status`/`category`/`level`/`since` mid-walk is not an error and corrupts
  nothing (the cursor names a filter-independent sort position), but the resulting pages are
  relative to the *new* filters, so the walk stops being a complete enumeration of either
  set. Treat a filter change as a new walk and drop the cursor.
- **Index:** `idx_job_listings_open_first_seen_keyset` on `(first_seen_at, source_id, id)`,
  partial `WHERE status = 'OPEN'` (migration `08765ce81d35`). Plain ASC columns served by a
  BACKWARD index scan; verified by EXPLAIN at prod scale to have **no Sort node** and to take
  the cursor tuple as an `Index Cond`, not a `Filter`. Any request that does **not** filter
  to `status=OPEN` — including one that **omits `status` entirely**, not just
  `status=CLOSED` — falls off the partial index and sorts. Correct, just unindexed, and no
  real caller does it.

**QA Router (`/api/jobs-qa`):**
- `GET /api/jobs-qa/stats` - Job statistics (params: company; returns total, open, closed, by company)
- `GET /api/jobs-qa/scrape-runs` - Scrape run history (params: company, limit; `skippedUpdate` is tri-state — `true`/`false` from the writer, `null` for rows written before the column existed)
- `GET /api/jobs-qa/scraper-health` - Stale-scraper report (params: `thresholdHours`, default 24). Enabled companies whose newest `job_freshness.last_seen_at` (the sidecar is the only freshness store since `18fe9c20a8fd`) is older than the threshold (a company with no job rows at all counts as stale). Internal-key auth only — **not** `require_admin` — so the daily `.github/workflows/scraper-health.yml` Action can call it with one header. Because internal-key is its ONLY gate and the public Vercel proxy holds that key unconditionally, the path is NOT in `PROXIED_PATHS` in `api/jobs-qa.ts` (an allowlist — only `scrape-runs` and `trigger-scrape` are forwarded) and 404s from the internet; reach it by calling Railway directly. `TestProxyAllowlistInvariant` asserts both directions: every allowlisted path carries `require_admin`, and every route lacking it is absent from the allowlist. Always 200; the caller decides red/green. Deliberately NOT folded into `/health/worker` (that is Railway's `healthcheckPath`; a stale company would restart-loop the container).
- `POST /api/jobs-qa/trigger-scrape` - Manually trigger scraper (params: company; default: google)

**Users Router (`/api/users`):**
- `GET /api/users` - Get or create authenticated user's profile (requires Bearer token)
- `PUT /api/users` - Update display name (requires Bearer token)
- `POST /api/users/visit` - Record one full-page-load visit (204; upserts the row then increments `visit_count` + stamps `last_visit_at`; requires Bearer token)
- `GET /api/users/enabled-companies` - List user's enabled companies (requires Bearer token)
- `PUT /api/users/enabled-companies` - Update user's enabled companies (requires Bearer token)
- `POST /api/users/companies` - Add a company to track by careers-page URL (requires Bearer token; per-user rate-limited). Deterministic ATS detection (Greenhouse/Ashby/Lever/Gem/Workday) resolves synchronously → 200 `{status: added|alreadyTracked, company}`; an unrecognized custom site enqueues async onboarding (Playwright capture + one Haiku `custom_json` recipe) → 202 `{status: pending, submissionId}`. User-added companies are deduped globally and stored `listed=false` (hidden from the public directory, visible only to users who track them). SSRF-guarded (`services/url_guard.py`).
- `GET /api/users/companies` - The user's runtime-added (custom, unlisted) tracked companies, for the frontend dynamic company registry (requires Bearer token)
- `GET /api/users/companies/submissions/{id}` - Poll an async add-company submission's status (owner-scoped; requires Bearer token)

**Saved Filters Router (`/api/users/saved-filters`):** all routes require a Bearer token.
- `GET /api/users/saved-filters` - Scalar saved filters (per-page time windows, shared locations, active keyword-list pointers); never 404s — returns server defaults (`recent=90d`, `trend=90d`, no locations) when the user has no row
- `PUT /api/users/saved-filters` - Full-replace (upsert) the scalar saved filters; 409 if an active keyword-list pointer is unknown or not owned
- `GET /api/users/saved-filters/keyword-lists` - List the user's named keyword lists by position, with the read-only built-in "Software Engineering" list (`builtin-swe`) synthesized last
- `POST /api/users/saved-filters/keyword-lists` - Create a keyword list (201); 409 on duplicate/reserved name, 422 at the per-user list cap
- `PATCH /api/users/saved-filters/keyword-lists/{list_id}` - Rename / replace tags / reorder (partial); 404 if not owned, 409 on name collision, 422 on the built-in id
- `DELETE /api/users/saved-filters/keyword-lists/{list_id}` - Delete a list (204; NULLs any active pointer referencing it); 404 if not owned, 422 on the built-in id
- `GET /api/users/saved-filters/locations/search` - Substring autocomplete over canonical location names (params: `q`, `limit`, `openOnly`)

**Jobs facets:** `GET /api/jobs/facets` - enrichment dropdown catalog (categories + levels with labels/order/parent) from the seeded dimensions.

**Internal Enrichment Router (`/api/internal/enrichment`, X-Internal-Key):** `GET /pending` (claim batch; title-priority order — entry-level/intern, then software-engineering, then everything else, newest `first_seen_at` within each tier), `POST /results` (idempotent write-back; returns `written`/`failed[]`(+`source_id`)/`warnings[]`), `GET /sample`, `GET /health`, `POST /metrics` (per-tick push → `enrichment_ticks`, idempotent on `tick_uuid`), `GET /corrections` (human-correction feed for the enricher's golden-merge).

**Admin Enrichment (`/api/admin/enrichment/*`, requires admin):** `GET /health`, `GET /needs-human` (paginated triage queue), `GET /ticks`, `GET /recent`, `POST /jobs/{source_id}/{job_id}/correct` (publish human labels + lock row; sets `human_decision='corrected'`), `POST /jobs/{source_id}/{job_id}/confirm` (one-click validate the proposal as-is + lock row; sets `human_decision='confirmed_correct'`; 409 if the row has no proposed labels), `POST /jobs/{source_id}/{job_id}/reenrich` (reset + unlock; clears `human_decision`). Backing SQL in `services/enrichment_monitor.py`. `job_enrichment.human_decision` (`NULL` | `corrected` | `confirmed_correct`) is the human verdict — distinct from the judge's `judged`/`judge_passed` — and rides the `/api/internal/enrichment/corrections` feed as `decision` so the enricher can tell a fix from a validated raise.

**Admin Router (`/api/admin`):**
- `GET /api/admin/users` - List all users with admin flag (requires admin)
- `GET /api/admin/users/stats` - User statistics (requires admin)
- `GET /api/admin/users/{user_id}/visits` - Per-user visit history (requires admin)
- `GET /api/admin/feedback` - List user feedback submissions (requires admin)
- `POST /api/admin/users/{user_id}/admin` - Grant admin to user (requires admin)
- `DELETE /api/admin/users/{user_id}/admin` - Revoke admin from user (requires admin)
- `POST /api/admin/jobs/{job_id}/normalize` - Re-normalize a single job's location via Claude Haiku (requires admin)
- `PUT /api/admin/locations/aliases/{raw_text}` - Create or update a location alias (requires admin)
- `GET /api/admin/locations/aliases` - List all location aliases (requires admin)
- `GET /api/admin/locations/health` - Location normalization health overview (requires admin)
- `GET /api/admin/locations/integrity` - Location integrity check (requires admin)
- `GET /api/admin/locations/reverse` - Reverse-lookup canonical → raw texts (requires admin)
- `GET /api/admin/locations/alias-originals` - Raw texts that alias to a canonical (requires admin)
- `GET /api/admin/locations/problem-jobs` - Jobs with problematic location data (requires admin)
- `POST /api/admin/locations/re-normalize-all` - Break-glass: reset all normalization_status to NULL and re-queue (requires admin)

**Features Router (`/api/features`):**
- `GET /api/features` - List all features with upvote counts, current user's vote state, and `completedAt` (null = open candidate, set = shipped) (optional auth)
- `POST /api/features/{feature_id}/upvote` - Add upvote for a feature (requires Bearer token)
- `DELETE /api/features/{feature_id}/upvote` - Remove upvote for a feature (requires Bearer token)

**Feedback Router (`/api/feedback`):**
- `POST /api/feedback` - Submit user feedback (public; optional Bearer token — stores anonymous if token missing/invalid)

**Companies Router (`/api/companies`):**
- `GET /api/companies` - List all enabled companies with directory profiles (public, no auth; alphabetical order)

**Locations Router (`/api/locations`):**
- `GET /api/locations/search` - Substring autocomplete over canonical location names (params: `q`, `limit`, `openOnly`; public, internal-key auth; feeds Location filter dropdowns on Recent Jobs and company hiring-trend pages)

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
│   ├── google_jwt.py    # Google One Tap token validation via Google JWKS
│   ├── internal_key.py  # X-Internal-Key middleware (server-to-server auth for proxied routes)
│   └── claims.py        # Typed claim helpers extracted from validated JWT payloads
├── routers/
│   ├── jobs.py                  # Jobs list and detail endpoints
│   ├── jobs_qa.py               # Stats, scrape runs, trigger scrape
│   ├── users.py                 # User profile + enabled-companies endpoints (auth required)
│   ├── saved_filters.py         # Saved-filters, keyword-list CRUD, location search (auth required)
│   ├── features.py              # Feature voting endpoints (list, upvote, remove upvote)
│   ├── admin.py                 # Admin-only endpoints: user management, enrichment oversight, location normalization, and feedback
│   ├── feedback.py              # Public user-feedback submission (POST /api/feedback; optional auth)
│   ├── companies.py             # Public curated-companies directory (GET /api/companies; no auth)
│   ├── locations.py             # Public canonical-location search (GET /api/locations/search; internal-key auth)
│   └── internal_enrichment.py  # Internal enrichment API (X-Internal-Key; GET /pending, POST /results, etc.)
├── services/
│   ├── database.py      # API query functions (reuses scripts/shared/database.py)
│   ├── db_rows.py       # TypedDict definitions for raw DB row shapes
│   ├── user_service.py  # User CRUD operations (get_or_create, update, record_visit)
│   ├── user_preferences_service.py  # Enabled-companies CRUD
│   ├── saved_filters_service.py     # Saved-filters + keyword-list CRUD, built-in SWE list, location search
│   ├── admin_service.py # Admin grant/revoke and is_admin check
│   ├── features_service.py  # Feature list and upvote logic
│   ├── features_seed.py # Seed starter features + reconcile shipped (completed_at) status
│   ├── feedback_service.py  # User feedback submission persistence
│   ├── companies_service.py # Curated-companies directory queries
│   ├── companies_seed.py    # Seed/reconcile the companies table from static config
│   ├── enrichment_monitor.py    # Admin enrichment triage queries (needs-human queue, ticks, recent)
│   ├── enrichment_writer.py     # Write-back path for enrichment results and corrections
│   ├── llm_client.py        # Shared Anthropic API client wrapper
│   ├── location_normalization.py  # Tier-1/Tier-2 normalization pipeline entry point
│   ├── location_canonicalize.py   # Claude Haiku prompt + schema for Tier-2 canonicalization
│   ├── location_admin.py          # Admin location alias CRUD and health/integrity queries
│   ├── location_monitor.py        # Location normalization health/integrity monitoring queries
│   ├── posthog_client.py    # Module-level singleton initialized at startup; get_posthog() returns None when token is unset (analytics-off graceful degradation)
│   ├── rate_limit.py        # Per-key async rate limiter (used by ATS clients)
│   ├── scraper_lock.py  # asyncio.Lock singleton shared by runner + auto-scraper
│   ├── scraper_runner.py # Async subprocess runner for scrapers
│   ├── auto_scraper.py  # Background scheduled scraping (Google/Apple/Microsoft)
│   ├── ashby_client.py      # Ashby ATS HTTP client
│   ├── eightfold_client.py  # Eightfold ATS HTTP client (SSRF allowlist lives here)
│   ├── gem_client.py        # Gem ATS HTTP client
│   ├── greenhouse_client.py # Greenhouse ATS HTTP client
│   ├── lever_client.py      # Lever ATS HTTP client
│   ├── workday_client.py    # Workday ATS HTTP client
│   ├── url_guard.py         # SSRF egress guard for user-supplied URLs (add-company flow)
│   ├── ats_detector.py      # Deterministic ATS detection + probe for a submitted careers URL
│   ├── custom_json_client.py # Runtime replay of a stored custom_json scrape recipe (no browser/LLM)
│   ├── recipe_generator.py  # One-time Claude Haiku custom_json recipe generation
│   ├── company_add_service.py # Add-company orchestration (detect → dedup → insert → enable)
│   └── company_submissions.py # company_submissions CRUD + additive per-user enablement
└── tasks/
    ├── procrastinate_app.py         # Procrastinate App instance + schema setup
    ├── heartbeat.py                 # Heartbeat task (liveness probe for /health/worker)
    ├── enqueue_*_fan_out.py (×7)    # Fan-out tasks: per-company fetch for each ATS + custom_json
    ├── fetch_*_company.py (×7)      # Leaf tasks: fetch + upsert one company's jobs (incl. custom_json)
    ├── onboard_custom_company.py    # Async add-company onboarding: Playwright capture → Haiku recipe → validate → create
    ├── normalize_location.py        # Leaf task: normalize one job's free-text location via Claude Haiku
    └── scan_unnormalized.py         # Periodic safety-net task: find NULL-status jobs and defer normalize_location
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
The same CLI also carries an unrelated **group S** (storage/churn): `last_seen_at`
index bloat, HOT/write-amplification counters, and the `job_listings ⟕ job_freshness`
anti-join invariants the `/api/jobs` INNER JOIN depends on — runbook in
**`src/backend/docs/job-listings-bloat.md`**.

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

**Merge-train deploy-skip trap (bit us 2026-08-05):** Railway's watch paths are
configured in the dashboard (not `railway.toml`), and queued deployments are
deduped to the newest commit. Merging a backend PR followed quickly by
non-backend merges (docs/skills/frontend) can leave the backend commit's
deployment SKIPPED — superseded by a newer commit that matches no watch path, so
the *whole* queue skips and prod silently keeps running the old code (observed
with #232 stacked under #235/#238: `alembic_version` stayed at the previous
head). After any merge train, check the newest deployment's status (`railway`
MCP `list_deployments` or the dashboard) and confirm `alembic_version` moved if
migrations were involved; re-trigger with the dashboard's Deploy button or a
commit touching `src/backend/**`.

## Docker

```bash
# Build (from project root)
docker build -f src/backend/Dockerfile -t jobs-api .

# Run
docker run -p 8080:8080 -e DATABASE_URL=postgresql://... jobs-api
```

Single-stage Python 3.13-slim image with Playwright browser dependencies.
