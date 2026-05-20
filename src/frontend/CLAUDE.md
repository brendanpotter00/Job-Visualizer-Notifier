# Frontend CLAUDE.md

React SPA for job posting analytics. Visualizes job posting activity over time for multiple companies using external ATS APIs (Workday, Eightfold) and backend-served data via `/api/jobs` (Greenhouse companies, Ashby companies, Lever companies, Gem companies, Google, Apple, Microsoft). Built with Redux Toolkit, Recharts, and Material-UI.

**Note:** Commands should be run from project root (not this directory). See root CLAUDE.md for full project context.

## Commands (from project root)

```bash
# Development
npm run dev:vercel -w src/frontend  # Start with Vercel Dev (REQUIRED - includes API proxies)
npm run dev              # Vite only (no API proxies, limited functionality)
npm run build            # Production build (runs tsc + vite build)
npm run type-check       # TypeScript validation only

# Testing
npm test                 # Run all tests (Vitest - 1300+ tests)
npm run test:coverage -w src/frontend  # Generate coverage report

# Code Quality
npm run lint             # ESLint
npm run format           # Prettier formatting
```

## Architecture Quick Reference

All paths below are relative to `src/frontend/src/`.

**State Management:**
- Redux Toolkit Query (RTK Query) for jobs data fetching with caching
- Traditional Redux slices for filters, app, and ui state
- Factory patterns: `createAPIClient` (api/clients/baseClient.ts) and `createFilterSlice` (features/filters/slices/createFilterSlice.ts)
- Graph and list filters operate independently (manual sync available)
- Jobs normalized by company ID in `byCompany` map for O(1) lookup

**Data Flow:**
User selects company → `getJobsForCompany` RTK Query endpoint (features/jobs/jobsApi.ts) → Factory selects API client → Transform to normalized Job model → RTK Query cache update → Memoized selectors filter data → Components render

**API Clients:**
Three ATS providers (Workday, Eightfold, Backend-Scraper) are supported. Workday uses the `createAPIClient` factory (api/clients/baseClient.ts) which handles validation, fetch, error handling, filtering, transformation, and metadata calculation. Eightfold (api/clients/eightfoldClient.ts) uses a dedicated client because its API requires sequential pagination with a hard 10-item page cap (used by Netflix). Backend-Scraper uses a dedicated client (api/clients/backendScraperClient.ts) for companies served from the backend `/api/jobs` endpoint — all Greenhouse, Ashby, Lever, and Gem boards (fetched by the backend Procrastinate worker) plus Google, Apple, and Microsoft (scraped via Python scripts).

**Key Selectors:**
- `selectCurrentCompanyJobsRtk` (features/jobs/jobsSelectors.ts) - Jobs for selected company
- `selectGraphFilteredJobs` (features/filters/selectors/graphFiltersSelectors.ts) - Apply graph filters
- `selectListFilteredJobs` (features/filters/selectors/listFiltersSelectors.ts) - Apply list filters + search
- `selectGraphBucketData` (features/filters/selectors/graphFiltersSelectors.ts) - Filtered jobs + time bucketing
- `selectRecentFilteredJobs` (features/filters/selectors/recentJobsSelectors.ts) - Apply recent jobs filters

**Routes/Pages:**
- `/` - Recent Job Postings (pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx) - Aggregated recent jobs across all companies
- `/companies` - Company Job Postings (pages/CompaniesPage/CompaniesPage.tsx) - Per-company job visualization with graph
- `/why` - Why This Was Built (pages/WhyPage/WhyPage.tsx) - About page
- `/qa` - QA (pages/QAPage/QAPage.tsx) - Admin page for triggering scrapers, viewing scrape runs, and debugging
- `/account` - Account (pages/AccountPage/AccountPage.tsx)
- `/vote-features` - Vote for Features (pages/VoteFeaturesPage/VoteFeaturesPage.tsx) - Feature voting page
- `/admin/users` - Admin Users (pages/AdminUsersPage/AdminUsersPage.tsx) - Admin-only user management (grant/revoke admin)

**Key Algorithms:**
- Time Bucketing: lib/timeBucketing.ts (dynamic bucket sizing for graph visualization)

