---
name: onesecondswe-backend-audit
description: |
  Comprehensive read-only production audit of the Job-Visualizer-Notifier backend.
  Verifies Procrastinate worker liveness, queue/event log health, per-ATS scrape
  cadence, OPEN/CLOSED status correctness, closed-job URL truthfulness, and
  Railway service state. Produces an evidence-backed write-up with prioritized
  findings. No writes — pure investigation.
trigger_phrases:
  - audit the backend
  - check backend health
  - verify production
  - is the worker running
  - are scrapes healthy
  - check closed jobs are really closed
  - verify ATS fetching
  - production health check
required_mcps:
  - mcp__postgres-prod__query
  - mcp__railway-mcp-server__list_projects
  - mcp__railway-mcp-server__list_services
  - mcp__railway-mcp-server__list_deployments
  - mcp__railway-mcp-server__get_logs
  - mcp__playwright__browser_navigate
  - mcp__playwright__browser_snapshot
  - mcp__playwright__browser_evaluate
  - mcp__playwright__browser_close
required_tools:
  - WebFetch
  - Bash
mode: read-only
---

# Backend Audit — Job Visualizer Notifier

A repeatable, evidence-backed production audit. **Read-only:** no DB writes,
no Railway restarts, no commits. Findings only.

## When to run

- After a non-trivial backend deploy (especially anything touching
  `src/backend/api/tasks/`, `src/backend/api/services/`, `scripts/shared/`).
- When jobs counts look off in the UI or `new_jobs` / `closed_jobs` drift.
- Scheduled cadence (e.g., weekly) — catches silent worker hangs that
  Railway's `ON_FAILURE` restart policy won't surface.

## Scope knobs (ask once before starting)

Use `AskUserQuestion` to pick scope. Defaults in **bold**:

1. **URL sample size for closed-job verification**: small (10/ATS), **medium (25/ATS)**, large (50/ATS).
2. **Include custom scrapers (Google/Apple/Microsoft)**: **yes** / no.
3. **Fix mode**: **report-only** / fix-safe-ops / fix-with-code.

For "report-only" (the default), the skill never mutates state. The other
two modes require explicit user confirmation per fix.

## Phase 0 — Pre-flight

Verify tools are wired up. If any of these fail, abort with a clear message.

> **Postgres MCP timezone trap — read this before writing any SQL.**
> The `mcp__postgres-prod__query` JSON serializer strips the tz tag from any
> `timestamp without time zone` and then re-renders the naked value *as if it
> were already local time*, producing a phantom shift equal to your local UTC
> offset (CDT = +5h, CST = +6h, PDT = +7h, UTC = 0). This bites you whenever
> you write `now() AT TIME ZONE 'UTC'` or cast `timestamptz → timestamp`.
> A `closed_on` of `2026-05-20T16:00:09Z` will render as `2026-05-20T21:00:09Z`
> on a CDT machine — same wall-clock, wrong label. **Mitigations:**
> 1. **Render `timestamptz` columns bare** (no cast). They serialize correctly as `…Z`.
> 2. For elapsed-time math use `EXTRACT(EPOCH FROM now())::bigint` and subtract integers.
> 3. Cross-check any "X hours ago" claim against bare `now()` before reporting.
> See `docs/incidents/` and the `## Critical Gotchas` block in repo-root
> `CLAUDE.md` for the May-2026 false-investigation this caused.

```sql
-- mcp__postgres-prod__query — use bare now() (renders as …Z correctly)
SELECT now() AS db_now,
       (SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema='public') AS public_tables;
```

Then list Railway projects to confirm MCP auth (tool names use underscores —
the hyphenated forms do not exist and abort Phase 0):

```
mcp__railway-mcp-server__list_projects
```

Expected project: `onesecondswe` with services `Job-Visualizer-Notifier` + `Postgres`.

Snapshot recent commits on `main` for context:

```bash
git log --oneline -10 main
```

## Phase A — Queue & worker health (Procrastinate)

The single most important liveness check. The worker can hang with `restartPolicyType: ON_FAILURE` *not* triggering, because a hung coroutine doesn't exit non-zero.

### A.1 — Job-state distribution

```sql
SELECT status, COUNT(*) FROM procrastinate_jobs GROUP BY status ORDER BY status;
```

Healthy: nearly all `succeeded`, zero `doing` older than 30 min, zero `failed` younger than the last fan-out tick.

### A.2 — Stuck and failed jobs

```sql
SELECT id, queue_name, task_name, status, attempts, scheduled_at, args
FROM procrastinate_jobs
WHERE status IN ('failed','doing','todo','cancelled','aborting')
ORDER BY id DESC LIMIT 50;
```

