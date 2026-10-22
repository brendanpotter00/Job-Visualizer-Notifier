---
name: scraper-health-watch
description: |
  Scraper-health watchdog (runs every 3h via launchd). Detects dead/stale scrape
  sources (silent-zero + staleness), a fleet-wide coverage collapse, mass job
  closures, and worker-heartbeat death against prod; researches where a moved job
  board went (subagent); opens a fix PR (NEVER merges); texts Brendan when
  something is wrong — CRITICAL outages re-alert every run until fixed (no 72h
  suppression) — plus one weekly all-clear. Headless via launchd, or invoke
  interactively.
trigger_phrases:
  - check scraper health
  - run the health watchdog
  - are the scrapers healthy
  - scraper health watch
  - health watch
required_mcps:
  - mcp__postgres-prod__query
required_tools:
  - Bash
  - Read
  - Grep
  - WebFetch
  - Task
mode: read-write   # repo writes + PR only; prod is strictly read-only
---

# Scraper Health Watch

One run answers: **is any company we track silently returning nothing, mass-closing,
or unscraped — or has the whole fleet's scrape coverage collapsed?** If yes: research
where the board moved, open a fix PR, text Brendan. A live outage (worker dead,
coverage collapse, mass closure) re-alerts on **every** run until it clears — a single
missed text must never again mean a silent multi-day outage (2026-08-29: one text, then
72h of self-suppression while prod stayed down 61h). If no: stay silent (heartbeat log
only; weekly all-clear text).

Ops runbook (launchd install, logs, pause): `scripts/health_watch/README.md`.
Headless entry point: `.claude/commands/health-watch-once.md` → this file, `daily` mode.

## §0 Hard rules (non-negotiable — read before anything else)

1. **Prod is read-only.** `mcp__postgres-prod__query` may run `SELECT` only. Never
   INSERT/UPDATE/DELETE/DDL, never `alembic upgrade`, never any one-off SQL script
   against prod, never Railway/Vercel mutation tools, never restart anything.
2. **Never merge or deploy.** No `gh pr merge`, no `--auto`, no pushes to `main`.
   The fix PR is the terminal artifact; Brendan merges.
3. **Never touch the checked-out working tree you run in.** All repo writes happen
   in a throwaway `git worktree` created for the run and removed after push.
4. **Bounded effort:** research subagent self-timeboxed to ~10 minutes per company;
   at most **1 fix PR per run** (batch all companies into it); at most **3 texts
   per run**; at most one retry on any failed step, then record and move on.
5. **Uncertainty is never "healthy."** A failed prod query, an unparseable result,
   or a probe you couldn't run classifies as `UNKNOWN` and is alertable.
6. **Texts go through** `bash /Users/bpotter/.claude/skills/message-brendan/send.sh "<msg>"`
   (call the script directly — do not use the Skill tool for it). Exit 0 = sent.
   If it fails, log `ALERT-SEND FAILED` to stderr and continue — never retry-loop.
