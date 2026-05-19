# Workday Backend Migration — Deploy Runbook

This runbook covers the production deploy of the Workday → backend cron+queue migration (Units 1–10 of [PLAN.md](./PLAN.md)). The entire change ships as a **single PR** spanning backend (Railway) and frontend (Vercel).

The pattern is structurally identical to the Ashby migration in [`../ashbyBackendMigration/DEPLOY.md`](../ashbyBackendMigration/DEPLOY.md) and the Lever migration in [`../leverBackendMigration/DEPLOY.md`](../leverBackendMigration/DEPLOY.md). Read either one in parallel — anything not contradicted here applies equally to Workday.

**Workday-specific:** a new `provider_config` JSONB column on `companies` was added in Unit 2's Alembic migration. Each Workday row carries `{base_url, tenant_slug, career_site_slug, default_facets?}` — this is what the per-company task uses to construct the POST URL and body. **The column name is a frozen contract** — a parallel Eightfold backend migration reuses it.

---

## Critical: Implicit Deploy Ordering

Even though Units 1–10 ship in one merge, the runtime deploys land on two different platforms with **different propagation timing**:

| Platform | What ships | Typical time to live |
|---|---|---|
| Railway (backend) | Units 1–6: `SourceId.WORKDAY`, `provider_config` column + 11 seed rows, `workday_client.py`, `fetch_workday_company` task, `enqueue_workday_fan_out` periodic, expanded worker queues, admin trigger endpoints | ~2–4 min build + boot |
| Vercel (frontend) | Units 7–8: `companies.ts` flipped to `backend-scraper` (11 entries), `api/workday.ts` **deleted**, Why-page Workday column | ~1–2 min |

**The backend MUST be live with `/api/jobs?company=<id>` returning Workday rows BEFORE frontend traffic hits the `backend-scraper` code paths for the 11 Workday companies.** If Vercel finishes first, frontend will request `/api/jobs?company=nvidia` against a backend that hasn't yet (a) seeded the 11 Workday companies, (b) booted the expanded worker, (c) populated `job_listings` with `workday_api` rows. Result: empty job lists for those 11 companies until the first cron tick (up to 30 min).

Mitigation: **the fan-out cron only runs every 30 min.** Don't wait — fire it manually as soon as Railway is healthy (see "First 30-min sanity check" below). This collapses the window from 30 min to ~30 sec.

A partial mid-PR rollback is **not possible** — `api/workday.ts`, `workdayClient.ts`, `workdayTransformer.ts`, and `lib/workdayDateParser.ts` are deleted in the same PR. If frontend goes live before backend, you cannot temporarily flip it back. Revert the merge commit instead.

---

## Pre-Merge Checklist

- [ ] **Env vars unchanged.** Workday's CXS endpoint requires no authentication; the new task uses the existing `DATABASE_URL`. Confirm with `railway variables` that `DATABASE_URL` is set.
- [ ] **Migrations round-trip clean locally.**
  ```bash
  cd src/backend
  alembic upgrade head
  alembic downgrade -1  # reverts provider_config column + workday seed
  alembic upgrade head
  ```
  The new `b9714f608e21` migration must apply, revert (scoped to `ats='workday'` plus the column drop — Greenhouse + Ashby rows must survive), and re-apply without error. The two roundtrip tests in `test_migration_companies.py` cover this in CI.
- [ ] **`SAFETY_GUARD_RATIO=0.1` is shared** (`scripts/shared/incremental.py`). The new `fetch_workday_company` task uses the same guard the Greenhouse + Ashby + Lever tasks do — if Workday's API returns < 10% of currently-active jobs for a company, the task aborts before closing anything.
- [ ] **`WORKDAY_MAX_PAGES=100` cap is in place.** A runaway pagination (e.g. Workday returns a `total` that lies, or never advances the cursor) ERROR-logs and returns partial results — the run records `error_count=0` but the operator should see the `pagination cap hit` line in Railway `@level:error` filters.
- [ ] **Backend tests pass:** `cd src/backend && pytest` clean. Expect 448+ tests including the 36-test workday_client suite, the 8-test fetch_workday_company suite, the 6-test enqueue_workday_fan_out suite, the 12-test workday router suite, and the 2 new migration roundtrip tests.
- [ ] **Frontend type-check + tests pass:** `npm run type-check && npm test -w src/frontend` clean (~1303 passed).
- [ ] **No lingering Workday legacy references:**
  ```bash
  grep -rE "WorkdayConfig|workdayClient|workdayTransformer|createWorkdayCompany|WorkdayJobPosting|workdayDateParser" src/frontend/src/ api/ vercel.json
  ```
  Must return zero matches.
- [ ] **`api/workday.ts` is deleted** (not just commented out) and no `vercel.json` route points to it. The `X-Workday-Base-Url` CORS allow-header is also gone.
- [ ] **11 Workday + 46 Ashby + 45 Greenhouse `sourceAts` tags:**
  ```bash
  grep -c "sourceAts: 'workday'" src/frontend/src/config/companies.ts    # → 11
  grep -c "sourceAts: 'ashby'" src/frontend/src/config/companies.ts      # → 46
  grep -c "sourceAts: 'greenhouse'" src/frontend/src/config/companies.ts # → 45
  ```
