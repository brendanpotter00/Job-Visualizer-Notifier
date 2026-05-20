# Lever Backend Migration — Deploy Runbook

This runbook covers the production deploy of the Lever → backend cron+queue migration (Units 1–9 of [PLAN.md](./PLAN.md)). The entire change ships as a **single PR** spanning backend (Railway) and frontend (Vercel).

The pattern is structurally identical to the Ashby migration in [`../ashbyBackendMigration/DEPLOY.md`](../ashbyBackendMigration/DEPLOY.md). Read that runbook in parallel — anything not contradicted here applies equally to Lever.

---

## Critical: Implicit Deploy Ordering

Even though Units 1–9 ship in one merge, the runtime deploys land on two different platforms with **different propagation timing**:

| Platform | What ships | Typical time to live |
|---|---|---|
| Railway (backend) | Units 1–6: `SourceId.LEVER`, `seed_lever_companies` migration, `lever_client.py`, `fetch_lever_company` task, `enqueue_lever_fan_out` periodic, expanded worker queues, admin trigger endpoints | ~2–4 min build + boot |
| Vercel (frontend) | Units 7–8: `companies.ts` flipped to `backend-scraper` (3 entries), `api/lever.ts` **deleted**, Why-page Lever column | ~1–2 min |

**The backend MUST be live with `/api/jobs?company=<id>` returning Lever rows BEFORE frontend traffic hits the `backend-scraper` code paths for Palantir / Spotify / Zoox.** If Vercel finishes first, frontend will request `/api/jobs?company=palantir` against a backend that hasn't yet (a) seeded the 3 Lever companies, (b) booted the expanded worker, (c) populated `job_listings` with `lever_api` rows. Result: empty job lists for those three companies until the first cron tick (up to 30 min).

Mitigation: **the fan-out cron only runs every 30 min.** Don't wait — fire it manually as soon as Railway is healthy (see "First 30-min sanity check" below). This collapses the window from 30 min to ~30 sec.

A partial mid-PR rollback is **not possible** — `api/lever.ts`, `leverClient.ts`, and `leverTransformer.ts` are deleted in the same PR. If frontend goes live before backend, you cannot temporarily flip it back. Revert the merge commit instead.

---

## Pre-Merge Checklist

- [ ] **Env vars unchanged.** Lever's public Postings API requires no authentication; the new task uses the existing `DATABASE_URL`. Confirm with `railway variables` that `DATABASE_URL` is set.
- [ ] **Migrations round-trip clean locally.**
  ```bash
  cd src/backend
  alembic upgrade head
  alembic downgrade -1  # reverts seed_lever_companies
  alembic upgrade head
  ```
  The new `seed_lever_companies` migration must apply, revert (scoped to `ats='lever'` — Greenhouse + Ashby rows must survive), and re-apply without error.
- [ ] **`SAFETY_GUARD_RATIO=0.1` is shared** (`scripts/shared/incremental.py`). The new `fetch_lever_company` task uses the same guard the Greenhouse + Ashby tasks do — if Lever's API returns < 10% of currently-active jobs for a company, the task aborts before closing anything.
- [ ] **Backend tests pass:** `cd src/backend && pytest` clean. Coverage ≥ baseline.
- [ ] **Frontend type-check + tests pass:** `npm run type-check && npm test -w src/frontend` clean.
- [ ] **No lingering Lever legacy references:**
  ```bash
  grep -rE "LeverConfig|leverClient|leverTransformer|createLeverCompany|LeverJobResponse" src/frontend/src/ api/ vercel.json
  ```
  Must return zero matches.
- [ ] **`api/lever.ts` is deleted** (not just commented out) and no `vercel.json` route points to it.
- [ ] **3 Lever + 46 Ashby + 45 Greenhouse `sourceAts` tags:**
  ```bash
  grep -c "sourceAts: 'lever'" src/frontend/src/config/companies.ts      # → 3
  grep -c "sourceAts: 'ashby'" src/frontend/src/config/companies.ts     # → 46
  grep -c "sourceAts: 'greenhouse'" src/frontend/src/config/companies.ts # → 45
  ```
- [ ] **CHANGELOG entry** drafted (per project ship workflow).

---

## Deploy Sequence

1. **Merge the PR to `main`.** Railway and Vercel auto-deploy on merge.
2. **Watch Railway build logs.** Look for:
   - `apply_alembic_migrations: upgrade head` — successful migration run, including `b29cd1eef0aab1 seed_lever_companies`.
   - `Procrastinate app opened` (idempotent — schema already installed for Greenhouse/Ashby).
   - `Procrastinate worker background task started (queues=['greenhouse_fetch', 'ashby_fetch', 'lever_fetch'], concurrency=5)` — confirms Unit 5's queue expansion landed.
   - `Started auto_scraper_loop` (existing — must still appear).
   - **No** repeated `connection pool exhausted` warnings.
3. **Once Railway reports healthy, manually trigger the Lever fan-out** to skip the 30-min cron wait:
   ```bash
   # Admin-gated; needs an Auth0 bearer token for an account with a row in
   # the `admins` table.
   #     export ADMIN_TOKEN="$(... your auth flow here ...)"
   curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-lever-fan-out' \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   # Expect: 202. Without bearer: 401. With non-admin: 403.
   ```

   To manually fire a single Lever company instead:
   ```bash
   curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-lever-fetch?company_id=palantir' \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   ```
