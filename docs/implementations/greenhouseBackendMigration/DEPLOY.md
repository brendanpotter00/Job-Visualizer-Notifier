# Greenhouse Backend Migration — Deploy Runbook

This runbook covers the production deploy of the Greenhouse → backend cron+queue migration (Units 1–7 of [PLAN.md](./PLAN.md)). The entire change ships as a **single PR** spanning backend (Railway) and frontend (Vercel).

---

## Critical: Implicit Deploy Ordering

Even though Units 1–7 ship in one merge, the runtime deploys land on two different platforms with **different propagation timing**:

| Platform | What ships | Typical time to live |
|---|---|---|
| Railway (backend) | Units 1–6: Procrastinate runtime, `companies` table + seed, fetch task, fan-out cron, admin endpoints | ~2–4 min build + boot |
| Vercel (frontend) | Unit 7: `companies.ts` flipped to `backend-scraper`, `api/greenhouse.ts` **deleted** | ~1–2 min |

**The backend MUST be live with `/api/jobs?company=<id>` returning Greenhouse rows BEFORE frontend traffic hits the `backend-scraper` code paths.** If Vercel finishes first, frontend will request `/api/jobs?company=stripe` against a backend that hasn't yet (a) booted Procrastinate, (b) run the fan-out cron, (c) populated `job_listings` with `greenhouse_*` rows. Result: empty job lists for ~30 min until the first cron tick.

Mitigation: **the fan-out cron only runs every 30 min.** Don't wait — fire it manually as soon as Railway is healthy (see "First 30-min sanity check" below). This collapses the window from 30 min to ~30 sec.

A partial mid-PR rollback is **not possible** — `api/greenhouse.ts` is deleted in the same PR. If frontend goes live before backend, you cannot temporarily flip it back. Revert the merge commit instead.

---

## Pre-Merge Checklist

- [ ] **Env vars unchanged.** Procrastinate reuses `DATABASE_URL` — no new Railway secrets required. Confirm with `railway variables` that `DATABASE_URL` is set.
- [ ] **Migrations round-trip clean locally.**
  ```bash
  cd src/backend
  alembic upgrade head
  alembic downgrade -2
  alembic upgrade head
  ```
  Both the `add_companies_table` and `seed_greenhouse_companies` migrations must apply, revert, and re-apply without error.
- [ ] **`SAFETY_GUARD_RATIO=0.1` documented** in code (`scripts/shared/incremental.py:40`). If the Greenhouse API returns < 10% of currently-active jobs for a company, the task aborts before closing anything. This is the only thing standing between a Greenhouse outage and us closing every Stripe job in the DB.
- [ ] **Backend tests pass:** `pytest src/backend/` clean.
- [ ] **Frontend type-check + tests pass:** `npm run type-check && npm test -w src/frontend` clean.
- [ ] **No lingering `type: 'greenhouse'` references** in `src/frontend/src/config/companies.ts` — every Greenhouse entry is `createBackendScraperCompany(...)`.
- [ ] **`api/greenhouse.ts` is deleted** (not just commented out) and no `vercel.json` route points to it.
- [ ] **CHANGELOG entry** drafted (per project ship workflow).

---

## Deploy Sequence

1. **Merge the PR to `main`.** Railway and Vercel auto-deploy on merge.
2. **Watch Railway build logs.** Look for:
   - `apply_alembic_migrations: upgrade head` — successful migration run.
   - `Procrastinate app opened` (or equivalent — installs `procrastinate_jobs` etc.).
   - `Worker starting on queues: ['greenhouse_fetch']`.
   - `Started auto_scraper_loop` (existing — must still appear, confirms coexistence).
   - **No** repeated `connection pool exhausted` warnings (memory notes the pool is sized to 15).
3. **Once Railway reports healthy, manually trigger the fan-out** to skip the 30-min wait:
   ```bash
   curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-greenhouse-fan-out'
   # Expect: 202
   ```
4. **Watch Vercel deploy.** Should be uneventful — frontend cutover is a config + transformer change. Confirm no `404` on the now-deleted `/api/greenhouse/*` route by checking the new build's preview URL once before promotion.

---

## Post-Deploy Monitoring

### First 30-min sanity check

Run all of these against prod Postgres (use the `postgres-prod` MCP or `psql` with the Railway connection string).

**1. Periodic scheduler is registered:**

```sql
SELECT * FROM procrastinate_periodic_defers
ORDER BY defer_timestamp DESC
LIMIT 5;
```

Expect: at least 1 row with `task_name = 'enqueue_greenhouse_fan_out'` and a recent `defer_timestamp`. If empty, the `@app.periodic` decorator never registered — check Railway logs for import errors in `src/backend/api/tasks/enqueue_greenhouse_fan_out.py`.

**2. Fan-out enqueued tasks:**

```sql
SELECT status, count(*)
FROM procrastinate_jobs
WHERE queue_name = 'greenhouse_fetch'
GROUP BY status;
```

Expect: ~45 rows total (one per enabled Greenhouse company), split across `todo` / `doing` / `succeeded` depending on worker progress. After ~2 min, most should be `succeeded`.

**3. Scrape runs are being recorded:**

```sql
SELECT count(*)
FROM scrape_runs
WHERE company IN (SELECT id FROM companies WHERE ats = 'greenhouse')
  AND started_at > now() - interval '1 hour';
```

Expect: ~45 rows after the first fan-out completes. If 0, the worker isn't picking up tasks — check that `run_worker_async(queues=['greenhouse_fetch'])` is actually started in the lifespan.

