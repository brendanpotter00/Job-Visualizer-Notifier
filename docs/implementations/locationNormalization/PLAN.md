# Location Normalization — Implementation Plan

> **Status:** Ready for implementation. This plan was drafted, then revised across a
> human-in-the-loop review session (decisions captured in **Decisions Locked** below).
> A rendered, annotated companion artifact lives next to this file:
> [`location-normalization-plan.html`](./location-normalization-plan.html) — open it in a
> browser for the visual version with worked examples and the original review annotations.
>
> **Handoff note for the implementing agent:** the **Decisions Locked** section captures
> choices a fresh agent is likely to second-guess and re-litigate. Each one has a *why*.
> Do not silently reverse them; if you believe one is wrong, raise it explicitly rather
> than "simplifying" it away.

---

## Business Context

This repository (Job Posting Analytics) visualizes job-posting activity over time across
many companies. Users browse and filter postings; the product's value is letting someone
answer questions like *"who's hiring backend engineers in SF or remote right now?"*

**Location is currently unusable as a filter dimension.** Postings arrive from ATS APIs
(Greenhouse, Ashby, Lever, Gem, Eightfold, Workday) and from custom scrapers
(Google, Apple, Microsoft) as free-text in a single `job_listings.location TEXT` column.
Real production values today (frequencies in parentheses) include:

| raw string | n | problem |
|---|---|---|
| `San Francisco` | 2,059 | bare city |
| `San Francisco, CA` | 662 | same place, different spelling |
| `San Francisco, California` | 302 | same place again |
| `Cupertino, California, United States` | 2,612 | full but verbose |
| `United States, Washington, Redmond` | 1,797 | **reversed** order |
| `US, CA, Santa Clara` | 564 | abbreviated + reversed |
| `Mountain View (US-MTV-EMF680)` | 271 | embedded building code |
| `Costa Mesa, CA (HQ)` | 1,363 | annotation noise |
| `Sunnyvale, CA, USA; Kirkland, WA, USA` | 202 | **two locations in one field** |
| `Remote - United States` | 294 | remote with scope |
| `Remote` | 250 | remote, unscoped |

There is no canonical form, no dedupe, no multi-location support, and no way to answer
"SF-or-remote" without brittle SQL `LIKE` matching that breaks on the long tail. Three
spellings of San Francisco are three unrelated strings today.

**Outcome of this work:** every `job_listings` row is associated with zero or more
*canonical* location rows via a join table. Filtering, grouping, and (later) geo
visualization key off normalized data instead of raw text. The frontend integration and
geo features are explicitly **out of scope** here — this plan delivers the data model and
the pipeline that populates it.

---

## Approach (and why)

A **two-tier cascade**, run asynchronously after each scrape:

1. **Tier 1 — Postgres alias cache** (`location_aliases`), keyed on the pre-normalized raw
   string. After warmup, ~90%+ of incoming locations are cache hits costing zero LLM calls.
2. **Tier 2 — Claude Haiku 4.5** (`claude-haiku-4-5-20251001`), invoked **only on cache
   misses**. Returns structured JSON for one *or more* canonical locations per string. The
   result is written back into the cache so the next occurrence is free.

**Why not a self-hosted local model:** the Railway backend container is memory-constrained
(see the April 2026 pool-pressure + memory incident); local models also degrade on exactly
the long-tail strings the cache can't short-circuit. Haiku at ~$0.0003/call against
~50–200 novel strings/day is well under $10/month fully amortized.

**Why not a regex/rules Tier 2:** every rule is a hard-coded special case; partial matches
break on cases like `south san francisco`; multi-location parsing collapses into ad-hoc
parser territory. Cache + LLM is the smallest design that handles every case above.

---

## Decisions Locked

These were settled during the review session. **Each has a rationale specifically so a
later agent does not undo it.**

1. **Reuse the existing Procrastinate infrastructure — do NOT "bootstrap" it.**
   Procrastinate already exists: `procrastinate>=2.0.0` in `requirements.txt`, the App
   singleton in `src/backend/api/tasks/procrastinate_app.py`, a worker started in the
   FastAPI lifespan, six per-ATS fan-out queues, and it manages its own schema. The
   normalize task is just a new `@procrastinate_app.task` on a new `normalize` queue.