7. **No AI-attribution footers** in commits or PR bodies (repo owner's standing rule).
8. In headless mode, follow the exit discipline in `health-watch-once.md`
   (no backgrounding, no polling loops, no ScheduleWakeup; end turn after the
   final status block).

State lives in `~/Library/Application Support/jvn-health-watch/`:
`heartbeat.log` (append-only, one line per run), `state.json` (last-texted
timestamps per alert key + `last_allclear`).

## §1 Modes

- **`daily`** — headless, launched by the LaunchAgent wrapper (the mode name is
  historical; the agent now fires **every 3h**, not once a day — see the plist).
  Full procedure, no narration beyond the final status block.
- **`interactive`** (default when invoked via the Skill tool) — same procedure;
  you may narrate and pause for the user.
- **`drill <scenario>`** — test the alert path without real findings. Scenarios:
  `drill unknown` (exercise the UNKNOWN text), `drill heartbeat` (exercise the
  worker-dead text). Skips §2's real checks, prefixes the text with `[DRILL]`,
  uses state key `drill:<scenario>` for the 72h cooldown, and never opens a PR.

## §2 Phase 1 — Prod health checks (SQL, read-only)

> **Postgres MCP timezone trap** (same as `onesecondswe-backend-audit`):
> `scrape_runs.started_at`/`completed_at` are **TEXT** — always cast
> `::timestamptz`. Use bare `now()` and `EXTRACT(EPOCH FROM ...)` for elapsed
> math. Never cast timestamptz → timestamp through the MCP.

Tunable constants (change here, nowhere else):

| Constant | Value | Rationale |
|---|---|---|
| `STALE_AFTER_HOURS` | 6 | 12 missed 30-min ATS ticks; 0 false positives when validated against prod (2026-07-25 and 2026-08-05) |
| `MASS_CLOSE_COMPANY_MIN` | 50 | per-company 24h closed_jobs floor. Stays an absolute number because Check B already scales it by the company's own size (`closed_24h > open_rows`) |
| `MASS_CLOSE_GLOBAL_PER_COMPANY` | 10 | global 24h closed_jobs alarm, **per enabled company** — the alarm level is `greatest(MASS_CLOSE_GLOBAL_FLOOR, MASS_CLOSE_GLOBAL_PER_COMPANY × enabled)`, never a hard-coded count. A fixed global count is a false alarm with a fuse on it: it stays correct only until the fleet grows past it. 2026-09-17: fleet went 133 → 193 companies, the normal weekday closure band rose to ~780–1040/24h, and the old fixed `MASS_CLOSE_GLOBAL = 1000` started paging CRITICAL every 3h against a corpus that was *growing* (2146 new vs 1027 closed, per-company Check B empty, 193/193 scraping, heartbeat 0.9m). 10/company is ~2× the observed weekday peak (~5.4/company) and holds that headroom at any fleet size |
| `MASS_CLOSE_GLOBAL_FLOOR` | 1000 | absolute floor under the global alarm, so a small fleet (<100 companies) can't scale the threshold down into everyday noise |
| `MASS_CLOSE_NET_SHRINK_MIN` | 0.05 | a global close wave is CRITICAL only if the OPEN corpus actually **net-shrank** by ≥5% in the window. A real mass closure destroys the corpus; healthy high-volume churn replaces it faster than it closes it. Volume over threshold *without* net shrink is informational (`close_volume_high:global`), never a page |
| `HEARTBEAT_DEAD_MINUTES` | 15 | task writes every 5 min (`heartbeat.py:106`); app's own threshold is 10 min (`main.py:53`) |
| `WARM_UP_HOURS` | 6 | reuses the staleness window — a company seeded less than one window ago has not had time to tick; see A1's warm-up guard |
| `COVERAGE_MIN_FRACTION` | 0.5 | Check D floor — alert if fewer than half of enabled companies had a successful scrape in 24h. On the 2026-08-29 outage this read 5/133 (3.8%); anything under ~50% is a fleet-level failure, not per-company drift |
| `VENDOR_MAINTENANCE_MIN_COMPANIES` | 2 | Check A2's vendor-maintenance branch — the smallest A2 cluster sharing one `ats` that can be read as a pod outage rather than a board move. One company alone is always the per-company path: a single zeroed board is far more likely to have moved than to be a vendor's maintenance window |
| `GUARD_LATCH_MIN_RUNS` | 4 | Check A3 floor — the last N runs ALL guard-skipped (`skipped_update`) marks a latched-dark company. 4 = `SCRAPER_GUARD_MAX_CONSECUTIVE_SKIPS`(3, `incremental.py`) + 1, so a normally auto-releasing `partial_scrape` (which releases by the 3rd skip) can never reach it — only a non-releasing `empty_scrape` latch or a partial whose released run also fails. Validated on prod 2026-08-31: fires on apple (81 consecutive `empty_scrape` skips), zero other companies |

> **A1 and A2 filter on `c.enabled` only — they do NOT filter on `c.visibility`**, so private
> custom companies (E7, `visibility='user'`) are in scope. That is fine at the current cadence
> and was **not** fine before: custom boards ran on a 24 h cadence until 2026-08-29, so
> `last_ok` was older than the 6 h window for most of every day and every one of them would
> have tripped A1 permanently the moment the feature flag flipped. They now harvest hourly
> (`companies.cadence_hours = 1`), comfortably inside the window, so a custom board appearing
> in A1 is a real signal. If the cadence is ever slowed past `STALE_AFTER_HOURS` again, add
> `AND c.visibility = 'public'` here or raise the window — do not just mute the noise.

**Check A1 — staleness** (companies whose last scrape that actually *wrote* is old or absent):

```sql
WITH per_company AS (
  SELECT c.id AS company, c.ats, c.board_token, c.created_at,
         -- `last_ok` = the last run that both returned jobs AND wrote to
         -- job_listings. A guard-tripped run (skipped_update=true) returned
         -- rows but ingested NOTHING, so it is not an "ok" run — excluding it
         -- is what makes A1 catch a company that keeps returning a small
         -- non-zero count and is guard-blocked every run (the 2026-08-28 Apple
         -- empty_scrape latch: jobs_seen=17>0 kept last_ok fresh, hiding a
         -- 3.5-day outage). Check A3 below is the fast primary alarm for that
         -- shape; this one-clause change makes A1 itself a backstop for it.
         max(sr.started_at::timestamptz)
           FILTER (WHERE sr.jobs_seen > 0 AND sr.skipped_update IS NOT TRUE) AS last_ok,
         max(sr.started_at::timestamptz) AS last_run,
         count(*) FILTER (WHERE sr.started_at::timestamptz > now() - interval '24 hours') AS runs_24h,
         count(*) FILTER (WHERE sr.started_at::timestamptz > now() - interval '24 hours'
                            AND sr.error_count > 0) AS err_24h
  FROM companies c
  LEFT JOIN scrape_runs sr ON sr.company = c.id
  WHERE c.enabled
  GROUP BY c.id, c.ats, c.board_token, c.created_at
)
SELECT company, ats, board_token, last_ok, last_run, runs_24h, err_24h,
       round(((EXTRACT(EPOCH FROM now())::bigint
             - EXTRACT(EPOCH FROM last_ok)::bigint)/3600.0)::numeric, 1) AS hours_since_ok
FROM per_company
WHERE (last_ok IS NULL OR last_ok < now() - interval '6 hours')
  -- WARM-UP GUARD. A company whose seed migration just deployed has never run,
  -- so last_ok IS NULL sorts it to the TOP (NULLS FIRST) of the degraded list,
  -- and a repoint PR against a perfectly healthy new company is the result.
  -- Give it one staleness window to produce its first non-zero run.
  AND created_at < now() - interval '6 hours'
ORDER BY hours_since_ok DESC NULLS FIRST;
```

**Check A2 — silent-zero signature** (last 3 runs all zero on an enabled company):

```sql
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

A company is **degraded** if it appears in A1 or A2; record which signal(s) tripped.
**A2 is what keeps the warm-up guard honest:** a brand-new company with a wrong
`board_token` still trips A2 (its runs are all zero) on its very first tick, so
suppressing "never ran yet" in A1 blinds nothing. A company younger than
`WARM_UP_HOURS` with no `scrape_runs` rows at all is warming up, not dead.
(Both queries returned exactly the same true positives with zero false positives
across 133 companies on 2026-07-25 and 2026-08-05. A 404-storm source writes ~6
rows per tick, so A2's "last 3" can span minutes, not 90 — that is why A1 exists.)

**A2 fired on a whole ATS at once? CHECK FOR A VENDOR MAINTENANCE WINDOW before
calling it degraded.** When A2 returns a *cluster* of companies that all share one
`ats`, the common cause is not N simultaneous board moves — it is one upstream pod
going down for scheduled maintenance. That shape is self-healing, has no available
human action, and recurs on the vendor's calendar, so paging for it every time is
the alert-fatigue hazard §2's A3 branch and §4.2 both warn about.

Confirm it with these five conditions — **all** must hold:

| # | Condition | How to verify |
|---|---|---|
| 1 | A2 fired for ≥2 companies sharing one `ats` | the A2 result set |
| 2 | **A1 is clean for every one of them** (fresh, <`STALE_AFTER_HOURS`) | A1 returned no rows for them |
| 3 | The vendor serves a **maintenance page** | probe the live endpoint yourself; see the table below |
| 4 | **Nothing was written or destroyed**: `closed_jobs = 0`, `new_jobs = 0`, `skipped_update = false` on every failed run | per-company 3h rollup |
| 5 | A same-`ats` tenant on a **different pod/host** succeeded in the same tick | compare `provider_config` hosts against the A2 set |

Condition 3 for Workday — the vendor states it outright in a redirect, so one
request settles it. Do **not** follow the redirect (the maintenance host answers
403 to non-browsers, which reads like a different failure); read the `location`
header:

```bash
curl -sS -D - -o /dev/null -m 25 -X POST \
  "https://<tenant>.<pod>.myworkdayjobs.com/wday/cxs/<tenant_slug>/<career_site_slug>/jobs" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"appliedFacets":{},"limit":20,"offset":0,"searchText":""}' \
  | grep -iE '^(HTTP/|location:)'
