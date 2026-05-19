# Eightfold Backend Migration — Deploy Runbook

This runbook covers the production deploy of the Eightfold → backend cron+queue migration (Units 1–10 of [PLAN.md](./PLAN.md), Unit 9 skipped). The entire change ships as a **single PR** spanning backend (Railway) and frontend (Vercel).

The pattern is structurally identical to the Greenhouse and Ashby migrations in [`../greenhouseBackendMigration/DEPLOY.md`](../greenhouseBackendMigration/DEPLOY.md) and [`../ashbyBackendMigration/DEPLOY.md`](../ashbyBackendMigration/DEPLOY.md). Read those runbooks in parallel — anything not contradicted here applies equally to Eightfold.

Eightfold has **one** company today (Netflix), so the operational footprint is smaller than Ashby (46) or Greenhouse (45). The security footprint is **larger** — the SSRF allowlist that lived in `api/eightfold.ts` was deleted in this PR and is now enforced in Python (`src/backend/api/services/eightfold_client.py`). Read the "Security Posture Change" section below before merging.

---

## Security Posture Change — SSRF allowlist moves Python-side

`api/eightfold.ts` (the deleted Vercel proxy) was the only thing preventing a wrong `tenant_host` from being turned into an SSRF target. Once it's gone, the same guarantee is enforced by `_is_allowed_eightfold_host` in `src/backend/api/services/eightfold_client.py`, applied at three layers:

| Layer | Where | Triggers |
|---|---|---|
| L1 (build) | The Alembic seed migration ships `tenant_host: 'explore.jobs.netflix.net'` — already on the allowlist. | Build-time check; never wrong if migration is unmodified. |
| L2 (queue) | `enqueue_eightfold_fan_out` re-validates `provider_config` before calling `defer_async`. | Row inserted out-of-band of the seed migration with a wrong `tenant_host`. |
| L3 (task) | `fetch_eightfold_company` re-validates `provider_config` at task entry, BEFORE any HTTP. | Hand-crafted `defer_async` (operator, buggy admin endpoint) with a wrong `tenant_host`. |

Allowlist contents (transcribed verbatim from the deleted `api/eightfold.ts`):

- Regex: `^(?:[a-z0-9-]+\.)*eightfold\.ai$` (case-insensitive)
- Vanity hosts: `{"explore.jobs.netflix.net"}`

**Adding a new Eightfold company in the future requires updating BOTH the seed migration (so the row exists) AND the vanity-host set in `eightfold_client.py` (so the fetch task accepts it).** The two were coupled in `api/eightfold.ts` originally; now this file is the source of truth.

---

## Workday PR #123 rebase coordination

This PR's Alembic migration adds a `provider_config JSONB NOT NULL DEFAULT '{}'::jsonb` column to `companies` AND seeds Netflix. The parallel **Workday PR #123** introduces the same column.

- **If Workday merges first (most likely):** rebase this PR. Edit the migration `20260519_*_add_provider_config_to_companies_and_seed_eightfold_companies.py`:
  1. Bump `down_revision` to point at the Workday migration revision (currently `b9714f608e21` on `feat/workday-backend-cron-queue`).
  2. **Remove the `op.add_column` half from `upgrade()`** and **the `op.drop_column` half from `downgrade()`** — the column already exists from Workday's migration.
  3. Keep the data-migration half (the `INSERT INTO companies ... ON CONFLICT (id) DO NOTHING`).
  4. Update the docstring's "Combined schema + data migration" line to "Data-only migration (column added by Workday migration)".
  5. Update the round-trip test `test_eightfold_seed_migration_roundtrip` — the `_column_exists` checks become regression guards against the Workday-merged column going away.

- **If this PR merges first:** the Workday rebase is the mirror operation.

The column name `provider_config` is a **frozen contract** between the two PRs — the rebase is mechanical, not architectural.

---

## Critical: Implicit Deploy Ordering

Even though Units 1–10 ship in one merge, the runtime deploys land on two different platforms with **different propagation timing**:

