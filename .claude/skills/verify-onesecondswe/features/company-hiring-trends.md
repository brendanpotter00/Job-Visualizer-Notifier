# Company Hiring Trends — `/companies` (`ROUTES.COMPANIES`)

Per-company view: a time-bucketed hiring-activity chart plus the same job cards as
the Recent page, both driven by one filter source (`graphFilters`) — the list
reflects the chart.

Page: `src/frontend/src/pages/CompaniesPage/CompaniesPage.tsx`.

## Sub-features

- **Hiring-activity chart** — jobs for the selected company, bucketed over a time window
  (empty buckets preserved across the full range).
- **Job list** — the same `JobListingCard`s, filtered by the shared `graphFilters`.
- **Company selection** — pick a company; the chart + list re-key to it.
- **Click-through to a posting** — open one job's detail / apply URL.

## How to get to it (user POV)

Sidebar "Company Hiring Trends", route `/companies`. Public (signed-out visitors see it,
same ~12-row list cap as elsewhere).

## Driving it with WebMCP

- **Trend buckets (Tier-1):**
  ```ts
  const t = await call(page, 'get_company_hiring_trend', { company: 'apple', timeWindow: '90d' });
  // t.companyId === 'apple'; t.total > 0; t.buckets is [{ bucketStart, bucketEnd, count }]
  // — reuses jobsApi.getJobsForCompany + bucketJobsByTime (the page's own data path).
  ```
- **Resolve a company id or name first** with `list_companies` (accepts `query`); the trend
  tool takes an id or a display name and falls back to a raw id for user-added boards.
- **One posting (Tier-1):**
  ```ts
  const j = await call(page, 'get_job', { source: 'greenhouse_api', id: '8533961002' });
  // j.job.url is the apply link; also title, company, location, firstSeenAt, category, level
  ```
- **DOM assert:** the page heading is "Company Hiring Trends"; job titles render as
  `role=heading level=3` cards identical to the Recent page. Assert `t.total` is consistent
  with a non-empty rendered list for a company with data (Apple, SpaceX, Anduril all have
  thousands of open rows in the clone).

## Gotchas

- **Default window is `90d`** for `get_company_hiring_trend` (the trend page's own default),
  vs `all` for `search_jobs` — pass `timeWindow` explicitly when comparing the two.
- **Empty buckets are intentional** — `bucketJobsByTime` returns zero-count buckets across
  the full range; don't treat a `count: 0` bucket as missing data.
- **`get_job` needs a real `(source, id)` pair.** Get one from `search_jobs` /
  `get_company_hiring_trend` first. In this harness the whole `/api` is proxied to `:8201`
  (`vite.e2e.config.ts`), so `GET /api/jobs/{source}/{id}` reaches the backend and `get_job`
  works. In **prod** that sub-path is not yet allow-listed in `api/jobs.ts` (a separate
  additive widen) — a prod-only limitation, irrelevant to driving it here.
- **`total` counts the company's fetched jobs, not a global figure** — it's the length of
  `getJobsForCompany`'s cache entry, the exact set the chart buckets.