## Frontend Foundations

All paths below are relative to `src/frontend/src/`.

This section documents the shared primitives and cross-cutting rules every page and feature must follow. These are the canonical building blocks — new code consumes them rather than re-inventing loading spinners, error alerts, or fetch lifecycles.

### Shared primitives

- **`LoadingState`** — `components/shared/LoadingIndicator.tsx`. Centered spinner with optional `caption` and `fullPage` props. Exported as `LoadingState` (preferred alias) and `LoadingIndicator` (original name). Use for any loading view: `<LoadingState fullPage />` for page-level initial loads, `<LoadingState size={60} minHeight={400} caption="…" />` for in-layout spinners.
- **`ErrorState`** — `components/shared/ErrorDisplay.tsx`. Error view with optional `inline` (Alert) vs card mode and optional `onRetry`. Exported as `ErrorState` (preferred alias) and `ErrorDisplay` (original name). Use `<ErrorState inline message={msg} onRetry={fn} />` for in-page errors; omit `inline` for the full-card variant.
- **`EmptyState`** — `components/shared/ErrorDisplay.tsx`. Empty-results view. Exported as `EmptyState` (preferred alias) and `EmptyStateDisplay` (original name). The job-specific `EmptyJobListState` wrapper stays — it reads copy from `constants/messages.ts`.
- **`extractErrorMessage(err, fallback?)`** — `lib/errors.ts`. Single source for decoding unknown errors (RTK Query `{ data }` shape, `Error` instances, strings, generic `{ message }` objects). Replaces the `err instanceof Error ? err.message : '…'` boilerplate and the nested RTK-Query ternaries. Always use this instead of hand-rolling the decode at the call site.
- **`useFetchWithStatus<T>`** — `hooks/useFetchWithStatus.ts`. Abortable fetch-lifecycle hook for page-level data loads. Mirrors the `AbortController` + `mountedRef` pattern used in `features/auth/useCurrentUser.ts` and `features/preferences/useEnabledCompanies.ts`. Use when a page or component needs to coordinate `loading` / `error` / `data` around a non-RTK-Query fetch. **Scope note:** RTK Query endpoints and the two auth-aware hooks above are intentionally not migrated — they have specialized behavior worth keeping separate.

### Rules

