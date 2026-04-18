# Eightfold AI ATS Provider — Implementation Plan

## TL;DR — Quick Reference

### Eightfold → Job model field mapping (from live `curl` of `explore.jobs.netflix.net`)

| Eightfold field (positions[]) | Type | → Job field | Transform |
|---|---|---|---|
| `id` | number | `id` | `String(raw.id)` |
| `name` | string | `title` | pass through |
| `department` | string \| null | `department` | pass through (undefined if null) |
| `location` | string ("City,State,Country") | `location` | split on `,`, trim, rejoin with `, ` |
| `locations` | string[] | (fallback) | use `[0]` if top-level `location` is empty |
| `t_create` | unix seconds (integer) | `createdAt` | `new Date(raw.t_create * 1000).toISOString()` |
| `t_update` | unix seconds | (fallback) | use only if `t_create` missing |
| `canonicalPositionUrl` | string | `url` | pass through |
| `work_location_option` | `"onsite"` \| `"remote"` \| `"hybrid"` \| null | `isRemote` | `raw.work_location_option === 'remote'` |
| `business_unit` | string \| null | (not mapped) | ignore for now |
| `display_job_id` / `ats_job_id` | string | `tags` (optional) | include as single-element tag |
| `type` | `"ATS"` | (ignored) | always `ATS` |
| `isPrivate` | boolean | filter | **SKIP** if `true` |
| `job_description` | string (often empty) | (ignored) | not stored on Job model |
| `source` | — | `source` | hard-coded `'eightfold'` |
| `company` | — | `company` | passed as `identifier` arg |

### File-by-file change list (execution order)

| # | Path | Action |
|---|---|---|
| 1 | `src/frontend/src/types/index.ts` | Add `'eightfold'` to `ATSProvider`; add `EightfoldConfig` interface; extend `Company.config` union |
| 2 | `src/frontend/src/api/types.ts` | Add `EightfoldJobPosition`, `EightfoldAPIResponse` types; extend `ATSConstants`; extend `APIError.atsProvider` union; extend `JobAPIClient.fetchJobs` config union |
| 3 | `src/frontend/src/api/clients/baseClient.ts` | Extend `ATSCompanyConfig` union; widen error-throwing `config.type` cast to include `'eightfold'` |
| 4 | `src/frontend/src/api/transformers/eightfoldTransformer.ts` | **NEW** — `transformEightfoldJob(raw, companyId)` |
| 5 | `src/frontend/src/api/clients/eightfoldClient.ts` | **NEW** — custom paginating client (modeled on `workdayClient`) |
| 6 | `src/frontend/src/api/utils.ts` (or wherever `getClientForATS` lives) | Add `case 'eightfold': return eightfoldClient;` |
| 7 | `api/eightfold.ts` | **NEW** — Vercel serverless proxy (GET, CORS, SSRF guard) |
| 8 | `src/frontend/src/config/companies.ts` | Add `createEightfoldCompany` factory; REMOVE Netflix Workday block (lines ~450–462); ADD Netflix Eightfold entry |
| 9 | `src/frontend/src/__tests__/api/transformers/eightfoldTransformer.test.ts` | **NEW** — mirror `workdayTransformer.test.ts` |
| 10 | `src/frontend/src/__tests__/api/eightfoldClient.test.ts` | **NEW** — pagination, error handling, abort signal |
| 11 | `src/frontend/src/__tests__/api/serverless/eightfold.serverless.test.ts` | **NEW** — proxy handler tests |
| 12 | `src/frontend/src/__tests__/api/utils.test.ts` (if exists) | UPDATE — add eightfold dispatch case |

---

## 1. Context and Verified Facts

### 1.1 Why this change

Netflix's Workday endpoint `https://netflix.wd1.myworkdayjobs.com/wday/cxs/netflix/Netflix/jobs` now returns HTTP 303 → `https://community.workday.com/maintenance-page`. Netflix has migrated to Eightfold AI. Their public careers portal now lives at `https://explore.jobs.netflix.net/` (backing `jobs.netflix.com`).

This plan adds **Eightfold** as a new ATS provider (joining greenhouse / lever / ashby / gem / workday / backend-scraper) and migrates Netflix from Workday to Eightfold.

