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
  - mcp__railway-mcp-server__list-projects
  - mcp__railway-mcp-server__list-services
  - mcp__railway-mcp-server__list-deployments
  - mcp__railway-mcp-server__get-logs
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

Then list Railway projects to confirm MCP auth:

```
mcp__railway-mcp-server__list-projects
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

```sql
SELECT worker_id, last_beat_at,
       EXTRACT(EPOCH FROM now()) - EXTRACT(EPOCH FROM last_beat_at) AS beat_age_s
FROM worker_heartbeats
ORDER BY last_beat_at DESC;
```

A `beat_age_s > 120` on every row = worker truly silent. Cross-reference
with Railway's `/health/worker` response.

### A.4 — Periodic-defer drift

```sql
SELECT id, task_name, periodic_id, defer_timestamp,
       to_timestamp(defer_timestamp) AT TIME ZONE 'UTC' AS defer_at, job_id
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

### B.1 — Last successful run per company

```sql
SELECT company,
       MAX(completed_at) AS last_completed,
       MAX(jobs_seen)     AS last_seen,
       SUM(error_count)   AS lifetime_errors,
       COUNT(*)           AS total_runs
FROM scrape_runs
WHERE completed_at IS NOT NULL
GROUP BY company
ORDER BY last_completed NULLS FIRST;
```

Expected: every enabled company has `last_completed` within ~30 min for Procrastinate-managed ATSes, and within ~2× scraper-interval for `apple` / `google` / `microsoft`.

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

Transient 5xx / network blips are normal; persistent errors on a single company warrant a look.

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
SELECT source_id,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE status='OPEN')   AS open_count,
       COUNT(*) FILTER (WHERE status='CLOSED') AS closed_count,
       COUNT(*) FILTER (WHERE status IS NULL)  AS null_count,
       COUNT(*) FILTER (WHERE status NOT IN ('OPEN','CLOSED')
                          AND status IS NOT NULL) AS other_count,
       MAX(last_seen_at) FILTER (WHERE status='OPEN') AS latest_open_seen
FROM job_listings
GROUP BY source_id
ORDER BY source_id;
```

Expected: `null_count = 0`, `other_count = 0`. `latest_open_seen` should be within one cron tick for queue-managed sources.

### C.2 — Distinct status values (cardinality check)

```sql
SELECT DISTINCT status FROM job_listings ORDER BY status;
```

Should return exactly `{OPEN, CLOSED}`.

### C.3 — Resurrection check (closed-then-seen-again)

```sql
SELECT source_id, COUNT(*)
FROM job_listings
WHERE closed_on IS NOT NULL AND last_seen_at > closed_on
GROUP BY source_id;
```

Should return 0 rows. Non-zero = either the absence logic re-opens jobs without clearing `closed_on`, or a write race.

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
| **Microsoft** | `apply.careers.microsoft.com/careers/apply?pid=<id>` | 404 / "no longer available" | **Tier 2** | SPA serves config JSON to WebFetch. |
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
SELECT id, title, company, closed_on, first_seen_at, last_seen_at,
       consecutive_misses
FROM job_listings
WHERE source_id = :src AND id IN (:ids);
```

## Phase E — Open-job spot-check (catches the inverse bug)

Sample 5 OPEN jobs per provider; confirm each is actually live.

```sql
WITH ranked AS (
  SELECT source_id, url, title, company,
         ROW_NUMBER() OVER (PARTITION BY source_id ORDER BY last_seen_at DESC) AS rn
  FROM job_listings
  WHERE status='OPEN' AND url IS NOT NULL AND url != ''
)
SELECT source_id, url, title, company FROM ranked WHERE rn <= 5
ORDER BY source_id, rn;
```

Probe with the same two-tier strategy as Phase D — `WebFetch` first, falling back to Playwright for SPA providers or any UNCLEAR result. Each probe should return STATUS: LIVE. Any STATUS: CLOSED here is a stale-OPEN bug (the inverse failure mode); screenshot it via `mcp__playwright__browser_take_screenshot` for the write-up.

## Phase F — Railway service health

### F.1 — Latest deployment

```
mcp__railway-mcp-server__list-deployments
  workspacePath: <repo root>
  service: Job-Visualizer-Notifier
  json: true
  limit: 5
```

Confirm latest deployment `status: SUCCESS` and `commitHash` matches a recent `main` commit. Note `createdAt` — long-running deploys (>24h since deploy with no restarts) are at higher risk of stuck-worker.

### F.2 — Tail logs for errors

```
mcp__railway-mcp-server__get-logs
  workspacePath: <repo root>
  service: Job-Visualizer-Notifier
  logType: deploy
  deploymentId: <latest>
  lines: 200
  filter: "@level:error OR Traceback OR psycopg OR pool OR SIGTERM OR SIGKILL OR OOM"
```

