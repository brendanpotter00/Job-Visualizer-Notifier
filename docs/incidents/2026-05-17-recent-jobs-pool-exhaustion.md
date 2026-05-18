# Incident: Recent Jobs Page Exhausts Backend Postgres Pool

**Date:** 2026-05-17 (regression deployed with #110 on prior day; reported and patched 2026-05-17)
**Severity:** Medium
**Impact:** Every load of the Recent Job Postings page (`/`) produced ~20 HTTP 500s on `/api/jobs?company=<id>` requests with `RuntimeError: Timed out waiting for a database connection`. Affected ~49 backend-scraper companies (all Greenhouse boards plus Google/Apple/Microsoft) on the SPA progress bar: about a third showed as "error" / had no job counts on first load. RTK Query's 10-minute cache absorbed the failure for subsequent visits within the same session, so the visible symptom for an individual user was "first load is broken, refresh fixes it intermittently." Backend availability for non-`/api/jobs` routes was unaffected by this incident alone — but the pre-existing proxy bug surfaced during diagnosis (see below) was making `/api/users` return 502 from local Vercel Dev, which was independently breaking the account page and the "Admin status unavailable" nav indicator. Both issues are fixed in #119.

## Summary

Before #110, three companies (Google/Apple/Microsoft) were served by the backend `/api/jobs` endpoint and the rest by external ATS APIs proxied through Vercel. The frontend has always fanned out one parallel fetch per company in `getAllJobs.onCacheEntryAdded`, but the three-DB-backed-companies load fit comfortably inside the backend's 15-slot Postgres pool. #110 migrated 46 Greenhouse boards from Vercel ATS proxies to the backend's Procrastinate queue + `/api/jobs`, growing the DB-backed set from 3 to 49 without changing the frontend's fanout pattern. The next page load attempted 49 simultaneous `/api/jobs?company=<id>` requests; the backend's per-request semaphore queues the 16th request onward, and the 5-second acquire timeout (`dependencies.py:76`) elapses on ~20 of them every time, producing 500s. Compounding the diagnosis: while restarting locally to validate the batched fix, the user hit a separate pre-existing bug in five Vercel serverless proxies that forwarded `req.body` for any non-null body — Vercel Dev parses an empty GET body as `{}`, and Node's `fetch` rejects \`Request with GET/HEAD method cannot have body\` — causing `/api/users` to return 502 and cascading into the FetchProgressBarSkeleton, account page, and nav admin indicator.

## Timeline

| Time (UTC)            | Event |
|-----------------------|-------|
| 2026-05-16 ~17:00     | #110 merges to `main` and deploys. The backend now ingests 46 Greenhouse boards via Procrastinate; the frontend's `createBackendScraperCompany('<id>', …)` factory is added for each one. The Recent Jobs page's per-company fanout to `/api/jobs?company=<id>` is unchanged. |
| 2026-05-17 01:46 — 02:00 | Railway production logs accumulate dense bursts of `RuntimeError: Timed out waiting for a database connection` on `/api/jobs` for `crunchyroll`, `apple`, `discord`, `gleanwork`, `gitlab`, `scaleai`, `airbnb`, `microsoft`, `lyft`, `thinkingmachines`, … — the backend-scraper set, matching page-load timing. The exception originates from `dependencies.py:76` (`semaphore.acquire(timeout=_pool_timeout)`), proving the failure mode is semaphore-timeout, not Postgres down or a query bug. |
| 2026-05-17 ~02:00     | User reports "almost 20 requests fail every time I go to [the Recent Job Postings page]". |
| 2026-05-17 ~02:30     | Root cause confirmed: 49 backend-scraper companies × parallel fanout against a 15-slot pool. Plan #119 drafted: collapse the 49-fanout into a single batched `/api/jobs?companies=a,b,c` request. |
| 2026-05-17 ~02:50     | Backend `companies` param + frontend `fetchJobsForCompanies` partition implemented and tested. All backend (`pytest`, 331 tests) and frontend (`vitest`, 1464 tests) suites pass. Type-check + lint clean. |
| 2026-05-17 ~03:00     | First local validation. Vercel Dev log shows `GET /api/jobs?status=OPEN&limit=5000 HTTP/1.1 200 OK` — **no `companies=` param** and the 5000 limit is hit. Diagnosis: `api/jobs.ts` proxy was passing only an allowlist of params (`status`, `company`, `limit`, `offset`) to the backend and silently dropping `companies`. Fixed in same PR. |
| 2026-05-17 ~03:15     | Second local validation. Backend now sees the `companies` param. With 16,257 total OPEN jobs across all backend-scraper companies and a former cap of `limit=5000`, the batched response was being truncated. Backend `le=10000` cap raised to `le=50000`; frontend batched default raised from `5000` to `50000`. Per-company default unchanged at 5000 (no single company has >5000 OPEN rows; Apple alone is 3,767). |
| 2026-05-17 ~03:30     | Third local validation. Recent Jobs page loads cleanly. User then reports `FetchProgressBarSkeleton` is stuck and the nav shows "Admin status unavailable". |
| 2026-05-17 ~03:40     | Diagnosis: `GET /api/users` returns 502 from Vercel Dev with body `{"error":"Upstream backend unavailable","details":"Request with GET/HEAD method cannot have body."}`. Root cause traced to `api/users.ts:39`'s `if (req.body != null)` body-forwarding gate. Pre-existing bug introduced when the proxies were homogenized to "forward body for any method" — Vercel Dev's body parser produces `{}` for an empty GET body, and `JSON.stringify({}) === "{}"` is non-empty truthy, so Node's `fetch` rejects the GET. The same anti-pattern is present in `api/admin.ts`, `api/features.ts`, `api/users.ts`, and `api/jobs-qa.ts`. |
| 2026-05-17 ~03:50     | All five proxies (above four + `api/jobs.ts` for the `companies` param) hardened with a POST/PUT/PATCH/DELETE method allowlist around body forwarding. |
| 2026-05-17 ~04:00     | PR #119 opened with both fixes bundled. Awaiting deploy + Railway log verification. |

## Root Cause

Two independent defects met on the Recent Jobs page. The first is the headline incident; the second was a pre-existing dormant bug that the diagnosis surfaced.

### Why the Recent Jobs page exhausts the pool

`src/frontend/src/features/jobs/jobsApi.ts` (`getAllJobs.onCacheEntryAdded`) iterates `COMPANIES` with `COMPANIES.map(async (company) => { … })` and `Promise.allSettled` — i.e. one parallel fetch per company, no concurrency cap. Before #110, that was 3 backend-scraper companies (Google/Apple/Microsoft) plus ~63 external ATS proxies. The 3 DB-backed calls used 3 of the 15 connection-pool slots and the page completed in under a second.

After #110, `createBackendScraperCompany(…)` was added for 46 Greenhouse boards, growing the backend-scraper set to 49 — fully 75% of the per-page fanout. Every page load now races 49 simultaneous `/api/jobs?company=<id>` requests against a pool sized for the pre-migration load:

```python
# src/backend/api/dependencies.py:24-35
def init_pool(dsn: str, minconn: int = 1, maxconn: int = 15, timeout: float = 5.0):
    _pool = ThreadedConnectionPool(minconn, maxconn, dsn, ...)
    _pool_semaphore = threading.Semaphore(maxconn)
    _pool_timeout = timeout
```

The semaphore lets requests queue rather than fail-fast with `PoolError`, but `semaphore.acquire(timeout=5.0)` raises `RuntimeError("Timed out waiting for a database connection")` if no slot opens within 5 s (`dependencies.py:76`). With 15 connections, an 8 MB-ish response from each query, and 49 requests, the back end of the queue cannot drain inside the timeout — ~20 requests fail every page load.

This was not a code regression on either side individually. The migration PR (#110) was correct: it moved Greenhouse onto the queue + DB-backed read path with proper deduplication, advisory locking, and tests. The frontend's `Promise.allSettled` fanout had been in `getAllJobs` since the initial multi-company implementation and was fine when N was small. The defect was a missing invariant: *N parallel reads against the DB-backed endpoint must stay ≤ the connection-pool slot count*. That invariant was implicit in the previous N=3 world and quietly violated when #110 grew N to 49.

The trigger was internal (config + factory additions in #110), not external, and the symptom appeared on the very next page load after deploy.

### Why `/api/users` was returning 502 once the batched fix was deployed locally

Five Vercel serverless proxies (`api/admin.ts`, `api/features.ts`, `api/jobs-qa.ts`, `api/users.ts`, and to a lesser extent `api/jobs.ts` for the new param) share a copy-pasted body-forwarding block:

```ts
if (req.body != null) {
  fetchOptions.body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
}
```

The intent, per the inline comment, was to support PATCH/DELETE bodies after a refactor removed an earlier `PUT/POST`-only restriction. The unstated assumption was that GET would have `req.body == null` and skip the block. In production-build Vercel that holds; in **Vercel Dev**, the local request parser produces `req.body = {}` for any incoming request, so the guard passes, `JSON.stringify({}) === "{}"` is attached as the request body, and Node's native `fetch` rejects GET/HEAD with body at the underlying `Request` constructor with `TypeError: Request with GET/HEAD method cannot have body`. The proxy's catch block turns that into 502 with the leaked detail string. The same defect is dormant in all five proxies — `/api/users` is the most visible because the account page, "Admin status unavailable" nav indicator, and `FetchProgressBarSkeleton` all depend on it.

The bug had been latent since the homogenization PR but had not surfaced because nobody had hit a code path that exercised both Vercel Dev *and* a GET request against one of these proxies under conditions that mattered. The Recent Jobs investigation forced a local restart cycle that exposed it.

## Fixes Applied

Both fixes ship in **PR #119**. Bundled because the diagnosis chain ran continuously and the proxy bug was only visible while validating the batching fix locally; splitting after the fact would have meant a synthetic re-bisection.

### Batching the DB-backed fanout

Files: `src/backend/api/routers/jobs.py`, `src/backend/api/services/database.py`, `src/frontend/src/api/clients/backendScraperClient.ts`, `src/frontend/src/features/jobs/jobsApi.ts`, plus tests.

**Backend**

- `GET /api/jobs` accepts a new `companies` query param: comma-separated, max 100 IDs, mutually exclusive with `company`. Empty values, empty IDs in the list, malformed IDs (validated against the existing `ENABLED_COMPANY_ID_PATTERN`), and the both-params combination all return 400. Backward-compatible — `company` keeps working for the per-company `/companies` page calls.
- `services/database.py` `_build_where` and `get_jobs` accept an optional `companies: list[str] | None` and emit `WHERE company = ANY(%s::text[])` via `psycopg2.sql.SQL` parameter binding (no string interpolation). The existing single-column `idx_job_listings_company` index serves the set scan; no new index needed at this scale.
- The `le=10000` limit cap is raised to `le=50000` to cover the union of OPEN jobs across all 49 companies (16,257 today, with Apple alone at 3,767). The per-company default remains 5000.

**Frontend**

- New `fetchJobsForCompanies(companyIds[])` in `backendScraperClient.ts`. Single `GET /api/jobs?companies=<csv>&status=OPEN&limit=50000`, groups the response rows by `row.company`, and returns one `FetchJobsResult` per requested ID — including empty `{ jobs: [], metadata: { totalCount: 0, … } }` for IDs absent from the response so per-company cache seeding stays uniform.
- `getAllJobs.onCacheEntryAdded` partitions `COMPANIES` into `backendScraperCompanies` (one batched call, all 49 progress entries flip success/error together) and `otherCompanies` (Lever/Ashby/Workday/Gem/Eightfold — keep the existing `Promise.allSettled` fanout against external Vercel proxies). Per-company progress updates and per-company RTK Query cache seeding via `upsertQueryData('getJobsForCompany', …)` are preserved on both branches so the `/companies` page click-through still hits a warm cache.

**Tests**

- Backend `test_jobs_router.py` gains 9 cases covering happy path with multiple companies, status combined with companies, `ORDER BY last_seen_at DESC` preserved across companies, unknown ID returns subset, rejection of empty value / empty ID-in-list / both-params / >100 IDs / invalid pattern.
- Frontend new files: `src/frontend/src/__tests__/api/backendScraperClient.test.ts` (7 tests — single call, grouping, missing-company → empty array, retryable APIError mapping for 5xx and 429, network error wrapping). `src/frontend/src/__tests__/features/jobs/jobsApi.batched.test.ts` (2 tests — exactly one `/api/jobs?companies=…` call on getAllJobs, per-company cache populated for every ID including ones with no rows).
- `src/frontend/src/__tests__/components/recent-jobs-page/RecentJobsFilters.test.tsx` adds a `vi.mock` for `fetchJobsForCompanies` paralleling the existing `getClientForATS` stub — the new entry point bypasses `getClientForATS`, so without this the seeded `byCompanyId['spacex']` cache was being clobbered to `[]` by the batched-fetch error path on every test in the file.

### Vercel proxy body-forwarding allowlist

Files: `api/admin.ts`, `api/features.ts`, `api/jobs-qa.ts`, `api/users.ts`, `api/jobs.ts`.

- All five proxies now gate body forwarding on a constant `const METHODS_WITH_BODY = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])` instead of `req.body != null` alone. The condition becomes `if (METHODS_WITH_BODY.has(req.method ?? '') && req.body != null)`. PATCH/DELETE still work; GET/HEAD no longer get a synthetic `{}` body in Vercel Dev.
- `api/jobs.ts` separately destructures the new `companies` query param from `req.query` and forwards it. The previous explicit allowlist of `status`/`company`/`limit`/`offset` was the reason the batched URL was being silently stripped during the first local validation.

## Lessons

- **A migration that changes "where a request lands" needs to revisit the request-shape on both sides.** #110 was internally correct as a backend migration, but it grew the population of one call shape (`/api/jobs?company=<id>`) from 3 to 49 without anyone re-checking the frontend's fanout pattern against the new N. The implicit `N ≤ pool slots` invariant lived only in operators' heads. For future migrations that consolidate routes, add an explicit "max concurrent calls under the new topology" check in the PR description — and prefer one batched/aggregated call over a fanout from day one when the data model supports it.
- **Always specify whether a `limit` is per-something or total.** The per-company `limit=5000` was correct (no single company has 5000 OPEN rows). The batched call inherited the same `5000` default and silently became a 5000-row-total cap across 49 companies. The bug was invisible from the URL — the caller had no way to tell which semantics applied without reading the route handler. Where a query param's semantics depend on whether another param is present, name the limits accordingly (`limit_per_company`, `total_limit`) or push the time/recency filter into SQL so the result set bounds itself.
- **Shared serverless-proxy code paths copy-paste their bugs.** Five proxies had the same defective body-forwarding gate. The fix was a one-line allowlist applied to each. The next layer of defense would be a shared `forwardRequest(req, res, targetUrl)` helper alongside the existing `forwardResponse` so the next "forward body for any method" refactor only has to be reviewed in one place. Punted from this PR; logged as a follow-up.
- **Vercel Dev and Vercel production parse `req.body` differently for GET.** Local dev produces `{}`; production produces `undefined`. Any check shaped `if (req.body)` or `if (req.body != null)` is a tripwire. Treat the body's truthiness as method-gated, not type-gated.
- **Two-stage validation chain saved time.** The 50000-row truncation and the proxy 502 both surfaced only because local validation kept going past "the unit tests passed." If the PR had been pushed straight from green CI it would have shipped a Recent Jobs page that worked but silently capped at 5000 jobs, and Daisy/Brendan would have eventually noticed missing companies and hit the same diagnosis. The hour spent on local validation collapsed two future incidents into one PR.

## Related

- #110 (`Move Greenhouse to Backend Cron + Queue`) — the migration that grew the DB-backed fanout from 3 to 49 and triggered the pool exhaustion. The migration itself was correct; this incident is the post-migration fanout-shape follow-up.
- `docs/implementations/greenhouseBackendMigration/PLAN.md` — pre-implementation plan for #110.
- `src/backend/CLAUDE.md` "Configuration" section — documents `DB_POOL_MAX=15` and the semaphore-with-timeout model that produced the visible error string.
- Prior Railway pool-pressure incident from April 2026 (`memory/project_railway_backend_health.md`) — the 8→15 bump that gave headroom for the pre-#110 world but, as noted in that memory, can't be raised further without provoking memory pressure on the Railway instance. That memory is what made "raise the cap to 50" the wrong answer and "collapse the fanout" the right one.