### 1.2 Eightfold endpoint (verified by `curl` on 2026-04-18)

```
GET https://{tenantHost}/api/apply/v2/jobs?domain={domain}&num={pageSize}&start={offset}
```

For Netflix: `tenantHost = "explore.jobs.netflix.net"`, `domain = "netflix.com"`.

Response shape (top-level keys observed):
```
{ domain, positions: [...], count: 609, branding: {...}, facets: {...}, ... }
```

Each `positions[]` entry (observed live):
```json
{
  "id": 790315489399,
  "name": "Administrative Assistant, Post Services",
  "location": "Los Angeles,California,United States of America",
  "locations": ["Los Angeles,California,United States of America"],
  "department": "Administration",
  "business_unit": "Streaming",
  "t_update": 1776297600,
  "t_create": 1776297600,
  "ats_job_id": "JR40083",
  "display_job_id": "JR40083",
  "type": "ATS",
  "job_description": "",
  "work_location_option": "onsite",
  "canonicalPositionUrl": "https://explore.jobs.netflix.net/careers/job/790315489399",
  "isPrivate": false,
  "stars": 0,
  "medallionProgram": null,
  "location_flexibility": null
}
```

### 1.3 Pagination cap — CRITICAL

Empirical testing (2026-04-18): **the server hard-caps `num` at 10** regardless of what's requested. Netflix currently has `count = 609`, so fetching everything requires **~61 sequential requests**. `start=600` returns 9 rows (partial final page).

### 1.4 CORS decision — PROXY REQUIRED

`curl -i -H "Origin: http://localhost:5173" https://explore.jobs.netflix.net/api/apply/v2/jobs?...` response:

- `content-type: application/json`
- NO `Access-Control-Allow-Origin` header
- Preflight OPTIONS returns `200` but NO CORS headers

Browsers will block direct requests. **We need a Vercel serverless proxy** mirroring `api/greenhouse.ts`. Proxy will be at `api/eightfold.ts`.

### 1.5 Date format

`t_create` and `t_update` are **unix timestamps in seconds** (not milliseconds). Values like `1776297600` decode to `2026-04-15T00:00:00.000Z`.

---

## 2. Type System Changes

### 2.1 `src/frontend/src/types/index.ts`

1. **Widen `ATSProvider`**:
   ```ts
   export type ATSProvider = 'greenhouse' | 'lever' | 'ashby' | 'workday' | 'gem' | 'eightfold' | 'backend-scraper';
   ```

2. **Add `EightfoldConfig`**:
   ```ts
   export interface EightfoldConfig {
     type: 'eightfold';
     /** Eightfold tenant host, e.g. "explore.jobs.netflix.net" (no protocol) */
     tenantHost: string;
     /** Domain query parameter Eightfold uses to scope jobs, e.g. "netflix.com" */
     domain: string;
     /** Optional override (server caps at 10) */
     defaultPageSize?: number;
     /** Optional custom API base URL (defaults to /api/eightfold) */
     apiBaseUrl?: string;
   }
   ```

3. **Extend `Company.config` union**:
   ```ts
   config: GreenhouseConfig | LeverConfig | AshbyConfig | GemConfig | WorkdayConfig | EightfoldConfig | BackendScraperConfig;
   ```

### 2.2 `src/frontend/src/api/types.ts`

1. Add `EightfoldJobPosition` and `EightfoldAPIResponse` types (see §3 mapping).
2. Extend `ATSConstants` with `Eightfold = 'eightfold'`.
3. Widen `APIError.atsProvider` union and `JobAPIClient.fetchJobs` config union.

### 2.3 `src/frontend/src/api/clients/baseClient.ts`

1. Extend `ATSCompanyConfig` union to include `EightfoldConfig`.
2. Widen error-throwing `config.type` casts to include `'eightfold'`.

---

## 3. Transformer — `src/frontend/src/api/transformers/eightfoldTransformer.ts` (NEW)