```

| Probe result | Meaning | Action |
|---|---|---|
| **303 → `community.workday.com/maintenance-page`** | vendor maintenance window | `vendor_maintenance:<ats>`, see §3 — **log-only**, no text, no PR |
| **200 with > 0 jobs** | the pod is fine; our scraper is broken | real DEGRADED — normal per-company path |
| **404 / connection error** | the board moved or was deleted | real DEGRADED — §6 board research, PR-able |

**Why this is log-only and not a 72h informational text.** Workday takes its pods
down on a **weekly** cadence, so a 72h cooldown expires *before* the next
occurrence and the key texts every single week forever. MEASURED: the identical
event — same 11 of 16 enabled Workday companies (`adobe blueorigin cisco
crowdstrike disney gm intel nvidia paypal snap zoom`, every one on a `wd1` or
`wd5` host), breaking at the 06:30Z tick after a clean 06:00Z tick, all five
conditions above satisfied, `wd12`/`wd108` tenants (`capitalone expedia
salesforce slack turo`) serving 200s throughout — fired on **three consecutive
Saturdays**: 2026-09-19T07:03Z, 2026-09-26T07:03Z, 2026-10-03T07:00Z. The
2026-09-26 window closed in about one hour (last error 07:32Z, clean from 08:00Z)
and destroyed nothing. Three identical self-healing texts in three weeks is a
reader being trained to swipe away the key that also carries real findings, which
is the mechanism of the 2026-08-29 missed text.

**The escalation backstop is what makes log-only safe, and it needs no new code.**
Condition 2 is a ≤`STALE_AFTER_HOURS` clock, not an exemption: if the window
outlasts 6h, **A1 fires on its own**, condition 2 breaks, the cluster stops
qualifying for this branch, and it classifies as ordinary DEGRADED and texts. So
a maintenance window that turns into a real outage alerts automatically. Likewise
a vendor break that is *not* maintenance (condition 3) or that *destroys rows*
(condition 4) never enters this branch at all. Re-probe every run — this branch is
never inherited from a previous run's verdict.

**Check A3 — latched guard** (a company whose recent runs ALL got guard-skipped —
it runs, returns a non-zero count, and writes **nothing** to `job_listings`).
This is the check that was missing on 2026-08-28: the Apple scraper collapsed to
17 jobs/run, tripped the `empty_scrape` guard every run, and stayed invisible to
A1 (jobs_seen=17>0 kept `last_ok` fresh), A2 (17≠0), and D (counted as scraped-ok)
for 3.5 days. Every prior check asks "did anything come back?"; this asks "did the
run actually **do** anything?". See
`docs/incidents/2026-08-28-apple-pagination-single-page.md`.

```sql
WITH lastN AS (
  SELECT company, jobs_seen, skipped_update, guard_reason, started_at,
         row_number() OVER (PARTITION BY company
                            ORDER BY started_at::timestamptz DESC) AS rn
  FROM scrape_runs
)
SELECT l.company, c.ats,
       count(*) FILTER (WHERE l.skipped_update)  AS skipped_of_last4,
       -- all distinct reasons across the latched runs (not max(), which would
       -- report only the lexicographically-largest of a mixed empty/partial latch)
       string_agg(DISTINCT l.guard_reason, ',')  AS guard_reasons,
       min(l.jobs_seen) AS min_seen, max(l.jobs_seen) AS max_seen
FROM lastN l
JOIN companies c ON c.id = l.company
WHERE c.enabled AND l.rn <= 4          -- GUARD_LATCH_MIN_RUNS (see below)
GROUP BY l.company, c.ats
HAVING count(*) = 4                     -- GUARD_LATCH_MIN_RUNS
   AND count(*) FILTER (WHERE l.skipped_update) = 4   -- GUARD_LATCH_MIN_RUNS
ORDER BY l.company;
```

> **Keep the three `4`s above in step with `GUARD_LATCH_MIN_RUNS`.** This is a
> SQL-in-Markdown check with no runtime binding, so the literal is inlined the
> same way every other check inlines its tunable (A1 hardcodes `interval '6
> hours'` for `STALE_AFTER_HOURS`, etc.). If you retune `GUARD_LATCH_MIN_RUNS`,
> change all three occurrences here (the `rn <= N` bound, the `count(*) = N`
> floor, and the all-skipped `= N`). They MUST match: `rn <= N` selects at most N
> rows, `count(*) = N` requires a full window of N, and the FILTER `= N` requires
> all N skipped.

A row here means the company runs and writes nothing, and (for `empty_scrape`)
will NOT self-heal: `resolve_safety_guard`'s bounded auto-release counts
`partial_scrape` only (`incremental.py:count_consecutive_partial_skips`), so
`empty_scrape` latches forever until a human acts. The 4-run floor
(`GUARD_LATCH_MIN_RUNS`) is why a normally auto-releasing `partial_scrape` can
never trip this: it releases by the 3rd consecutive skip, so 4 consecutive skips
means a non-releasing latch.