| Platform | What ships | Typical time to live |
|---|---|---|
| Railway (backend) | Units 1–6: `SourceId.EIGHTFOLD`, `provider_config` column + Netflix seed migration, `eightfold_client.py` (with SSRF allowlist), `fetch_eightfold_company` task, `enqueue_eightfold_fan_out` periodic, expanded worker queues (`eightfold_fetch` added), admin trigger endpoints | ~2–4 min build + boot |
| Vercel (frontend) | Units 7–8: Netflix in `companies.ts` flipped to `backend-scraper`, `api/eightfold.ts` **deleted**, eightfold client + transformer + serverless test deleted, `vercel.json` rewrite removed, Why-page Eightfold column gets the capitalized display name | ~1–2 min |

**The backend MUST be live with `/api/jobs?company=netflix` returning Eightfold rows BEFORE frontend traffic hits the `backend-scraper` code paths for Netflix.** If Vercel finishes first, frontend will request `/api/jobs?company=netflix` against a backend that hasn't yet (a) seeded the Netflix row, (b) booted the worker with `eightfold_fetch`, (c) populated `job_listings` with `eightfold_api` rows. Result: empty job list for Netflix for ~30 min until the first cron tick.

Mitigation: **the fan-out cron only runs every 30 min.** Don't wait — fire it manually as soon as Railway is healthy (see "Post-Deploy Monitoring" below). This collapses the window from 30 min to ~30 sec.

A partial mid-PR rollback is **not possible** — `api/eightfold.ts`, `eightfoldClient.ts`, and `eightfoldTransformer.ts` are deleted in the same PR. If frontend goes live before backend, you cannot temporarily flip it back. Revert the merge commit instead.

---

## Pre-Merge Checklist

- [ ] **Env vars unchanged.** Eightfold's public `/api/apply/v2/jobs` endpoint requires no authentication; the new task uses the existing `DATABASE_URL`. Confirm with `railway variables`.
- [ ] **Migrations round-trip clean locally.**
  ```bash
  cd src/backend
  alembic upgrade head
  alembic downgrade -1  # reverts add_provider_config + seed_eightfold
  alembic upgrade head
  ```
  The migration must apply (column add + 1 Netflix row), revert (column drop + Netflix delete scoped to `ats='eightfold'` — Greenhouse and Ashby rows must survive), and re-apply without error.
- [ ] **Workday rebase status confirmed.** If Workday PR #123 has merged, see "Workday PR #123 rebase coordination" above before merging this PR.
- [ ] **`SAFETY_GUARD_RATIO=0.1` is shared** (`scripts/shared/incremental.py`). The new `fetch_eightfold_company` task uses the same guard as Greenhouse + Ashby.
- [ ] **MAX_PAGES = 100 in `eightfold_client.py`.** Confirms partial-return backstop is in place. At MAX_PAGES, the task logs ERROR and returns the partial result rather than raising — a partial-but-large fetch is more useful than zero-jobs that would trip the safety guard.
- [ ] **SSRF allowlist contents** in `src/backend/api/services/eightfold_client.py` match the deleted `api/eightfold.ts`:
  ```bash
  grep -E "explore.jobs.netflix.net|eightfold\\\\.ai" src/backend/api/services/eightfold_client.py
  # Should show: the regex pattern + the vanity-host set entry.
  ```
- [ ] **Backend tests pass:** `cd src/backend && pytest` clean. Coverage ≥ baseline.
- [ ] **Frontend type-check + tests pass:** `npm run type-check && npm test` clean.
- [ ] **No lingering Eightfold legacy references:**
  ```bash
  grep -rE "EightfoldConfig|EightfoldJobPosition|EightfoldAPIResponse|createEightfoldCompany|eightfoldClient|eightfoldTransformer" src/frontend/src/ api/ vercel.json
  ```
  Must return zero matches (excluding `sourceAts: 'eightfold'` which is intentional).
- [ ] **`api/eightfold.ts` is deleted** (not just commented out) and no `vercel.json` rewrite points to it.
- [ ] **Netflix is the only Eightfold company in companies.ts:**
  ```bash
  grep -c "sourceAts: 'eightfold'" src/frontend/src/config/companies.ts  # → 1
  ```
- [ ] **CHANGELOG entry** drafted (per project ship workflow).

---

## Deploy Sequence