Cross-reference any `failed` rows with later runs of the same `task_name` — a row stuck "failed" in history is fine if the next periodic invocation succeeded.

### A.3 — Liveness via event log (CRITICAL CHECK)

Use the integer-epoch form to dodge the Postgres MCP timezone bug (see Phase 0):

```sql
SELECT now() AS db_now,
       MAX(at) AS latest_event,
       EXTRACT(EPOCH FROM now()) - EXTRACT(EPOCH FROM MAX(at)) AS gap_seconds
FROM procrastinate_events;
```

**Hard rule:** if `gap_seconds > 2700` (45 min), the worker is hung or dead. The cron fires every 30 min, so a 30+ min silence is suspicious; 45+ min is confirmed.

### A.3b — Worker heartbeats (cross-check)

Since 2026-05 there's also a periodic heartbeat task writing to a
`worker_heartbeats` table and a `/health/worker` Railway probe (commits
`f0d1b5e`, `ba3259a`). Use it as a second-source liveness signal — the
heartbeat keeps writing even when ATS fan-out tasks are silent for legit
reasons (e.g., nothing scheduled in the current minute).

The table has exactly two columns — `id` and `at`
(`src/backend/api/db_models.py`, migration `2aaec46888f4`); there is no
`worker_id` or `last_beat_at` anywhere in the schema.

```sql
SELECT id, at,
       EXTRACT(EPOCH FROM now())::bigint - EXTRACT(EPOCH FROM at)::bigint AS beat_age_s
FROM worker_heartbeats
ORDER BY at DESC
LIMIT 5;
```

The heartbeat fires every 5 minutes (`@procrastinate_app.periodic(cron="*/5 * * * *")`,
`src/backend/api/tasks/heartbeat.py:106`), so successive rows should be ~300s
apart. **Rule: `beat_age_s > 600` on the NEWEST row = worker silent** — 600s is
the app's own freshness threshold (`_HEARTBEAT_FRESHNESS_SECONDS = 10 * 60`,
`src/backend/api/main.py:53`, applied by `/health/worker`), so the audit and
the health endpoint can never disagree. (A 120s rule would flag a perfectly
healthy worker on most polls — below the normal inter-beat interval.)
Cross-reference with Railway's `/health/worker` response.

### A.4 — Periodic-defer drift

```sql
-- to_timestamp() rendered BARE: adding `AT TIME ZONE 'UTC'` strips the tz tag
-- and the MCP re-labels the naked value as local time (verified 2026-08-05: a
-- 06:15Z defer rendered as 11:15Z on a CDT machine — the Phase-0 trap, in this
-- skill's own SQL).
SELECT id, task_name, periodic_id, defer_timestamp,
       to_timestamp(defer_timestamp) AS defer_at, job_id
FROM procrastinate_periodic_defers
ORDER BY id DESC;
```

There should be one row per fan-out task (`enqueue_<provider>_fan_out`). `defer_timestamp` may show a future tick even when the worker is dead — **do not** trust this as a liveness signal. The authoritative liveness signal is A.3.

### A.5 — Per-queue/task breakdown

```sql
SELECT queue_name, task_name, status, COUNT(*)
FROM procrastinate_jobs
GROUP BY queue_name, task_name, status
ORDER BY queue_name, task_name, status;
```

Expected queues today: `greenhouse_fetch`, `ashby_fetch`, `lever_fetch`, `gem_fetch`, `eightfold_fetch`, `workday_fetch`. Adapt as new providers are added.

## Phase B — `scrape_runs` audit

The per-run ground truth. Schema: `run_id, company, started_at, completed_at, mode, jobs_seen, new_jobs, closed_jobs, details_fetched, error_count`. Note `started_at` / `completed_at` are stored as **TEXT** — cast to `::timestamptz` when comparing.

### B.1 — Per-company run health (latest run, not lifetime aggregates)

> **Why this table was replaced (2026-08-05).** The old version reported
> `MAX(jobs_seen)` (a lifetime maximum masquerading as "most recent") and
> keyed its expectation on `last_completed` being fresh. A dead source
> *completes* a run every tick — it completes with an error — so on
> 2026-07-25 the old table showed four sources that had been returning zero
> jobs for 16-53 days as green. A tool that reassures during an outage is
> worse than no tool; this shape makes that impossible.

