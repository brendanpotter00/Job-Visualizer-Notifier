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
| `SCRAPER_COMPANIES` | Comma-separated company list | `apple,google,microsoft,amazon,tiktok` |
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
| `ENRICHMENT_CUSTOM_SHARE_PCT` | Share of each `/pending` batch reserved for custom (user-added) companies; `0` disables custom claiming | `10` |
| `ENRICHMENT_CUSTOM_PER_COMPANY_CAP` | Per-custom-company eligibility window: only a company's newest N *unclaimed* OPEN rows compete for the custom slice | `500` |
| `POSTHOG_PROJECT_TOKEN` | PostHog analytics API key — if unset, all analytics is disabled (`get_posthog()` returns `None`) | *(optional)* |
| `POSTHOG_HOST` | PostHog ingestion host (US cloud endpoint) | `https://us.i.posthog.com` |
| `FEEDBACK_RATE_LIMIT_MAX` | Max feedback submissions per client IP per window | `5` |
| `FEEDBACK_RATE_LIMIT_WINDOW_SECONDS` | Rate-limit sliding window duration (seconds) | `60` |
| `RESOLVE_RATE_LIMIT_MAX` / `..._WINDOW_SECONDS` | Burst limit on `POST /api/companies/resolve`, per authenticated user | `10` / `60` |
| `USER_COMPANY_ADD_RATE_LIMIT_MAX` / `..._WINDOW_SECONDS` | Burst limit on `POST /api/users/companies`, per authenticated user. In-memory, so it resets on deploy — a burst smoother, not the spend guard | `10` / `60` |
| `USER_COMPANY_RENAME_RATE_LIMIT_MAX` / `..._WINDOW_SECONDS` | Burst limit on `PATCH /api/users/companies/{id}` (the rename), per authenticated user. Its OWN bucket, an order of magnitude looser than the add pair: a rename is one UPDATE — no browser, no outbound request, no LLM — so it charges neither the add burst limiter nor the monthly cap (fixing a typo must not cost one of twenty adds) | `30` / `60` |
| `CUSTOM_COMPANY_MONTHLY_ADD_LIMIT` | **The spend guard.** URLs one user may submit to `POST /api/users/companies` per UTC calendar month (resets on the 1st). Every submission counts — success, refusal, already-published — and deleting a company does **not** refund a slot. Counted off the append-only `company_add_attempts` audit (`services/add_quota.py`), which is what makes "no refund" real. **The number is the number of adds allowed — `0` allows NONE** (a per-user kill switch; it is not an "unlimited" sentinel, and it boots with a WARNING). **Fail-closed both ways**: a typo'd env var NAME is dropped by `extra="ignore"` and this 20 stands, and a typo'd VALUE landing on `0` blocks adds instead of granting unbounded spend. Local dev uses a large number (10000), never 0. **Admins are exempt** — the cap never refuses a caller with a row in `admins` (the same grant `require_admin` reads), their adds are still recorded, the 10/60s burst limiter still applies, and `GET /api/users/companies` omits the `quota` block so the counter agrees with what is enforced. The lookup fails CLOSED: an error means "not an admin" and the cap applies | `20` |
| `COMPANY_NAME_SEARCH_ENABLED` | Accept a typed company **name** in the add box, not only a URL. Off (default) → `POST /api/companies/search-by-name` returns **503** and the box stays URL-only. On → one Browserbase **Search** call per attempt (~$0.007; the plan includes 1,000 free), then free deterministic scoring of all 25 results via `resolve_ats_url` — no model call, no browser. Needs `BROWSERBASE_API_KEY`. **Independent of `CAPTURE_USE_BROWSERBASE`**: that buys Browsers for discovery, this buys the Search API — different products, separately priced. Pair with the build-time `VITE_COMPANY_NAME_SEARCH_ENABLED`, backend first | `false` |
| `BROWSERBASE_API_KEY` / `BROWSERBASE_PROJECT_ID` | Browserbase credentials. Read by discovery's optional hosted-browser path (`CAPTURE_USE_BROWSERBASE`) and by name search (`COMPANY_NAME_SEARCH_ENABLED`, which needs only the key) | *(optional)* |
| `DEV_RESET_ENABLED` | **LOCAL DEVELOPMENT ONLY. Never set this in Railway.** Registers `GET/POST /api/users/dev-reset` (`routers/dev_reset.py`), which deletes every `visibility='user'` company the caller owns and everything it owns — jobs, freshness/location/tag/enrichment sidecars, `company_scripts`, `company_harvests`, `scrape_runs`, `user_companies`, and the `company_add_attempts` audit (so the 20/month quota is refunded too). It exists because the add flow is only testable once per board: after the first add the endpoint answers "you already track this". **Off means the router is NOT registered** — the path 404s like one that was never written, rather than 403ing and advertising itself. **The flag is not the real guard**: the endpoint independently re-derives at call time that `DATABASE_URL` parses to a **loopback** host (`services/dev_reset.assert_local_database` — parsed with libpq's own `parse_dsn`, not substring-matched and not `urlsplit` alone, because a DSN's `?host=`/`?hostaddr=` parameter overrides the URL authority and would otherwise read as "localhost" while connecting to production; fail-closed on anything unparseable) **and** asks the live connection where it actually is (`assert_local_connection` — `conn.info.host` plus `SELECT inet_server_addr()`), 403ing otherwise, so setting this on the wrong machine still deletes nothing. It is also **never proxied** — absent from every `PROXIED_ROUTES` in `api/*.ts` and pinned in `NOT_PROXIED` by `api/tests/test_proxy_path_allowlists.py`, so the QA page calls the backend origin directly. Scoped to the caller by default (`?scope=mine`); **`?scope=all` clears every user's and requires an `admins` grant** (two of its DELETEs have no WHERE clause). CLI equivalent: `scripts/one_off/dev_reset_custom_companies.py` | `false` |

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
  never assumed-UTC. **Inclusive**: `first_seen_at >= since`. No server default; which window
  the Recent page opens on is the frontend's business.
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
  non-deterministically. The UI no longer sorts at all — it renders the rows in the order
  this endpoint returns them (`selectRecentJobsSorted` was deleted with the client-side
  walk), so this ORDER BY *is* the Recent page's ordering, not a mirror of one.
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