1. **Merge the PR to `main`.** Railway and Vercel auto-deploy on merge.
2. **Watch Railway build logs.** Look for:
   - `apply_alembic_migrations: upgrade head` — successful migration run, including `08e719b2aa03 add_provider_config_to_companies_and_seed_eightfold_companies`.
   - `Procrastinate app opened`.
   - `Procrastinate worker background task started (queues=['greenhouse_fetch', 'ashby_fetch', 'eightfold_fetch'], concurrency=5)` — confirms Unit 5's queue expansion landed.
   - **No** `not on the SSRF allowlist` errors at startup (those would indicate a malformed `tenant_host` in the seed migration).
   - **No** repeated `connection pool exhausted` warnings.
3. **Once Railway reports healthy, manually trigger the Eightfold fan-out** to skip the 30-min cron wait:
   ```bash
   # Admin-gated; needs an Auth0 bearer token for an account with a row in
   # the `admins` table.
   #     export ADMIN_TOKEN="$(... your auth flow here ...)"
   curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-eightfold-fan-out' \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   # Expect: 202. Without bearer: 401. With non-admin: 403.
   ```

   To manually fire Netflix's per-company task instead:
   ```bash
   curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-eightfold-fetch?company_id=netflix' \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
   ```
4. **Watch Vercel deploy.** Spot-check the preview URL once before promotion: open the Why page and confirm the new "Eightfold (1)" column renders (with capital E — was previously lowercased).

---

## Post-Deploy Monitoring

### First 30-min sanity check

Run all of these against prod Postgres (use the `postgres-prod` MCP or `psql` with the Railway connection string).

**1. The seed populated 1 Eightfold company with valid provider_config:**

```sql
SELECT count(*) FROM companies WHERE ats = 'eightfold';
-- Expected: 1

SELECT id, board_token, provider_config FROM companies WHERE ats = 'eightfold';
-- Expected: ('netflix', 'netflix', {"tenant_host": "explore.jobs.netflix.net", "domain": "netflix.com"})

SELECT count(*) FROM companies WHERE ats = 'eightfold'
  AND provider_config ? 'tenant_host'
  AND provider_config ? 'domain';
-- Expected: 1 (integrity check — both required keys present)
```

**2. Periodic scheduler is registered:**

```sql
SELECT * FROM procrastinate_periodic_defers
WHERE task_name = 'enqueue_eightfold_fan_out'
ORDER BY defer_timestamp DESC
LIMIT 5;
```

Expect: at least 1 row with a recent `defer_timestamp`. If empty, the `@app.periodic` decorator never registered — check Railway logs for import errors in `src/backend/api/tasks/enqueue_eightfold_fan_out.py` (most likely cause: `__init__.py` is missing the side-effect import).

**3. Fan-out enqueued tasks (after manual trigger):**

```sql
SELECT status, count(*)
FROM procrastinate_jobs
WHERE queue_name = 'eightfold_fetch'
GROUP BY status;
```

Expect: ~1 row (Netflix only — Eightfold has 1 company today), in `succeeded` after ~30 sec. If the row is stuck in `failed` with a "not on the SSRF allowlist" message, the seed migration's `tenant_host` is wrong (this should be impossible if the migration was deployed unmodified).

**4. `scrape_runs` rows landing:**

```sql
SELECT *
FROM scrape_runs
WHERE company = 'netflix'
  AND started_at > now() - interval '5 minutes'
ORDER BY started_at DESC;
-- Expected: ≥ 1 row, with mode='full', jobs_seen ≈ Netflix's open-job count (~600-1000),
--           error_count=0 (or error_count=1 if the safety guard tripped — investigate).
```

**5. `job_listings` populated:**

```sql
SELECT count(*) FROM job_listings
WHERE source_id = 'eightfold_api' AND company = 'netflix' AND status = 'OPEN';
-- Expected: hundreds to a thousand+ rows, depending on Netflix's current open req count.
```

**6. The pagination cap did NOT fire:**

Search Railway logs for `MAX_PAGES`. If the log line "Eightfold pagination MAX_PAGES (100) reached for explore.jobs.netflix.net" appears, raise `MAX_PAGES` in `eightfold_client.py` — Netflix has more than 1000 open reqs and we're returning partial data.

### 2-hour cross-reference

Spot-check Netflix against the live Eightfold API:

