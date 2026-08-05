---
name: smoke-test-deployed
description: |
  Post-merge verification of the deployed production environment
  (https://onesecondswe.dev). Run this after every squash-merge to main:
  it waits for the Vercel and/or Railway deploys triggered by the merge to
  settle, then runs a browser smoke test, read-only prod SQL sanity checks,
  and a Railway log scan, and returns a structured PASS/FAIL verdict with
  evidence. Trigger on: "smoke test prod", "verify the deploy", "check prod
  after merge", "post-merge verification".
trigger_phrases:
  - smoke test prod
  - smoke test the deploy
  - verify the deploy
  - verify prod
  - post-merge verification
  - check prod after merge
required_tools:
  - Bash
  - mcp__playwright__browser_navigate
  - mcp__postgres-prod__query
mode: read-only
---

# smoke-test-deployed — verify prod after a merge to main

## Invocation arguments (the caller MUST pass these)

- `scope`: `backend` | `frontend` | `both` — which side the merged PR touched
  (backend = anything under `src/backend/**`).
- `merge_sha`: the squash-merge commit sha on main. If omitted, resolve with
  `git fetch origin main --quiet && git rev-parse origin/main`.
- `expect_migration` (optional): the alembic revision id that should be the
  single row in `alembic_version` after this deploy. Pass it whenever the PR
  shipped a migration.
- `extra_checks` (optional): free-text list of ticket-specific assertions,
  e.g. "navigate to /companies and assert the trend graph renders" or a
  read-only SQL assertion.

Identifiers used throughout:
- Railway: project `onesecondswe`, service `Job-Visualizer-Notifier`,
  environment `production`.
- Vercel: project `job-visualizer-notifier`,
  team `team_k1U3D3dnN1fV5XnqAzCUg0MF`.
- Site: https://onesecondswe.dev

## Step 0 — Anchor the merge

```bash
git fetch origin main --quiet
git show -s --format='%H %cI %s' <merge_sha>
```

Record the sha and the commit time (this is the "deploy window" start for log
scans).

> **`[vercel-skip]` does NOT suppress production builds in this project.**
> Observed 2026-08-04/05: commits tagged `[vercel-skip]` still produced a
> Vercel production deployment. Treat a tagged commit as still deploying and
> poll for it in Step 1a; do not record `SKIPPED` on the strength of the tag.

## Step 1 — Wait for deploys to settle

Run 1a and 1b as applicable to `scope`. Poll; do not sleep blind.

### 1a. Vercel (always — see the `[vercel-skip]` note in Step 0)

Poll Vercel deployments for project `job-visualizer-notifier` (MCP
`list_deployments`, target production) every **20s, timeout 10 minutes**
(typical build 1–3 min). Find the deployment whose git metadata commit sha
equals `merge_sha` — NEVER just take the newest deployment (another merge or
a weekly bot PR may have deployed in between).

- Settled = state `READY`.
- State `ERROR` = build failed → pull `get_deployment_build_logs` for that
  deployment id, capture the last ~40 lines, and go to the Verdict step with
  FAIL. Note: prod keeps serving the previous build — Vercel deploys are
  atomic — so this is not an outage.
- No deployment matching the sha after 10 min → fallback check via GitHub:
  `gh api repos/brendanpotter00/Job-Visualizer-Notifier/commits/<merge_sha>/status --jq '{state: .state, contexts: [.statuses[].context]}'`
  If GitHub shows no Vercel status either, FAIL (classification: infra,
  "Vercel never picked up the merge").

### 1b. Railway (ONLY if scope includes backend — the service watch path is src/backend/**)

First confirm a deploy is actually expected:
```bash
git diff --name-only <merge_sha>^ <merge_sha> -- src/backend/ | head
```
If that is empty, skip 1b entirely (watch path will not trigger).

Poll Railway `list_deployments` for project `onesecondswe`, service
`Job-Visualizer-Notifier`, environment `production`, every **30s, timeout 15
minutes** (build 2–6 min, plus the healthcheck probe). Match the
deployment to `merge_sha` via its commit metadata; if the API does not
expose the sha, take the oldest deployment created AFTER the merge commit
time from Step 0.

- Settled = status `SUCCESS`, and **`SUCCESS` means the `/health/worker`
  probe passed.** The settled manifest reads
  `healthcheckPath = /health/worker`, matching the repo's `railway.toml`, and
  the probe demonstrably ran (200) on the `2cbb7e0` deploy. Trust the status.
  - **Read `healthcheckPath` off the SETTLED deployment record only.** The
    field is populated as the deploy settles: on a record still in `WAITING`
    (or otherwise mid-flight) it reads `null`, which says nothing about the
    service's configuration. So resolve the deployment to `SUCCESS` *first*,
    then read the manifest off that same record. Reading it off an in-flight
    record and treating the `null` as configuration is the mistake to avoid.
  - *Historical note:* between 2026-08-04 and 2026-08-05 two smoke runs read
    `healthcheckPath = null` and this step carried a caveat treating `SUCCESS`
    as "container started" only. Those sightings were most likely the
    read-too-early artifact above rather than real config drift — both were
    taken while the deploy was still settling. Caveat retired. Kept as a dated
    line so a genuine recurrence is recognised fast instead of rediscovered,
    but check the read timing before concluding drift.
  - Still corroborate worker liveness in Step 3 via DB stream freshness (a
    recent `worker_heartbeats.at`, or `job_freshness` advancing within the
    last scrape interval). Not because the probe is untrusted, but because it
    checks the worker at *startup* — Step 3 is what catches a worker that
    died afterwards.
- Status `FAILED` or `CRASHED`, or the deployment keeps restarting: pull
  `get_logs` (build + deploy) for that deployment, capture any `Traceback` /
  `alembic` error lines, and FAIL. IMPORTANT extra check on this path:
  verify the OLD deployment is still serving (browser:
  https://onesecondswe.dev loads and `/api/jobs` returns 200). Report
  "prod still on previous deploy: yes/no" in the verdict — the caller's
  revert urgency depends on it.
- No new deployment appears within 3 minutes despite backend files having
  changed: FAIL (classification: infra, "Railway watch path did not
  trigger").

After both settle, wait **60 seconds** before Step 2.

## Step 2 — Browser smoke (host-side Playwright MCP, real public URL)

1. Navigate to `https://onesecondswe.dev/`.
2. Wait for job-list content (up to 15s), snapshot, and assert job cards
   render: at least one company/job card visible in the accessibility
   snapshot. A header-only or blank page = FAIL.
3. Console messages: assert ZERO error-level messages from our own bundle
   (stack pointing at /assets/*.js = hard FAIL; a lone third-party/extension
   error is recorded but not failing). Warnings ignored.
4. Network requests: every request to `/api/jobs` (and any other `/api/*`
   calls the page made) returned 200. Any 5xx = FAIL. A 4xx that is normal
   for anonymous users (auth-gated endpoints returning 401) is not a
   failure; a NEW 4xx is recorded and judged.
5. Run each `extra_checks` browser assertion passed by the caller.

Transient-failure guard: if any browser check fails, wait 60s and repeat
Step 2 ONCE from the navigate. Only a second consecutive failure counts.

## Step 3 — Read-only prod SQL sanity (mcp__postgres-prod__query)

1. Always: `SELECT version_num FROM alembic_version;` — assert EXACTLY ONE
   row (multiple rows = multi-head disaster, hard FAIL). If
   `expect_migration` was passed, assert the value equals it. If a migration
   shipped but `expect_migration` was not passed, record the value.
2. Always: `SELECT count(*) FROM companies;` — assert > 0 (connectivity +
   non-empty-DB sanity).
3. Backend scope: worker liveness, since Railway `SUCCESS` proves nothing
   (Step 1b). Assert a DB stream is still advancing — e.g.
   `SELECT max(at) FROM worker_heartbeats;` or `SELECT max(last_seen_at) FROM
   job_freshness;` — inside the last scrape interval.
4. **Resync / freshness correctness is DIRECTIONAL, post-sidecar-cutover.**
   Freshness now lives on `job_freshness`, not `job_listings`. The assertion
   that must hold is `freshness_behind = 0` (no listing whose sidecar row is
   older than what the scrape wrote). Total drift between the sidecar and the
   now-historical `job_listings` copy **grows by design** and is NOT a
   failure — and after the Unit 4 contract migration (`18fe9c20a8fd`) the
   parent columns are gone entirely, so any drift query written against them
   will error rather than return a number. Never treat a growing drift count
   as a regression; only `freshness_behind > 0` is one.
5. Run each `extra_checks` SQL assertion.

Gotcha (from CLAUDE.md): this MCP mis-renders `timestamptz -> timestamp`
casts as local time. For any time-elapsed assertion use
`EXTRACT(EPOCH FROM now())::bigint` comparisons, never `AT TIME ZONE`.

## Step 4 — Railway log scan (only when a Railway deploy happened in 1b)

`get_logs` for the NEW deployment, window = deploy start → now (only lines
since this deploy; do not scan the previous deployment's logs). Scan for:

- `Traceback` / `CRITICAL` / `ERROR` lines → any hit = record; a startup
  traceback or repeated identical tracebacks = FAIL.
- HTTP 5xx access-log lines → any = FAIL.
- Known noise to IGNORE: scraper-side 4xx from external ATS boards, and
  Procrastinate worker chatter at INFO level.

Optionally corroborate with Railway `http_error_rate` for the service over
the last 15 minutes (should be ~0% 5xx).

## Step 5 — Verdict (always produce this exact block)

```
SMOKE RESULT: PASS | FAIL
merge_sha: <sha>
scope: <backend|frontend|both>
vercel: READY <deployment-id-or-url> in <Xm Ys> | ERROR <evidence>
railway: SUCCESS <deployment-id> in <Xm Ys> (healthcheckPath=<path> read off the SETTLED deployment record; report it verbatim — a `null` read *after* the deploy settled means the drift recurred, so re-add the corroboration caveat; a `null` read mid-flight is just too-early and must be re-read) | SKIPPED (no src/backend changes) | FAILED <evidence> (prod still on previous deploy: yes/no)
browser: cards=<n>, console_errors=<n>, api_calls=<n>x200 [, retried_once=yes]
sql: alembic_version=<rev> (expected <rev>|n/a), companies=<n>, worker_stream_age=<Xm>, freshness_behind=<n>
logs: <n> 5xx, <n> tracebacks in deploy window | SKIPPED
extra_checks: <each with pass/fail>
classification: n/a | transient-suspected | code-regression | infra
```

Classification rules (this is what the caller keys the revert decision on):
- `code-regression`: a deterministic failure that reproduced on the Step 2
  retry, or two independent signals agree (e.g. /api/jobs 5xx in the browser
  AND a matching traceback in Railway logs; or alembic_version wrong AND
  startup traceback). The caller should revert the PR.
- `transient-suspected`: failed once, passed on retry — report it, verdict
  is still PASS with the retry noted. Failed twice but purely
  network-flavored (timeouts, a single edge 502, DNS) with logs clean and
  SQL clean → verdict FAIL but classification transient-suspected: the
  caller should re-run this whole skill once in 5 minutes BEFORE reverting.
- `infra`: deploy pipeline problems (Vercel never triggered, Railway watch
  path silent, build-infra errors unrelated to the diff). Reverting the PR
  usually will not help; the caller should notify the owner instead.

This skill never mutates anything: no re-deploys, no reverts, no DB writes.
The CALLER owns the response to FAIL (revert PR = `git revert <merge_sha>`
on a new branch + PR; if the failed change shipped a migration that already
applied, the revert PR MUST include a new forward migration that undoes the
schema change, because alembic only runs at deploy startup and prod DB
access is read-only).
