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
| `MASS_CLOSE_COMPANY_MIN` | 50 | per-company 24h closed_jobs floor |
| `MASS_CLOSE_GLOBAL` | 1000 | global 24h closed_jobs alarm |
| `HEARTBEAT_DEAD_MINUTES` | 15 | task writes every 5 min (`heartbeat.py:106`); app's own threshold is 10 min (`main.py:53`) |
| `WARM_UP_HOURS` | 6 | reuses the staleness window — a company seeded less than one window ago has not had time to tick; see A1's warm-up guard |
| `COVERAGE_MIN_FRACTION` | 0.5 | Check D floor — alert if fewer than half of enabled companies had a successful scrape in 24h. On the 2026-08-29 outage this read 5/133 (3.8%); anything under ~50% is a fleet-level failure, not per-company drift |

> **A1 and A2 filter on `c.enabled` only — they do NOT filter on `c.visibility`**, so private
> custom companies (E7, `visibility='user'`) are in scope. That is fine at the current cadence
> and was **not** fine before: custom boards ran on a 24 h cadence until 2026-08-29, so
> `last_ok` was older than the 6 h window for most of every day and every one of them would
> have tripped A1 permanently the moment the feature flag flipped. They now harvest hourly
> (`companies.cadence_hours = 1`), comfortably inside the window, so a custom board appearing
> in A1 is a real signal. If the cadence is ever slowed past `STALE_AFTER_HOURS` again, add
> `AND c.visibility = 'public'` here or raise the window — do not just mute the noise.

**Check A1 — staleness** (companies whose last non-zero scrape is old or absent):

```sql
WITH per_company AS (
  SELECT c.id AS company, c.ats, c.board_token, c.created_at,
         max(sr.started_at::timestamptz) FILTER (WHERE sr.jobs_seen > 0) AS last_ok,
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

Plus the global alarm:

```sql
SELECT coalesce(sum(closed_jobs), 0) AS closed_24h_total
FROM scrape_runs
WHERE started_at::timestamptz > now() - interval '24 hours';
```

Alert if any per-company row returns, or `closed_24h_total >= 1000`.

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
) f ON f.company = c.id;
```

Alert **CRITICAL** (key `coverage_collapse`) if `scraped_ok_24h <
COVERAGE_MIN_FRACTION * enabled`. Carry the raw ratio into the text
(`only 5/133 scraped in 24h`) — that one line is the whole point: a per-company
staleness list (Check A) can bury a total collapse; this number cannot.

## §3 Phase 2 — Classify

Severity — highest wins, and it decides the alert cadence (§4):

- **CRITICAL** — an active outage: worker heartbeat dead (C), coverage collapse
  (D), or a mass closure (B). These **re-alert on every run until resolved** —
  never suppressed by the 72h window (§4.2).
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
   `mass_closure:<company>`, `unknown_prod`. **Why this is not "spam":** the
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
   `drill:<scenario>`. Suppress the text if the same key was texted within 72h;
   still record the finding in the heartbeat line.
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
       d = re.search(r"^down_revision(?::[^=]*)?\s*=\s*['\"]([0-9a-f]+)['\"]", t, re.M)
       if m: revs[m.group(1)] = p.name
       if d: downs.add(d.group(1))
   heads = [r for r in revs if r not in downs]
   print('HEADS:', [(h, revs[h]) for h in heads])
   raise SystemExit(0 if len(heads) == 1 else 1)
   EOF
   ```

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
  `could not determine prod health (MCP error)`, `board not found — needs a human`).
- **CRITICAL escalation (§4.2):** when a CRITICAL key is still active on a repeat
  run, lead with the elapsed duration and a day counter so each send is visibly
  worse and can never be mistaken for a prior text, e.g.
  `JVN health CRITICAL day 3: worker DEAD 61h — only 5/133 scraping. Restart Railway.`
  Derive elapsed from the finding itself (heartbeat `minutes_ago`, or
  `now - state.json.first_texted[key]`).
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
2026-08-05T16:03Z verdict=DEGRADED severity=degraded checked=133 coverage=131/133 stale=fireworksai,thinkingmachines mass_closure=none heartbeat_min=3 pr=https://github.com/.../pull/NNN texted=1 suppressed=none
```

Always include `severity=` (ok|degraded|critical|unknown) and `coverage=<scraped_ok_24h>/<enabled>`
(Check D) — a collapse then reads at a glance in the log, e.g. a worker-death run is
`verdict=CRITICAL severity=critical checked=133 coverage=5/133 heartbeat_min=3648 ... texted=1 suppressed=none`.
(`verdict=OK ... coverage=133/133 ... pr=none texted=0` on the quiet path.) The
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
| Branch `fix/board-move-<date>` already exists | Suffix `-2`; if an OPEN PR exists for it, treat as dedupe hit instead |
| send.sh missing/broken | stderr `ALERT-SEND FAILED`; heartbeat records it; wrapper's own 72h-cooldown failure text is the backstop |