```sql
WITH latest AS (
  SELECT DISTINCT ON (company)
         company, jobs_seen AS latest_jobs_seen, error_count AS latest_error_count,
         completed_at AS last_completed
  FROM scrape_runs
  WHERE completed_at IS NOT NULL
  ORDER BY company, started_at::timestamptz DESC
),
agg AS (
  SELECT company,
         MAX(started_at::timestamptz) FILTER (WHERE jobs_seen > 0) AS last_nonzero_at,
         MAX(jobs_seen)   AS lifetime_max_jobs_seen,
         SUM(error_count) AS lifetime_errors,
         COUNT(*)         AS total_runs
  FROM scrape_runs
  GROUP BY company
)
SELECT l.company, l.last_completed, l.latest_jobs_seen, l.latest_error_count,
       a.last_nonzero_at,
       round(((EXTRACT(EPOCH FROM now())::bigint
             - EXTRACT(EPOCH FROM a.last_nonzero_at)::bigint)/3600.0)::numeric, 1)
           AS hours_since_nonzero,
       a.lifetime_max_jobs_seen, a.lifetime_errors, a.total_runs
FROM latest l
JOIN agg a USING (company)
ORDER BY hours_since_nonzero DESC NULLS FIRST;
```

Read it in this order: `latest_jobs_seen` is what the source produced on its
most recent run; `hours_since_nonzero` is how long since it last produced
anything. Expected: every enabled company has `last_completed` within ~30 min
for Procrastinate-managed ATSes (within ~2× scraper-interval for
`apple`/`google`/`microsoft`) **AND** `hours_since_nonzero` under ~6h. A fresh
`last_completed` with a large `hours_since_nonzero` is the dead-source
signature, not health. The `lifetime_*` columns are context only — never read
them as current state. Note this table spans every company with run history,
including deliberately-disabled ones (e.g. `unity3d` tops it with a stale
`last_completed`) — cross-check `companies.enabled` before flagging; B.1b
already filters to enabled.

### B.1b — Silent-zero sources (CRITICAL CHECK)

**Returns zero rows on a healthy system.** Any row is a P0/P1 finding (see
severity rubric). Two proven signals — run both; prefer flagging the union
and noting which signal(s) tripped:

```sql
-- Signal 1: staleness — last non-zero scrape older than 6h (12 missed ATS
-- ticks) or absent entirely. Validated 2026-07-25 and 2026-08-05: exactly the
-- known-broken set, zero false positives across all enabled companies.
WITH per_company AS (
  SELECT c.id AS company, c.ats,
         max(sr.started_at::timestamptz) FILTER (WHERE sr.jobs_seen > 0) AS last_ok,
         max(sr.started_at::timestamptz) AS last_run,
         count(*) FILTER (WHERE sr.started_at::timestamptz > now() - interval '24 hours'
                            AND sr.error_count > 0) AS err_24h
  FROM companies c
  LEFT JOIN scrape_runs sr ON sr.company = c.id
  WHERE c.enabled
  GROUP BY c.id, c.ats
)
SELECT company, ats, last_ok, last_run, err_24h,
       round(((EXTRACT(EPOCH FROM now())::bigint
             - EXTRACT(EPOCH FROM last_ok)::bigint)/3600.0)::numeric, 1) AS hours_since_ok
FROM per_company
WHERE last_ok IS NULL OR last_ok < now() - interval '6 hours'
ORDER BY hours_since_ok DESC NULLS FIRST;
```

```sql
-- Signal 2: the {0,0,0} signature — last 3 runs all zero on an enabled
-- company. One zero run is normal (a small board can genuinely empty for a
-- tick); three consecutive is not. Caveat: a 404ing source writes ~6 rows per
-- tick (retry storm), so "last 3" can span minutes — that is why Signal 1
-- exists alongside it.
WITH last3 AS (
  SELECT company, jobs_seen,
         row_number() OVER (PARTITION BY company ORDER BY started_at::timestamptz DESC) AS rn
  FROM scrape_runs
)
SELECT c.id AS company, c.ats, array_agg(l.jobs_seen ORDER BY l.rn) AS last3_jobs_seen
FROM companies c
JOIN last3 l ON l.company = c.id AND l.rn <= 3
WHERE c.enabled
GROUP BY c.id, c.ats
HAVING sum(l.jobs_seen) = 0
ORDER BY c.id;
```

Worked example (2026-08-05): both signals returned exactly `fireworksai`
(105h dark, 288/288 errored runs/24h — greenhouse board 404, moved to
Ashby) and `thinkingmachines` (13h dark — same move), out of 132 enabled
companies. That morning's detection led to the fix PR within the hour —
this check is the one that catches the incident this epic was written about.
The same SQL powers the `scraper-health-watch` skill's daily run and (in
`job_freshness` form) the `GET /api/jobs-qa/scraper-health` endpoint —
cross-check against the endpoint when the API is reachable, but keep the SQL
here so the audit works when the API is exactly what's broken.

### B.2 — Aborted runs (started but never completed)