```ts
import type { Job } from '../../types';
import type { EightfoldJobPosition } from '../types';

export function transformEightfoldJob(
  raw: EightfoldJobPosition,
  companyId: string
): Job {
  const id = String(raw.id ?? raw.ats_job_id ?? raw.display_job_id ?? '');

  const rawLocation = raw.location || raw.locations?.[0];
  const location = rawLocation
    ? rawLocation.split(',').map((s) => s.trim()).filter(Boolean).join(', ')
    : undefined;

  const department = raw.department || undefined;

  const unixSeconds = raw.t_create ?? raw.t_update;
  const createdAt = unixSeconds
    ? new Date(unixSeconds * 1000).toISOString()
    : new Date().toISOString();

  const isRemote = raw.work_location_option === 'remote';

  const reqId = raw.display_job_id || raw.ats_job_id;
  const tags = reqId ? [reqId] : undefined;

  return {
    id,
    source: 'eightfold' as const,
    company: companyId,
    title: raw.name,
    department,
    location,
    isRemote,
    createdAt,
    url: raw.canonicalPositionUrl,
    tags,
    raw,
  };
}
```

**Key decisions / rationale**:

- `t_create` is the posting time. Unix **seconds**, so multiply by 1000.
- `raw.location` is comma-delimited without spaces — split+rejoin with `", "` for display consistency.
- `isPrivate` positions are filtered in the **client**, not the transformer.
- `employmentType` and `team` are not available on Eightfold list endpoint — leave undefined.

**Note on Job model**: verify the exact `Job` interface in `src/frontend/src/types/index.ts` during implementation. If field names differ (e.g., `postedAt` vs `createdAt`, `jobUrl` vs `url`), adjust to match.

---

## 4. Client — `src/frontend/src/api/clients/eightfoldClient.ts` (NEW)

**Decision**: Do NOT use `createAPIClient` factory. Eightfold requires pagination (page cap = 10, 61+ pages for Netflix). Follow the `workdayClient.ts` pattern.

### 4.1 Constants

```ts
const EIGHTFOLD_MAX_PAGE_SIZE = 10; // Hard server-side cap, verified 2026-04-18
const MAX_ITERATIONS = 200; // Safety: 200 * 10 = 2000 jobs. Raise if a tenant grows beyond.
```

### 4.2 Control flow (mirror `workdayClient`)

1. **Validate config type** — throw if `config.type !== 'eightfold'`.
2. **Build endpoint**:
   ```ts
   const apiBase = cfg.apiBaseUrl || '/api/eightfold';
   const endpoint = `${apiBase}/api/apply/v2/jobs`;
   ```
3. **Pagination loop** (while `iteration < MAX_ITERATIONS`):
   - `const url = \`${endpoint}?domain=${encodeURIComponent(cfg.domain)}&num=${pageSize}&start=${offset}\``
   - `fetch(url, { signal, headers: { Accept: 'application/json', 'X-Eightfold-Tenant-Host': cfg.tenantHost }})`
   - If `!response.ok`: throw `APIError` (retryable on 500/503/429).
   - `const data: EightfoldAPIResponse = await response.json()`
   - On first iteration: capture `total = data.count`
   - `allPositions.push(...data.positions)`
   - **Stopping conditions** (any): `fetchedSoFar >= total`, `fetchedSoFar >= options.limit`, `data.positions.length === 0`, `data.positions.length < pageSize`
   - Else: `offset += pageSize`
4. **Filter invalid/private**:
   ```ts
   const valid = allPositions.filter(
     (p) => p.id && p.name && p.canonicalPositionUrl && !p.isPrivate
   );
   ```
5. **Transform**: derive `companyId` from `cfg.domain.split('.')[0]`. For `"netflix.com"` → `"netflix"`. Document this contract: `cfg.domain` must start with the internal company slug.
6. **Apply `since` filter** client-side (copy from workdayClient).
7. **Apply `limit`** client-side.
8. **Return** `{ jobs, metadata: { totalCount, fetchedAt } }`.

### 4.3 Edge cases

- **Abort**: `options.signal` threaded into every `fetch`. Check `signal.aborted` before next page.
- **Sequential fetches** (not parallel) to stay polite to the undocumented endpoint.
- **Max iterations guard**: log error; return partial results.
- **JSON parse errors**: wrap in retryable `APIError`.

---

## 5. Serverless Proxy — `api/eightfold.ts` (NEW)

Modeled on `api/greenhouse.ts` (GET passthrough) with Workday-style dynamic host handling.