**Saved Filters Router (`/api/users/saved-filters`):** all routes require a Bearer token.
- `GET /api/users/saved-filters` - Scalar saved filters (per-page time windows, shared locations, active keyword-list pointers); never 404s — returns server defaults (`recent=all`, `trend=90d`, no locations) when the user has no row
- `PUT /api/users/saved-filters` - Full-replace (upsert) the scalar saved filters; 409 if an active keyword-list pointer is unknown or not owned
- `GET /api/users/saved-filters/keyword-lists` - List the user's named keyword lists by position, with the read-only built-in "Software Engineering" list (`builtin-swe`) synthesized last
- `POST /api/users/saved-filters/keyword-lists` - Create a keyword list (201); 409 on duplicate/reserved name, 422 at the per-user list cap
- `PATCH /api/users/saved-filters/keyword-lists/{list_id}` - Rename / replace tags / reorder (partial); 404 if not owned, 409 on name collision, 422 on the built-in id
- `DELETE /api/users/saved-filters/keyword-lists/{list_id}` - Delete a list (204; NULLs any active pointer referencing it); 404 if not owned, 422 on the built-in id
- `GET /api/users/saved-filters/locations/search` - Substring autocomplete over canonical location names (params: `q`, `limit`, `openOnly`)

**Jobs facets:** `GET /api/jobs/facets` - enrichment dropdown catalog (categories + levels with labels/order/parent) from the seeded dimensions.

**Jobs Search Router (`/api/jobs/search`)** — the Recent Jobs page's read path. Where
`GET /api/jobs` is a windowed dump the client filters, this applies the user's whole
filter set in SQL and pages the *result*. Router `routers/jobs_search.py`, SQL
`services/job_search.py`.