**Before alerting, PROBE THE BOARD — a latch is not by itself a bug.** A row
tells you the scraper wrote nothing; it does not tell you whether there was
anything to write. Those are different incidents with opposite fixes, and the
board's own API separates them in one request. For an ATS-backed company
(`ats` in greenhouse/ashby/lever/gem — skip this for `script` and `recipe`,
which have no single token to probe), fetch the endpoint in §6's probe table for
the stored `board_token` and branch on the result:

| Probe result | Meaning | Action |
|---|---|---|
| **404 / connection error** | the board moved or was deleted | **CRITICAL** `guard_latched:<company>`, and run §6 board research — this is PR-able |
| **200 with > 0 jobs** | the board is serving roles we are not writing | **CRITICAL** `guard_latched:<company>`, text-only — a genuine scraper bug |
| **200 with 0 jobs** | the scraper AGREES with the board | **NOT critical** — informational, see below |

**Why 200-with-0-jobs must not page.** The scraper is correct: the company took
its roles down and our zero matches theirs. Paging CRITICAL on every run for a
company that is simply not hiring trains the reader to ignore the key that also
fires for real outages, which is how the 2026-08-29 missed text happened. The
alert-fatigue risk here is the actual hazard, not the empty board.

MEASURED, 2026-09-11 — the case this rule was written from. `console` latched on
`empty_scrape` and paged CRITICAL. Its careers page still showed 17 roles, and
the first read of that was "the board is fine, our scraper broke". It was the
opposite: **console.com/careers is a Framer page with 17 hand-written
`jobs.ashbyhq.com/console/<uuid>` links**, and the board behind them is empty —
posting API `{"jobs": [], "apiVersion": "1"}`, the embed GraphQL 0 postings, and
a posting fetched **by id** returns `null`. Console removed the roles from Ashby
and never updated their marketing site. The scraper was right the whole time.

**Do not read a careers page to decide whether a board is alive.** A hardcoded
link is indistinguishable from a live one, and `jobs.ashbyhq.com/<board>/<uuid>`
answers **HTTP 200 for any path** because it is a JS shell — the same trap that
makes `_prove_job_link` blind on iCIMS boards. Only the API answers this.

**What the informational branch must say**, because suppressing the page has a
real cost: the guard stays latched, so every OPEN row for that company is frozen
— never refreshed, never closed — until a human closes them or disables the
company. Emit key `board_empty:<company>` on the 72h informational cooldown
(§4.3) carrying the frozen-row count and both facts that produced the verdict:
the probe result AND the stored token. Phrase it as a decision to make, not an
outage: *"console: Ashby board alive but empty (200, 0 jobs); 15 OPEN rows
frozen by the guard — close them or disable the company."*

Re-probe on every run. A company that comes back (200 with > 0 jobs) while still
latched flips straight to CRITICAL, which is the case this branch must never
swallow.

**Check B — mass closures** (the 2026-03-29 incident closed 3,582 Apple jobs in
~6 minutes; see `docs/incidents/2026-03-29-mass-job-closure.md`):

```sql
WITH recent AS (
  SELECT company, sum(closed_jobs) AS closed_24h
  FROM scrape_runs
  WHERE started_at::timestamptz > now() - interval '24 hours'
  GROUP BY company
),
open_now AS (
  SELECT company, count(*) AS open_rows
  FROM job_listings
  WHERE status = 'OPEN'
  GROUP BY company
)
SELECT r.company, r.closed_24h, coalesce(o.open_rows, 0) AS open_rows
FROM recent r
LEFT JOIN open_now o USING (company)
WHERE r.closed_24h >= 50 AND r.closed_24h > coalesce(o.open_rows, 0)
ORDER BY r.closed_24h DESC;
```

Plus the global alarm. It is **fleet-relative and shape-aware** — it must never be
a bare count compared against a constant, because the fleet grows and the constant
does not (see `MASS_CLOSE_GLOBAL_PER_COMPANY` for the 2026-09-17 drift). This one
query returns every number the rule needs, so the threshold can never be eyeballed:

```sql
WITH window_totals AS (
  SELECT coalesce(sum(closed_jobs), 0) AS closed_24h_total,
         coalesce(sum(new_jobs), 0)    AS new_24h_total
  FROM scrape_runs
  WHERE started_at::timestamptz > now() - interval '24 hours'
),
corpus AS (
  SELECT count(*) AS open_rows_total FROM job_listings WHERE status = 'OPEN'
),
fleet AS (
  SELECT count(*) AS enabled_companies FROM companies WHERE enabled
)
SELECT w.closed_24h_total,
       w.new_24h_total,
       c.open_rows_total,
       f.enabled_companies,
       -- MASS_CLOSE_GLOBAL_FLOOR / MASS_CLOSE_GLOBAL_PER_COMPANY
       greatest(1000, 10 * f.enabled_companies) AS close_alarm_threshold,
       -- >0 means the corpus net-shrank; <0 means it grew despite the closures
       round(((w.closed_24h_total - w.new_24h_total)::numeric)
             / nullif(c.open_rows_total, 0), 4) AS net_shrink_fraction
FROM window_totals w CROSS JOIN corpus c CROSS JOIN fleet f;
```

Alert if **any per-company row returns** from the query above, or if the global
numbers meet BOTH global conditions:

1. `closed_24h_total >= close_alarm_threshold` — the volume is abnormal *for this
   fleet size*, and
2. `net_shrink_fraction >= 0.05` (`MASS_CLOSE_NET_SHRINK_MIN`) — the OPEN corpus
   actually shrank, i.e. jobs were destroyed rather than churned.

Both ⇒ CRITICAL `mass_closure:global` (§4.2, re-texts every run).

