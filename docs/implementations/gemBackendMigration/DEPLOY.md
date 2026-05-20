# Gem Backend Migration — Deploy Runbook

This runbook covers the production deploy of the Gem → backend cron+queue migration (Units 1–10 of [PLAN.md](./PLAN.md)). The entire change ships as a **single PR** spanning backend (Railway) and frontend (Vercel).

The pattern is structurally identical to the Ashby migration in [`../ashbyBackendMigration/DEPLOY.md`](../ashbyBackendMigration/DEPLOY.md). Read that runbook in parallel — anything not contradicted here applies equally to Gem.

---

## Critical: Implicit Deploy Ordering

Even though Units 1–10 ship in one merge, the runtime deploys land on two different platforms with **different propagation timing**:

| Platform | What ships | Typical time to live |
|---|---|---|
| Railway (backend) | Units 1–6: `SourceId.GEM`, `seed_gem_companies` migration, `gem_client.py`, `fetch_gem_company` task, `enqueue_gem_fan_out` periodic, expanded worker queues, admin trigger endpoints | ~2–4 min build + boot |
| Vercel (frontend) | Units 7–8: `companies.ts` flipped to `backend-scraper` (3 entries), `api/gem.ts` **deleted**, Why-page Gem column | ~1–2 min |

**The backend MUST be live with `/api/jobs?company=<id>` returning Gem rows BEFORE frontend traffic hits the `backend-scraper` code paths.** If Vercel finishes first, frontend will request `/api/jobs?company=retool` against a backend that hasn't yet (a) seeded the 3 Gem companies, (b) booted the expanded worker, (c) populated `job_listings` with `gem_api` rows. Result: empty job lists for ~30 min until the first cron tick.

Mitigation: **the fan-out cron only runs every 30 min.** Don't wait — fire it manually as soon as Railway is healthy (see "First 30-min sanity check" below). This collapses the window from 30 min to ~30 sec.

A partial mid-PR rollback is **not possible** — `api/gem.ts`, `gemClient.ts`, and `gemTransformer.ts` are deleted in the same PR. If frontend goes live before backend, you cannot temporarily flip it back. Revert the merge commit instead.

---

## Pre-Merge Checklist

- [ ] **Env vars unchanged.** Gem's public job-board API requires no authentication; the new task uses the existing `DATABASE_URL`. Confirm with `railway variables` that `DATABASE_URL` is set.
- [ ] **Migrations round-trip clean locally.**
  ```bash
  cd src/backend
  alembic upgrade head
  alembic downgrade -1  # reverts seed_gem_companies
  alembic upgrade head
  ```
  The new `seed_gem_companies` migration must apply, revert (scoped to `ats='gem'` — Greenhouse + Ashby rows must survive), and re-apply without error.
- [ ] **`SAFETY_GUARD_RATIO=0.1` is shared** (`scripts/shared/incremental.py`). The new `fetch_gem_company` task uses the same guard the Greenhouse / Ashby tasks do — if Gem's API returns < 10% of currently-active jobs for a company, the task aborts before closing anything.
- [ ] **Backend tests pass:** `cd src/backend && pytest` clean. Coverage ≥ baseline. The merge ships 22 new backend tests (Units 2/3/4/5/6).
- [ ] **Frontend type-check + tests pass:** `npm run type-check && npm test` clean. The merge ships 2 new WhyPage tests (Unit 8). 1408+ existing tests stay green.
- [ ] **No lingering Gem legacy references:**
  ```bash
  grep -rE "GemConfig|gemClient|gemTransformer|createGemCompany|GemJobResponse|GemOptions" src/frontend/src/ api/ vercel.json
  ```
  Must return zero matches.
- [ ] **`api/gem.ts` is deleted** (not just commented out) and no `vercel.json` route points to it.
- [ ] **3 Gem `sourceAts` tags:**
  ```bash
  grep -c "sourceAts: 'gem'" src/frontend/src/config/companies.ts  # → 3
  ```
  And the Ashby (46) + Greenhouse (45) counts are unchanged.
- [ ] **CHANGELOG entry** drafted (per project ship workflow).

---

## Deploy Sequence

1. **Merge the PR to `main`.** Railway and Vercel auto-deploy on merge.
2. **Watch Railway build logs.** Look for:
   - `apply_alembic_migrations: upgrade head` — successful migration run, including `b29c1ef8800600 seed_gem_companies`.
   - `Procrastinate app opened` (idempotent — schema already installed for Greenhouse + Ashby).
   - `Procrastinate worker background task started (queues=['greenhouse_fetch', 'ashby_fetch', 'gem_fetch'], concurrency=5)` — confirms Unit 5's queue expansion landed.
   - `Started auto_scraper_loop` (existing — must still appear).
   - **No** repeated `connection pool exhausted` warnings.
3. **Once Railway reports healthy, manually trigger the Gem fan-out** to skip the 30-min cron wait:
   ```bash
   # Admin-gated; needs an Auth0 bearer token for an account with a row in
   # the `admins` table.
   #     export ADMIN_TOKEN="$(... your auth flow here ...)"
   curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-gem-fan-out' \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   # Expect: 202. Without bearer: 401. With non-admin: 403.
   ```

   To manually fire a single Gem company instead:
   ```bash
   curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-gem-fetch?company_id=retool' \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   ```