**4. Per-tick volume:**

```sql
SELECT date_trunc('minute', queueing_lock_expiration_at) AS tick, count(*)
FROM procrastinate_jobs
WHERE queue_name = 'greenhouse_fetch'
  AND task_name = 'fetch_greenhouse_company'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 5;
```

Expect: ~45 rows per tick (matching enabled Greenhouse company count).

### First 2-hour sanity check

**Greenhouse jobs are actually persisted:**

```sql
SELECT count(*) FROM job_listings WHERE id LIKE 'greenhouse_%';
```

Expect: non-zero, growing toward the sum of Greenhouse companies' open-job counts (likely a few thousand). If 0, tasks ran but writes didn't land — check Railway logs for `upsert_jobs_batch` errors.

**Spot-check a high-volume company:**

```sql
SELECT count(*) FROM job_listings WHERE company = 'stripe';
```

Compare against `https://boards-api.greenhouse.io/v1/boards/stripe/jobs` — counts should be within ~5% (some race on jobs posted/closed between the two reads).

**Frontend smoke test:**

- Load the prod frontend in a fresh tab.
- Open a Greenhouse company page (e.g. Stripe).
- DevTools Network tab: confirm `/api/jobs?company=stripe` (200, JSON body with jobs), confirm **zero** requests to `/api/greenhouse/*`.
- DevTools Console: zero errors related to job loading.

---

## What to Look For If Things Go Wrong

### Symptoms → likely causes

| Symptom | Where to look | Likely cause |
|---|---|---|
| Empty company pages on frontend | `SELECT count(*) FROM job_listings WHERE company='<id>';` | Fan-out hasn't run yet, or fetch task failing. Check `procrastinate_jobs.status`. |
| Lots of `failed` in `procrastinate_jobs` | Railway logs grep: `fetch_greenhouse_company failed` | Greenhouse API 5xx, or transform error on an unexpected payload shape. |
| `scrape_runs.error_count > 0` for many companies | Same row's `error` column | Same as above. Look for `safety_guard_triggered` specifically. |
| `safety_guard_triggered` in `scrape_runs` | Railway logs: `safety_guard_triggered` | Greenhouse returned < 10% of active count. This is **correct defensive behavior** — no jobs were closed. Investigate the company's Greenhouse board manually (did they wipe it? did they rename their board_token?). |
| Procrastinate `todo` queue growing unboundedly | `SELECT count(*) FROM procrastinate_jobs WHERE status='todo';` | Worker not running, or concurrency=5 too low. Check Railway logs for `Worker starting on queues`. |
| Same task retrying forever | `procrastinate_job_events` for the task_id | Task is non-idempotent or hitting a permanent error. `RetryStrategy(max_attempts=5)` should cap this — check `attempts` column. |
| Railway memory climbing | Railway metrics dashboard | httpx fetches shouldn't allocate much; if memory spikes, suspect a connection leak (every task should release its psycopg2 connection back to the pool). |

### Railway log greps

```bash
railway logs | grep -E "fetch_greenhouse_company failed|safety_guard_triggered|Worker starting|Procrastinate"
```

---

## Rollback Procedure

**Important:** A partial rollback is **not possible**. The PR deletes `api/greenhouse.ts`, so the frontend cannot temporarily fall back to direct ATS calls. The only safe rollback is reverting the whole merge.

### Steps

1. **Revert the merge commit:**
   ```bash
   git checkout main
   git pull
   git revert -m 1 <merge-sha>
   git push origin main
   ```
   The `-m 1` flag tells `git revert` to keep the `main`-side parent and undo everything from the merged branch.

2. **Wait for both deploys to complete.** Railway redeploys the prior backend (no Procrastinate, no `companies` table use). Vercel redeploys the prior frontend (Greenhouse entries back to `type: 'greenhouse'`, `api/greenhouse.ts` restored).

3. **Verify rollback success:**
   - Frontend Network tab: requests once again hit `/api/greenhouse/*` (200).
   - Prod Postgres: `SELECT count(*) FROM procrastinate_jobs;` still works (tables remain — schema is additive) but no new rows are being inserted.
   - The seeded `companies` rows are harmless to leave in place.

### What the revert does NOT undo

- The `companies` table and its seed data stay in Postgres (additive migration; downgrade is intentionally avoided in prod to prevent destructive rewrites).
- The Procrastinate tables (`procrastinate_jobs`, `procrastinate_periodic_defers`, etc.) stay in Postgres.
- The `consecutive_misses` counter values on `job_listings` rows that were touched by the new task remain set.

None of this affects the rolled-back code path — those rows simply aren't read.

### If only the frontend is broken (backend is healthy)

You cannot ship just a frontend revert because the backend revert is in the same merge. Best you can do without a full revert:

1. Hotfix-branch from `main` post-merge.
2. Add a temporary `api/greenhouse.ts` that re-implements the Vercel proxy (copy from `git show <pre-merge-sha>:api/greenhouse.ts`).
3. In `companies.ts`, flip just the broken companies back to `createGreenhouseCompany(...)`.
4. Ship the hotfix.

This is more work than a clean revert. Prefer the revert unless prod is on fire and you need surgical recovery.

---

## See Also

- [PLAN.md](./PLAN.md) — full migration plan, Units 1–8.
- `scripts/shared/incremental.py` — `SAFETY_GUARD_RATIO`, `MISSED_RUN_THRESHOLD`.
- `src/backend/api/tasks/` — task definitions.
- `src/backend/api/main.py` — lifespan hooks that start the worker.