**Volume over threshold but the corpus grew or held flat** (condition 1 without
condition 2) is **not** an outage and must not page: emit INFORMATIONAL
`close_volume_high:global` on the 72h cooldown (§4.3) carrying all four raw
numbers, e.g. *"closures 2310/1930 over the fleet-relative alarm but the corpus
grew (3400 new vs 2310 closed) — churn, not an outage; re-check the alarm level
if this repeats."* That branch is the standing guard against the failure mode this
check has already had once: re-texting CRITICAL at every run while every other
signal (per-company Check B empty, full coverage, live heartbeat, growing corpus)
says the fleet is healthy.

Sanity-check the shape before believing a global number either way: a **business-hours
curve** (a low overnight floor rising to a single daytime peak) is normal ATS churn.
A real mass closure is a **spike** — thousands of rows inside minutes (2026-03-29:
3,582 Apple jobs in ~6 minutes), and it lands on one company, so Check B's per-company
arm fires first. If the per-company arm is empty and the hourly curve is business-hours
shaped, the global number is churn no matter how large it looks:

```sql
SELECT date_trunc('hour', started_at::timestamptz) AS hour_utc,
       sum(closed_jobs) AS closed
FROM scrape_runs
WHERE started_at::timestamptz > now() - interval '24 hours'
GROUP BY 1 ORDER BY 1;
```

**Check C — worker heartbeat:**

```sql
SELECT max(at) AS last_beat,
       round((EXTRACT(EPOCH FROM (now() - max(at)))/60.0)::numeric, 1) AS minutes_ago
FROM worker_heartbeats;
```

Alert if `last_beat` is NULL or `minutes_ago > 15`.

**Check D — coverage collapse** (the single unmissable number: how many tracked
companies actually produced a successful scrape in the last day). Independent of
Check C — it fires even if the heartbeat mechanism itself is lying, and it is the
signal that would have screamed on 2026-08-29 when only the 5 standalone Python
scrapers kept running while all 128 worker-driven companies went dark:

```sql
SELECT
  count(*) FILTER (WHERE c.enabled) AS enabled,
  count(*) FILTER (WHERE c.enabled AND f.company IS NOT NULL) AS scraped_ok_24h
FROM companies c
LEFT JOIN (
  SELECT DISTINCT company
  FROM scrape_runs
  WHERE started_at::timestamptz > now() - interval '24 hours'
    AND jobs_seen > 0
    -- A guard-skipped run returned rows but wrote nothing, so it is not a
    -- "successful scrape" for coverage purposes (same reasoning as A1/A3).
    AND skipped_update IS NOT TRUE
) f ON f.company = c.id;
```

Alert **CRITICAL** (key `coverage_collapse`) if `scraped_ok_24h <
COVERAGE_MIN_FRACTION * enabled`. Carry the raw ratio into the text
(`only 5/133 scraped in 24h`) — that one line is the whole point: a per-company
staleness list (Check A) can bury a total collapse; this number cannot.

## §3 Phase 2 — Classify

Severity — highest wins, and it decides the alert cadence (§4):

- **CRITICAL** — an active outage: worker heartbeat dead (C), coverage collapse
  (D), a mass closure (B — a per-company row, or the global alarm with **both**
  its conditions met: fleet-relative volume AND a net-shrinking corpus), or a
  latched guard (A3 — a company that runs but writes
  nothing) **whose board probe did not come back 200-with-0-jobs**. These
  **re-alert on every run until resolved** — never suppressed by the 72h window
  (§4.2). A3 is text-only when the board still serves jobs (a scraper code bug a
  human must fix); a 404 probe makes it PR-able board research instead (§6).
- **INFORMATIONAL — `board_empty:<company>`** — A3 latched AND the board probed
  200 with 0 jobs. The scraper agrees with the board; the company stopped
  hiring. Not an outage, so it takes the 72h cooldown (§4.3) rather than paging
  every run. It still has to be said, because the latch freezes every OPEN row
  for that company until a human closes them or disables it.
- **INFORMATIONAL — `close_volume_high:global`** — Check B's global volume arm
  tripped but the OPEN corpus did not net-shrink (and no per-company row fired).
  High churn on a growing fleet, not an outage, so it takes the 72h cooldown
  (§4.3) instead of paging every 3h. Read it as a request to re-check the alarm
  level, not as a closure event; if it recurs for more than a week or two the
  fleet has outgrown `MASS_CLOSE_GLOBAL_PER_COMPANY` and that constant — not this
  run's verdict — is what needs changing.
- **INFORMATIONAL (log-only) — `vendor_maintenance:<ats>`** — an A2 cluster of
  ≥`VENDOR_MAINTENANCE_MIN_COMPANIES` companies sharing one `ats`, satisfying all
  five conditions in A2's vendor-maintenance branch (A1 clean, vendor maintenance
  page on a live probe, nothing written or closed, a same-`ats` tenant on another
  pod healthy). The scraper is correct and the vendor is mid-window. **Recorded in
  the heartbeat line, never texted, never a PR** — there is no human action for
  another vendor's maintenance, and the window recurs weekly, so any cooldown
  short enough to be useful also makes it a weekly false page. If the window
  outlasts `STALE_AFTER_HOURS` the companies enter A1 and the run re-classifies
  them as ordinary DEGRADED, which does text. Verified, never assumed: a cluster
  that fails any of the five conditions is DEGRADED, not this.

- **DEGRADED** — per-company staleness / silent-zero (A) with the fleet still
  broadly healthy; carry the per-company list (id, ats, board_token, hours dark,
  signals). PR-able board moves dedupe on the open PR (§4.1).
- **UNKNOWN** — any check errored or returned something unparseable. Treated as
  CRITICAL for alerting (`unknown_prod`); never downgrade to OK.
- **OK** — A/B/C/D all clean.

## §4 Phase 3 — Dedupe gate (dedupe drift, NEVER an active outage)

1. **Board-move incidents** (PR-able): run
   `gh pr list --state open --label scraper-health --json number,url,body`.
   Each watchdog PR body carries a machine-readable line `Companies: id1, id2`.
   A degraded company already named in any open scraper-health PR is
   **suppressed** — no new PR, no text for it. (The open PR is the incident
   record; merging it fixes the scraper and the SQL goes green. A PR closed
   without merging naturally re-alerts on the next run.)