- [ ] **All 11 seeded rows have the three required keys in `provider_config`:**
  ```sql
  SELECT id, provider_config
  FROM companies
  WHERE ats = 'workday'
    AND (
      provider_config->>'base_url' IS NULL OR provider_config->>'base_url' = ''
      OR provider_config->>'tenant_slug' IS NULL OR provider_config->>'tenant_slug' = ''
      OR provider_config->>'career_site_slug' IS NULL OR provider_config->>'career_site_slug' = ''
    );
  -- Expected: 0 rows. Any row returned is a malformed seed — the per-company
  -- task would record error_count=1 for it and never populate jobs.
  ```
- [ ] **CHANGELOG entry** drafted (per project ship workflow).

---

## Deploy Sequence

1. **Merge the PR to `main`.** Railway and Vercel auto-deploy on merge.
2. **Watch Railway build logs.** Look for:
   - `apply_alembic_migrations: upgrade head` — successful migration run, including `b9714f608e21 add_provider_config_to_companies_and_seed_workday_companies`.
   - `Procrastinate app opened` (idempotent — schema already installed for Greenhouse/Ashby).
   - `Procrastinate worker background task started (queues=['greenhouse_fetch', 'ashby_fetch', 'workday_fetch'], concurrency=5)` — confirms Unit 5's queue expansion landed.
   - `Started auto_scraper_loop` (existing — must still appear).
   - **No** repeated `connection pool exhausted` warnings.
3. **Once Railway reports healthy, manually trigger the Workday fan-out** to skip the 30-min cron wait:
   ```bash
   # Admin-gated; needs an Auth0 bearer token for an account with a row in
   # the `admins` table.
   #     export ADMIN_TOKEN="$(... your auth flow here ...)"
   curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-workday-fan-out' \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   # Expect: 202. Without bearer: 401. With non-admin: 403.
   ```

   To manually fire a single Workday company instead:
   ```bash
   curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-workday-fetch?company_id=nvidia' \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   ```
4. **Watch Vercel deploy.** Should be uneventful — Unit 7+8 are a config + type-system change. Spot-check the preview URL once before promotion: open the Why page and confirm the new "Workday (11)" column renders alongside "Ashby (46)", "Greenhouse (45)", and "Custom Web Scrapers (3)".

---

## Post-Deploy Monitoring

### First 30-min sanity check

Run all of these against prod Postgres (use the `postgres-prod` MCP or `psql` with the Railway connection string).

**1. The seed populated 11 Workday companies with provider_config:**

```sql
SELECT count(*) FROM companies WHERE ats = 'workday';
-- Expected: 11
SELECT count(*) FROM companies WHERE ats = 'ashby';
-- Expected: 46 (unchanged)
SELECT count(*) FROM companies WHERE ats = 'greenhouse';
-- Expected: 45 (unchanged)

-- All 11 Workday rows have the three required provider_config keys:
SELECT count(*)
FROM companies
WHERE ats = 'workday'
  AND provider_config ? 'base_url'
  AND provider_config ? 'tenant_slug'
  AND provider_config ? 'career_site_slug';
-- Expected: 11
```

**2. Periodic scheduler is registered:**

```sql
SELECT * FROM procrastinate_periodic_defers
WHERE task_name = 'enqueue_workday_fan_out'
ORDER BY defer_timestamp DESC
LIMIT 5;
```

Expect: at least 1 row with a recent `defer_timestamp`. If empty, the `@app.periodic` decorator never registered — check Railway logs for import errors in `src/backend/api/tasks/enqueue_workday_fan_out.py` (most likely cause: `__init__.py` is missing the side-effect import).

**3. Fan-out enqueued tasks (after manual trigger):**

```sql
SELECT status, count(*)
FROM procrastinate_jobs
WHERE queue_name = 'workday_fetch'
GROUP BY status;
```

Expect: 11 rows total (one per enabled Workday company), split across `todo` / `doing` / `succeeded`. After ~30-60s, most should be `succeeded` — Workday companies typically have hundreds-to-thousands of jobs and paginate 20 at a time, so each takes longer than Lever / Gem / Ashby.

**4. `scrape_runs` rows landing:**

```sql
SELECT count(*)
FROM scrape_runs
WHERE company IN (SELECT id FROM companies WHERE ats = 'workday')
  AND started_at > now() - interval '5 minutes';
-- Expected: ≤ 11 (grows as each per-company task completes)
```

**5. `job_listings` populated:**

```sql
SELECT company, count(*)
FROM job_listings
WHERE source_id = 'workday_api'
GROUP BY company
ORDER BY 2 DESC;
-- Expected: rows for nvidia, adobe, expedia, turo, blueorigin, snap, gm,
-- disney, slack, capitalone, paypal.
```