- **Params:** `status` (default `OPEN`, unlike `/api/jobs` which has none), `since`
  (inclusive, tz-aware ISO), `cursor`, `limit` (default 100, max 500), plus six
  **repeatable** multi-value filters: `category`, `level`, `company`, `location`,
  `include`, `exclude`. Repeated (`?category=a&category=b`) rather than CSV because
  canonical location names and keywords legitimately contain commas.
- **Response is an ENVELOPE**, not a bare array: `{jobs, nextCursor, meta}`.
  `nextCursor` present iff the page came back full; **its absence is the only
  end-of-walk signal**. In the body deliberately — `/api/jobs` uses `X-Next-Cursor`
  only because it could not break an existing body contract, and that header needs
  all three delivery hops wired or it vanishes silently. `meta`
  (`filteredTotal`, `countLast24h`, `countLast3h`) rides page 1 only. `filteredTotal`
  honours the whole filter set; the two recency counts are scoped to the caller's
  `company` list and to **nothing else** — they deliberately ignore `category`,
  `level`, `include`/`exclude`, `location`, `since` and `status`, because "Past 24
  Hours" answers "how busy are the boards I follow", not "how many rows match my
  current chips". Dropping the company scope would inflate them ~40x for a reader
  following 3 of 133 boards; adding any other dimension would change what the tile
  means while it still looks like the same number.
- **Cursors are filter-bound.** A search cursor embeds an 8-hex fingerprint of the
  filter set (`compute_filter_fingerprint` in `pagination.py`); replaying one under
  different filters is a **409**, not a silently-incoherent walk. `limit` is excluded
  from the fingerprint, so changing page size mid-walk stays legal — but `since` is
  included, so **a client must freeze its window bound and replay it verbatim**.
- **409 vs 422 on `cursor` is a contract, not a detail.** `409` = the token decoded
  perfectly but names a different query (fingerprint moved, or `_SEARCH_CURSOR_VERSION`
  did) — the fix is mechanical and belongs to the CLIENT: drop the cursor, re-request
  page 1. `422` = the token is malformed and nothing downstream can repair it. The
  frontend needs the split: it renders 400/422 `detail` to the reader verbatim, and
  "restart the walk from page 1" is not a sentence a reader can act on — while its
  next-page Retry replays the same rejected cursor. `useRecentJobsSearch` keys its
  restart on the 409 (`STALE_CURSOR_STATUS`). Raised as `StaleCursorError`, a subclass
  of `InvalidCursorError` so `/api/jobs` (no fingerprint, never raises it) is unchanged.
