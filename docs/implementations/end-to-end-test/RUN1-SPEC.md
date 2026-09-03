# RUN1 — WebMCP e2e implementation spec (contract)

This is the **binding contract** the next stages follow exactly. It supersedes the
looser wording in [`PLAN.md`](./PLAN.md) wherever they disagree — every such
disagreement is called out inline as **⚠ Correction to PLAN/audit**, because they were
written against a newer `main` than the branch this worktree was cut from.

All paths are **worktree-absolute-equivalent**, rooted at:
`/Users/bpotter/developer/personal/Job-Visualizer-Notifier/.claude/worktrees/end-to-end-tests/`
(written below relative to that root).

Ground rules that do not move:
- **Additive only.** New files under `src/frontend/src/webmcp/`, `.claude/skills/verify-onesecondswe/`, and a widen (not rewrite) of one allowlist array in `api/jobs.ts`. Never delete or rewrite existing app code. **Do not `git commit`.**
- **Reuse, never duplicate.** Every `execute()` calls an *existing* app fetch client, RTK Query endpoint, Redux thunk/action, or pure selector util. No tool re-implements API or filter logic.
- **Reuse the harness.** The e2e stack (`e2e/shared/stack/`), auth seam (`e2e/shared/auth/`), DB helpers (`e2e/shared/db/`), and Playwright base (`e2e/shared/playwright/`) are consumed as-is. Nothing here rebuilds them.

---

## 0. The two facts that break the audit's assumptions (read first)

### 0.1 There is no `GET /api/jobs/search` on this branch
The audit ([`PLAN.md`](./PLAN.md) line 14) maps `search_jobs → GET /api/jobs/search`. **That route does not exist in this worktree.** The backend jobs router (`src/backend/api/routers/jobs.py`) declares exactly three GETs:

| Backend route | Line | Purpose |
|---|---|---|
| `GET /api/jobs` (keyset-paged) | `jobs.py:62` | the feed. Params: `company`, `companies`, `status`, `category`, `level`, `limit`, `offset`, `since`, `cursor`. `X-Next-Cursor` header = next page; its **absence is the only end-of-walk signal**. |
| `GET /api/jobs/facets` | `jobs.py:277` | enrichment dropdown catalog |
| `GET /api/jobs/{source_id}/{job_id}` | `jobs.py:292` | one posting |

**⚠ Correction to PLAN/audit:** `search_jobs` maps to **`GET /api/jobs`** (keyset), not `/api/jobs/search`. Keyword include/exclude, location, employmentType and softwareOnly are **client-side** filters in this app (the backend `/api/jobs` only filters by `company(ies)`, `status`, `category`, `level`, `since`). So `search_jobs.execute` = *server fetch via the app's keyset client* **+** *the app's own client-side predicate* (§1.1).

### 0.2 `get_job`'s proxy path is NOT allow-listed
`api/jobs.ts:36` allow-lists only `['', 'facets']` and its own comment (`jobs.ts:32-35`) states `GET /api/jobs/{source_id}/{job_id}` is deliberately **not** forwarded ("no frontend caller uses it"). Consequences:
- **Under the e2e stack** the frontend proxies the *whole* `/api` prefix to `:8201` (`e2e/shared/stack/vite.e2e.config.ts:36`), so `fetch('/api/jobs/<src>/<id>')` reaches the backend route directly. `get_job` works in the gate with no change.
- **In prod (Vercel)** the same fetch 404s at the proxy. Since WebMCP tools ship as real prod capabilities, **`get_job` requires widening the allowlist** — a required additive work-unit (§1.5, §2.4). The gate proves `get_job` regardless; the widen is what makes it true in prod too.

---

## 1. The WebMCP tools (the contract)

Twelve+2 tools across three tiers. Every tool object has the shape:

```ts
interface WebMcpToolDef {
  name: string;
  description: string;              // agent-facing, one sentence, says WHAT + returns WHAT
  inputSchema: JSONSchema7;         // draft-07 object schema; additionalProperties:false
  annotations: { readOnlyHint: boolean; openWorldHint?: boolean };
  execute(args): Promise<ToolResult>;  // args already validated against inputSchema
}
type ToolResult = {
  content: [{ type: 'text'; text: string }];   // JSON.stringify(structuredContent) — for real WebMCP
  structuredContent: unknown;                  // the raw object — what the shim returns to Playwright
  isError?: boolean;
};
```

