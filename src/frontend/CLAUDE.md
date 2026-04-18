# Frontend CLAUDE.md

React SPA for job posting analytics. Visualizes job posting activity over time for multiple companies using external ATS APIs (Greenhouse, Lever, Ashby, Workday, Gem, Eightfold) and backend-scraped data (Google, Apple). Built with Redux Toolkit, Recharts, and Material-UI.

**Note:** Commands should be run from project root (not this directory). See root CLAUDE.md for full project context.

## Commands (from project root)

```bash
# Development
npm run dev:vercel       # Start with Vercel Dev (REQUIRED - includes API proxies)
npm run dev              # Vite only (no API proxies, limited functionality)
npm run build            # Production build (runs tsc + vite build)
npm run type-check       # TypeScript validation only

# Testing
npm test                 # Run all tests (Vitest - 768+ tests)
npm run test:coverage    # Generate coverage report

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
Seven ATS providers (Greenhouse, Lever, Ashby, Workday, Gem, Eightfold, Backend-Scraper) are supported. Greenhouse/Lever/Ashby/Workday/Gem use `createAPIClient` factory (api/clients/baseClient.ts) which handles validation, fetch, error handling, filtering, transformation, and metadata calculation. Eightfold (api/clients/eightfoldClient.ts) uses a dedicated client because its API requires sequential pagination with a hard 10-item page cap (used by Netflix). Backend-Scraper uses a dedicated client (api/clients/backendScraperClient.ts) for companies scraped via Python scripts and served from the backend API (Google, Apple).

**Key Selectors:**
- `selectCurrentCompanyJobs` (features/jobs/jobsSelectors.ts) - Jobs for selected company
- `selectGraphFilteredJobs` (features/filters/selectors/graphFiltersSelectors.ts) - Apply graph filters
- `selectListFilteredJobs` (features/filters/selectors/listFiltersSelectors.ts) - Apply list filters + search
- `selectGraphBucketData` (features/filters/selectors/graphFiltersSelectors.ts) - Filtered jobs + time bucketing
- `selectRecentJobsFilteredJobs` (features/filters/selectors/recentJobsSelectors.ts) - Apply recent jobs filters

**Routes/Pages:**
- `/` - Recent Job Postings (pages/RecentJobPostingsPage/RecentJobPostingsPage.tsx) - Aggregated recent jobs across all companies
- `/companies` - Company Job Postings (pages/CompaniesPage/CompaniesPage.tsx) - Per-company job visualization with graph
- `/why` - Why This Was Built (pages/WhyPage/WhyPage.tsx) - About page
- `/qa` - QA (pages/QAPage/QAPage.tsx) - Admin page for triggering scrapers, viewing scrape runs, and debugging
- `/account` - Account (pages/AccountPage/AccountPage.tsx)

**Key Algorithms:**
- Time Bucketing: lib/timeBucketing.ts (dynamic bucket sizing for graph visualization)

## Common Tasks

**Adding a Company:**
Edit `config/companies.ts` and use the appropriate factory function:
- `createGreenhouseCompany()` - Greenhouse ATS
- `createLeverCompany()` - Lever ATS
- `createAshbyCompany()` - Ashby ATS
- `createWorkdayCompany()` - Workday ATS
- `createEightfoldCompany()` - Eightfold AI (pass `{ tenantHost, domain }`; Netflix uses `explore.jobs.netflix.net` / `netflix.com`)
- `createBackendScraperCompany()` - Companies scraped via Python scripts (requires backend setup)

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

1. **Use Vercel Dev**: Must run `npm run dev:vercel` (not `npm run dev`) - Vercel serverless functions in `api/` directory proxy ATS API calls to avoid CORS issues
2. **Vite env files must live in `src/frontend/`, NOT the project root**: The root `vite.config.ts` sets `root: 'src/frontend'`. Vite resolves `.env` files relative to its `root`, so it reads `src/frontend/.env.local`, NOT `<project-root>/.env.local`. **DO NOT add `envDir` to `vite.config.ts` to point at the project root** — this breaks Vercel Dev's API proxy routing, causing all `/api/*` requests to fail. Instead, frontend `VITE_*` env vars go in `src/frontend/.env.local` and backend/Vercel env vars go in `<project-root>/.env.local`.
3. **Vercel Dev cloud env vars override ALL local `.env` files for serverless functions (`api/*.ts`)**: `vercel dev` pulls env vars from the linked Vercel project and they take absolute precedence — `.env.local`, `.env.development.local`, and even shell env vars are all ignored. The `api/utils/backendUrl.ts` helper works around this by detecting `localhost` in the request Host header to use `http://localhost:8000` for local dev. **Do NOT rely on `process.env` in serverless functions for local dev config.**
4. **macOS port 5000 is AirPlay**: Never configure backend services on port 5000 — macOS Monterey+ runs AirPlay Receiver there via ControlCenter. It silently accepts HTTP connections and returns 403, masking "connection refused" errors. The backend runs on port 8000.
5. **Graph/List Filter Independence**: Separate by design - changing graph filters doesn't affect list
6. **Empty Buckets Matter**: Time bucketing creates empty buckets for full range - don't filter them out
7. **Factory Patterns**: When modifying API or filter logic, update the factory functions, not individual implementations
8. **Zero TypeScript Errors Required**: Run `npm run type-check` before committing
9. **Test Coverage**: Maintain >85% coverage (768+ tests passing)
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

- `greenhouse.ts` - Greenhouse API proxy
- `lever.ts` - Lever API proxy
- `ashby.ts` - Ashby API proxy
- `workday.ts` - Workday API proxy
- `gem.ts` - Gem API proxy
- `eightfold.ts` - Eightfold AI proxy (catch-all route at `/api/eightfold/:path(.*)`; requires `X-Eightfold-Tenant-Host` header, SSRF-allowlisted to `*.eightfold.ai` + known vanity hosts like `explore.jobs.netflix.net`)
- `jobs.ts` - Backend jobs API proxy (for scraped companies)
- `jobs-qa.ts` - Backend QA endpoints proxy (scraper triggers, run history)
- `users.ts` - Backend users API proxy (forwards Authorization header)

## See Also

- **Root CLAUDE.md** - Full project documentation including backend and scripts
- **docs/architecture.md** - Comprehensive Mermaid diagrams for data flow, state shape, factory patterns (located at `src/frontend/docs/architecture.md`)
- **Greenhouse API**: https://developers.greenhouse.io/job-board.html
- **Lever API**: https://github.com/lever/postings-api