**6. Pagination cap not hit on any company:**

Check Railway `@level:error` for `Workday pagination cap hit`. Expect zero matches. If any appear, investigate that company's actual job count vs the cap (`100 * 20 = 2000`).

### 2-hour cross-reference

Spot-check NVIDIA against the live Workday API:

```bash
curl -X POST 'https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs' \
  -H 'Content-Type: application/json' \
  -d '{"appliedFacets": {"locationHierarchy1": ["2fcb99c455831013ea52fb338f2932d8"], "jobFamilyGroup": ["0c40f6bd1d8f10ae43ffaefd46dc7e78"], "timeType": ["5509c0b5959810ac0029943377d47364"]}, "limit": 20, "offset": 0, "searchText": ""}' \
  | jq '.total'
```

Then:

```sql
SELECT count(*) FROM job_listings
WHERE source_id = 'workday_api' AND company = 'nvidia' AND status = 'OPEN';
```

The DB count should be `>=` (or very close to) the API count — minor drift is acceptable because of the consecutive-misses lifecycle (a job seen earlier today but not in this minute's fetch is still `OPEN` until misses ≥ 2).

### Frontend smoke

Open `/companies` and switch to NVIDIA, Adobe, Expedia (and a few of the simpler tenants). Jobs should render. Network tab should show `/api/jobs?company=<id>`, **zero** `/api/workday/*` requests.

Open `/why`. Four columns visible: **Ashby (46)**, **Greenhouse (45)**, **Workday (11)**, **Custom Web Scrapers (3)** (Google/Apple/Microsoft only). The Lever / Gem columns are present too if their parallel PRs have merged; if not yet merged, those companies remain in their respective Lever/Gem columns.

---

## Rollback

If something breaks:

1. **Revert the merge commit on `main`.** Both Railway and Vercel will auto-redeploy the reverted SHA. The Workday companies in the DB will remain seeded (no schema-level rollback) but the worker stops listening on `workday_fetch` once `main.py` reverts. **The `provider_config` column also remains** — that's safe because the column is unused by all other ATS providers (default `'{}'::jsonb`).
2. **For a full schema rollback** (rare; required only if `provider_config` causes a downstream incident):
   ```bash
   cd src/backend
   alembic downgrade -1
   ```
   This runs the migration's `downgrade()`: scope-deletes Workday rows AND drops the `provider_config` column. **Do not run this if a parallel Eightfold migration that also uses `provider_config` has already shipped** — it would drop their data too. Coordinate with whoever is on call before running.
3. **Asymmetric rollback risk:** `api/workday.ts`, `workdayClient.ts`, `workdayTransformer.ts`, and `lib/workdayDateParser.ts` were deleted. Reverting the merge restores them, but if Vercel deploys the revert before Railway, the frontend will briefly try to fetch from `/api/workday/*` against a backend that's still in the new shape. The blast radius is small — the proxy will work (Workday's CXS endpoint has no auth and Vercel redeploys the proxy quickly), but expect ~1 min of network errors per Workday company.
4. **Do NOT** manually `DELETE FROM companies WHERE ats='workday'` as part of rollback — the seed migration's `downgrade()` handles it via `alembic downgrade -1`, scoped properly to leave Greenhouse + Ashby intact.

---

## Out-of-Band Operator Actions

These ad-hoc commands are useful for QA but should not be required as part of the normal deploy:

- Force-refetch a single Workday company that's stuck:
  ```bash
  curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-workday-fetch?company_id=<id>' \
    -H "Authorization: Bearer ${ADMIN_TOKEN}"
  ```
- Inspect worker progress live:
  ```sql
  SELECT id, queue_name, task_name, status, args, attempts
  FROM procrastinate_jobs
  WHERE queue_name = 'workday_fetch' AND status IN ('todo', 'doing')
  ORDER BY id DESC LIMIT 20;
  ```
- Toggle a company's enabled flag (e.g. to skip it temporarily):
  ```sql
  UPDATE companies SET enabled = false WHERE id = '<company_id>' AND ats = 'workday';
  ```
- Inspect a single row's `provider_config`:
  ```sql
  SELECT id, board_token, provider_config FROM companies WHERE id = '<company_id>';
  ```
- Patch a malformed `provider_config` in place (operator hotfix; prefer a new
  migration for permanent changes):
  ```sql
  UPDATE companies
  SET provider_config = jsonb_set(provider_config, '{career_site_slug}', '"NewSlug"')
  WHERE id = '<company_id>' AND ats = 'workday';
  ```

---

## What's Out of Scope

Per [PLAN.md](./PLAN.md): Eightfold migration is tracked as a follow-up sibling PR. It will follow this same pattern with its own queue (`eightfold_fetch`) and `sourceAts` value (`'eightfold'`), and will reuse the `provider_config` JSONB column added in this migration — same name, different per-row shape (`{tenant_host, domain, default_page_size?}`).