```sql
SELECT company, run_id, started_at
FROM scrape_runs
WHERE started_at IS NOT NULL
  AND completed_at IS NULL
  AND started_at::timestamptz < now() - interval '30 minutes';
```

Should return 0 rows.

### B.3 — Recent errors

```sql
SELECT company, COUNT(*) AS error_runs, MAX(started_at) AS latest_error_at
FROM scrape_runs
WHERE error_count > 0
  AND started_at::timestamptz > now() - interval '24 hours'
GROUP BY company
ORDER BY error_runs DESC;
```

**Thresholds** (validated 2026-08-05, when the dead sources showed 288 and 162
error runs against Netflix's transient 18):

- `error_runs > 20` in 24h on one company → investigate (P1 candidate). At the
  30-min cadence a company gets ≤48 non-retried runs/day, so >20 errored means
  a sustained failure, not a blip — while a provider-wide 502 wobble (~12-18
  runs) stays under it.
- `error_runs = ALL of that company's runs in 24h` → the source is fully dead
  (P0/P1 per the rubric); cross-check B.1b, which will also name it.
- The run-count *shape* tells you the failure mode before you read a single
  log: ~6 error rows per tick = the HTTP-error path (Procrastinate retry
  storm, e.g. a 404); exactly 1 row per tick with `error_count=1` = the
  safety-guard path (HTTP 200 with an empty/truncated board — no retry, no
  closures). See the operational note on the two zero-job paths.

### B.4 — Closed-jobs trend per provider

```sql
SELECT DATE_TRUNC('day', completed_at::timestamptz) AS day,
       company,
       SUM(closed_jobs)
FROM scrape_runs
WHERE completed_at::timestamptz > now() - interval '7 days'
  AND closed_jobs > 0
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
```

A provider reporting **0 closed_jobs for >24h** while others aren't is a smoking gun for a stuck fan-out (or a regression in absence-detection).

## Phase C — OPEN / CLOSED status correctness

### C.1 — Per-source counts + freshness

```sql
-- Freshness comes from the job_freshness sidecar (see the cutover note in
-- Operational notes): job_listings.last_seen_at froze at the 2026-08-05
-- write-repoint deploy and only advances on new-row INSERTs.
SELECT j.source_id,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE j.status='OPEN')   AS open_count,
       COUNT(*) FILTER (WHERE j.status='CLOSED') AS closed_count,
       COUNT(*) FILTER (WHERE j.status IS NULL)  AS null_count,
       COUNT(*) FILTER (WHERE j.status NOT IN ('OPEN','CLOSED')
                          AND j.status IS NOT NULL) AS other_count,
       MAX(COALESCE(f.last_seen_at, j.last_seen_at))
           FILTER (WHERE j.status='OPEN') AS latest_open_seen
FROM job_listings j
LEFT JOIN job_freshness f ON f.source_id = j.source_id AND f.id = j.id
GROUP BY j.source_id
ORDER BY j.source_id;
```

Expected: `null_count = 0`, `other_count = 0`. `latest_open_seen` should be within one cron tick for queue-managed sources.

### C.2 — Distinct status values (cardinality check)

```sql
SELECT DISTINCT status FROM job_listings ORDER BY status;
```

Should return exactly `{OPEN, CLOSED}`.

### C.3 — Resurrection check (closed-then-seen-again)

```sql
-- Sidecar freshness, for the same reason as C.1 — against the frozen
-- job_listings column this check can never fire again and silently loses
-- its purpose.
SELECT j.source_id, COUNT(*)
FROM job_listings j
JOIN job_freshness f ON f.source_id = j.source_id AND f.id = j.id
WHERE j.closed_on IS NOT NULL AND f.last_seen_at > j.closed_on
GROUP BY j.source_id;
```

Should return 0 rows. Non-zero = either the absence logic re-opens jobs without clearing `closed_on`, or a write race. (Small counts can also be a benign
close→re-see race within one tick — check the gap size before escalating.)

### C.4 — Per-ATS provider list (sanity)

```sql
SELECT ats, COUNT(*) FROM companies WHERE enabled=true GROUP BY ats ORDER BY ats;
```

## Phase D — Closed-job URL verification

For each provider, sample closed jobs and probe the URL with `WebFetch`. The sample size comes from the Phase-0 scope knob; default = 25 per provider, stratified 50/50 recent vs older.

### D.1 — Pull the sample

```sql
WITH ranked AS (
  SELECT source_id, url, closed_on, title, company,
         ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY closed_on DESC) AS rn_recent,
         ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY closed_on ASC)  AS rn_old
  FROM job_listings
  WHERE status='CLOSED' AND url IS NOT NULL AND url != ''
)
SELECT source_id, url, closed_on::date AS closed_date, title, company
FROM ranked
WHERE rn_recent <= :half OR rn_old <= :half  -- e.g., 13 + 13 = 26 for medium
ORDER BY source_id, closed_on DESC;
```

If the result blob exceeds tool output limits, page per-source.

### D.2 — Probe URLs (two-tier: WebFetch then Playwright)

The repo has the Playwright MCP wired up (artifacts under `.playwright-mcp/`).
Use a two-tier strategy to balance speed with coverage:

**Tier 1 — `WebFetch` (fast, parallel, ~8 calls per turn).** Good enough for
providers whose closed-job page is static HTML or whose `og:` metadata is
authoritative (Apple, Greenhouse, Ashby, Gem, Eightfold, plain anchor tags).

Prompt template (use verbatim):

> Is this URL showing an ACTIVE job posting someone can apply to RIGHT NOW, or has it been CLOSED/REMOVED/expired? Look for indicators like 404, "no longer available", "this position has been filled", "the position you are looking for does not exist", redirects to search/home, or live "Apply" button. Answer in this exact format only: STATUS: <LIVE|CLOSED|UNCLEAR> | EVIDENCE: <one short sentence>

**Tier 2 — Playwright MCP (slower, sequential, definitive).** Use for every
JS-SPA provider (Lever, Workday, Microsoft, Google) and for any Tier-1 result
that came back `UNCLEAR` or `403`. Playwright renders the actual page, so
"could not verify" should be vanishingly rare with this tier.

Playwright tools to use, in order, per URL:

```
mcp__playwright__browser_navigate         { url: <job_url> }
mcp__playwright__browser_snapshot         // accessibility tree of the page
mcp__playwright__browser_evaluate         { function: "() => ({
  title: document.title,
  bodyText: document.body.innerText.slice(0, 2000),
  url: window.location.href,
  status: window.performance?.getEntriesByType?.('navigation')?.[0]?.responseStatus ?? null
})" }
```

Then classify with the provider-specific rules in §D.3. Close the browser at
the end of the batch with `mcp__playwright__browser_close` to free resources.

Throughput tips for Tier 2:
- Don't `navigate` in parallel — one tab, sequential URLs, ~3-5 s per probe.
- Cap each provider at the Phase-0 sample size; don't fall back to Tier 2 for
  *every* URL or the audit will take an hour.
- If a Playwright probe takes >15 s, abort that URL and mark UNCLEAR rather
  than blocking the batch.
- Optional: capture screenshots for false-close candidates only —
  `mcp__playwright__browser_take_screenshot` with `fullPage: false` is enough
  for an evidence attachment. Save under `.playwright-mcp/` so they survive
  the session.

### D.3 — Provider-specific classification rules

| Provider | URL pattern | "Properly closed" indicator | Probe tier | Notes |
|---|---|---|---|---|
| **Apple** | `jobs.apple.com/.../details/<id>` | Literal banner: *"Sorry, this role does not exist or is no longer available"* | Tier 1 | Static — WebFetch sufficient. |
| **Greenhouse** | `job-boards.greenhouse.io/<board>/jobs/<id>` or `boards.greenhouse.io/<board>/jobs/<id>` | 302 → board index without the role | Tier 1 | Some boards (`stripe.com/jobs`, `unity.com/careers`) redirect via referer; check the title doesn't appear. |
| **Ashby** | `jobs.ashbyhq.com/<board>/<uuid>` | Empty SPA: only generic `Jobs` heading, no `og:title` of `<role> @ <company>` | Tier 1 (og:title) | Falls back to Tier 2 if og:title is ambiguous. |
| **Gem** | `jobs.gem.com/<board>/<id>` | Bare `<Board> Careers` header, no job content | Tier 2 | JS-rendered; Playwright snapshot needed to see whether the job body actually rendered. |
| **Eightfold** | `<tenant_host>/careers/job/<position_id>` (today: `explore.jobs.netflix.net`) | 404 or page lacks the live application form | **Tier 2 (always)** | Known false-close risk. Use Playwright + screenshot any LIVE-but-DB-CLOSED finding for evidence. |
| **Lever** | `jobs.lever.co/<board>/<uuid>` | 404 / redirect to `/<board>` | **Tier 2** | Returns HTTP 403 to WebFetch (anti-bot); Playwright passes through. **DO NOT flag "apply page renders but absent from `/v0/postings`" as a false-close** — see Lever recruiter-delist note in Operational notes. |
| **Workday** | `<tenant>.wd<N>.myworkdayjobs.com/<site>/details/<slug>_<reqid>` | 404 / redirect to job search | **Tier 2** | Heavy SPA — WebFetch sees only the shell. |
| **Microsoft** | `apply.careers.microsoft.com/careers/apply?pid=<id>` | 404 / "no longer available" | **Tier 2** | The stored `apply?pid=` URL hits a sign-in wall before any job-state signal — structurally unverifiable (proven in the 2026-08-05 dry run). Probe the public job page `jobs.careers.microsoft.com/global/en/job/<job number>` instead (the `job_number` is in the row/details), or mark the provider UNVERIFIABLE rather than UNCLEAR. |
| **Google** | `www.google.com/about/careers/applications/jobs/results/<id>-<slug>?...` | Redirect to search results without the role | **Tier 2** | Use `browser_evaluate` to confirm the specific role title is absent from the rendered results list. |

If a Tier 2 probe still returns UNCLEAR (e.g., bot-detection challenge, captcha), flag it in the write-up rather than scoring — but with Playwright available these should be rare exceptions, not whole-provider gaps.

### D.4 — Per-ATS scorecard format

```
Greenhouse: 47/50 confirmed CLOSED (3 unclear), 0 false-close ✅
Ashby:      22/25 confirmed CLOSED, 3 unclear, 0 false-close ✅
Eightfold:   0/2  confirmed CLOSED, 0 unclear, 2 false-close 🔴
Apple:      24/25 confirmed CLOSED ✅
…
```

If the false-close count > 0, dig into each one: pull `consecutive_misses`, `first_seen_at`, `last_seen_at`, `closed_on` and look for patterns (timing tied to a recent deploy? pagination boundary? dedup collision?).

```sql
-- last_seen_at / consecutive_misses come from the sidecar; the job_listings
-- copies are frozen legacy values.
SELECT j.id, j.title, j.company, j.closed_on, j.first_seen_at,
       f.last_seen_at, f.consecutive_misses
FROM job_listings j
LEFT JOIN job_freshness f ON f.source_id = j.source_id AND f.id = j.id
WHERE j.source_id = :src AND j.id IN (:ids);
```

## Phase E — Open-job spot-check (catches the inverse bug)

Sample 5 OPEN jobs per provider; confirm each is actually live.

```sql
-- Ranked by sidecar freshness so "most recently seen OPEN" means what it says
-- (the job_listings column is frozen legacy).
WITH ranked AS (
  SELECT j.source_id, j.url, j.title, j.company,
         ROW_NUMBER() OVER (PARTITION BY j.source_id
                            ORDER BY COALESCE(f.last_seen_at, j.last_seen_at) DESC) AS rn
  FROM job_listings j
  LEFT JOIN job_freshness f ON f.source_id = j.source_id AND f.id = j.id
  WHERE j.status='OPEN' AND j.url IS NOT NULL AND j.url != ''
)
SELECT source_id, url, title, company FROM ranked WHERE rn <= 5
ORDER BY source_id, rn;
```

Probe with the same two-tier strategy as Phase D — `WebFetch` first, falling back to Playwright for SPA providers or any UNCLEAR result. Each probe should return STATUS: LIVE. Any STATUS: CLOSED here is a stale-OPEN bug (the inverse failure mode); screenshot it via `mcp__playwright__browser_take_screenshot` for the write-up.

## Phase F — Railway service health

### F.1 — Latest deployment

```
mcp__railway-mcp-server__list_deployments
  service_id: Job-Visualizer-Notifier
  limit: 5
```

(Parameter names verified against the live tool schema 2026-08-05: it takes
`service_id` / `project_id` / `environment_id` / `limit` — there is no
`workspacePath` or `json` parameter; omitted ids fall back to the linked
project/service.)

Known failure mode: `list_projects` (account-scope) succeeding while
project-scope calls return `Unauthorized. Please run railway login again`
means the Railway token expired — not a connectivity problem. Report Phase F
as BLOCKED-on-auth, lean on A.3/A.3b for liveness, and tell the user to
`railway login`; do not spin retrying.

Confirm latest deployment `status: SUCCESS` and `commitHash` matches a recent `main` commit. Note `createdAt` — long-running deploys (>24h since deploy with no restarts) are at higher risk of stuck-worker.

### F.2 — Tail logs for errors

There is no OR-syntax `filter` parameter — the real schema takes a single
`search` string plus a `level` filter. Make a few targeted calls instead:

```
mcp__railway-mcp-server__get_logs
  service_id: Job-Visualizer-Notifier
  log_type: deploy
  deployment_id: <latest>
  lines: 200
  level: error
```

then repeat with `search:` set to each of `Traceback`, `psycopg`, `SIGKILL`,
`OOM` (drop `level` when searching — a Traceback line is not always tagged
error). Skip any search term that already appeared in the `level: error` pass.

### F.3 — Liveness via log gap

If Phase A.3 showed a stale event log, also pull recent unfiltered logs and verify there are zero log lines after the last `procrastinate_events.at` — that's the "worker is silent, container is up" pattern.

```
mcp__railway-mcp-server__get_logs
  service_id: Job-Visualizer-Notifier
  log_type: deploy
  lines: 50
```

## Phase G — Write-up

A single markdown block with these exact sections, in this order:

1. **TL;DR** — green/yellow/red verdict per area (worker, queue, scrape_runs, status correctness, URLs, Railway). One sentence per area.
2. **What I checked** — short bullet per phase, with the SQL count or probe count.
3. **What's working** — explicit list with evidence linked (query name or probe count).
4. **What's broken / suspicious** — each issue with:
   - Severity (P0 / P1 / P2)
   - Evidence (SQL row or log excerpt)
   - Impact (user-facing or correctness-facing)
   - Suggested next step (without doing it, in report-only mode)
5. **Per-ATS scorecard** — table with: open count, closed count, last-run UTC, closed-correctness %, open-live %.
6. **Open questions / inconclusive** — anything not fully verified (e.g., SPA-provider closed URLs) and why.
7. **Recommended action order** — numbered list; the user picks what to act on.

### Severity rubric (use consistently)

- **P0** — Data is silently going stale right now. Examples: worker hung, fan-out task permanently failing for >2 ticks, every closed job is actually live, **more than one enabled source silent-zero (B.1b returns ≥2 rows), or any silent-zero source dark for >24h** — at that point the product is serving stale postings as fresh.
- **P1** — Real correctness bug affecting a real user-visible field, but bounded scope. Examples: a single provider producing false-closes; a single company stuck not scraping; **a single source freshly silent-zero (B.1b, <24h dark)** — it becomes P0 by aging, so name it in the write-up's action order either way.
- **P2** — Cosmetic / cleanup. Examples: stale historical `failed` rows that no longer affect production, drift between `procrastinate_periodic_defers` and reality.

## Operational notes (carry forward between runs)

- **Tracebacks in earlier logs** from `httpx.HTTPStatusError 502` against Workday tenants are normal — Procrastinate retries them. Only flag if they're terminal (4 attempts → status `failed`).
- **The `job_freshness` sidecar cutover (2026-08, #224).** `last_seen_at` and
  `consecutive_misses` live in the `job_freshness` table, keyed `(source_id, id)`;
  the columns of the same names on `job_listings` are FROZEN legacy values that
  only get stamped on new-row INSERT. Any freshness question — "when was this
  job last seen", "how many misses" — must join the sidecar (every query in
  this skill already does). Reading the legacy columns makes quiet-but-healthy
  sources look dead and dead sources look as fresh as their last insert.
- **The two zero-job failure paths** (read the failure's shape off run counts
  before opening a single log):
  1. *HTTP-error path* (e.g. board 404s): `raise_for_status()` raises, the run
     is recorded with `error_count=1`, then re-raised so Procrastinate retries
     up to 5× — **~6 `scrape_runs` rows per tick**, and the upsert/close phases
     never run (nothing false-closes).
  2. *Safety-guard path* (HTTP 200 with an empty/truncated board):
     `jobs_seen=0` trips the guard, which logs ERROR and returns normally —
     **exactly 1 row per tick**, no retry, no closures. Note the guard is gated
     on `active_count > 0`, so once a broken source has closed out all its
     jobs the guard stops firing entirely — the guard is not a detector; B.1b is.
- **`closed_on` is a real `timestamptz`** set to whenever `mark_jobs_closed` ran (see `mark_jobs_closed` in `scripts/shared/database.py` — around line 702 as of 2026-08-05; grep rather than trust line numbers). The hour IS meaningful — useful for correlating closes with specific scrape runs. Just remember the Phase-0 timezone-bug caveat when rendering it through the MCP. One deliberate exception: board-move repoint migrations close orphaned rows under a fixed midnight sentinel (e.g. `a7c31d9e0b46`, `e2835a568ade`) so their downgrades stay surgical — a batch of closes at exactly `T00:00:00+00:00` is a repoint backfill, not a scrape event.
- **`procrastinate_periodic_defers.defer_timestamp` lies** when the worker is hung — it gets bumped by the cron scheduler but no new job lands. Always cross-check against `procrastinate_events` (A.3) and `worker_heartbeats` (A.3b).
- **Eightfold dedup collisions** (PR #126's `upsert_jobs_batch` dedup pass) can silently drop jobs → mark them as missed → close them. If you see Netflix false-closes, grep recent logs for `upsert_jobs_batch.*WARN.*dropped duplicate`.
- **The 10%-active safety guard** in `fetch_<provider>_company.py` (`SAFETY_GUARD_RATIO = 0.1` in `scripts/shared/incremental.py:33`) blocks mass closure when an API blip returns *fewer than 10%* of the previously-active count. So it only catches catastrophic drops (~90%+ missing), NOT single-job drops. If a single provider closed ~1-5 jobs and other counts look healthy, the guard is irrelevant to the diagnosis.
- **`MISSED_RUN_THRESHOLD = 2`** (`scripts/shared/incremental.py:27`) closes a job after **two consecutive scrapes** miss its id — ~60-90 min at the 30-min cadence. This is intentionally aggressive. Bumping it would just delay both true and false closes.
- **Auto-reopen on reappearance is wired in.** `_UPSERT_ON_CONFLICT` in `scripts/shared/database.py` (around line 103 post-cutover; grep for it) unconditionally resets `status='OPEN'` and `closed_on=NULL` whenever a row's composite key reappears in any scrape, and the same-transaction `job_freshness` upsert resets `consecutive_misses=0` / advances `last_seen_at`. So any false-close that gets re-listed within the company's normal cadence auto-corrects on the next tick. Don't propose "add an auto-reopen path" — it's already there. (Caveat: this only helps rows the same `source_id` re-fetches — orphans left behind by an ATS move must be closed deliberately, which is what the repoint migrations do.)
- **`source_id` values are `<provider>_api` or `<provider>_scraper`**, NOT bare provider names. Current set: `lever_api`, `greenhouse_api`, `ashby_api`, `gem_api`, `eightfold_api`, `workday_api`, `apple_scraper`, `google_scraper`, `microsoft_scraper`. Querying for `source_id='lever'` returns zero rows — easy mistake.
- **Lever recruiter-delist pattern (NOT a bug).** When a Lever posting is absent from `api.lever.co/v0/postings/<board>?mode=json` but `jobs.lever.co/<board>/<id>` still renders `APPLY FOR THIS JOB`, the most common cause is the recruiter intentionally toggling off public distribution (or moving the posting to "confidential" / "internal-only"). The apply URL persists so internal referrals keep working. From this product's perspective ("notify about applyable roles"), CLOSED is the correct call — cold applications to delisted Lever URLs are dead-on-arrival. **Do NOT flag these as P0/P1 false-closes.** Note in the write-up if interesting (e.g. >10/day on one company), but treat as expected behavior. The header comment of `scripts/one_off/2026-05-21_reopen_false_closed.sql` records the investigation that established this (the original plan-file write-up lived outside the repo and is gone; the SQL header is the surviving evidence). That one-off was a one-time data fix — but note its *shape* (header rationale → guarded UPDATE → expected rowcount) has since become the template for deliberate data corrections, and board-move close-outs now ship inside repoint migrations (`a7c31d9e0b46`).

## Failure modes worth flagging

Adapt as the codebase evolves:

| Symptom | Likely root cause | Where to look |
|---|---|---|
| All providers stop scraping simultaneously | Worker hung / container crashed silently | Phase A.3, Railway logs |
| One provider stops, others fine | That provider's fan-out task failed terminally | Phase A.2, `procrastinate_events` for the task |
| `new_jobs=0` and `closed_jobs=0` for a provider | Could be legit (no activity) OR upstream API returning empty | Phase B.4 + sample a few of that provider's company API calls |
| One company at zero jobs for hours/days while its runs "complete" | Board moved ATS (404 → retry storm) or emptied (200 → guard path) | **Phase B.1b (CRITICAL CHECK)** + probe the board URL directly; the `scraper-health-watch` skill automates the fix |
| Mass false-closes for one provider | Pagination / dedup bug in that provider's transformer | Phase D + `upsert_jobs_batch` WARN log |
| `status IS NULL` rows | Schema migration regression or backfill miss | Phase C.1 — explain provenance before remediating |

## What this skill does NOT do

- Mutate production state (no UPDATEs, no `procrastinate_jobs` purges, no Railway restarts) — that's deliberate; surface findings and let the user act.
- Replace `/investigate` for root-cause analysis of a specific known bug; this skill is broad surveillance.
- Cover the frontend or Vercel side — see `/qa` or `/canary` for live-app probing.
- Stress-test or load-test — read-only correctness only.

## Completion

End with a single sentence summary like:

> Audit complete. <N> findings: <P0 count> P0, <P1 count> P1, <P2 count> P2. <one-line top-priority action>.

Report STATUS: `DONE` (no concerns), `DONE_WITH_CONCERNS` (findings present), or `BLOCKED` (couldn't reach an MCP).
