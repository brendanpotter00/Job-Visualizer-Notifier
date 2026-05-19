# Ashby Backend Migration — Deploy Runbook

This runbook covers the production deploy of the Ashby → backend cron+queue migration (Units 1–10 of [PLAN.md](./PLAN.md)). The entire change ships as a **single PR** spanning backend (Railway) and frontend (Vercel).

The pattern is structurally identical to the Greenhouse migration in [`../greenhouseBackendMigration/DEPLOY.md`](../greenhouseBackendMigration/DEPLOY.md). Read that runbook in parallel — anything not contradicted here applies equally to Ashby.

---

## Critical: Implicit Deploy Ordering

Even though Units 1–10 ship in one merge, the runtime deploys land on two different platforms with **different propagation timing**:

| Platform | What ships | Typical time to live |
|---|---|---|
| Railway (backend) | Units 1–6: `SourceId.ASHBY`, `seed_ashby_companies` migration, `ashby_client.py`, `fetch_ashby_company` task, `enqueue_ashby_fan_out` periodic, expanded worker queues, admin trigger endpoints | ~2–4 min build + boot |
| Vercel (frontend) | Units 7–9: `companies.ts` flipped to `backend-scraper` (46 entries), `api/ashby.ts` **deleted**, Why-page Ashby column, Greenhouse `sourceAts` retrofit | ~1–2 min |

**The backend MUST be live with `/api/jobs?company=<id>` returning Ashby rows BEFORE frontend traffic hits the `backend-scraper` code paths.** If Vercel finishes first, frontend will request `/api/jobs?company=notion` against a backend that hasn't yet (a) seeded the 46 Ashby companies, (b) booted the expanded worker, (c) populated `job_listings` with `ashby_api` rows. Result: empty job lists for ~30 min until the first cron tick.

Mitigation: **the fan-out cron only runs every 30 min.** Don't wait — fire it manually as soon as Railway is healthy (see "First 30-min sanity check" below). This collapses the window from 30 min to ~30 sec.

A partial mid-PR rollback is **not possible** — `api/ashby.ts`, `ashbyClient.ts`, and `ashbyTransformer.ts` are deleted in the same PR. If frontend goes live before backend, you cannot temporarily flip it back. Revert the merge commit instead.

---

## Pre-Merge Checklist

- [ ] **Env vars unchanged.** Ashby's public job-board API requires no authentication; the new task uses the existing `DATABASE_URL`. Confirm with `railway variables` that `DATABASE_URL` is set.
- [ ] **Migrations round-trip clean locally.**
  ```bash
  cd src/backend
  alembic upgrade head
  alembic downgrade -1  # reverts seed_ashby_companies
  alembic upgrade head
  ```
  The new `seed_ashby_companies` migration must apply, revert (scoped to `ats='ashby'` — Greenhouse rows must survive), and re-apply without error.
- [ ] **`SAFETY_GUARD_RATIO=0.1` is shared** (`scripts/shared/incremental.py`). The new `fetch_ashby_company` task uses the same guard the Greenhouse task does — if Ashby's API returns < 10% of currently-active jobs for a company, the task aborts before closing anything.
- [ ] **Backend tests pass:** `cd src/backend && pytest` clean. Coverage ≥ baseline.
- [ ] **Frontend type-check + tests pass:** `npm run type-check && npm test` clean. Note: 3 failures in `RecentJobsFilters.test.tsx` are pre-existing and unrelated; confirm no NEW failures.
- [ ] **No lingering Ashby legacy references:**
  ```bash
  grep -rE "AshbyConfig|ashbyClient|ashbyTransformer|createAshbyCompany|AshbyJobResponse|AshbyAPIResponse|AshbyOptions" src/frontend/src/ api/ vercel.json
  ```
  Must return zero matches.
- [ ] **`api/ashby.ts` is deleted** (not just commented out) and no `vercel.json` route points to it.
- [ ] **46 Ashby + 45 Greenhouse `sourceAts` tags:**
  ```bash
  grep -c "sourceAts: 'ashby'" src/frontend/src/config/companies.ts      # → 46
  grep -c "sourceAts: 'greenhouse'" src/frontend/src/config/companies.ts # → 45
  ```
- [ ] **CHANGELOG entry** drafted (per project ship workflow).

---

## Deploy Sequence

1. **Merge the PR to `main`.** Railway and Vercel auto-deploy on merge.
2. **Watch Railway build logs.** Look for:
   - `apply_alembic_migrations: upgrade head` — successful migration run, including `a17b7c0ffee500 seed_ashby_companies`.
   - `Procrastinate app opened` (idempotent — schema already installed for Greenhouse).
   - `Procrastinate worker background task started (queues=['greenhouse_fetch', 'ashby_fetch'], concurrency=5)` — confirms Unit 5's queue expansion landed.
   - `Started auto_scraper_loop` (existing — must still appear).
   - **No** repeated `connection pool exhausted` warnings.
3. **Once Railway reports healthy, manually trigger the Ashby fan-out** to skip the 30-min cron wait:
   ```bash
   # Admin-gated; needs an Auth0 bearer token for an account with a row in
   # the `admins` table.
   #     export ADMIN_TOKEN="$(... your auth flow here ...)"
   curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-ashby-fan-out' \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   # Expect: 202. Without bearer: 401. With non-admin: 403.
   ```

   To manually fire a single Ashby company instead:
   ```bash
   curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-ashby-fetch?company_id=notion' \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   ```