Key features:
- CORS headers: `Access-Control-Allow-Origin: *`, methods `GET, OPTIONS`, allowed header `X-Eightfold-Tenant-Host`.
- `X-Eightfold-Tenant-Host` header required. Validate against `EIGHTFOLD_HOST_PATTERN = /^[a-z0-9.-]+\.(eightfold\.ai|net|com)$/i` as an SSRF guard.
- Path constraint: `targetPath` must start with `api/apply/`.
- Build `targetUrl = \`https://${tenantHeader}/${targetPath}${qs}\`` and fetch GET with `Accept: application/json`, descriptive `User-Agent`.
- Forward response status + body.
- Log `[Eightfold Proxy]` request/response for debugging.

**`vercel.json` rewrite**: check whether `vercel.json` has catch-all rewrites for existing proxies (e.g., `/api/eightfold/(.*)` → `/api/eightfold?path=$1`). If greenhouse/lever/ashby have them, add analogous rewrite for eightfold.

---

## 6. Client dispatch

Find the ATS dispatch (`getClientForATS` or similar — search repo for `case 'greenhouse'` in `src/frontend/src/api/`). Add:

```ts
case 'eightfold':
  return eightfoldClient;
```

Import at top of the dispatch file.

---

## 7. Company config — `src/frontend/src/config/companies.ts`

### 7.1 Add factory

Insert after `createWorkdayCompany` and before `createBackendScraperCompany`:

```ts
interface EightfoldOptions extends FactoryOptions {}

function createEightfoldCompany(
  id: string,
  name: string,
  eightfoldConfig: {
    tenantHost: string;
    domain: string;
  },
  options: EightfoldOptions = {}
): Company {
  const config: EightfoldConfig = {
    type: 'eightfold',
    tenantHost: eightfoldConfig.tenantHost,
    domain: eightfoldConfig.domain,
  };
  const jobsUrl = `https://${eightfoldConfig.tenantHost}/careers`;
  return {
    id,
    name,
    ats: 'eightfold',
    config,
    jobsUrl,
    recruiterLinkedInUrl: options.recruiterLinkedInUrl,
  };
}
```

Add `EightfoldConfig` to the imports.

### 7.2 Remove Netflix Workday entry

Delete the existing block (around lines 450–462) that calls `createWorkdayCompany('netflix', 'Netflix', ...)`.

### 7.3 Add Netflix Eightfold entry

New `// Eightfold companies` section after the Workday block, before the Backend scraper block:

```ts
// Eightfold companies
createEightfoldCompany(
  'netflix',
  'Netflix',
  {
    tenantHost: 'explore.jobs.netflix.net',
    domain: 'netflix.com',
  },
  {
    recruiterLinkedInUrl:
      'https://www.linkedin.com/search/results/content/?keywords=hiring%20software%20engineer&origin=FACETED_SEARCH&sortBy=%5B%22relevance%22%5D&authorCompany=%5B%22165158%22%5D',
  }
),
```

`COMPANY_IDS.Netflix = 'netflix'` stays unchanged.

---

## 8. Tests (target ≥85% coverage)

### 8.1 `eightfoldTransformer.test.ts`

Mirror `workdayTransformer.test.ts`. Cover:
- Basic transformation of a full Netflix position fixture.
- ID fallback (numeric → ats_job_id → display_job_id → empty).
- Location split/trim/rejoin with `, `; fallback to `locations[0]`; undefined when both absent.
- Date parsing (unix seconds → ISO); fallback `t_create → t_update → now`.
- `isRemote` detection for `remote`, `onsite`, `hybrid`, null.
- Private filter is NOT applied in transformer (preserves `raw`).
- Reference equality of `raw`.

### 8.2 `eightfoldClient.test.ts`

Mock `globalThis.fetch`. Cover:
- Rejects non-eightfold config types.
- Single-page result (count=5).
- Multi-page with correct `start=0,10,20,...` (count=25 → 3 pages → 25 aggregated).
- Partial final page triggers stop (count=23).
- Empty-page safety.
- `options.limit` stops early.
- `isPrivate: true` positions filtered out.
- Positions missing `canonicalPositionUrl` dropped.
- 500/429 → retryable APIError; 404/401 → non-retryable.
- Network error and JSON parse error wrapped properly.
- `since` filter by `createdAt`.
- `signal` threaded and respected.
- `MAX_ITERATIONS` guard.
- `X-Eightfold-Tenant-Host` header on every request.

