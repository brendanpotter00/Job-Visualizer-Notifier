# WebMCP → server-side `/api/jobs/search` fold — rework plan

**Stage:** SYNC + PLAN (senior architect). **Do not edit tool code in this stage.**
This is the spec the next (implement) stage executes.

## Merge state

- `git merge origin/main` into `end-to-end-test` → merge commit **`fd598e50`**, clean
  ort auto-merge, **zero conflicts**. Expected App.tsx / main.tsx / vite-env.d.ts
  conflicts did **not** materialize.
- `App.tsx` auto-merged with **both** intents intact: main's lazy `/landing` route +
  `LegacyLandingRedirect`, AND our `{WEBMCP_CONFIG.isEnabled && <WebMcpBridge />}` plus
  `import { WEBMCP_CONFIG, WebMcpBridge } from '../webmcp'`. No hand-fix needed.
- Both CLAUDE.md files (root + frontend) were rewritten by #252 and now describe the
  server-side read path; treat them as authoritative.

## Type-check after merge (the breakage the next stage fixes)

`npx tsc --noEmit` (Node 22.14.0) → **6 errors, ALL in `src/webmcp/tools/tier1Read.ts`,
all from `search_jobs` only**:

```
tier1Read.ts(3,10)  TS2305  backendScraperClient has no export 'chunkCompanyIds'
tier1Read.ts(3,27)  TS2305  backendScraperClient has no export 'fetchJobsPage'
tier1Read.ts(4,10)  TS2305  jobsApi has no export 'jobsWindowForTimeWindow'
tier1Read.ts(4,35)  TS2305  jobsApi has no export 'sinceForWindow'
tier1Read.ts(6,26)  TS2307  Cannot find module '../../features/jobs/keysetWalk'
tier1Read.ts(132,29) TS7006 Parameter 'chunk' implicitly 'any'  (fallout of the above)
```

Every other tool (all of tier2, all of tier3, and the other five tier1 tools)
type-checks **clean** — they already ride surviving symbols. **`search_jobs` is the
entire code fix.** `get_job` is a **runtime** break the compiler can't see (see §4).

## Per-tool verdict