```bash
curl -s 'https://explore.jobs.netflix.net/api/apply/v2/jobs?domain=netflix.com&num=10&start=0' \
  | jq '.count'
```

Then:

```sql
SELECT count(*) FROM job_listings
WHERE source_id = 'eightfold_api' AND company = 'netflix' AND status = 'OPEN';
```

The DB count should be `>=` (or very close to) the API's reported `count`. Minor drift is acceptable because of the consecutive-misses lifecycle (a job seen earlier today but not in this minute's fetch is still `OPEN` until misses ≥ 2). Also note Eightfold sometimes under-reports `count` — the DB number is the ground truth.

### Frontend smoke

Open `/companies` and select Netflix. Jobs should render. Network tab should show `/api/jobs?company=netflix`, **zero** `/api/eightfold/*` requests.

Open `/why`. Four ATS columns visible: **Ashby (46)**, **Greenhouse (45)**, **Eightfold (1)** (Netflix only), **Custom Web Scrapers (3)** (Google/Apple/Microsoft only). The "Eightfold" header should be capitalized (was lowercase before this PR).

---

## Rollback

If something breaks:

1. **Revert the merge commit on `main`.** Both Railway and Vercel will auto-redeploy the reverted SHA. The Netflix row in the DB will remain seeded (no schema-level rollback) but the worker stops listening on `eightfold_fetch` once `main.py` reverts. That's safe — orphan rows are harmless and `procrastinate_jobs` drains gracefully via `SELECT … FOR UPDATE SKIP LOCKED`.
2. **Asymmetric rollback risk:** `api/eightfold.ts`, `eightfoldClient.ts`, and `eightfoldTransformer.ts` were deleted. Reverting the merge restores them, but if Vercel deploys the revert before Railway, the frontend will briefly try to fetch from `/api/eightfold/*` against a backend that hasn't restored the Vercel proxy yet (since the proxy is a Vercel artifact, this should auto-resolve when Vercel's revert completes — typically ~1 min behind Railway).
3. **`provider_config` column survives the revert.** If the Workday PR has NOT merged, the column was added by this PR's migration; reverting drops it via `downgrade()`. If Workday HAS merged, the column predates this PR and is left alone by the (rebased) revert — that's correct.
4. **Do NOT** manually `DELETE FROM companies WHERE ats='eightfold'` as part of rollback — the seed migration's `downgrade()` handles it scoped to `ats='eightfold'`, leaving Greenhouse + Ashby + Workday intact.

---

## Out-of-Band Operator Actions

These ad-hoc commands are useful for QA but should not be required as part of the normal deploy:

- Force-refetch Netflix:
  ```bash
  curl -X POST 'https://<RAILWAY_BACKEND>/api/jobs-qa/trigger-eightfold-fetch?company_id=netflix' \
    -H "Authorization: Bearer ${ADMIN_TOKEN}"
  ```
- Inspect worker progress live:
  ```sql
  SELECT id, queue_name, task_name, status, args, attempts
  FROM procrastinate_jobs
  WHERE queue_name = 'eightfold_fetch' AND status IN ('todo', 'doing')
  ORDER BY id DESC LIMIT 20;
  ```
- Toggle Netflix's enabled flag (e.g. to skip it temporarily):
  ```sql
  UPDATE companies SET enabled = false WHERE id = 'netflix' AND ats = 'eightfold';
  ```
- Add a new Eightfold-hosted company (requires a new Alembic migration AND a vanity-host allowlist entry):
  1. Write a new Alembic migration that does `INSERT INTO companies` with the new id + `provider_config={tenant_host, domain}`.
  2. Edit `src/backend/api/services/eightfold_client.py::_EIGHTFOLD_VANITY_HOSTS` to include the new `tenant_host` (only required if it's not under `*.eightfold.ai`).
  3. Add a `createBackendScraperCompany` entry to `src/frontend/src/config/companies.ts` with `sourceAts: 'eightfold'`.
  4. Ship as a separate PR.

---

## What's Out of Scope

Per [PLAN.md](./PLAN.md#non-goals): Lever / Workday / Gem migrations are tracked in their own PRs. Each follows this same pattern with its own queue (`lever_fetch`, etc.) and `sourceAts` value. The Workday PR shares the `provider_config` column with this PR (see "Workday PR #123 rebase coordination" above).