4. **Watch Vercel deploy.** Should be uneventful — Unit 7+8 are a config + type-system change. Spot-check the preview URL once before promotion: open the Why page and confirm the new "Lever (3)" column renders alongside "Ashby (46)", "Greenhouse (45)", and "Custom Web Scrapers (3)".

---

## Post-Deploy Monitoring

### First 30-min sanity check

Run all of these against prod Postgres (use the `postgres-prod` MCP or `psql` with the Railway connection string).

**1. The seed populated 3 Lever companies:**

```sql
SELECT count(*) FROM companies WHERE ats = 'lever';
-- Expected: 3
SELECT count(*) FROM companies WHERE ats = 'ashby';
-- Expected: 46 (unchanged)
SELECT count(*) FROM companies WHERE ats = 'greenhouse';
-- Expected: 45 (unchanged)
```

**2. Periodic scheduler is registered:**

```sql
SELECT * FROM procrastinate_periodic_defers
WHERE task_name = 'enqueue_lever_fan_out'
ORDER BY defer_timestamp DESC
LIMIT 5;
```

Expect: at least 1 row with a recent `defer_timestamp`. If empty, the `@app.periodic` decorator never registered — check Railway logs for import errors in `src/backend/api/tasks/enqueue_lever_fan_out.py` (most likely cause: `__init__.py` is missing the side-effect import).

**3. Fan-out enqueued tasks (after manual trigger):**

```sql
SELECT status, count(*)
FROM procrastinate_jobs
WHERE queue_name = 'lever_fetch'
GROUP BY status;
```

Expect: 3 rows total (one per enabled Lever company), split across `todo` / `doing` / `succeeded`. After ~30s, most should be `succeeded`.

**4. `scrape_runs` rows landing:**

```sql
SELECT count(*)
FROM scrape_runs
WHERE company IN (SELECT id FROM companies WHERE ats = 'lever')
  AND started_at > now() - interval '5 minutes';
-- Expected: ≤ 3 (grows as each per-company task completes)
```

**5. `job_listings` populated:**

```sql
SELECT company, count(*)
FROM job_listings
WHERE source_id = 'lever_api'
GROUP BY company
ORDER BY 2 DESC;
-- Expected: rows for palantir, spotify, zoox
```

### 2-hour cross-reference

Spot-check Palantir against the live Lever API:

```bash
curl -s 'https://api.lever.co/v0/postings/palantir?mode=json' | jq 'length'
```

Then:

```sql
SELECT count(*) FROM job_listings
WHERE source_id = 'lever_api' AND company = 'palantir' AND status = 'OPEN';
```

The DB count should be `>=` (or very close to) the API count — minor drift is acceptable because of the consecutive-misses lifecycle (a job seen earlier today but not in this minute's fetch is still `OPEN` until misses ≥ 2).

### Frontend smoke

Open `/companies` and switch to Palantir, Spotify, Zoox. Jobs should render. Network tab should show `/api/jobs?company=<id>`, **zero** `/api/lever/*` requests.

Open `/why`. Four columns visible: **Ashby (46)**, **Greenhouse (45)**, **Lever (3)**, **Custom Web Scrapers (3)** (Google/Apple/Microsoft only).

---

## Rollback

If something breaks:

1. **Revert the merge commit on `main`.** Both Railway and Vercel will auto-redeploy the reverted SHA. The Lever companies in the DB will remain seeded (no schema-level rollback) but the worker stops listening on `lever_fetch` once `main.py` reverts. That's safe — orphan rows are harmless and `procrastinate_jobs` already drains gracefully via `SELECT … FOR UPDATE SKIP LOCKED`.
2. **Asymmetric rollback risk:** `api/lever.ts`, `leverClient.ts`, and `leverTransformer.ts` were deleted. Reverting the merge restores them, but if Vercel deploys the revert before Railway, the frontend will briefly try to fetch from `/api/lever/*` against a backend that already removed its companies seeding. The blast radius is small — the proxy will work (Lever's public Postings API has no auth and Vercel redeploys the proxy quickly), but expect ~1 min of network errors per Lever company.
3. **Do NOT** manually `DELETE FROM companies WHERE ats='lever'` as part of rollback — the seed migration's `downgrade()` handles it via `alembic downgrade a17b7c0ffee500`, scoped properly to leave Greenhouse + Ashby intact.

---

## Out-of-Band Operator Actions

These ad-hoc commands are useful for QA but should not be required as part of the normal deploy:

- Force-refetch a single Lever company that's stuck:
  ```bash
  curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-lever-fetch?company_id=<id>' \
    -H "Authorization: Bearer ${ADMIN_TOKEN}"
  ```
- Inspect worker progress live:
  ```sql
  SELECT id, queue_name, task_name, status, args, attempts
  FROM procrastinate_jobs
  WHERE queue_name = 'lever_fetch' AND status IN ('todo', 'doing')
  ORDER BY id DESC LIMIT 20;
  ```
- Toggle a company's enabled flag (e.g. to skip it temporarily):
  ```sql
  UPDATE companies SET enabled = false WHERE id = '<company_id>' AND ats = 'lever';
  ```

---

## What's Out of Scope

Per [PLAN.md](./PLAN.md#non-goals): Workday / Gem / Eightfold migrations are tracked as follow-ups. Each will follow this same pattern with its own queue (`workday_fetch`, etc.) and `sourceAts` value.