### 8.3 `eightfold.serverless.test.ts`

Mirror `workday.serverless.test.ts`. Cover:
- Method validation (GET, OPTIONS allowed; others → 405).
- CORS headers on OPTIONS and regular responses.
- Missing/invalid tenant-host header → 400.
- Path validation (must start with `api/apply/`).
- Request forwarding (target URL + querystring + headers).
- Response forwarding (status + body).
- Fetch throw → 500.

### 8.4 Dispatch test

Add a test for the ATS dispatch helper covering `'eightfold'`.

---

## 9. Manual verification steps

1. `npm run type-check` — zero errors.
2. `npm run lint` — zero errors.
3. `npm test` — all new tests pass; existing 768+ still green.
4. `npm run test:coverage` — new files ≥85%.
5. `npm run dev:vercel` — wait for Vercel Dev + Vite.
6. In browser at http://localhost:5173:
   - Go to `/companies`, select **Netflix**.
   - Expect ~609 jobs to load (spinner → graph + list).
   - Click a job → `https://explore.jobs.netflix.net/careers/job/{id}` opens.
   - DevTools → Network: ~61 sequential `GET /api/eightfold/api/apply/v2/jobs?...&start=N` requests.
7. Confirm no Workday-Netflix references remain: `grep -rn "netflix" src/frontend/src/__tests__/` and fix any broken snapshot/assertion.
8. `vercel.json` — add rewrite for `/api/eightfold/(.*)` if pattern matches existing proxies.
9. `npm run build` — must succeed.

---

## 10. Risks and edge cases

1. **Rate limiting**: Eightfold publishes no limits. Sequential requests keep RPS low (~5). Retry semantics set `retryable=true` on 429/500/503.
2. **Schema drift**: endpoint is undocumented. Use `[key: string]: unknown` on the response types, optional fields on the position, and `raw` preservation.
3. **Nullability**: `department`, `business_unit`, `medallionProgram`, `location_flexibility`, `work_location_option` can be `null`. Coerce with `|| undefined`.
4. **Date parsing**: `t_create` is **seconds**, not ms. Multiply by 1000.
5. **Page size cap of 10**: many requests per company. For Netflix-size tenants (~600 jobs) acceptable. For 10k+ tenants, reconsider.
6. **Private positions**: `isPrivate: true` filtered client-side. If Eightfold adds a `status: "closed"` field later, add a filter for that too.
7. **SSRF at proxy**: regex allowlist + path prefix. Future hardening: derive allowlist from `companies.ts` build-time set.
8. **Company identifier derivation**: `cfg.domain.split('.')[0]` yields `"netflix"` for `netflix.com`. If future tenants violate this (e.g., `company-xyz.co.uk`), add explicit `companyId` to `EightfoldConfig`.
9. **Tests referencing Netflix as Workday**: any existing `__tests__` with `ats: 'workday'` for Netflix will break. Update assertions.
10. **`COMPANY_IDS.Netflix`**: string value unchanged (`'netflix'`). Redux selectors and user preferences remain compatible.

---

## 11. Sequencing / execution order

1. Types first (§2) — unlocks everything.
2. Transformer + transformer tests (§3, §8.1).
3. Proxy handler + tests (§5, §8.3).
4. Client + client tests (§4, §8.2).
5. Dispatch wiring (§6, §8.4).
6. Company config changes (§7).
7. Full test suite + type-check (§9 steps 1–4).
8. Manual dev smoke test (§9 steps 5–7).
9. `vercel.json` review (§9 step 8).
10. Prod build (§9 step 9).
11. Update root `CLAUDE.md` and `src/frontend/CLAUDE.md` to mention Eightfold.

---

## Critical files for implementation

- `src/frontend/src/types/index.ts`
- `src/frontend/src/api/types.ts`
- `src/frontend/src/api/clients/workdayClient.ts` (reference pattern)
- `src/frontend/src/api/clients/baseClient.ts`
- `src/frontend/src/config/companies.ts`
- `api/workday.ts` (reference pattern)
- `api/greenhouse.ts` (reference pattern)
- `vercel.json`