1. **Typed Redux hooks only.** All Redux consumers import `useAppDispatch` and `useAppSelector` from `app/hooks.ts`. Raw `useDispatch` / `useSelector` from `react-redux` is forbidden in `src/` outside that single file (it is the intended entry point). If a new file imports raw hooks, the review is rejected.
2. **Page-level fetch lifecycles use `useFetchWithStatus` or RTK Query — never both, never neither.** Inline `useState` + `useEffect` + `fetch` blocks for page/component data are prohibited. If a fetch needs caching, invalidation, or cross-page sharing, use RTK Query (`features/jobs/jobsApi.ts` pattern). If a fetch is page-local and read-only with a simple lifecycle, use `useFetchWithStatus`. User-action mutations (e.g. QAPage's trigger-scrape button) stay hand-rolled and do not fall under this rule — `useFetchWithStatus` is read-only by design.
3. **All error decoding goes through `extractErrorMessage`.** Do not introduce new `err instanceof Error ? err.message : '…'` ternaries or new `'data' in err` blocks.
4. **All page loading / error UI uses `LoadingState` / `ErrorState`.** Do not render raw `<CircularProgress />` in a centered `<Box>` or raw `<Alert severity="error">` at the page level. Nested-component spinners (e.g. chart skeletons, job-card skeletons) are fine and live alongside `LoadingState` in `components/shared/LoadingIndicator.tsx`.

### Remaining `eslint-disable` comments (authoritative list)

The following `eslint-disable` directives are allowed; all others must be justified in review. Each is documented here with the justification pulled from the code.

**`react-hooks/*` family:**

- `hooks/useFetchWithStatus.ts:141` — `react-hooks/exhaustive-deps`. The hook spreads the caller-provided `deps` array into its internal `useEffect` dep list. ESLint's exhaustive-deps rule cannot prove the spread is stable-by-convention across renders. The hook contract requires callers to pass a stable `fetcher` (via `useCallback`) and a deps array, mirroring `useEffect` semantics. The disable is localized to the single `useEffect` line.
- `components/layout/RootLayout.tsx:56` — `react-hooks/set-state-in-effect`. Auto-syncs `drawerOpen` local state with the `isMobile` MUI `useMediaQuery` breakpoint. `isMobile` is an external subscription (MUI wraps `matchMedia`), so mirroring it into local state via an effect is the React-recommended pattern. A `useSyncExternalStore` rewrite against `matchMedia` would be net-neutral for behavior and adds visual-regression risk around drawer-width transitions.
- `components/companies-page/MetricsDashboard/hooks/useTimeBasedJobCounts.ts:24` — `react-hooks/purity`. Samples `Date.now()` inside `useMemo` to compute rolling time-window counts (last 12h / 24h / 3d). Injecting `now` as an argument would relocate the `Date.now()` call into every caller in `MetricsDashboard/*`. Keeping the disable localizes the impurity to one line.

**Other disables:**

- `features/filters/slices/graphFiltersSlice.ts:55` — `@typescript-eslint/no-explicit-any`. `createFilterSlice` generates action creators via computed property names (`[set${CapitalizedName}TimeWindow]`), which TypeScript cannot infer through. The `as any` cast on `slice.actions` is the documented TS limitation (see https://github.com/reduxjs/redux-toolkit/issues/368). Types are still enforced at dispatch sites.
- `features/filters/slices/listFiltersSlice.ts:55` — `@typescript-eslint/no-explicit-any`. Same rationale as `graphFiltersSlice.ts`.
- `features/filters/slices/recentJobsFiltersSlice.ts:60` — `@typescript-eslint/no-explicit-any`. Same rationale as `graphFiltersSlice.ts`.
- `features/auth/GoogleCredentialContext.tsx:10` — `react-refresh/only-export-components`. The file exports both a React component (`GoogleCredentialProvider`) and the context object (`GoogleCredentialContext`) consumers need for `useContext`. Splitting into two files is possible but adds no runtime value; the disable is the established pattern for context modules.

New code must not add disables. If a new disable appears unavoidable, update this list with the file, line, rule, and justification in the same PR.

## Common Tasks

**Adding a Company:**
Edit `config/companies.ts` and use the appropriate factory function:
- `createWorkdayCompany()` - Workday ATS
- `createEightfoldCompany()` - Eightfold AI (pass `{ tenantHost, domain }`; Netflix uses `explore.jobs.netflix.net` / `netflix.com`)
- `createBackendScraperCompany()` - Companies served from the backend `/api/jobs` endpoint, including Greenhouse boards, Ashby boards, Lever boards, and Gem boards (fetched by the backend Procrastinate worker — also requires a row in the backend `companies` table; pass `{ sourceAts: 'greenhouse' | 'ashby' | 'lever' | 'gem' }` to tag the originating ATS) and Python-script-scraped companies (Google, Apple, Microsoft)

**Adding ATS Provider:**
1. Create transformer in `api/transformers/[provider]Transformer.ts`
2. Create client using `createAPIClient` factory (~15 lines)
3. Add Vercel serverless proxy in project root `api/[provider].ts`
4. Add to company configs and client selection logic

**Adding Filters:**
1. Add field to `GraphFilters` or `ListFilters` type (types/index.ts)
2. Update `createFilterSlice` factory (features/filters/slices/createFilterSlice.ts)
3. Update filtering logic (features/filters/selectors/graphFiltersSelectors.ts or listFiltersSelectors.ts)
4. Add UI control (components/companies-page/GraphFilters.tsx or ListFilters.tsx)

**Debugging:**
- Redux DevTools for state inspection
- Selector tests: __tests__/features/filters/
- API transformer tests: __tests__/api/transformers/
- Time bucketing tests: __tests__/lib/timeBucketing.test.ts

## Critical Gotchas

1. **Use Vercel Dev**: Must run `npm run dev:vercel -w src/frontend` (not `npm run dev`) - Vercel serverless functions in `api/` directory proxy ATS API calls to avoid CORS issues
2. **Vite env files must live in `src/frontend/`, NOT the project root**: The root `vite.config.ts` sets `root: 'src/frontend'`. Vite resolves `.env` files relative to its `root`, so it reads `src/frontend/.env.local`, NOT `<project-root>/.env.local`. **DO NOT add `envDir` to `vite.config.ts` to point at the project root** — this breaks Vercel Dev's API proxy routing, causing all `/api/*` requests to fail. Instead, frontend `VITE_*` env vars go in `src/frontend/.env.local` and backend/Vercel env vars go in `<project-root>/.env.local`.
3. **Vercel Dev cloud env vars override ALL local `.env` files for serverless functions (`api/*.ts`)**: `vercel dev` pulls env vars from the linked Vercel project and they take absolute precedence — `.env.local`, `.env.development.local`, and even shell env vars are all ignored. The `api/utils/backendUrl.ts` helper works around this by detecting `localhost` in the request Host header to use `http://localhost:8000` for local dev. **Do NOT rely on `process.env` in serverless functions for local dev config.**
4. **macOS port 5000 is AirPlay**: Never configure backend services on port 5000 — macOS Monterey+ runs AirPlay Receiver there via ControlCenter. It silently accepts HTTP connections and returns 403, masking "connection refused" errors. The backend runs on port 8000.
5. **Graph/List Filter Independence**: Separate by design - changing graph filters doesn't affect list
6. **Empty Buckets Matter**: Time bucketing creates empty buckets for full range - don't filter them out
7. **Factory Patterns**: When modifying API or filter logic, update the factory functions, not individual implementations
8. **Zero TypeScript Errors Required**: Run `npm run type-check` before committing
9. **Test Coverage**: Maintain >85% coverage (1300+ tests passing)
10. **Memory Management**: Large job datasets require careful handling:
   - **Tables**: Always paginate tables with 100+ rows - unpaginated tables with thousands of rows cause severe browser memory issues (50+ GB)
   - **Selectors**: `selectAllJobsFromQuery` flattens all jobs - use filtered selectors when possible
   - **Pattern**: See QAPage jobs table for pagination pattern (useMemo for slice + TablePagination component)

## Key Files

All paths relative to `src/frontend/src/`:

- Redux Store: `app/store.ts`
- Type Definitions: `types/index.ts`
- Company Config: `config/companies.ts`
- Route Definitions: `config/routes.ts`
- API Client Factory: `api/clients/baseClient.ts`
- Backend Scraper Client: `api/clients/backendScraperClient.ts`
- Filter Slice Factory: `features/filters/slices/createFilterSlice.ts`
- Jobs RTK Query API: `features/jobs/jobsApi.ts`, `jobsSelectors.ts`, `progressHelpers.ts`
- Recent Jobs Filters: `features/filters/slices/recentJobsFiltersSlice.ts`, `selectors/recentJobsSelectors.ts`
- Time Bucketing: `lib/timeBucketing.ts`
- Main App: `app/App.tsx`

## Vercel Serverless Functions

Located in project root `api/` directory (proxies to avoid CORS):

- `workday.ts` - Workday API proxy
- `eightfold.ts` - Eightfold AI proxy (catch-all route at `/api/eightfold/:path(.*)`; requires `X-Eightfold-Tenant-Host` header, SSRF-allowlisted to `*.eightfold.ai` + known vanity hosts like `explore.jobs.netflix.net`)
- `jobs.ts` - Backend jobs API proxy (for scraped companies)
- `jobs-qa.ts` - Backend QA endpoints proxy (scraper triggers, run history)
- `users.ts` - Backend users API proxy (forwards Authorization header)
- `features.ts` - Feature voting API proxy (forwards Authorization header)
- `admin.ts` - Admin API proxy (forwards Authorization header; admin-only endpoints)

## See Also

- **Root CLAUDE.md** - Full project documentation including backend and scripts
- **docs/architecture.md** - Comprehensive Mermaid diagrams for data flow, state shape, factory patterns (located at `src/frontend/docs/architecture.md`)
- **Greenhouse API**: https://developers.greenhouse.io/job-board.html
- **Lever Postings API** (used by backend client): https://github.com/lever/postings-api