### F.3 — Liveness via log gap

If Phase A.3 showed a stale event log, also pull recent unfiltered logs and verify there are zero log lines after the last `procrastinate_events.at` — that's the "worker is silent, container is up" pattern.

```
mcp__railway-mcp-server__get-logs
  workspacePath: <repo root>
  service: Job-Visualizer-Notifier
  logType: deploy
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

- **P0** — Data is silently going stale right now. Examples: worker hung, fan-out task permanently failing for >2 ticks, every closed job is actually live.
- **P1** — Real correctness bug affecting a real user-visible field, but bounded scope. Examples: a single provider producing false-closes; a single company stuck not scraping.
- **P2** — Cosmetic / cleanup. Examples: stale historical `failed` rows that no longer affect production, drift between `procrastinate_periodic_defers` and reality.

## Operational notes (carry forward between runs)

- **Tracebacks in earlier logs** from `httpx.HTTPStatusError 502` against Workday tenants are normal — Procrastinate retries them. Only flag if they're terminal (4 attempts → status `failed`).
- **`closed_on` is a real `timestamptz`** set to whenever `mark_jobs_closed` ran (see `scripts/shared/database.py:615-643`). The hour IS meaningful — useful for correlating closes with specific scrape runs. Just remember the Phase-0 timezone-bug caveat when rendering it through the MCP.
- **`procrastinate_periodic_defers.defer_timestamp` lies** when the worker is hung — it gets bumped by the cron scheduler but no new job lands. Always cross-check against `procrastinate_events` (A.3) and `worker_heartbeats` (A.3b).
- **Eightfold dedup collisions** (PR #126's `upsert_jobs_batch` dedup pass) can silently drop jobs → mark them as missed → close them. If you see Netflix false-closes, grep recent logs for `upsert_jobs_batch.*WARN.*dropped duplicate`.
- **The 10%-active safety guard** in `fetch_<provider>_company.py` (`SAFETY_GUARD_RATIO = 0.1` in `scripts/shared/incremental.py:33`) blocks mass closure when an API blip returns *fewer than 10%* of the previously-active count. So it only catches catastrophic drops (~90%+ missing), NOT single-job drops. If a single provider closed ~1-5 jobs and other counts look healthy, the guard is irrelevant to the diagnosis.
- **`MISSED_RUN_THRESHOLD = 2`** (`scripts/shared/incremental.py:27`) closes a job after **two consecutive scrapes** miss its id — ~60-90 min at the 30-min cadence. This is intentionally aggressive. Bumping it would just delay both true and false closes.
- **Auto-reopen on reappearance is wired in.** `_UPSERT_ON_CONFLICT` in `scripts/shared/database.py:88-100` unconditionally resets `status='OPEN'`, `closed_on=NULL`, `consecutive_misses=0` whenever a row's composite key reappears in any scrape. So any false-close that gets re-listed within the company's normal cadence auto-corrects on the next tick. Don't propose "add an auto-reopen path" — it's already there.
- **`source_id` values are `<provider>_api` or `<provider>_scraper`**, NOT bare provider names. Current set: `lever_api`, `greenhouse_api`, `ashby_api`, `gem_api`, `eightfold_api`, `workday_api`, `apple_scraper`, `google_scraper`, `microsoft_scraper`. Querying for `source_id='lever'` returns zero rows — easy mistake.
- **Lever recruiter-delist pattern (NOT a bug).** When a Lever posting is absent from `api.lever.co/v0/postings/<board>?mode=json` but `jobs.lever.co/<board>/<id>` still renders `APPLY FOR THIS JOB`, the most common cause is the recruiter intentionally toggling off public distribution (or moving the posting to "confidential" / "internal-only"). The apply URL persists so internal referrals keep working. From this product's perspective ("notify about applyable roles"), CLOSED is the correct call — cold applications to delisted Lever URLs are dead-on-arrival. **Do NOT flag these as P0/P1 false-closes.** Note in the write-up if interesting (e.g. >10/day on one company), but treat as expected behavior. The investigation that established this is at `/Users/brendanpotter/.claude/plans/what-do-you-mean-quiet-crane.md` (and the one-off SQL in `scripts/one_off/2026-05-21_reopen_false_closed.sql` was a one-time data fix, not a precedent).

## Failure modes worth flagging

Adapt as the codebase evolves:

| Symptom | Likely root cause | Where to look |
|---|---|---|
| All providers stop scraping simultaneously | Worker hung / container crashed silently | Phase A.3, Railway logs |
| One provider stops, others fine | That provider's fan-out task failed terminally | Phase A.2, `procrastinate_events` for the task |
| `new_jobs=0` and `closed_jobs=0` for a provider | Could be legit (no activity) OR upstream API returning empty | Phase B.4 + sample a few of that provider's company API calls |
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