2. **`normalize` rides the shared worker pool with NO concurrency cap.**
   An earlier draft proposed a dedicated `concurrency=2` worker to "protect" ATS fetches.
   **Rejected** — that is anti-scale and not worker-agnostic (if the deployment scales to
   N workers, normalization should use all N and drain a backlog fast). Add `"normalize"`
   to `_WORKER_QUEUES` (`main.py:45`) and let it scale with the pool. Normalization tasks
   are independent (one `job_id` each, order doesn't matter), so they parallelize freely.

3. **Never hold a DB connection across the Haiku call. (Load-bearing — do not "simplify"
   into a single transaction.)**
   Structure each task as: **tx1** = read `job_listings` row + Tier-1 lookup, then
   *release the connection* → **LLM call with no connection open** → **tx2** = write the
   results. *Why this is non-negotiable:* the `2026-05-17` pool-exhaustion incident was
   caused by connections held for the full duration of slow work. A 10s LLM hold on an
   open connection is exactly that anti-pattern. With this discipline, 500 in-flight
   normalize tasks ≠ 500 open connections — connection count tracks brief write-moments,
   not task lifetime, which is what makes Decision #2 (uncapped concurrency) safe. A
   Tier-1 hit skips the LLM and may write in a single short transaction.

4. **Enqueue strategy: chain in the ATS fetch tasks (A1) + safety-net for the subprocess
   scrapers (B1). Do NOT migrate the web scrapers first.**
   The 6 ATS providers already flow through `fetch_<p>_company` → `upsert_jobs_batch`;
   chain `normalize_location.defer_async` there. Google/Apple/Microsoft run on the old
   `auto_scraper.py` subprocess loop (Playwright `--headless`); they're covered by the
   safety-net periodic task. *Why not migrate the scrapers to Procrastinate first:* it's a
   real, separate project (you don't want Playwright browsers inside the in-process
   worker's event loop — memory), normalization works fine without it, and the
   `defer_async` hook is identical regardless of which task calls it, so this plan is
   already forward-compatible. Tracked as its own initiative.

5. **Multi-location is a join table, never a field on `job_listings`.**
   `job_listings` gains exactly **one** new column: `normalization_status`. It is *not*
   given a location list/array/CSV. A job with two locations produces **two**
   `job_locations` rows (each a FK to a canonical `locations` row). This is standard 3NF;
   "how many locations does this job have?" is `COUNT(*)` on `job_locations`. The raw
   `location` string is kept untouched for provenance.

6. **`remote_scope` is part of the `locations` UNIQUE key — intentional.**
   `Remote (US)`, `Remote (EU)`, and `Remote (Global)` are *distinct* canonical locations
   (they filter differently). Removing `remote_scope` from the uniqueness key would
   collapse them into one row. Don't "clean that up."

7. **lat/lng: keep the nullable columns, leave them NULL in v1, and do NOT ask Haiku for
   coordinates.** Coordinates are the thing LLMs hallucinate most. A real geocoding pass
   over `canonical_name` (Nominatim/Mapbox) is deferred to the geo follow-up. The columns
   exist so consumers can be built incrementally; the v1 prompt explicitly omits coords.

8. **Admin endpoints reuse `require_admin` and extend the existing `routers/admin.py`.**
   An admin-role system already exists (`admins` table, `require_admin` dependency at
   `auth/dependencies.py:62`, `is_admin_by_email`). Do **not** hard-code an admin email.
   The `require_internal_key` middleware already gates the whole app, so these endpoints
   sit behind both infra and admin auth automatically.

9. **Confidence floor is adopted.** The Haiku prompt returns a per-location `confidence`;
   below a threshold, set `normalization_status='failed'` instead of caching a low-trust
   guess. This is the cheapest defense against cache poisoning.

10. **Bulk `re-normalize-all` is a break-glass tool; targeted correction is primary.**
    Keep a gated, throttled `re-normalize-all` admin endpoint, but expect it to be rarely
    used. The day-to-day correction path is a `source='manual'` alias override (one admin
    endpoint) plus, as a follow-up, a Claude location-audit skill that queries prod for
    suspect rows and fixes them via the admin endpoints.

11. **The safety-net is a Procrastinate periodic task, not a separate Railway cron
    service.** The periodic-task machinery already exists (the `enqueue_<p>_fan_out` tasks
    use it); mirror that rather than standing up a new Railway cron service.

---

## Repo Constraints (must follow)

- **Bare table names — no `_{env}` suffix.** Test isolation is per-worker Postgres schema
  via `PYTEST_SCHEMA` + `search_path` (see `docs/implementations/envAgnosticTables/`), not
  table suffixes.
- **Alembic autogenerate only.** Edit `src/backend/api/db_models.py`, run
  `alembic revision --autogenerate -m "..."`, then review. **Never hand-write a revision
  file.** Baseline revision is `91337142414f`.
- **Combined ALTER TABLE / catalog-only DDL.** Per the `2026-04-18` Postgres-volume-fill
  incident, all DDL must avoid full-table rewrites: `ADD COLUMN` nullable with no default
  backfill, `RENAME`, `CREATE TABLE`. No `USING` clauses, no rewriting `NOT NULL` adds. See
  `docs/implementations/alembicMigration/DEPLOY.md`.
- **Autogen will show Procrastinate's runtime tables as phantom "removed."** Strip
  `procrastinate_jobs` / `procrastinate_events` / `procrastinate_periodic_defers` from the
  generated `upgrade()`/`downgrade()` (precedent: the `20260519` and `20260521` revisions).
- **Connection style.** Backend code uses `psycopg2.pool.ThreadedConnectionPool` +
  `RealDictCursor` (request path) or a standalone per-task psycopg2 connection (worker
  tasks). Not SQLAlchemy sessions. New worker code mirrors the existing `fetch_*` tasks.
- **`apply_alembic_migrations(database_url)`** runs on FastAPI startup — schema migrations
  apply themselves on deploy.
- **Coverage > 80%** (per the root `CLAUDE.md`).

---

## Architecture

```
   6 ATS providers (EXISTING, Procrastinate)        Google/Apple/Microsoft (EXISTING)
   enqueue_<p>_fan_out  (periodic)                  auto_scraper.py  (while-True loop)
        │  defer per company                              │  spawns subprocess
        ▼                                                 ▼
   fetch_<p>_company  ──►  db.upsert_jobs_batch     run_scraper.py --headless (Playwright)
        │  (NEW) for each inserted id:                    │  writes to DB directly
        │  normalize_location.defer_async(job_id)         │  (no in-process defer hook)
        ▼                                                 ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │  procrastinate_jobs  (EXISTING table)  —  NEW queue: normalize          │
   │  drained by the EXISTING worker pool (scales with it; no cap)           │
   └──────────────────────────────────────────────────────────────────────┘
        │                                                 ▲
        ▼                                                 │ (NEW) safety-net periodic task
   normalize_location(job_id):                            │ scan_unnormalized:
     tx1: SELECT location, status; if done → return       │   SELECT id WHERE
          Tier 1: alias-cache lookup; HIT → write → done   │   normalization_status IS NULL
     (release connection)                                  │   LIMIT n → defer each
     Tier 2: await Haiku → list[CanonicalLocation]         │   (covers the subprocess
     tx2: UPSERT locations / aliases / job_locations;      │    scrapers + LLM-failure tail
          set normalization_status='done'                  │    + pre-existing rows)
```

The worker, fan-out tasks, and `fetch_*` tasks **already exist** in
`src/backend/api/tasks/`. This feature adds the `normalize` queue, the `normalize_location`
task, the `scan_unnormalized` periodic task, the enqueue chaining, the two service modules,
and the admin endpoints.

---

## Schema

Four new tables in `src/backend/api/db_models.py`, plus one additive column on `JobListing`.

```python
class Location(Base):
    __tablename__ = "locations"
    id              = Column(Integer, primary_key=True)
    canonical_name  = Column(Text, nullable=False)        # "San Francisco, CA, US"
    kind            = Column(Text, nullable=False)        # 'city'|'region'|'country'|'remote'
    city            = Column(Text, nullable=True)
    region          = Column(Text, nullable=True)
    country         = Column(Text, nullable=True)
    remote_scope    = Column(Text, nullable=True)         # NULL|'global'|'us'|'eu'|...
    lat             = Column(Float, nullable=True)        # NULL in v1 (Decision #7)
    lng             = Column(Float, nullable=True)        # NULL in v1
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__  = (
        UniqueConstraint("kind", "city", "region", "country", "remote_scope",
                         name="uq_locations_canonical"),   # remote_scope intentional (Decision #6)
    )

class LocationAlias(Base):
    __tablename__ = "location_aliases"
    raw_text     = Column(Text, primary_key=True)         # pre-normalized cache key
    source       = Column(Text, nullable=False)           # 'llm'|'manual'  (manual wins; Decision #10)
    confidence   = Column(Float, nullable=True)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

class AliasLocation(Base):                                # join: one alias → 1..N locations, ordered
    __tablename__ = "alias_locations"
    raw_text               = Column(Text, ForeignKey("location_aliases.raw_text",
                                     ondelete="CASCADE"), primary_key=True)
    normalized_location_id = Column(Integer, ForeignKey("locations.id"), primary_key=True)
    position               = Column(Integer, nullable=False)   # order within the raw string

class JobLocation(Base):                                  # join: job ↔ canonical location (Decision #5)
    __tablename__ = "job_locations"
    job_listing_id         = Column(Text, ForeignKey("job_listings.id",
                                     ondelete="CASCADE"), primary_key=True)
    normalized_location_id = Column(Integer, ForeignKey("locations.id"), primary_key=True)
    is_primary             = Column(Boolean, default=False, nullable=False)
```

Additive column on `JobListing`:

```python
normalization_status = Column(Text, nullable=True)   # NULL|'pending'|'done'|'failed'
```

`normalization_status IS NULL` means "never attempted" — the queryable signal the
safety-net task uses. **`locations` starts empty and is populated lazily** by Tier-2 cache
misses (`ON CONFLICT DO NOTHING` dedupes); no seed/backfill is required.

**Field semantics (`kind` vs the parts):** `kind` is the discriminator that tells you which
structured fields are meaningful; `city`/`region`/`country` are the parts.

| kind | city | region | country | remote_scope |
|---|---|---|---|---|
| city | San Francisco | CA | US | — |
| region | — | CA | US | — |
| country | — | — | US | — |
| remote | — | — | — | us |

---

## Worked Examples (real prod strings)

**A — three spellings → one canonical row (the dedup win).** `San Francisco`,
`San Francisco, CA`, `San Francisco, California` all normalize to the same `locations` row.

- `locations`: 1 row — `(1, "San Francisco, CA, US", city, San Francisco, CA, US)`
- `location_aliases`: 3 rows — `san francisco`, `san francisco, ca`, `san francisco, california` (all `source='llm'`)
- `alias_locations`: 3 rows — each alias → location `1`, `position=0`
- `job_locations`: one row per job, all → location `1`. The 2nd and 3rd spellings were
  cache hits (zero LLM calls); the `UNIQUE` constraint short-circuited the `locations` insert.

**B — multi-location → two rows + `position`.** `Sunnyvale, CA, USA; Kirkland, WA, USA`:

- `job_listings`: **one** row; raw `location` unchanged; only `normalization_status='done'` is new.
- `locations`: 2 rows — `(2, Sunnyvale, CA, US)`, `(3, Kirkland, WA, US)`
- `alias_locations`: 2 rows — alias → `2` (`position=0`), alias → `3` (`position=1`)
- `job_locations`: 2 rows for the one job — `(job, 2, is_primary=true)`, `(job, 3, is_primary=false)`

**C — remote with scope.** `Remote - United States` → `(4, "Remote (US)", remote, remote_scope=us)`;
bare `Remote` → `(5, "Remote (Global)", remote, remote_scope=global)`. Distinct rows by design.

**D — messy → clean** (LLM handles, cache forever after):
`United States, Washington, Redmond` → `Redmond, WA, US`;
`Mountain View (US-MTV-EMF680)` → `Mountain View, CA, US`;
`Costa Mesa, CA (HQ)` → `Costa Mesa, CA, US`.

---

## Units of Work

Each unit is small, individually mergeable, individually verifiable. Order matters.

### Unit 1 — Wire the `normalize` queue + Anthropic config
**Status:** DONE
**Why first:** trivial plumbing the rest depends on. Procrastinate itself is already wired
(Decision #1).
- Add `"normalize"` to `_WORKER_QUEUES` in `src/backend/api/main.py:45` (the existing
  worker drains it alongside the fetch queues; no separate/capped worker — Decision #2).
- Add `anthropic` to `src/backend/api/requirements.txt`.
- Add `anthropic_api_key: SecretStr | None` to `src/backend/api/config.py`.
**Verify:** worker boots with `normalize` in the startup queue log.

### Unit 2 — Schema migration (additive)
**Status:** DONE (migration `c876c313e55c`, down_revision `c4f0a2d8b9e1`)
- Add the 4 tables + `normalization_status` to `db_models.py` exactly as in **Schema**.
- `alembic revision --autogenerate -m "add location normalization tables"`; review per the
  combined-ALTER-TABLE rule (nullable add, no `job_listings` rewrite); strip Procrastinate's
  phantom runtime-table drops from the generated migration.
**Verify:** `alembic upgrade head` + `downgrade -1` round-trips; new
`src/backend/api/tests/test_migration_locations.py` mirrors `test_migration_features.py`;
backend startup still succeeds.

### Unit 3 — Tier 1: alias-cache lookup
**Status:** DONE
- New `src/backend/api/services/location_normalization.py`:
  - `normalize_string(raw) -> str` — pure: lowercase, trim, collapse whitespace, normalize
    unicode dashes/quotes.
  - `lookup_alias(conn, raw) -> list[int] | None` — pre-normalize, then
    `SELECT normalized_location_id FROM alias_locations JOIN location_aliases USING (raw_text)
    WHERE raw_text=%s ORDER BY position`. `None` on miss, ordered `list[int]` on hit.
**Verify:** unit tests with seeded aliases — single hit, multi-location hit, miss→None,
normalization edge cases.

### Unit 4 — Tier 2: Claude Haiku client
**Status:** DONE
- New `src/backend/api/services/llm_client.py`:
  - `async def normalize_location_via_llm(raw) -> list[CanonicalLocation]` (Pydantic model:
    `canonical_name, kind, city, region, country, remote_scope, confidence`). **No lat/lng**
    (Decision #7).
  - `anthropic.AsyncAnthropic` + `claude-haiku-4-5-20251001`, structured/JSON output, 10s
    timeout. Let Procrastinate handle retries (no tenacity).
  - Prompt in-module: short system prompt + 2–3 few-shot examples (single, multi-location,
    remote-with-scope). The prompt returns a per-location `confidence` (Decision #9).
**Verify:** mocked client — single, multi, malformed JSON (raises), API error (raises so
Procrastinate retries).

### Unit 5 — `normalize_location` task (the glue)
**Status:** DONE
**Depends on Units 1–4.**
- New `src/backend/api/tasks/normalize_location.py`:
  ```python
  @procrastinate_app.task(queue="normalize",
                          retry=RetryStrategy(max_attempts=5, exponential_wait=2))
  async def normalize_location(job_id: str) -> None: ...
  ```
  Structure (**Decision #3 — do not collapse into one transaction**):
  1. **tx1:** `SELECT location, normalization_status FROM job_listings WHERE id=%s`.
     Short-circuit if `status='done'`. If `location` is NULL/empty → `status='failed'`
     reason `no-location`, return. Run Tier-1 `lookup_alias`; on hit, write `job_locations`,
     set `status='done'`, return. **Release the connection.**
  2. `await normalize_location_via_llm(location)` with **no connection open**.
  3. If max confidence < floor → `status='failed'` (don't cache the guess).
  4. **tx2:** UPSERT each `CanonicalLocation` into `locations`
     (`ON CONFLICT (kind,city,region,country,remote_scope) DO NOTHING RETURNING id`);
     INSERT `location_aliases` (`source='llm'`, avg confidence); INSERT `alias_locations`
     (one per canonical, with `position`); INSERT `job_locations` (first `is_primary=true`);
     `UPDATE job_listings SET normalization_status='done'`. Use `ON CONFLICT DO NOTHING`
     so concurrent workers normalizing the same raw string don't deadlock.
- Mirror the existing `fetch_*` tasks' standalone-connection + `asyncio.to_thread(db.…)` pattern.
**Verify:** integration test (real Postgres + mocked LLM): `location='sf'` → 1 `job_locations`
row + alias + `status='done'`; re-run = cache hit (LLM **not** called); multi-location → 2
rows; LLM raises → ends `failed`/retried, job stays unnormalized for the safety-net.

### Unit 6 — Enqueue after scrape (ATS path = A1)
**Status:** DONE (reused `seen_ids - pre_upsert_active`; `upsert_jobs_batch` unchanged)
- Extend `scripts/shared/database.py::upsert_jobs_batch` (currently returns `int`, line ~421)
  to also return inserted IDs: `execute_values(..., fetch=True)` with
  `RETURNING id, (xmax = 0) AS inserted` (generalize the `(xmax = 0) AS inserted` trick
  already in `upsert_job`), collect the inserted ids. Keep the count return or add a sibling
  function — update callers + `scripts/tests/integration/test_database.py` accordingly.
- In each `fetch_<p>_company` task, after upsert, for each new id:
  `await normalize_location.configure(queue="normalize").defer_async(job_id=id)`.
  (`fetch_eightfold_company` already computes `seen_ids - pre_upsert_active` — same idea,
  generalized.)
- **Subprocess scrapers (Google/Apple/Microsoft) are NOT changed here** — they're covered by
  Unit 7 (Decision #4).
**Verify:** run a fan-out fetch on a non-empty company; `SELECT count(*) FROM procrastinate_jobs
WHERE queue_name='normalize'` matches the new-job count; all drain to `done`.

### Unit 7 — Safety-net periodic task: scan unnormalized
**Status:** DONE (skip-when-no-key for auto-recovery; `*/5` cron, SCAN_LIMIT=100)
- New `src/backend/api/tasks/scan_unnormalized.py`, registered as a **Procrastinate periodic
  task** (mirror the `enqueue_<p>_fan_out` periodic pattern — Decision #11):
  `SELECT id FROM job_listings WHERE normalization_status IS NULL LIMIT %s` → defer
  `normalize_location` per id → return count. Throttle the limit so a backfill can't fan
  thousands of Haiku calls at once.
- Catches the subprocess-scraper jobs, the LLM-failure tail, and pre-existing rows.
**Verify:** seed 5 rows with `normalization_status IS NULL`, run `scan_unnormalized(limit=10)`,
assert 5 deferred + count returned.

### Unit 8 — Admin endpoints
**Status:** DONE
- Add to the **existing** `src/backend/api/routers/admin.py` (don't create it), each gated by
  `_admin: TokenClaims = Depends(require_admin)` like the existing grant/revoke endpoints:
  - `POST /api/admin/jobs/{job_id}/normalize` — reset `normalization_status=NULL` and defer
    `normalize_location` (the audit agent's per-job fix).
  - `PUT /api/admin/locations/aliases/{raw_text}` — **manual override**: upsert a
    `source='manual'` alias → location mapping that wins over the cached `llm` guess
    (the primary correction primitive — Decision #10).
  - `GET /api/admin/locations/aliases?contains=...` — debug/inspect.
  - `POST /api/admin/locations/re-normalize-all` — **break-glass only**: reset all to NULL
    then defer `scan_unnormalized`; gate + throttle (Decision #10).
- Mount is already done (`routers/admin.py` is mounted). The `require_internal_key`
  middleware already gates the whole app, so these sit behind both infra + admin auth.
**Verify:** admin token → 2xx; non-admin → 403; missing internal key → 401; the job's
`normalization_status` cycles to `done` within seconds.

---

## Risks & Failure Modes

**F1 — Connection-hold & worker contention under the 10s LLM call.**
Root cause reference: `docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md` — 49
simultaneous reads each held one of 15 pool slots for the full request; the 5s semaphore
acquire timeout (`dependencies.py:76`) elapsed on ~20 of them. The fix there was
*structural* (batch the fanout); **raising `DB_POOL_MAX` was explicitly the wrong answer**
(Railway's 3 GB ceiling + Playwright memory pressure). Note `normalize` does **not** use the
15-slot request pool — like every `fetch_*` task it opens its own standalone psycopg2
connection. The residual risk (total concurrent connections vs memory) is neutralized by
Decision #3 (don't hold a connection across the LLM call), which keeps connection count
tracking brief write-moments rather than in-flight task count — so normalization can scale
with the whole worker pool without a cap. If ATS fetches ever need shielding from a huge
normalize backlog, use a *separate worker replica* for the `normalize` queue, never a
coroutine cap.

**F2 — Cache poisoning → correction workflow.** A wrong LLM result is cached and reused (no
per-alias invalidation). Mitigations, layered: (a) **confidence floor** → `status='failed'`
instead of caching a guess (Decision #9, adopted in the prompt + client); (b) **manual
override** persists via a `source='manual'` alias that wins over the `llm` one (Unit 8);
(c) **a Claude location-audit skill** (follow-up) that queries prod for suspect canonical
rows (e.g. `kind='country'` where a city was expected, low-confidence aliases, orphans) and
corrects them via the admin endpoints. *Document the correction workflow in ops/DEPLOY docs.*

**F3 — Bulk re-normalize is break-glass.** `re-normalize-all` bypasses the cache and could
fan thousands of Haiku calls; keep it gated + throttled and expect it to be rarely used.
Day-to-day correction is the targeted audit-agent path (F2).

> **Migration heads** (not tracked as a risk here per the plan owner): a new Alembic
> revision off baseline `91337142414f` plus any in-flight migration PR can produce a
> multi-head crash-loop on boot. The plan owner will recompute heads before merging Unit 2.

---

## Out of Scope (separate follow-ups)

- **Frontend integration** — exposing `normalized_locations` in `/api/jobs`, location
  filters/facets, Redux selectors. The schema/API contract here is stable to build against.
- **Geo features + geocoding pass** — distance queries, map clustering; owns populating
  `lat`/`lng` (Decision #7).
- **Backfill of existing rows** — handled over time by the Unit 7 safety-net; or run
  `re-normalize-all` once at deploy if faster backfill is needed.
- **In-memory L1 cache** (`lru_cache` over `lookup_alias`) — premature; add only if
  profiling shows the alias `SELECT` is hot.
- **Claude location-audit skill** — the agent that queries prod and corrects via the admin
  endpoints (F2).
- **Migrating Google/Apple/Microsoft scrapers onto Procrastinate** — its own initiative
  (Decision #4); when it lands, Unit 6 path B collapses into the A1 chain.

---

## End-to-End Verification (after all 8 units)

1. `docker compose up -d postgres`; `alembic upgrade head` applies the new schema.
2. Start the backend; the lifespan boots the worker with `normalize` in its queue list.
3. `POST /api/admin/jobs/<existing-id>/normalize` (admin token). Within ~5s:
   - `SELECT normalization_status FROM job_listings WHERE id=...` → `done`
   - `SELECT * FROM job_locations WHERE job_listing_id=...` → 1+ rows
   - `location_aliases` / `locations` have the new rows
4. Trigger a second job with the same raw string → **no new** `location_aliases` row (cache
   hit), `job_locations` populated.
5. Run an ATS fan-out fetch → `procrastinate_jobs WHERE queue_name='normalize'` matches the
   new-job count; all drain to `done`.
6. `pytest src/backend/api/tests/` green, coverage > 80%.

---

## Critical Files Touched

| File | Change |
|---|---|
| `src/backend/api/requirements.txt` | add `anthropic` (procrastinate already present) |
| `src/backend/api/config.py` | add `anthropic_api_key` |
| `src/backend/api/main.py` | add `"normalize"` to `_WORKER_QUEUES` (line ~45) |
| `src/backend/api/db_models.py` | 4 new tables + `normalization_status` |
| `src/backend/alembic/versions/<new>.py` | autogenerated migration |
| `src/backend/api/services/location_normalization.py` | new — Tier 1 |
| `src/backend/api/services/llm_client.py` | new — Tier 2 Haiku |
| `src/backend/api/tasks/normalize_location.py` | new — the task |
| `src/backend/api/tasks/scan_unnormalized.py` | new — safety-net periodic task |
| `src/backend/api/tasks/fetch_*_company.py` (×6) | chain `normalize_location.defer_async` after upsert |
| `scripts/shared/database.py` | `upsert_jobs_batch` returns new IDs |
| `src/backend/api/routers/admin.py` | add normalize/override/re-normalize endpoints |

## Existing Utilities to Reuse

- **Procrastinate app + task pattern:** `src/backend/api/tasks/procrastinate_app.py`,
  `fetch_*_company.py`, `enqueue_*_fan_out.py` (periodic + `defer_async` + standalone conn).
- **Batch upsert:** `scripts/shared/database.py::upsert_jobs_batch` (line ~421) and the
  `(xmax = 0) AS inserted` trick in `upsert_job` (line ~403).
- **Migration test pattern:** `src/backend/api/tests/test_migration_features.py`.
- **Admin auth:** `require_admin` (`src/backend/api/auth/dependencies.py:62`),
  `is_admin_by_email` (`src/backend/api/services/admin_service.py:33`), existing
  `routers/admin.py`.
- **Settings:** extend `src/backend/api/config.py::Settings` rather than create a parallel module.

---

## Implementation Addendum — Verified Context (2026-06-07)

> Added during the implementation handoff after reading the live codebase + querying
> production (read-only). These are **facts**, not new decisions — honor them; they
> refine the sketch above to match the real repo and prod state.

### Production state (verified read-only via prod Postgres)
- **Current Alembic head = `c4f0a2d8b9e1`** on both disk and prod `alembic_version`. **Single
  head — no multi-head risk at time of writing.** The Unit-2 migration MUST set
  `down_revision = "c4f0a2d8b9e1"` (not the baseline `91337142414f`). Re-check
  `alembic heads` immediately before merging in case another migration PR lands first.
- **`job_listings`**: 44,666 rows; `location TEXT` nullable exists; **`normalization_status`
  does NOT exist yet** → the additive nullable `ADD COLUMN` is safe and won't rewrite the table.
- **None** of `locations` / `location_aliases` / `alias_locations` / `job_locations` exist in
  prod → `CREATE TABLE` is clean.
- **4,040** rows have NULL/empty location (→ `status='failed'` reason `no-location`, never an
  LLM call). **1,438** distinct non-null location strings (the realistic ceiling on cold-cache
  Haiku calls during full backfill — a few dollars total).
- **1 admin** row exists → admin endpoints are end-to-end testable with a real admin token.
- After Unit 2 deploys, **all 44,666 rows have `normalization_status IS NULL`** and the Unit-7
  safety-net begins draining them. **The throttle on `scan_unnormalized(limit=...)` is
  load-bearing** — keep the per-tick limit small (e.g. 50–100) so a 44k backfill cannot fan
  thousands of concurrent Haiku calls or normalize tasks at once.

### Codebase conventions to match (override the sketch where they differ)
- **Use `TIMESTAMP(timezone=True)`, NOT `DateTime`**, for the new `created_at` columns —
  every model in `db_models.py` uses `TIMESTAMP(timezone=True)` + `server_default=func.now()`.
  Add **`Float`** to the `sqlalchemy` import block in `db_models.py` (lat/lng); it is not
  currently imported.
- **Config secret style:** use `anthropic_api_key: str | None = None` (plain `str`, matching
  the existing `internal_api_key: str | None`), **not** `SecretStr`. The Schema sketch's
  `SecretStr` was illustrative; consistency with the existing settings wins.
- Mirror the standalone-psycopg2-connection + `asyncio.to_thread(db.…)` pattern from
  `fetch_greenhouse_company.py` exactly (acquire conn in a thread, `try/finally` close, ERROR
  log on close failure). The Procrastinate app singleton is `procrastinate_app` in
  `tasks/procrastinate_app.py`; periodic tasks use the `@procrastinate_app.periodic(cron=...)`
  + `@procrastinate_app.task(...)` stacked-decorator pattern from `enqueue_greenhouse_fan_out.py`.
- `_WORKER_QUEUES` is the tuple at `src/backend/api/main.py:45` (currently 6 fetch queues +
  `heartbeat`). Add `"normalize"`. A backend test pins this tuple's membership — update that test.

### Schema correctness fix discovered during implementation (2026-06-07)
- **`uq_locations_canonical` is `NULLS NOT DISTINCT`** (amended Unit 2; prod is PostgreSQL 17.9, PG15+).
  Plain `UNIQUE` over the nullable `(kind,city,region,country,remote_scope)` would NOT dedup, because
  Postgres treats NULLs as distinct by default and every `kind` has ≥1 NULL keyed column (city-kind →
  `remote_scope` NULL; remote-kind → city/region/country NULL). Without `NULLS NOT DISTINCT` the dedup
  `ON CONFLICT` never fires and duplicate canonical rows accumulate. Verified via `pg_index.indnullsnotdistinct`
  + a live duplicate-rejection proof. Expressed as `postgresql_nulls_not_distinct=True` on the model + migration.
  **Unit 5 upserts target this constraint** (`ON CONFLICT ON CONSTRAINT uq_locations_canonical`), and any
  SELECT-existing-id fallback MUST use `IS NOT DISTINCT FROM` for the nullable columns.

### NEW load-bearing requirement — graceful degradation when `ANTHROPIC_API_KEY` is unset (FINAL DESIGN: leave-NULL + safety-net skip → auto-recovery)
**The Railway prod env var `ANTHROPIC_API_KEY` is NOT confirmed set** (could not be read).
The feature MUST be safe to deploy *before* the key is configured, and recover automatically
once it is set. Final coherent design:
- **Unit 5 `normalize_location` on missing key →** log a single WARN and **return, leaving
  `normalization_status` NULL** (no DB write, no raise → no retry burn, worker stays green).
- **Unit 7 safety-net `scan_unnormalized` →** at the top, if `settings.anthropic_api_key` is
  falsy, **skip entirely (defer nothing) and return 0**. This is what makes leave-NULL safe:
  the safety-net does NOT re-defer the NULL backlog while the key is absent, so there's no
  stuck-window churn — the backlog simply stays NULL and dormant.
- **Auto-recovery:** once `ANTHROPIC_API_KEY` is added in Railway, the very next safety-net tick
  starts draining the NULL backlog (and Unit-6 scrape-chaining resumes normally). **No manual
  `re-normalize-all` is needed** for the no-key case — `re-normalize-all` remains a break-glass
  tool for cache-poisoning corrections only.
- Tier 1 (alias cache), the schema migration, the admin endpoints, and the enqueue chaining
  are all independent of the key and ship/operate normally without it.
- **Deploy note to surface in the PR description + DEPLOY notes:** add `ANTHROPIC_API_KEY` to
  the Railway `Job-Visualizer-Notifier` service to activate normalization. Until then rows stay
  unnormalized (NULL) and dormant (harmless); after the key is set they drain automatically.

### End-to-end verification additions (beyond the plan's §End-to-End Verification)
- Run the three production verifiers (`railway-prod-verifier`, `postgres-prod-verifier`,
  `vercel-prod-verifier`) on the final diff before opening the PR. Postgres focus: the additive
  migration applies cleanly against current prod (`c4f0a2d8b9e1`) with no full-table rewrite.
  Railway focus: worker boots with `normalize` in the queue list and no crash-loop with the key
  absent. Vercel focus: no `api/*.ts` proxy or request-flow change is required (backend-only
  feature) — confirm nothing regressed.
- `vercel-prod-verifier` is expected to be a near-no-op (this is a backend-only change with no
  `api/*.ts`, `vercel.json`, or `process.env.*` edits); run it anyway to confirm that.