2. **CRITICAL alerts re-text on EVERY run — no 72h suppression.** Keys
   `heartbeat_dead`, `coverage_collapse`, `mass_closure:global`,
   `mass_closure:<company>`, `guard_latched:<company>`, `unknown_prod`. **Why this is not "spam":** the
   2026-08-29 incident — `heartbeat_dead` was texted once, then this gate
   suppressed it for 72h; that single text was missed and prod stayed dark 61h.
   An ongoing, actionable outage MUST keep alerting until it clears. Re-send every
   run and make each message escalate (§9) — carry the elapsed duration/day-count
   so a repeat reads as "still down, and longer," never as an identical dupe.
   `state.json` still records `last_texted` + a `first_texted` per critical key
   (for the heartbeat line and the escalation math), but it does **not** gate the
   send.
3. **Informational alerts keep the 72h cooldown** — these are known needs-human
   items, not live outages, so nagging adds nothing: keys `notfound:<company>`,
   `board_empty:<company>`, `close_volume_high:global`, `drill:<scenario>`. Suppress the text if the same key
   was texted within 72h; still record the finding in the heartbeat line.
   `board_empty` sits here rather than under CRITICAL because the scraper is
   behaving correctly — but note it is the one informational key that can flip:
   if the board later probes 200 with > 0 jobs while the guard is still latched,
   it becomes `guard_latched:<company>` and loses the cooldown.
   **`vendor_maintenance:<ats>` is NOT in this group** — it is log-only (§3), so
   it never texts and needs no `state.json` entry at all. A 72h cooldown cannot
   gate a weekly recurrence: it expires before the next window and the key then
   pages every week forever.
4. If everything found is a §4.1/§4.3 suppression (no CRITICAL active): append the
   heartbeat line with `suppressed=<ids/keys>` and end (weekly all-clear still
   applies, §9).

## §5 Phase 4 — Upstream probes (trivial research path)

For each non-suppressed degraded company, confirm upstream state yourself before
any deeper research (per-ATS live checks, same table as
`.claude/skills/add-company/SKILL.md` Step 0):

| ATS | Probe |
|-----|-------|
| greenhouse | `https://boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true` |
| ashby | `https://api.ashbyhq.com/posting-api/job-board/<token>` — lowercase, case-sensitive |
| lever | `https://api.lever.co/v0/postings/<token>?mode=json` |
| gem | `https://api.gem.com/job_board/v0/<token>/job_posts/` |
| smartrecruiters | `https://api.smartrecruiters.com/v1/companies/<token>/postings` — **200 with `totalFound: 0` means unknown company, not a hit** |

1. Probe the company's **current** board (its `ats`/`board_token` from Check A).
   If it now returns jobs, the outage self-healed — drop it from the work list
   and note `self_healed` in the heartbeat line.
2. Guess-probe the other ATSes with obvious candidates: the current
   `board_token`, the company `id`, and simple variants (with/without dashes,
   `-ai`/`-hq` suffixes, company display name slugified).