- **Filter semantics** are a port of the frontend matcher this replaced. Dimensions
  AND, values within a dimension OR. An active `category`/`level` filter **hides
  unenriched (NULL) rows** — ~65% of OPEN rows. `entry` expands to
  `{entry, new_grad}`. Keyword terms match title / raw location / company / tags —
  the same haystack `matchesSearchTags` builds on the client. `department` is NOT
  searched: E7 Phase 3 (#248) deleted the field from the frontend model, so
  matching the `experience_level` column it used to map to would make the endpoint
  WIDER than the page it replaces. `team` is not searched
  because no transformer ever populates it — there is nothing to match.
  Locations resolve hierarchically against the `locations` catalog, including the
  synthesized `United States` and `<State>, US` options that have no catalog row.
- **Index:** `idx_job_listings_open_category_keyset` on
  `(enrichment_category, first_seen_at, source_id, id)` partial `WHERE status='OPEN'`
  (migration `4b5d40dbc774`) — equality column leading, sort tuple trailing, so a
  category filter is an ordered seek instead of a scan that discards ~99% of the
  corpus. Four columns, not five: wedging `enrichment_level` in would order entries
  by level within a category and destroy the ordering for the common category-only
  query.
- **Keyword index:** `idx_job_tags_tag_trgm`, a **GIN trigram** index on
  `job_tags(tag)` plus `CREATE EXTENSION pg_trgm` (migration `536c1cddcd28`).
  `_KEYWORD_PREDICATE` matches `t.tag ILIKE '%term%'`, and a LEADING wildcard is
  unservable by the plain btree `idx_job_tags_tag` — so before this, every keyword
  term cost one FULL scan of `job_tags`, **LIMIT-independent** (the planner
  de-correlates the `EXISTS` into a hashed `SubPlan` run once), and **page 1 pays
  it twice** (the page query and `filtered_total`). Measured at prod scale, the
  6-term built-in list goes 617 ms → 209 ms of DB time and a 20-term set
  1807 ms → 442 ms; the `job_tags` share drops ~25x (~43 ms → ~1.5 ms per term).
  **Blind spot to know about:** a term under THREE characters has no complete
  trigram, so `go`/`ai`/`ml` still get the `Seq Scan` (~110 ms each). The index is
  mirrored in `db_models.py` with a `before_create` hook that installs the
  extension, because `create_all` would otherwise fail on `gin_trgm_ops`.
  `downgrade()` drops the index but NOT the extension — an extension is
  database-global and a `DROP … CASCADE` could take unrelated objects with it.

**Internal Enrichment Router (`/api/internal/enrichment`, X-Internal-Key):** `GET /pending` (claim batch; title-priority order — entry-level/intern, then software-engineering, then everything else, newest `first_seen_at` within each tier; the batch is **split** — `ENRICHMENT_CUSTOM_SHARE_PCT` of it is reserved for custom companies, dealt round-robin across them, and each slice absorbs the other's unused budget so the reservation never idles the enricher), `POST /results` (idempotent write-back; returns `written`/`failed[]`(+`source_id`)/`warnings[]`), `GET /sample`, `GET /health`, `POST /metrics` (per-tick push → `enrichment_ticks`, idempotent on `tick_uuid`), `GET /corrections` (human-correction feed for the enricher's golden-merge).

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
- `GET /health/worker` - Procrastinate worker liveness probe; checks `procrastinate_events` freshness, combined `worker_heartbeats` freshness, **and each lane's own heartbeat freshness** (`lanes` + `stale_lanes` in the payload name which worker is dead); returns 200 OK or 503; used as Railway's `healthcheckPath`

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
│   ├── scraper_health.py    # Stale-scraper report query (used by GET /api/jobs-qa/scraper-health)
│   ├── auto_scraper.py  # Background scheduled scraping (Google/Apple/Microsoft/Amazon/TikTok)
│   ├── db_watchdog.py   # Daemon thread probing the DB; exits process after ~5-6 min unreachability so Railway restarts
│   ├── ashby_client.py      # Ashby ATS HTTP client
│   ├── eightfold_client.py  # Eightfold ATS HTTP client (SSRF allowlist lives here)
│   ├── gem_client.py        # Gem ATS HTTP client
│   ├── greenhouse_client.py # Greenhouse ATS HTTP client
│   ├── lever_client.py      # Lever ATS HTTP client
│   └── workday_client.py    # Workday ATS HTTP client
└── tasks/
    ├── procrastinate_app.py         # Procrastinate App instance (explicit pool sizing — two workers each pin a LISTEN connection) + schema setup + CUSTOM_ATS_FIRST_FETCH_QUEUE
    ├── heartbeat.py                 # Per-lane heartbeat tasks (bulk + interactive) backing /health/worker
    ├── enqueue_*_fan_out.py (×6)    # Fan-out tasks: enqueue per-company fetch for each ATS
    ├── fetch_*_company.py (×6)      # Leaf tasks: fetch + upsert one company's jobs
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
- **Background workers**: Three tasks run in the FastAPI lifespan context — **two Procrastinate workers on disjoint queue sets**, plus the auto-scraper:
  1. **Bulk Procrastinate worker** (`_BULK_QUEUES` in `main.py`, concurrency 5) — the six public ATS fan-outs + per-company fetches, the `*/15` custom-company claim tick and the recurring custom re-harvests it defers (`custom_ats_fetch`, one per board per `companies.cadence_hours` — **1 h**, matching the `*/30` public crons as closely as the INTEGER column allows; it was 24 h while a harvest still meant a browser session), `heartbeat`, `normalize`. Scheduled, unattended, tens of thousands of jobs.
  2. **Interactive Procrastinate worker** (`_INTERACTIVE_QUEUES`, concurrency 2) — a **reserved lane** for work a human is watching a spinner for: `custom_discovery` (a pasted URL + its five-step checklist), `custom_ats_first_fetch` (the add-time first harvest, which closes the checklist's last step), and `interactive_heartbeat`. It exists because these used to share one worker with the bulk queues, so a fan-out tick holding all five slots left a user's discovery job sitting in `todo` (2026-08-26). Splitting by queue rather than by `priority` is deliberate — priority only decides who goes next when a slot frees, and the problem was that no slot ever freed.
  - Both are supervised with auto-restart, and both pass **`install_signal_handlers=False`**. This is load-bearing: Procrastinate's default installs `loop.add_signal_handler(SIGTERM, worker.stop)`, which clobbers the `signal.signal(SIGTERM, server.handle_exit)` uvicorn set in `Server.capture_signals()`. One SIGTERM then stops only the worker — `run_worker_async` returns *normally*, so nothing is logged — and uvicorn keeps serving with no worker while still holding the port. That is exactly what happened on 2026-08-26 (14h of no jobs drained; the operator's replacement uvicorn died on "address already in use"). A normal return from `run_worker_async` is now logged as an error and restarted, never returned from.
  - **Observability:** each lane has its own heartbeat queue, so `worker_heartbeats.lane` tells you *which* worker died and `/health/worker` 503s on either lane going stale. A single undifferentiated heartbeat would let one dead lane hide behind the survivor's ticks.
  3. **Auto-scraper loop** (`services/auto_scraper.py`) — asyncio task that periodically spawns subprocesses for the script-ats scrapers (Google, Apple, Microsoft, Amazon, TikTok).
- **Scraper subprocess**: Runs `scripts/run_scraper.py` via `asyncio.create_subprocess_exec`
- **Job lifecycle (first seen → missed → closed → reopened)**: every `fetch_*_company.py` leaf task writes through `scripts/shared/database.py`, so the lifecycle rules are shared with the script scrapers and documented once in **`scripts/CLAUDE.md` § Job Lifecycle**. Read it before assuming anything about `first_seen_at`, `closed_on` or `consecutive_misses` — in particular, `first_seen_at` is stamped once at INSERT and is **never** updated when a closed job reopens, which is what makes it a safe keyset sort key (`api/pagination.py`). **What it now holds is the effective posted date, not "when we first saw it"** — seeded at INSERT from the board's own posting date when the board publishes a real one, from first sight otherwise; `created_at` is the true insert time and `posted_on` the raw board value. A board that publishes a bucket (`"Posted 30+ Days Ago"`) has published no date, and we never synthesise one.
- **Two liveness watchdogs, partitioning the failure space** (both daemon threads that `os._exit` so Railway `ON_FAILURE` restarts the container; `/health/worker` is Railway's `healthcheckPath` but gates deploy cutover only and never restarts a live container):
  - **DB watchdog** (`services/db_watchdog.py`, exit 70): probes the DB on fresh connections with hard wall-clock deadlines; exits after ~5-6 sustained minutes of **DB unreachability** (see the 2026-08-10 incident doc).
  - **Worker watchdog** (`services/worker_watchdog.py`, exit 75): reads `MAX(worker_heartbeats.at)` and exits when the worker heartbeat is stale past ~15 min **while the DB is reachable** — i.e. the executor is **wedged** but the DB is fine (the 2026-08-29 incident: `run_worker_async` hung mid-drain after a transient DB blip and never returned; nothing restarted it for 61h). Keys on `worker_heartbeats`, NOT `procrastinate_events`, because the periodic deferrer keeps writing events even with a dead executor. An unreachable DB is inconclusive here and left to the DB watchdog. Tunable via `WORKER_WATCHDOG_*` env vars; disabled under pytest by a conftest fixture.
    ⚠️ **It reads `MAX(at)` across ALL lanes, so it restarts on BOTH lanes dying, not one.**
    A single dead lane keeps `MAX(at)` fresh from its survivor and this watchdog stays
    quiet — `/health/worker` still 503s on it (that probe is per-lane), but nothing
    auto-restarts. Making the restart per-lane means grouping by `lane`, which is a
    deliberate follow-up rather than part of the lane split.

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