`execute` returns `structuredContent` (a plain JS object); the wrapper in `register.ts` fills `content` from it. The shim's `call()` returns `structuredContent` directly so `page.evaluate` gets clean JSON.

Tool context passed to every factory: `ToolCtx = { store: AppStore; getNavigate(): NavigateFn | null; getLogin(): (() => Promise<void>) | null }` (see §2.5 for how navigate/login are captured).

### Tier 1 — Read & discover (`readOnlyHint: true`, anonymous-safe)

#### 1.1 `search_jobs`
- **Maps to:** `GET /api/jobs` (keyset) via `fetchJobsPage` **+** client-side `filterJobsByFilters`.
- **Reuse (exact symbols):**
  - `fetchJobsPage(companyIds, { since, cursor, limit, signal })` — `src/frontend/src/api/clients/backendScraperClient.ts:301` (hard-codes `status=OPEN`, forwards `since`/`cursor`/`limit`; returns `{ jobs, byCompanyId, nextCursor }`).
  - `chunkCompanyIds(ids)` — same file — to partition >150 ids (backend cap) into chunks.
  - `sinceForWindow` + `jobsWindowForTimeWindow` — re-exported from `src/frontend/src/features/jobs/jobsApi.ts:31-36` (originals in `features/jobs/keysetWalk.ts`) — turn `timeWindow` into the `since` floor.
  - `filterJobsByFilters(jobs, filters, locationCatalog)` — `src/frontend/src/features/filters/utils/jobFilteringUtils.ts` (the predicate behind `selectRecentFilteredJobs`, `features/filters/selectors/recentJobsSelectors.ts:87`) — applies include/exclude/location/employmentType/softwareOnly/category/level.
  - `selectLocationCatalog(state)` — `src/frontend/src/features/locations/locationCatalogSlice.ts` — for location matching; read from `ctx.store.getState()`.
  - Build the `RecentJobsFilters` object with the slice's own utils (`features/filters/utils/filterReducerUtils.ts`: `setSoftwareOnlyInFilters`, etc.) so `softwareOnly`/tag semantics match the UI exactly.
- **Company scope:** if `company[]` given, resolve names→ids first (accept id or display name; resolve via `COMPANIES` in `config/companies.ts`); else default to **all `ats==='backend-scraper'` company ids** (`COMPANIES.filter(c => c.ats==='backend-scraper').map(c=>c.id)`), mirroring the Recent feed.
- **inputSchema:**
```json
{ "type":"object","additionalProperties":false,"properties":{
  "include":{"type":"array","items":{"type":"string"},"description":"Keyword must-match (OR within, applied to title/team/location text)."},
  "exclude":{"type":"array","items":{"type":"string"},"description":"Keyword must-not-match."},
  "category":{"type":"array","items":{"type":"string"},"description":"Enrichment category slugs from list_filter_options (OR)."},
  "level":{"type":"array","items":{"type":"string"},"description":"Enrichment level slugs; 'entry' also matches new_grad."},
  "company":{"type":"array","items":{"type":"string"},"description":"Company id or display name; omit for all companies."},
  "location":{"type":"array","items":{"type":"string"},"description":"Canonical location names from search_locations."},
  "timeWindow":{"type":"string","enum":["30m","1h","3h","6h","12h","24h","3d","7d","14d","30d","90d","180d","all"],"default":"all"},
  "limit":{"type":"integer","minimum":1,"maximum":500,"default":100},
  "cursor":{"type":"string","description":"Opaque X-Next-Cursor from a prior call; filter-bound (see Gotchas)."}
}}
```
- **Returns (`structuredContent`):**
```ts
{ jobs: JobSummary[],            // serialized (§1.9), length <= limit
  meta: { filteredTotal: number, // rows AFTER client-side filters — the assert anchor
          serverReturned: number,// rows the server page yielded before client filter
          nextCursor: string|null, hasMore: boolean } }
```

#### 1.2 `list_filter_options`
- **Maps to:** `GET /api/jobs/facets`.
- **Reuse:** `jobsApi.endpoints.getFacets.initiate()` — `src/frontend/src/features/jobs/jobsApi.ts:915` — `await ctx.store.dispatch(getFacets.initiate()).unwrap()`. Returns `JobFacets { categories: FacetOption[], levels: FacetOption[] }` (`types/index.ts:334-345`).
- **inputSchema:** `{ "type":"object","additionalProperties":false,"properties":{} }`
- **Returns:** `{ categories, levels }` (slug/label/sortOrder/parentSlug each).