| Tool | File | Status | Rewire |
|---|---|---|---|
| **`search_jobs`** | tier1Read | **BROKEN (compile)** | Full rewrite onto `GET /api/jobs/search`. See §3. |
| **`get_job`** | tier1Read | **BROKEN (runtime)** | Proxy rejects `/api/jobs/{source}/{id}`. See §4. |
| `list_filter_options` | tier1Read | OK | `jobsApi.endpoints.getFacets` — survives unchanged. |
| `list_companies` | tier1Read | OK | `companiesApi.listCuratedCompanies` — unchanged. |
| `search_locations` | tier1Read | OK | `locationsApi.searchLocations` — unchanged. |
| `get_company_hiring_trend` | tier1Read | OK | `jobsApi.endpoints.getJobsForCompany` — survives (per-company path was never part of #252's teardown). |
| `apply_feed_filters` | tier2DriveUi | OK | `recentJobsFilters` setters — unchanged. |
| `reset_feed_filters` | tier2DriveUi | OK | unchanged. |
| `open_job` | tier2DriveUi | OK | `window.open` — unchanged. |
| all 5 tier-3 | tier3Auth | OK | savedFilters / features / feedback / auth — unchanged. |

`shared.ts` helpers **all survive** (`buildRecentFilters`, `buildSearchTags`,
`resolveCompany`, `toJobSummary`, `parseRecentArgs`, etc.) — `setSearchTags` /
`setSoftwareOnlyInFilters` from `filterReducerUtils` still exist. Only the two
`import` lines and the `execute()` body of `search_jobs` reference dead code.

---

## 3. `search_jobs` — the rewrite (the whole job)

### What the endpoint now is (verified against merged code)

`GET /api/jobs/search` (through the `api/jobs.ts` proxy, sub-path `search` — already
allowlisted). Params, all as the proxy forwards them:

- `since` — ISO-8601 **with offset**, inclusive `first_seen_at >= since`. **Frozen for
  the whole walk**; it is in the cursor fingerprint, so a changed `since` on a later
  page is a **409**. Optional at the endpoint (default → all-time) but the client
  always sends an explicit floor (`EPOCH_ISO` for "all").
- `limit` — 1..500, default 100. **Changing it mid-walk is legal, does not invalidate a
  cursor.**
- `cursor` — opaque token from the prior response's `nextCursor`. Echo verbatim. Valid
  **only under the exact filter set that minted it**.
- `category`, `level`, `company`, `location`, `include`, `exclude` — **repeatable**
  (OR within each). `level` sent **UNEXPANDED** (server owns `new_grad ⊂ entry`).
  `location` matched **hierarchically**. include/exclude are case-insensitive substring
  over title / raw location / company / tags.
- `status` — defaults OPEN; the tool leaves it defaulted.

**Response `{jobs, nextCursor, meta}`:**
- `jobs`: `BackendJobListing[]` — same rows as `/api/jobs`, so `transformBackendJob(row,
  row.company)` maps them (identical to what `jobsApi.searchJobs.queryFn` does).
- `nextCursor`: present **iff `len(jobs) == limit`**; **absence/null is the only
  end-of-walk signal.**
- `meta`: **page 1 only** (`cursor is None`), `{filteredTotal, countLast24h,
  countLast3h}`. Counts describe the **filter set**, not the page; the two recency
  figures are **company-scoped only** (ignore category/level/keyword/location/time).

**Status contract** (surface these to the agent, don't swallow):
- **409** = stale cursor → *drop the cursor, re-request page 1.* This is the
  `STALE_CURSOR_STATUS` (exported from `jobsApi.ts`) the UI hook keys recovery on.
- **422** = malformed cursor / bad `since` / bad slug / control chars / empty value.
- **400** = too many values (`company` ≤ 500, `category`/`level` ≤ 20 each,
  `location` ≤ 100, `include`+`exclude` **share** a budget of 20).

### The frozen-`since` problem (must be solved in the tool)

The UI freezes `since` via `useRecentJobsSearch`'s debounced snapshot stamp. **A
stateless tool has no snapshot** — if `execute()` recomputes
`sinceForTimeWindow(timeWindow, Date.now())` on every call, page 2 (called seconds
later) gets a different `since` than page 1 and the server **409s**. 60s quantization
(`SINCE_QUANTUM_MS`) only masks it inside one minute; a slow agent walk still breaks.

**Fix: fold the frozen `since` into the tool's own opaque cursor.** Keep the tool's
"opaque, filter-bound, base64" cursor contract (same shape promise the old
composite-cursor `decodeCursor`/`encodeCursor` made) but change its *payload*:

```
toolCursor = base64( JSON.stringify({ c: <server nextCursor>, s: <frozen since ISO> }) )
```

- **No input cursor →** page 1: compute `since = sinceForTimeWindow(timeWindow,
  Date.now())`, fetch with no server `cursor`, return `nextCursor = encode({c, s:since})`.
- **Input cursor present →** decode it; **reuse `s` as `since`** (frozen) and pass `c` as
  the server `cursor`. Do **not** recompute `since`. `timeWindow` on a follow-up call is
  ignored for `since` (the frozen value wins) — document this in the tool description.
- **Malformed tool cursor** (bad base64/JSON) → treat as page 1 (fresh walk), mirroring
  the old `decodeCursor` "empty map → restart" behavior.
- **Server 409** (agent replayed a cursor after changing a filter) → return
  `err('search_jobs cursor is stale — drop it and call again with no cursor', {status:
  409})`. Don't auto-restart silently; the agent changed filters and must know.

This keeps `limit` freely changeable mid-walk (not in the cursor), preserves the
"filter change = fresh walk" contract, and never emits a moving `since`.

### Build the args — reuse the merged builders, don't re-derive

1. `const parsed = parseRecentArgs(rawArgs)` (survives).
2. `const filters = buildRecentFilters(parsed)` (survives — folds include/exclude tags,
   softwareOnly, resolves company names→ids, drops unresolved).
3. `const args = buildSearchJobsArgs({ filters, enabledCompanyIds: null, since,
   isSignedOut: false })` from `../../features/jobs/searchJobsArgs`.
   - **`enabledCompanyIds: null`** on purpose — the tool scopes by the agent's explicit
     `company` arg only, never the operator's personal enabled-companies preference. With
     `enabled === null`, `buildSearchJobsArgs` sets `companies = selected` (or `undefined`
     = all), and its `null` (disjoint) return path is unreachable — but still guard it:
     `if (args === null) return ok({ jobs: [], meta: {...zeros, nextCursor: null,
     hasMore: false} })`.
   - **`isSignedOut: false`** so it doesn't apply the 12-row overlay cap.
4. **Override the limit**: `buildSearchJobsArgs` hardcodes limit to
   `RECENT_SEARCH_PAGE_SIZE` / `SIGNED_OUT_FETCH_LIMIT`. The tool wants its own
   `limit` (1..500, clamp as today). Use `const finalArgs = { ...args, limit }`.
5. Serialize with `buildSearchJobsQuery(finalArgs, serverCursor)` (survives, exported
   from `searchJobsArgs`) — it already emits repeated params + `%20` spaces + presence
   cursor. **Do not hand-build the query string.**

### Fetch, validate, transform, shape the result

- `fetch('/api/jobs/search?' + buildSearchJobsQuery(finalArgs, serverCursor), { headers:
  { Accept: 'application/json' } })`.
- Non-ok → map status: 409 → the stale-cursor `err` above; else
  `err('search_jobs failed (<status>)', { status })`.
- Ok → `const body = validateSearchJobsResponse(await res.json(), { isFirstPage:
  serverCursor === null })` (survives; renames `meta`→`counts`, validates row shape).
- `const jobs = body.jobs.map((row) => transformBackendJob(row, row.company)).map(
  toJobSummary)`. **No client-side `filterJobsByFilters`, no `locationCatalog`, no
  sort** — the server already filtered and ordered.
- **New `meta` output shape** (reconcile with the verify skill — see §5):
  ```
  meta: {
    filteredTotal: body.counts?.total ?? null,   // page-1 only; null on cursor pages
    last24h:       body.counts?.last24h ?? null,
    last3h:        body.counts?.last3h  ?? null,
    returned:      jobs.length,                    // rows on THIS page
    nextCursor:    body.nextCursor ? encode({c: body.nextCursor, s: since}) : null,
    hasMore:       body.nextCursor !== null,
  }
  ```
  `serverReturned` (old name) → rename to `returned` **or** keep `serverReturned` as an
  alias — but its meaning changed (see §5); the verify doc must move in lockstep.

### Imports to DELETE from tier1Read.ts (the 5 dead ones)

`chunkCompanyIds`, `fetchJobsPage` (backendScraperClient); `jobsWindowForTimeWindow`,
`sinceForWindow` (jobsApi); `chunkKey` (keysetWalk — file deleted);
`filterJobsByFilters` (jobFilteringUtils); `selectLocationCatalog`
(locationCatalogSlice); plus the now-unused `buildRecentFilters`/`bucketJobsByTime`
imports only if they end up unused (bucketJobsByTime is still used by
`get_company_hiring_trend`; `buildRecentFilters` is still used by the new `search_jobs`,
`backendScraperCompanyIds` becomes unused — drop it).

### Imports to ADD

From `../../features/jobs/searchJobsArgs`: `buildSearchJobsArgs`, `buildSearchJobsQuery`,
`sinceForTimeWindow`. From `../../features/jobs/validateSearchJobsResponse`:
`validateSearchJobsResponse`. `transformBackendJob` is already imported. `STALE_CURSOR_STATUS`
from `../../features/jobs/jobsApi` (optional — for the 409 branch).

---

## 4. `get_job` — proxy widen is STILL NEEDED

`get_job` does `fetch('/api/jobs/${source}/${id}')`. The merged `api/jobs.ts` allowlist
is `resolveProxyPath(path, ['', 'facets', 'search'])` — a two-segment `source/id` path
resolves to **null → `PROXY_REJECTION`** (a 4xx). Verified our pre-merge branch
(`24588ff7`) allowlisted only `['', 'facets']` and **never touched `api/jobs.ts`**, so
this widen was **never present** — `get_job` has been broken against the real proxy the
whole time (only the store-only harness hid it). The proxy carries an explicit comment:

> NOT allowlisted, deliberately … Add it here (with a test) when something actually
> needs it.

**Two options for the implement stage (pick one, note it):**
- **(A, recommended) Widen the proxy** — add the `{source}/{id}` detail route to
  `api/jobs.ts` with its own handling **and a proxy test** (`api/__tests__` /
  wherever the sibling proxy tests live). It must forward only GET, inject the internal
  key like the rest, and 404 cleanly. This is a *decision* per the comment — the e2e
  surface (which `get_job` is a first-class part of) is the thing that "actually needs
  it." This is the intended path.
- **(B) Re-point `get_job`** onto an existing allowlisted read. There is **no**
  single-posting endpoint reachable today, so B means deriving the job from a
  `search_jobs`-style call — lossy and wrong for a by-id fetch. **Reject B.**

Response mapping is unchanged: `transformBackendJob(raw, raw.company)` → `toJobDetail`.

---

## 5. verify-onesecondswe feature map — updates the plan mandates

The tool **names** don't change, so the map's tool columns stay. But two docs drift:

### 5a. Add `/landing` (main #250)

`ROUTES.LANDING` = `/landing`, `ROUTES.LANDING_LEGACY` = `/admin/landing-prototypes`
(redirects). It's a **user-facing route in `config/routes.ts`**, which is the map's
inclusion rule — but it's mock-data-only, unlisted (direct-URL only), touches **no** real
API and **no** WebMCP tool. Mirror `why.md` (the existing tool-less/static precedent):
- Add a row to `features/README.md` table: `landing.md` | `/landing` `LANDING` |
  **none (mock-only, no real APIs)**.
- Add a short `features/landing.md` with the four H2s; "Driving it with WebMCP" = none,
  Gotchas = mock fixtures / full-bleed (no drawer) / unlisted-by-design.
- Note `LANDING_LEGACY` is a redirect, covered by `landing.md` (same treatment the map
  gives `MY_COMPANIES_LEGACY`).
- (Alternative: list it under "Intentionally unmapped" with the "no WebMCP tool touches
  it" rationale. The `why.md` precedent argues for a real file — recommend the file.)

### 5b. `recent-jobs.md` now describes the DELETED client-side model — rewrite these

- "**The tool filters ONE server page (≤ limit) client-side; the page filters its own
  `useGetAllJobsQuery` cache.**" — both halves are false now. Server filters; the page
  uses `searchJobs` infinite query; `useGetAllJobsQuery` is gone.
- "`res.meta.serverReturned >= filteredTotal`" — **no longer holds.** The server pages the
  *result*, so one page is `returned ≤ limit`, and `filteredTotal` is the total across all
  pages: `returned ≤ filteredTotal`, not `≥`. Update the anchor assertion + the field name
  if the tool renames `serverReturned`→`returned`.
- "**Cursors are filter-bound … restarts the walk from page 1 (no 409)**" — the *tool's*
  opaque cursor still restarts a mangled token, but a genuine filter/version mismatch on
  the **server** cursor is now a real **409**. Document the 409 = drop-cursor-restart
  contract.
- "**auto-deepen the keyset walk / `RecentJobsList`'s empty-fetch budget**" gotcha — the
  client-side deepening walk is gone; a filter narrowing now returns matches directly.
  Remove or rewrite.
- The `meta` example (`filteredTotal`, `last24h`, `last3h`, `returned`, `hasMore`) should
  match §3's output shape.

*(5b is verify-skill maintenance — flag for the maintain-verification-skill stage; it is
not tool code.)*

---

## Reference — deleted vs surviving symbols

**Deleted by #252** (any tool importing these breaks): `keysetWalk.ts` (`chunkKey`),
`useAllJobsProgress.ts`, `progressHelpers.ts`, `jobsSelectors.ts` (old recent selectors),
`fetchJobsPage` + `chunkCompanyIds` (backendScraperClient), `sinceForWindow` +
`jobsWindowForTimeWindow` (jobsApi), `useGetAllJobsQuery` / `selectAllJobsFromQuery` /
`selectRecentFilteredJobs`.

**Survives and is the new target surface**: `jobsApi.endpoints.{getJobsForCompany,
getFacets, searchJobs}`; `searchJobsArgs.{buildSearchJobsArgs, buildSearchJobsQuery,
sinceForTimeWindow, EPOCH_ISO}`; `validateSearchJobsResponse`; `searchJobsTypes.{SearchJobsArgs,
SearchJobsPage, SearchJobsCounts}`; `transformBackendJob`; `STALE_CURSOR_STATUS`;
`recentJobsSelectors.{selectRecentJobsFilters, selectRecentCompanyOptions}`;
all `recentJobsFiltersSlice` setters; every `shared.ts` helper except
`backendScraperCompanyIds` (drop it).