4. **Watch Vercel deploy.** Should be uneventful — Unit 7+8 are a config + type-system change. Spot-check the preview URL once before promotion: open the Why page and confirm the new "Gem (3)" column renders alongside "Ashby (46)", "Greenhouse (45)", and "Custom Web Scrapers (3)".

---

## Post-Deploy Monitoring

### First 30-min sanity check

Run all of these against prod Postgres (use the `postgres-prod` MCP or `psql` with the Railway connection string).

**1. The seed populated 3 Gem companies (existing seeds untouched):**

```sql
SELECT count(*) FROM companies WHERE ats = 'gem';
-- Expected: 3
SELECT count(*) FROM companies WHERE ats = 'ashby';
-- Expected: 46 (unchanged)
SELECT count(*) FROM companies WHERE ats = 'greenhouse';
-- Expected: 45 (unchanged)
```

**2. Periodic scheduler is registered:**

```sql
SELECT * FROM procrastinate_periodic_defers
WHERE task_name = 'enqueue_gem_fan_out'
ORDER BY defer_timestamp DESC
LIMIT 5;
```

Expect: at least 1 row with a recent `defer_timestamp`. If empty, the `@app.periodic` decorator never registered — check Railway logs for import errors in `src/backend/api/tasks/enqueue_gem_fan_out.py` (most likely cause: `__init__.py` is missing the side-effect import).

**3. Fan-out enqueued tasks (after manual trigger):**

```sql
SELECT status, count(*)
FROM procrastinate_jobs
WHERE queue_name = 'gem_fetch'
GROUP BY status;
```

Expect: 3 rows total (one per enabled Gem company), split across `todo` / `doing` / `succeeded`. After ~30s, most should be `succeeded`.

**4. `scrape_runs` rows landing:**

```sql
SELECT count(*)
FROM scrape_runs
WHERE company IN (SELECT id FROM companies WHERE ats = 'gem')
  AND started_at > now() - interval '5 minutes';
-- Expected: ≤ 3 (grows as each per-company task completes)
```

**5. `job_listings` populated:**

```sql
SELECT company, count(*)
FROM job_listings
WHERE source_id = 'gem_api'
GROUP BY company
ORDER BY 2 DESC;
-- Expected: rows for nominal, retool, gem.
```

### 2-hour cross-reference

Spot-check Retool against the live Gem API:

```bash
curl -s 'https://api.gem.com/job_board/v0/retool/job_posts/' | jq 'length'
```

Then:

```sql
SELECT count(*) FROM job_listings
WHERE source_id = 'gem_api' AND company = 'retool' AND status = 'OPEN';
```

The DB count should be `>=` (or very close to) the API count — minor drift is acceptable because of the consecutive-misses lifecycle (a job seen earlier today but not in this minute's fetch is still `OPEN` until misses ≥ 2).

### Frontend smoke

Open `/companies` and switch to Nominal, Retool, Gem. Jobs should render. Network tab should show `/api/jobs?company=<id>`, **zero** `/api/gem/*` requests.

Open `/why`. Four columns visible: **Ashby (46)**, **Greenhouse (45)**, **Gem (3)**, **Custom Web Scrapers (3)** (Google/Apple/Microsoft only). All three Gem companies should appear inside the new Gem column.

---

## Rollback

If something breaks:

1. **Revert the merge commit on `main`.** Both Railway and Vercel will auto-redeploy the reverted SHA. The Gem companies in the DB will remain seeded (no schema-level rollback) but the worker stops listening on `gem_fetch` once `main.py` reverts. That's safe — orphan rows are harmless and `procrastinate_jobs` already drains gracefully via `SELECT … FOR UPDATE SKIP LOCKED`.
2. **Asymmetric rollback risk:** `api/gem.ts`, `gemClient.ts`, and `gemTransformer.ts` were deleted. Reverting the merge restores them, but if Vercel deploys the revert before Railway, the frontend will briefly try to fetch from `/api/gem/*` against a backend that already removed its companies seeding. The blast radius is small — the proxy will work (Gem's public API has no auth and Vercel redeploys the proxy quickly), but expect ~1 min of network errors per Gem company (only 3, so the user-visible impact is small).
3. **Do NOT** manually `DELETE FROM companies WHERE ats='gem'` as part of rollback — the seed migration's `downgrade()` handles it via `alembic downgrade a17b7c0ffee500`, scoped properly to leave Greenhouse + Ashby intact.

---

## Out-of-Band Operator Actions

These ad-hoc commands are useful for QA but should not be required as part of the normal deploy:

- Force-refetch a single Gem company that's stuck:
  ```bash
  curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-gem-fetch?company_id=<id>' \
    -H "Authorization: Bearer ${ADMIN_TOKEN}"
  ```
- Inspect worker progress live:
  ```sql
  SELECT id, queue_name, task_name, status, args, attempts
  FROM procrastinate_jobs
  WHERE queue_name = 'gem_fetch' AND status IN ('todo', 'doing')
  ORDER BY id DESC LIMIT 20;
  ```
- Toggle a company's enabled flag (e.g. to skip it temporarily):
  ```sql
  UPDATE companies SET enabled = false WHERE id = '<company_id>' AND ats = 'gem';
  ```

---

## What's Out of Scope

Per [PLAN.md](./PLAN.md#non-goals): Lever / Workday / Eightfold migrations are tracked as follow-ups. Each will follow this same pattern with its own queue (`lever_fetch`, etc.) and `sourceAts` value.