#### 1.3 `list_companies`
- **Maps to:** `GET /api/companies` (curated directory).
- **Reuse:** `companiesApi.endpoints.listCuratedCompanies.initiate()` — `src/frontend/src/features/companies/companiesApi.ts:27` — returns `CuratedCompany[]`. Resolves company **name→id** for `search_jobs`.
- **inputSchema:** `{ "type":"object","additionalProperties":false,"properties":{ "query":{"type":"string","description":"Optional case-insensitive substring over name/id."} } }`
- **Returns:** `{ companies: { id, name, ats, ... }[] }` (filtered by `query` if given).

#### 1.4 `search_locations`
- **Maps to:** `GET /api/locations/search`.
- **Reuse:** `locationsApi` — `src/frontend/src/features/locations/locationsApi.ts` (baseUrl `/api/locations`, path `search?q=&limit=&openOnly=`). Dispatch its `initiate` endpoint (or call the module's search fn). Note the `%20`-encoding caveat already handled by the app's serializer.
- **inputSchema:**
```json
{ "type":"object","additionalProperties":false,"required":["q"],"properties":{
  "q":{"type":"string","minLength":1},
  "limit":{"type":"integer","minimum":1,"maximum":50,"default":10},
  "openOnly":{"type":"boolean","default":false} } }
```
- **Returns:** `{ locations: {canonicalName, ...}[] }`.

#### 1.5 `get_job`
- **Maps to:** `GET /api/jobs/{source_id}/{job_id}` (**needs proxy widen — §0.2, §2.4**).
- **Reuse:** a thin `fetch('/api/jobs/'+encodeURIComponent(source)+'/'+encodeURIComponent(id))`. There is no existing frontend caller, so this is the one new fetch call — but it hits the **same proxy path** the app uses for `/api/jobs`, so it is not a new client, just a new sub-path. Validate `res.ok`; on 404 return `{ isError:true }` result with a readable message.
- **inputSchema:**
```json
{ "type":"object","additionalProperties":false,"required":["source","id"],"properties":{
  "source":{"type":"string","description":"ATS source id (job.source)."},
  "id":{"type":"string","description":"Posting id (job.id)."} } }
```
- **Returns:** `{ job: JobDetail }` — full posting incl. `url` (apply link), `title`, `company`, `location`, `firstSeenAt`, `category`, `level`.

#### 1.6 `get_company_hiring_trend`
- **Maps to:** the `/companies` page data path — full per-company set → client-side time-bucketing.
- **Reuse:**
  - `jobsApi.endpoints.getJobsForCompany.initiate({ companyId })` — `src/frontend/src/features/jobs/jobsApi.ts:335` — the exact single-company cache entry the trend page reads.
  - `bucketJobsByTime(jobs, timeWindow)` — `src/frontend/src/lib/timeBucketing.ts:123` → `TimeBucket[]` (`types/index.ts:138`).
- **inputSchema:**
```json
{ "type":"object","additionalProperties":false,"required":["company"],"properties":{
  "company":{"type":"string","description":"Company id or display name."},
  "timeWindow":{"type":"string","enum":["30m","1h","3h","6h","12h","24h","3d","7d","14d","30d","90d","180d","all"],"default":"90d"} } }
```
- **Returns:** `{ companyId, timeWindow, buckets: {bucketStart,bucketEnd,count}[], total: number }`. (Default `90d` — the trend page's own default per `graphFiltersSlice`.)

### Tier 2 — Drive the live page (`readOnlyHint: false`)

All three navigate the **real router** via the captured `navigate` (§2.5). If `getNavigate()` is null (bridge not mounted), fall back to `window.history.pushState('','', '/'); window.dispatchEvent(new PopStateEvent('popstate'))` so BrowserRouter still updates.

#### 2.1 `apply_feed_filters`
- **Maps to:** `recentJobsFiltersSlice` action dispatches + `navigate('/')`.
- **Reuse (exact actions, `features/filters/slices/recentJobsFiltersSlice.ts:48-72`):** for each **provided** arg field, dispatch the matching setter — `setRecentJobsTimeWindow`, `setRecentJobsCategory`, `setRecentJobsLevel`, `setRecentJobsCompany`, `setRecentJobsLocation`, `setRecentJobsEmploymentType`, `setRecentJobsSoftwareOnly`, and for `include`/`exclude` build `SearchTag[]` and dispatch `setRecentJobsSearchTags`. Omitted fields are **left untouched** (additive, mirrors per-control UI). For a deterministic slate, call `reset_feed_filters` first.
- **inputSchema:** same property set as `search_jobs` **minus** `cursor`/`limit` (it is arrange-the-UI, not a query). Same enums.
- **Returns:** `{ applied: RecentJobsFilters }` (the resulting slice state, read back from `store.getState().recentJobsFilters.filters`).

#### 2.2 `reset_feed_filters`
- **Maps to:** `resetRecentJobsFilters()` + `navigate('/')`.
- **inputSchema:** `{ "type":"object","additionalProperties":false,"properties":{} }`
- **Returns:** `{ applied: RecentJobsFilters }` (the initial state).

#### 2.3 `open_job`
- **Maps to:** `window.open(url, '_blank', 'noopener')`.
- **inputSchema:** `{ "type":"object","additionalProperties":false,"required":["url"],"properties":{ "url":{"type":"string","format":"uri","description":"A posting's apply URL (job.url from search_jobs / get_job)."} } }`
- **Returns:** `{ opened: true, url }`. **Annotation:** `openWorldHint:true`. **Gotcha:** popup-blocked without a user gesture — the gate asserts the intent via `page.on('popup')` or a `window.open` stub, not a live navigation (§3 Evidence).

### Tier 3 — Personalize (sign-in required, except feedback)

#### 3.1 `request_sign_in`
- **Maps to:** `useAuth().login()` (= `loginWithRedirect()` / Google One-Tap). **No token ever reaches the agent.**
- **Reuse:** the captured `getLogin()` (§2.5), which is `useAuth().login` (`features/auth/useAuth.ts:66,89`).
- **inputSchema:** `{ "type":"object","additionalProperties":false,"properties":{} }`
- **Returns:** `{ prompted: true }`. **Gotcha:** cannot complete headlessly. The gate does **not** drive real Auth0 — signed-in flows use the JWKS-seam minted token in `localStorage` (`e2e/shared/auth/storage_state.ts`). This tool is mapped and its "prompt fires" path is smoke-checked, but authentication for Tier-3 side-effect tests comes from the fixture, not this tool.

#### 3.2 `set_enabled_companies`
- **Maps to:** `PUT /api/users/enabled-companies`.
- **Reuse:** `updateEnabledCompanies(token, companyIds, autoEnroll)` — `features/auth/authService.ts:188`; then dispatch `loadEnabledCompanies(token)` (`features/preferences/enabledCompaniesSlice.ts:28`) to refresh the store. `token = await getTokenOrNull()` (`features/features/getTokenOrNull.ts`, already the store's thunk `extraArgument`); if null → `{ isError:true, message:'Sign in required' }`.
- **inputSchema:**
```json
{ "type":"object","additionalProperties":false,"required":["companyIds"],"properties":{
  "companyIds":{"type":"array","items":{"type":"string"}},
  "autoEnroll":{"type":"boolean","default":true} } }
```
- **Returns:** `{ companyIds, autoEnroll }` (server echo). **DB side-effect:** `user_enabled_companies` rows — asserted in Evidence.

#### 3.3 `save_filter_defaults`
- **Maps to:** `PUT /api/users/saved-filters`.
- **Reuse:** `savedFiltersApi.endpoints.updateSavedFilters.initiate(body)` — `features/savedFilters/savedFiltersApi.ts:148` — `.unwrap()`. Token attached automatically via the slice's `prepareHeaders` + `getTokenOrNull`.
- **inputSchema:** mirror the `SavedFilters` type (`types/index.ts:~219`) — `recentTimeWindow`, `trendTimeWindow`, `locations[]`, active keyword-list pointers. (Implementer: copy the field set from `SavedFilters`; do not invent fields.)
- **Returns:** the server's saved-filters echo. **DB side-effect:** `user_saved_filters`.

#### 3.4 `upvote_feature`
- **Maps to:** `POST /api/features/{id}/upvote`.
- **Reuse:** `featuresApi.endpoints.upvoteFeature.initiate(featureId)` — `features/features/featuresApi.ts:47` — `.unwrap()` (optimistic patch + token via extra already built in).
- **inputSchema:** `{ "type":"object","additionalProperties":false,"required":["featureId"],"properties":{ "featureId":{"type":"string"} } }`
- **Returns:** `{ featureId, upvoteCount, hasUpvoted }`. **DB side-effect:** `feature_upvotes`.

#### 3.5 `submit_feedback` (anonymous-capable)
- **Maps to:** `POST /api/feedback`.
- **Reuse:** `feedbackApi.endpoints.submitFeedback.initiate({ message })` — `features/feedback/feedbackApi.ts` — `.unwrap()`. Optional auth (stores anonymous when signed-out).
- **inputSchema:** `{ "type":"object","additionalProperties":false,"required":["message"],"properties":{ "message":{"type":"string","minLength":1,"maxLength":5000} } }` (`FEEDBACK_MAX_LENGTH=5000`).
- **Returns:** `{ submitted: true }`. **DB side-effect:** `feedback` row.

### 1.9 Shared serializer
One helper `toJobSummary(job: Job)` / `toJobDetail(job: Job)` in `webmcp/tools/shared.ts` picks a stable, agent-useful subset of the `Job` type (`types/index.ts:32`): `id, source, company, title, team, location, isRemote, employmentType, firstSeenAt, url, category, level`. Never emit `raw`. This is the only place a `Job` is shaped for the wire, so the assert layer has one contract.

### Tier/annotation summary

| Tool | Tier | readOnlyHint | Reused symbol | Side-effect asserted |
|---|---|---|---|---|
| `search_jobs` | 1 | true | `fetchJobsPage` + `filterJobsByFilters` | — (meta.filteredTotal) |
| `list_filter_options` | 1 | true | `jobsApi.getFacets` | — |
| `list_companies` | 1 | true | `companiesApi.listCuratedCompanies` | — |
| `search_locations` | 1 | true | `locationsApi` search | — |
| `get_job` | 1 | true | `fetch('/api/jobs/{src}/{id}')` (+proxy widen) | — |
| `get_company_hiring_trend` | 1 | true | `jobsApi.getJobsForCompany` + `bucketJobsByTime` | — |
| `apply_feed_filters` | 2 | false | `recentJobsFiltersSlice` setters + navigate | DOM: filtered list |
| `reset_feed_filters` | 2 | false | `resetRecentJobsFilters` + navigate | DOM: full feed |
| `open_job` | 2 | false | `window.open` | popup event |
| `request_sign_in` | 3 | false | `useAuth().login` | prompt fires |
| `set_enabled_companies` | 3 | false | `updateEnabledCompanies` + `loadEnabledCompanies` | `user_enabled_companies` |
| `save_filter_defaults` | 3 | false | `savedFiltersApi.updateSavedFilters` | `user_saved_filters` |
| `upvote_feature` | 3 | false | `featuresApi.upvoteFeature` | `feature_upvotes` |
| `submit_feedback` | 3 | false | `feedbackApi.submitFeedback` | `feedback` |

---

## 2. File layout

New directory `src/frontend/src/webmcp/`:

```
src/frontend/src/webmcp/
├── index.ts            # public surface: registerWebMcpTools, WEBMCP_CONFIG, WebMcpBridge
├── config.ts           # WEBMCP_CONFIG.isEnabled = import.meta.env.VITE_WEBMCP === '1'
├── register.ts         # registerWebMcpTools(store): build tools, register on BOTH surfaces
├── refs.ts             # module-level navigateRef / loginRef (+ set/get); no React import
├── bridge.tsx          # <WebMcpBridge/> — captures useNavigate()+useAuth().login into refs
├── types.ts            # WebMcpToolDef, ToolResult, ToolCtx, Window.__webmcp__ typings
└── tools/
    ├── shared.ts       # toJobSummary/toJobDetail, resolveCompany(nameOrId), buildRecentFilters(args)
    ├── tier1Read.ts    # (ctx) => WebMcpToolDef[]  (§1.1–1.6)
    ├── tier2DriveUi.ts # (ctx) => WebMcpToolDef[]  (§2.1–2.3)
    └── tier3Auth.ts    # (ctx) => WebMcpToolDef[]  (§3.1–3.5)
```

### 2.1 Single entry: `registerWebMcpTools(store)`
`register.ts` exports **one** function `registerWebMcpTools(store: AppStore): void`. It:
1. Builds `ctx = { store, getNavigate, getLogin }` (getters read `refs.ts`).
2. Concatenates `tier1Read(ctx)`, `tier2DriveUi(ctx)`, `tier3Auth(ctx)` into `TOOLS`.
3. For each tool, registers on the **real** API when present: `document.modelContext?.registerTool?.({ name, description, inputSchema, annotations, execute: wrapForWebMcp(execute) })` where `wrapForWebMcp` maps the returned `structuredContent` into the MCP `{content:[{type:'text',text}], structuredContent}` envelope.
4. Always installs the **shim**: `window.__webmcp__ = { list(): {name,description,inputSchema,annotations}[]; call(name, args): Promise<structuredContent> }`. `call` validates `name` exists, runs `execute(args)`, returns `structuredContent` (throws a structured error object otherwise). This is what Playwright drives via `page.evaluate`.
5. Is **idempotent** — a second call replaces `window.__webmcp__` and re-registers (guard against StrictMode double-invoke).

**⚠ Note:** real WebMCP (`document.modelContext.registerTool`) only exists behind a Chrome origin-trial; in every dev/CI browser it is `undefined`. The shim is therefore the surface the gate uses — the real registration is best-effort and must never throw when the API is absent.

### 2.2 Call site (startup, behind flag)
In `src/frontend/src/main.tsx`, after `store` is imported, before/after render (either is fine — the shim only needs `store`):
```ts
import { WEBMCP_CONFIG, registerWebMcpTools } from './webmcp';
if (WEBMCP_CONFIG.isEnabled) registerWebMcpTools(store);
```
This is the *only* edit to `main.tsx` and it is guarded — with `VITE_WEBMCP` unset the import cost is a dead branch and **zero** runtime behavior changes (byte-identical prod default).

### 2.3 Bridge mount (behind flag)
In `src/frontend/src/app/App.tsx`, inside `AppContent` (which is inside `<BrowserRouter>`), render `{WEBMCP_CONFIG.isEnabled && <WebMcpBridge/>}`. `WebMcpBridge` is a render-null component: a `useEffect` that assigns `useNavigate()` and `useAuth().login` into `refs.ts`, cleaning up on unmount. It touches no other state. With the flag off it is never mounted.

### 2.4 Proxy widen (required for `get_job` in prod)
`api/jobs.ts:36` — widen the allowlist from `['', 'facets']` to `['', 'facets', ':source/:job']` (using the `:param` segment form `resolveProxyPath` already supports — see `api/users.ts:34-37` for precedent). Re-emit body via `forwardResponse` (already done). Add one proxy test asserting `/api/jobs/microsoft/abc` forwards and a traversal (`/api/jobs/../admin`) still 404s. **Additive** — no existing behavior changes. The gate passes with or without this (whole-`/api` proxy), but this is what makes `get_job` a real prod capability.

### 2.5 navigate/login capture — the reconciliation
Registration is `registerWebMcpTools(store)` (store-only, per the contract). Router navigation and Auth0 login are React-hook-bound, so they are captured **out of band** by `WebMcpBridge` into module refs (`refs.ts`), and the Tier-2/3 tools read them through `ctx.getNavigate()`/`ctx.getLogin()` at call time (not registration time). This keeps the single store-only entry **and** uses the real router/auth. **Decision, flagged:** navigation falls back to the History API + `popstate` when the bridge is absent, so the tools degrade gracefully in a store-only harness.

---

## 3. The verification skill — `.claude/skills/verify-onesecondswe/`

Generated per the Pstack **create-verification-skill** method
(`docs/implementations/end-to-end-test/create-verification-skill/SKILL.md`). It is a
project-local skill written for a cold agent. **`name: verify-onesecondswe`**, YAML
frontmatter naming the app, the surface (React SPA driven through WebMCP tools), and
when to reach for it. Sections, each grounded in the harness that already exists:

### Launch
- **Reuse `e2e/shared/stack/stack_up.sh`** — backend `:8201`, frontend `:3201`, `jobscraper_e2e` DB. It already: refreshes the DB seam, boots uvicorn on the JWKS-patched `e2e_app.py`, boots `vite dev` with the whole-`/api` proxy, and health-waits both. **The one addition:** export `VITE_WEBMCP=1` into the frontend env before `vite dev` so the shim registers (Vite exposes `process.env.VITE_*` at dev time; the skill's Launch sets it in the shell that `stack_up.sh` inherits, or writes it into `src/frontend/.env.local` as verification scaffolding removed in Cleanup).
- **Ready when:** `stack_up.sh` returns 0 (its own `/health` + `/` waits), **and** `window.__webmcp__.list().length === <tool count>` via a one-shot `page.evaluate` (proves the flag took).
- **Never** touches `:8000/:8100/:3000` (the owner's stack) — inherited from `stack_up.sh`.

### Doctor (read-only "is this worth driving?")
1. `curl -fsS http://127.0.0.1:8201/health` → `OK` 200.
2. `curl -fsS http://127.0.0.1:8201/health/worker` → 200 (Procrastinate lanes alive).
3. `page.evaluate(() => window.__webmcp__?.list()?.map(t=>t.name))` → the expected tool-name set, non-empty. A missing shim means `VITE_WEBMCP` didn't take — a drift fix under edit scope, not a product bug.
Run before the first drive, and again after any surprising failure.

### Drive
- **Reuse `e2e/shared/playwright/`** — `fixtures.ts` (`signedInPage`/`signedInContext`, JWKS-seam minted token) and `playwright.config.ts`.
- Invoke every tool through the shim, never through DOM selectors:
  ```ts
  const res = await page.evaluate(
    ([n, a]) => window.__webmcp__.call(n, a),
    ['search_jobs', { category: ['software_engineering'], timeWindow: '30d' }] as const,
  );
  ```
- **WebMCP is the arrange/act layer; the DOM is the assert layer.** After a Tier-2 tool, assert the rendered list against `res.meta.filteredTotal`. Signed-out flows use a plain context; Tier-3 side-effect flows use `signedInContext`.

### Evidence (proof standards)
Capture, per driven feature, into the run's artifacts dir (named by the skill, e.g. `.claude/skills/verify-onesecondswe/artifacts/<run>/`):
1. **ARIA snapshot** of the asserted region (`await expect(locator).toMatchAriaSnapshot(...)` or `locator.ariaSnapshot()`).
2. **Screenshot** of the resulting page.
3. **`meta` counts** from the tool result (the `filteredTotal`/`serverReturned` numbers the DOM must match).
4. **A DB row** proving the side effect for Tier-3, read through **`e2e/shared/db/assertions.py`** helpers against `jobscraper_e2e` (e.g. `set_enabled_companies` → `user_enabled_companies`; `submit_feedback` → `feedback`; `upvote_feature` → `feature_upvotes`).
- Exercise the **real user path** (a tool call that hits the real endpoint/store), not an internal setter. `open_job` verifies the popup **intent** (a `page.on('popup')` listener or a `window.open` stub) since headless popups are blocked — documented, not hidden. `request_sign_in` is smoke-only (auth comes from the fixture).

### Cleanup
- **Reuse `e2e/shared/stack/stack_down.sh`** — kills only pidfile-recorded processes, never by name.
- Sweep both test identities' companies through the product's own delete path (`e2e/shared/db/reset_user.py`), exactly as `fixtures.ts:sweepOwnedCompanies` does.
- Remove any `VITE_WEBMCP=1` scaffolding the Launch wrote.
- **Evidence survives teardown** — artifacts live outside the torn-down stack, at the named path; the skill re-confirms they exist after cleanup.

### Helpers
Any script the skill ships (e.g. a `drive.spec.ts` or a `doctor.sh`) is executable and its exact invocation is shown in the skill body. No reverse-engineering.

### Feature map — `.claude/skills/verify-onesecondswe/features/`
`features/README.md` (index) + **one file per user-facing route** mined from `src/frontend/src/config/routes.ts`. Each feature file has **exactly these four H2s, in this order** (per the create-skill method):

```
## Sub-features
## How to get to it (user POV)
## Driving it with WebMCP
## Gotchas
```

Required feature files (the WebMCP-drivable, user-facing routes):

| File | Route | Primary tools |
|---|---|---|
| `recent-jobs.md` | `/` (`RECENT_JOBS`) | `search_jobs`, `apply_feed_filters`, `reset_feed_filters`, `open_job`, `list_filter_options`, `search_locations`, `list_companies` |
| `company-hiring-trends.md` | `/companies` (`COMPANIES`) | `get_company_hiring_trend`, `get_job`, `list_companies` |
| `curated-companies.md` | `/curated-companies` | `list_companies` |
| `saved-filters.md` | `/saved-filters` | `save_filter_defaults`, `set_enabled_companies` (login-gated) |
| `vote-features.md` | `/vote-features` | `upvote_feature`, `submit_feedback` |
| `account.md` | `/account` | `request_sign_in` |
| `add-companies.md` | `/add-companies` (flag-gated) | none new — cross-reference the existing `e2e/add-companies` gate |
| `why.md` | `/why` | none (static) — documents the no-tool reachability path |

**Decision, flagged:** the **admin** routes (`/qa`, `/admin/*`, `/location-pipeline`) are listed in `features/README.md` as **intentionally unmapped** — they are `AdminRoute`-gated, not WebMCP-driven, and reachable only with an admin grant. The README states the concrete prerequisite (a row in `admins`) so a future maintainer knows they are `verified-unreachable`, not missing. This matches the create-skill guidance to seed the top user-facing features first.

---

## 4. The human-readable catalog — `docs/implementations/end-to-end-test/E2E-FEATURE-CATALOG.md`

A top-level, non-agent-facing map: **every end-to-end feature and each concrete use case it tests.** Mined from three sources: `config/routes.ts`, the feature map (§3), and `e2e/add-companies/CASES.md` (**AC-01..AC-12**, and note AC-13..AC-25 exist but the catalog anchors on AC-01..AC-12 per the task).

Structure — one section per feature area, each with a **use-case table**:

| Column | Meaning |
|---|---|
| Use-case ID | `UC-<feature>-NN` (new), or the existing `AC-NN` where the Add-Companies gate already covers it |
| What it tests | one line, user-outcome framed |
| WebMCP arrange → act | the tool call(s) |
| DOM/DB assert | the observable end state |

Required sections and their seed use cases (the next stage fills the tables; these are the mandated rows):

- **Recent job feed (`/`)** — filter by category (assert list count == `meta.filteredTotal`, the ~65% NULL-row gotcha), keyword include/exclude, location filter, company filter, time-window narrowing, reset restores full feed, open a posting.
- **Company hiring trends (`/companies`)** — trend buckets render for a company, empty buckets preserved, click-through to one posting via `get_job`.
- **Curated companies (`/curated-companies`)** — directory lists all tracked companies; name→id resolution.
- **Saved filters (`/saved-filters`)** — save default time windows/locations (DB: `user_saved_filters`); set enabled companies (DB: `user_enabled_companies`); feed reflects enabled set after reload.
- **Feedback & voting (`/vote-features`)** — upvote a feature (DB: `feature_upvotes`); submit feedback signed-out (DB: `feedback`, anonymous) and signed-in.
- **Account / auth (`/account`)** — `request_sign_in` surfaces the prompt (smoke); Tier-3 auth via the JWKS-seam fixture.
- **Add companies (`/add-companies`)** — **cross-reference the existing gate**, mapping AC-01..AC-12 to their user cases (careers-URL add, ATS dedupe/`already_public`, one-time discovery, delete/purge, flags, ownership isolation, idempotent re-add, trackAnyway override). This section **points at** `e2e/add-companies/CASES.md`; it does not restate the assertions.

The catalog explicitly records the two **known limits** so a reader is not misled: category/level filters hide unenriched (NULL) rows — assert on `meta.filteredTotal`; and `search_jobs` cursors are **filter-bound** (replaying a cursor after a filter change is a fresh walk, not a 409-safe resume — **⚠ Correction to PLAN line 51**, which asserts a 409; on this branch the backend treats a filter change as a new-but-valid walk, so re-search from scratch on any filter change).

---

## 5. Sequencing for the next stages

1. **Proxy widen** (`api/jobs.ts`, §2.4) + its test — smallest, unblocks `get_job` in prod.
2. **`webmcp/` module** (§2) — Tier-1 first (read-only, lowest risk), then Tier-2, then Tier-3; wire `main.tsx` + `App.tsx` behind the flag.
3. **verify-onesecondswe skill** (§3) — generate, then prove it end-to-end once (Launch→Doctor→drive ONE mapped feature→Evidence→Cleanup) per the create-skill method before handing over.
4. **E2E-FEATURE-CATALOG.md** (§4) — fill the use-case tables from the proven skill + `CASES.md`.

Type-check gate after each: `npm run type-check` (zero errors required) and `npm run lint`.