4. **Watch Vercel deploy.** Should be uneventful — Unit 7+9 are a config + type-system change. Spot-check the preview URL once before promotion: open the Why page and confirm the new "Ashby (46)" column renders alongside "Greenhouse (45)" and "Custom Web Scrapers (3)".

---

## Post-Deploy Monitoring

### First 30-min sanity check

Run all of these against prod Postgres (use the `postgres-prod` MCP or `psql` with the Railway connection string).

**1. The seed populated 46 Ashby companies:**

```sql
SELECT count(*) FROM companies WHERE ats = 'ashby';
-- Expected: 46
SELECT count(*) FROM companies WHERE ats = 'greenhouse';
-- Expected: 45 (unchanged)
```

**2. Periodic scheduler is registered:**

```sql
SELECT * FROM procrastinate_periodic_defers
WHERE task_name = 'enqueue_ashby_fan_out'
ORDER BY defer_timestamp DESC
LIMIT 5;
```

Expect: at least 1 row with a recent `defer_timestamp`. If empty, the `@app.periodic` decorator never registered — check Railway logs for import errors in `src/backend/api/tasks/enqueue_ashby_fan_out.py` (most likely cause: `__init__.py` is missing the side-effect import).

**3. Fan-out enqueued tasks (after manual trigger):**

```sql
SELECT status, count(*)
FROM procrastinate_jobs
WHERE queue_name = 'ashby_fetch'
GROUP BY status;
```

Expect: ~46 rows total (one per enabled Ashby company), split across `todo` / `doing` / `succeeded`. After ~2 min, most should be `succeeded`.

**4. `scrape_runs` rows landing:**

```sql
SELECT count(*)
FROM scrape_runs
WHERE company IN (SELECT id FROM companies WHERE ats = 'ashby')
  AND started_at > now() - interval '5 minutes';
-- Expected: ≤ 46 (grows as each per-company task completes)
```

**5. `job_listings` populated:**

```sql
SELECT company, count(*)
FROM job_listings
WHERE source_id = 'ashby_api'
GROUP BY company
ORDER BY 2 DESC
LIMIT 10;
-- Expected: rows for Notion, OpenAI, Ramp, Linear, etc.
```

### 2-hour cross-reference

Spot-check Notion against the live Ashby API:

```bash
curl -s 'https://api.ashbyhq.com/posting-api/job-board/notion?includeCompensation=true' \
  | jq '.jobs | length'
```

Then:

```sql
SELECT count(*) FROM job_listings
WHERE source_id = 'ashby_api' AND company = 'notion' AND status = 'OPEN';
```

The DB count should be `>=` (or very close to) the API count — minor drift is acceptable because of the consecutive-misses lifecycle (a job seen earlier today but not in this minute's fetch is still `OPEN` until misses ≥ 2).

### Frontend smoke

Open `/companies` and switch to Notion, OpenAI, Ramp, Cursor. Jobs should render. Network tab should show `/api/jobs?company=<id>`, **zero** `/api/ashby/*` requests.

Open `/why`. Three columns visible: **Ashby (46)**, **Greenhouse (45)**, **Custom Web Scrapers (3)** (Google/Apple/Microsoft only). Cursor should appear inside the Ashby column despite its `cursor.com/careers` jobsUrl — verifies the `sourceAts` mechanism replaced URL-prefix detection successfully.

---

## Rollback

If something breaks:

1. **Revert the merge commit on `main`.** Both Railway and Vercel will auto-redeploy the reverted SHA. The Ashby companies in the DB will remain seeded (no schema-level rollback) but the worker stops listening on `ashby_fetch` once `main.py` reverts. That's safe — orphan rows are harmless and `procrastinate_jobs` already drains gracefully via `SELECT … FOR UPDATE SKIP LOCKED`.
2. **Asymmetric rollback risk:** `api/ashby.ts`, `ashbyClient.ts`, and `ashbyTransformer.ts` were deleted. Reverting the merge restores them, but if Vercel deploys the revert before Railway, the frontend will briefly try to fetch from `/api/ashby/*` against a backend that already removed its companies seeding. The blast radius is small — the proxy will work (Ashby's public API has no auth and Vercel redeploys the proxy quickly), but expect ~1 min of network errors per Ashby company.
3. **Do NOT** manually `DELETE FROM companies WHERE ats='ashby'` as part of rollback — the seed migration's `downgrade()` handles it via `alembic downgrade ebb479b7eed5`, scoped properly to leave Greenhouse intact.

---

## Out-of-Band Operator Actions

These ad-hoc commands are useful for QA but should not be required as part of the normal deploy:

- Force-refetch a single Ashby company that's stuck:
  ```bash
  curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-ashby-fetch?company_id=<id>' \
    -H "Authorization: Bearer ${ADMIN_TOKEN}"
  ```
- Inspect worker progress live:
  ```sql
  SELECT id, queue_name, task_name, status, args, attempts
  FROM procrastinate_jobs
  WHERE queue_name = 'ashby_fetch' AND status IN ('todo', 'doing')
  ORDER BY id DESC LIMIT 20;
  ```
- Toggle a company's enabled flag (e.g. to skip it temporarily):
  ```sql
  UPDATE companies SET enabled = false WHERE id = '<company_id>' AND ats = 'ashby';
  ```

---

## What's Out of Scope

Per [PLAN.md](./PLAN.md#non-goals): Lever / Workday / Gem / Eightfold migrations are tracked as follow-ups. Each will follow this same pattern with its own queue (`lever_fetch`, etc.) and `sourceAts` value.