3. A **hit** = HTTP 200 **and** jobs count > 0 **and** the jobs plausibly belong
   to that company (sanity-check a couple of titles/URLs; job count within ~3×
   of the company's frozen OPEN rows is a good corroboration signal).
   Record every probe (URL → status/count) as evidence for the PR body.

## §6 Phase 5 — Research subagent (non-trivial cases)

For each company the trivial path did not resolve, spawn ONE subagent via the
Task/Agent tool (`subagent_type: "general-purpose"`), then **independently
re-probe** any claim it returns before writing code — a subagent claim alone is
never sufficient. Prompt template:

```
Find where <DISPLAY NAME> (company id "<id>") hosts its job board now.
Old board: <ats>/<board_token> — confirmed dead (<evidence: 404 / 200-empty>).
Careers URL from our config: <url from companies.ts>.

Timebox yourself to ~10 minutes. Procedure:
1. Fetch the careers URL (WebFetch); follow "open roles"/"apply" links; look for
   ATS hostnames in hrefs (greenhouse.io, ashbyhq.com, lever.co, gem.com,
   myworkdayjobs.com, smartrecruiters.com, eightfold.ai).
2. Web-search: "<display name>" jobs site:jobs.ashbyhq.com, site:boards.greenhouse.io,
   site:jobs.lever.co, "<display name> careers <ats-name>".
3. Probe every candidate token against the ATS API endpoints:
   greenhouse https://boards-api.greenhouse.io/v1/boards/<t>/jobs
   ashby      https://api.ashbyhq.com/posting-api/job-board/<t>   (lowercase)
   lever      https://api.lever.co/v0/postings/<t>?mode=json
   gem        https://api.gem.com/job_board/v0/<t>/job_posts/
   A hit is HTTP 200 with >0 jobs that are plausibly this company's.

Return ONLY strict JSON:
{"company": "<id>",
 "verdict": "found" | "unsupported" | "gone" | "inconclusive",
 "new_ats": "<greenhouse|ashby|lever|gem|eightfold|workday|null>",
 "new_token": "<token|null>",
 "evidence": ["<probe URL -> result>", "..."]}
"unsupported" = board found on an ATS this repo has no client for (say which).
"gone" = affirmative evidence the company stopped hiring/board removed.
"inconclusive" = you could not determine it — never guess.
```

Map verdicts to actions: `found` (and parent re-probe confirms) → include in the
fix PR (§7). `unsupported`/`gone` **with affirmative evidence** → include as a
soft-disable (unity3d precedent). `inconclusive` → text-only finding
(`notfound:<company>` alert key), **no code change** — never act on absence of
evidence.

## §7 Phase 6 — Build the fix (throwaway worktree)

Skip this phase entirely if no company reached `found`/`unsupported`/`gone`.

1. From the repo checkout you run in:
   `git fetch origin main` then
   `git worktree add .claude/worktrees/health-watch-<YYYYMMDD-HHMM> origin/main -b fix/board-move-<YYYYMMDD>`
   (suffix `-2` etc. on branch collision). Work **only** inside it; `git -C` or
   `cd` there for every command below.
2. **One batched migration for all companies in this run** (single-head
   discipline: two open PRs that both chain off the same head cannot both merge
   cleanly — this is why the run batches). Copy
   `.claude/skills/scraper-health-watch/templates/migration_repoint.py.tmpl` to
   `src/backend/alembic/versions/<UTCnow %Y%m%d_%H%M%S>_<rev>_repoint_moved_boards.py`
   and fill every `{{SLOT}}`. Generate `<rev>` with
   `python3 -c "import uuid; print(uuid.uuid4().hex[:12])"`. Determine
   `{{DOWN_REVISION}}` (the current head) and later verify single-head with:

   ```bash
   python3 - <<'EOF'
   import re, pathlib
   revs, downs = {}, set()
   for p in pathlib.Path('src/backend/alembic/versions').glob('*.py'):
       t = p.read_text()
       m = re.search(r"^revision(?::\s*\w+)?\s*=\s*['\"]([0-9a-f]+)['\"]", t, re.M)
       if m: revs[m.group(1)] = p.name
       # A MERGE migration writes a TUPLE: down_revision = ('abc', 'def').
       # Capture the whole RHS and pull every hash out of it — matching only a
       # single quoted string here (as this check used to) makes a merge's
       # parents invisible, and an unseen parent is reported as a head. That
       # read 9 phantom heads on a genuinely single-head main (2026-10-03),
       # i.e. the check failed 100% of the time and verified nothing.
       d = re.search(r"^down_revision(?::[^=]*)?\s*=\s*(.+)$", t, re.M)
       if d: downs.update(re.findall(r"['\"]([0-9a-f]{8,})['\"]", d.group(1)))
   heads = [r for r in revs if r not in downs]
   print('HEADS:', [(h, revs[h]) for h in heads])
   raise SystemExit(0 if len(heads) == 1 else 1)
   EOF
   ```

   If this prints more than one head, **confirm with real Alembic before
   believing it** (`alembic heads`) — and if the extra "heads" are all files
   whose names say `merge`, you are looking at a parser artifact, not a branched
   history.

   Expected rowcounts for the stale-row close-out come from live SQL (read-only):
   `SELECT count(*) FROM job_listings WHERE company = '<id>' AND source_id = '<old_ats>_api' AND status = 'OPEN'`.
   Rowcounts are **logged, not asserted** in the migration (a7c31d9e0b46 pattern);
   the fixed `closed_on` sentinel (today's date, `T00:00:00+00:00`) is what makes
   `downgrade()` surgical. The close-out executes **at deploy time, after merge —
   Brendan's control point**.
3. **Frontend `src/frontend/src/config/companies.ts`:** move each repointed
   company's `createBackendScraperCompany(...)` entry into its new ATS section
   with the new `sourceAts` and board URL (`https://jobs.ashbyhq.com/<token>`
   form for Ashby). The `id` and `COMPANY_IDS` enum member never change (PK +
   logo key). For soft-disables, remove the entry + enum member (unity3d
   precedent, see commit `0a6ddf9`).
4. **`src/frontend/src/config/changelog.ts`:** one new top entry modeled on id
   `ats-migrations-2026-07` (user-facing tone, `tags: ['improvement']`).
5. **Checks (all inside the worktree):**
   - `npm ci --no-audit --no-fund` then `npm run type-check` (if `npm ci` fails,
     note "type-check not run: <reason>" in the PR body — degraded PR beats no PR)
   - `python3 -m py_compile src/backend/alembic/versions/<newfile>.py`
   - the single-head check above
6. Commit with a conventional title, e.g.
   `fix(companies): re-point fireworksai and thinkingmachines to Ashby`.
   Plain commit message. **No attribution footers.**

## §8 Phase 7 — Push + PR

```
git push -u origin fix/board-move-<YYYYMMDD>
gh pr create --title "<conventional title>" --label scraper-health --body-file <body>
```

Body from `templates/pr_body.md.tmpl` — the `Companies:` line is load-bearing
(dedupe, §4). Create the label first if missing:
`gh label create scraper-health --color B60205 --description "Opened by scraper-health-watch" || true`.
Never merge; never `--auto`. Then `git worktree remove <path> --force` (the
branch stays pushed).

## §9 Phase 8 — Text Brendan

Compose ONE message covering everything found this run (≤3 sends per run only
when chunking forces it; send.sh chunks long messages itself):

```
JVN health: 2 scrapers down
fireworksai: dark 5d (greenhouse 404 -> ashby/fireworks, 49 jobs)
thinkingmachines: dark 1d (greenhouse 404 -> ashby/thinkingmachines, 35 jobs)
Fix PR: <url>
```

- One line per company: `id: dark Nd (<old evidence> -> <destination or verdict>)`.
- Non-PR findings get their own line (`worker heartbeat DEAD 47m`,
  `apple: guard-latched, 4/4 runs skipped (empty_scrape, 17 jobs) — scraper writing nothing`,
  `could not determine prod health (MCP error)`, `board not found — needs a human`).
- A `mass_closure:global` line always names the number **and the fleet-relative
  level it beat**, so the reader can judge it without opening the log:
  `mass closure: 4820 closed/24h vs 1930 alarm, corpus -9% (193 companies)`.
  Never text a bare closed count — a count with no denominator is exactly what
  made the 2026-09-17 false alarm unreadable as a false alarm.
- A `board_empty` finding names the probe AND the consequence, so the reader can
  tell it apart from a latch that IS a bug and knows what is being asked of them:
  `console: Ashby board alive but empty (200, 0 jobs) — 15 OPEN rows frozen by the
  guard; close them or disable the company`. Never write it as "dark" or
  "broken" — the scraper is agreeing with the board.
- **CRITICAL escalation (§4.2):** when a CRITICAL key is still active on a repeat
  run, lead with the elapsed duration and a day counter so each send is visibly
  worse and can never be mistaken for a prior text, e.g.
  `JVN health CRITICAL day 3: worker DEAD 61h — only 5/133 scraping. Restart Railway.`
  Derive elapsed from the finding itself (heartbeat `minutes_ago`, or
  `now - state.json.first_texted[key]`).
- **A `vendor_maintenance:<ats>` finding is NEVER a line in the text** (§3) — it
  is log-only. If it is the run's *only* finding, send nothing at all and let the
  heartbeat line carry it. The weekly all-clear below is still evaluated: a run
  whose sole finding is a vendor maintenance window is not `OK`, so it does not
  send one either.
- `[DRILL]` prefix in drill mode.
- **Weekly all-clear:** if verdict is OK and `state.json.last_allclear` is
  missing or older than **6.5 days**, send
  `JVN health: all clear (<N> sources healthy). Watchdog alive.`
- After ANY successful send (exit 0), update `state.json`: set `last_texted` for
  each alert key just sent (ISO timestamp); for a CRITICAL key, set `first_texted`
  only if not already present (so escalation can measure how long it's been down);
  and set `last_allclear = now` (every text proves liveness). When a CRITICAL key
  comes back clean on a later run, clear its `first_texted`/`last_texted` so the
  next occurrence starts a fresh escalation.
- On send failure: `ALERT-SEND FAILED` to stderr, do not retry-loop; the
  heartbeat line still records what should have been sent.

## §10 Phase 9 — Heartbeat + status block (FINAL step)

Append exactly one line to `~/Library/Application Support/jvn-health-watch/heartbeat.log`
(create the directory if needed):

```
2026-08-05T16:03Z verdict=DEGRADED severity=degraded checked=133 coverage=131/133 stale=fireworksai,thinkingmachines guard_latched=none mass_closure=none(612/1330) heartbeat_min=3 pr=https://github.com/.../pull/NNN texted=1 suppressed=none
```

`mass_closure=` always carries the global arm's raw ratio, even when clean:
`mass_closure=none(1027/1930)` — observed `closed_24h_total` over the
fleet-relative `close_alarm_threshold`. That makes threshold drift visible in the
log *before* it starts paging: a ratio creeping toward 1.0 over successive runs is
the fleet outgrowing the constant, and is the cue to raise
`MASS_CLOSE_GLOBAL_PER_COMPANY` rather than to wait for a false CRITICAL. Use
`mass_closure=global(2310/1930,shrink=0.07)` when it fires and
`mass_closure=churn(2310/1930,shrink=-0.03)` for the informational branch.

`vendor_maintenance=` carries the log-only A2 cluster branch, naming the ats, the
cluster size over the enabled count for that ats, and the pods, e.g.
`vendor_maintenance=workday(11/16,wd1+wd5)` — or `none`. This is the field that
makes a silent run auditable: because the branch never texts, the log line is the
*only* record that 11 companies were dark and why it was correct not to page. A
run carrying it reads `verdict=DEGRADED` with `stale=none`, which is the signature
to look for.

`guard_latched=` lists any Check A3 companies (comma-separated ids, or `none`) —
a run where `guard_latched=apple` but `coverage` and `stale` look fine is exactly
the 2026-08-28 blind spot reading correctly at last.

Always include `severity=` (ok|degraded|critical|unknown) and `coverage=<scraped_ok_24h>/<enabled>`
(Check D) — a collapse then reads at a glance in the log, e.g. a worker-death run is
`verdict=CRITICAL severity=critical checked=133 coverage=5/133 mass_closure=none(0/1330) heartbeat_min=3648 ... texted=1 suppressed=none`.
(`verdict=OK ... coverage=133/133 mass_closure=none(612/1330) ... pr=none texted=0` on the quiet path.) The
launchd wrapper checks this file's mtime advanced — skipping this line makes the
wrapper report the run as failed. Print the same line as the final status block,
then end the turn immediately (headless: no further tool calls).

## §11 Edge cases

| Situation | Action |
|---|---|
| Board moved to an ATS with no client in this repo (`unsupported`, affirmative evidence) | Soft-disable PR (`enabled = FALSE`, listings untouched — unity3d precedent); text names the ATS it moved to |
| Research inconclusive | Text-only (`notfound:<company>`), NO code change |
| Company seeded <`WARM_UP_HOURS` ago, no runs yet | Not degraded — A1's warm-up guard drops it. It re-enters A1 automatically once it ages past the window; A2 already covers a bad `board_token` |
| Current board self-healed by probe time | Drop from work list, note `self_healed` in heartbeat |
| Prod MCP unreachable / query error | verdict UNKNOWN, text (key `unknown_prod`), no PR |
| Alembic head moved between reading it and committing | Re-read head, re-parent the new migration, retry once |
| `gh` unauthenticated or push rejected | Text without PR link + `ALERT-SEND` the failure detail; loud stderr |
| >1 company degraded | One batched PR, one text listing all |
| Global closure volume high, but per-company Check B empty AND corpus grew | NOT a mass closure — informational `close_volume_high:global` on the 72h cooldown. Never CRITICAL, never a PR. Recurring for >1–2 weeks means raise `MASS_CLOSE_GLOBAL_PER_COMPANY`, not mute the check |
| Fleet size changed a lot since the thresholds were last reviewed | Nothing to do — the global closure alarm and Check D are both fleet-relative by construction. Only `MASS_CLOSE_COMPANY_MIN` is absolute, and Check B scales it per company |
| Branch `fix/board-move-<date>` already exists | Suffix `-2`; if an OPEN PR exists for it, treat as dedupe hit instead |
| A2 fires for a cluster of companies sharing one `ats` | Do NOT read it as N board moves. Run A2's five-condition vendor-maintenance check first; all five hold ⇒ log-only `vendor_maintenance:<ats>`, no text, no PR. Any condition unverified ⇒ ordinary DEGRADED |
| A vendor maintenance window outlasts `STALE_AFTER_HOURS` | Nothing to do — the companies enter A1, condition 2 breaks, and the run classifies them DEGRADED and texts automatically. The log-only branch cannot hide a window that became an outage |
| send.sh missing/broken | stderr `ALERT-SEND FAILED`; heartbeat records it; wrapper's own 72h-cooldown failure text is the backstop |
