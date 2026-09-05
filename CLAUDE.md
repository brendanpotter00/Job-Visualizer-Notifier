# CLAUDE.md

Job Posting Analytics - A monorepo containing a TypeScript + React frontend, Python FastAPI backend, and Python scraping scripts. The frontend visualizes job posting activity over time for multiple companies, all served from the backend's `/api/jobs` endpoint (Greenhouse, Ashby, Lever, Gem, Eightfold/Netflix, and Workday boards, plus Google, Apple, Microsoft, Amazon, TikTok). Built with Redux Toolkit, Recharts, and Material-UI.

## Project Structure

```
├── src/frontend/          # React SPA (see src/frontend/CLAUDE.md)
├── src/backend/api/       # FastAPI backend (see src/backend/CLAUDE.md)
├── scripts/               # Python scrapers (see scripts/CLAUDE.md)
├── api/                   # Vercel serverless functions (ATS proxies)
└── docs/                  # Docs: local setup, implementations, incidents, analysis, enrichment, animations
```

## Commands (run from project root)

```bash
# Development
npm run dev:vercel -w src/frontend  # Start with Vercel Dev (REQUIRED - includes API proxies)
npm run dev              # Vite only (no API proxies, limited functionality)
npm run build            # Production build (runs tsc + vite build)
npm run type-check       # TypeScript validation only

# Testing
npm test                 # Run all tests (Vitest)
npm run test:coverage -w src/frontend  # Generate coverage report

# Code Quality
npm run lint             # ESLint
npm run format           # Prettier formatting
```

## Backend Development

```bash
# Start PostgreSQL (required for backend)
docker compose up -d postgres

# Run backend API (from project root)
source .venv/bin/activate
PYTHONPATH=. uvicorn src.backend.api.main:app --host 0.0.0.0 --port 8000 --reload

# Backend runs on http://localhost:8000
# API docs: http://localhost:8000/docs
```

## Architecture Quick Reference

**State Management:**
- Redux Toolkit Query (RTK Query) for jobs data fetching with caching
- Traditional Redux slices for filters, app, and ui state
- Factory patterns: `createAPIClient` (src/frontend/src/api/clients/baseClient.ts) and `createFilterSlice` (src/frontend/src/features/filters/slices/createFilterSlice.ts)
- The company hiring-trend page has a single filter source (`graphFilters`) that drives both the graph and the job list — the list reflects the graph
- Two job read paths, and they do NOT share a cache shape. The company hiring-trend
  page uses `getJobsForCompany` (one RTK Query entry per company id). The Recent
  Jobs page pages `GET /api/jobs/search` through the `searchJobs` **infinite**
  query, whose cache key is the whole filter set and whose entry is a list of
  server-returned pages. The old `byCompanyId` map — the all-companies fan-out both
  pages once shared — was removed with the client-side walk; there is no store-wide
  index of every job any more, and re-adding one would put the whole corpus back in
  memory (see Gotcha #7 / #10)

**Data Flow:**
User selects company → `getJobsForCompany` RTK Query endpoint (src/frontend/src/features/jobs/jobsApi.ts) → Factory selects API client → Transform to normalized Job model → RTK Query cache update → Memoized selectors filter data → Components render

**API Clients:**
Backend-Scraper (src/frontend/src/api/clients/backendScraperClient.ts) is the only production client — every company flows through the backend `/api/jobs` endpoint. Greenhouse, Ashby, Lever, Gem, Eightfold/Netflix, and Workday boards are fetched by the backend Procrastinate worker (SSRF allowlist for Eightfold lives in Python `src/backend/api/services/eightfold_client.py`); Google, Apple, Microsoft, Amazon, TikTok, and Meta are scraped via Python scripts. The `createAPIClient` factory (src/frontend/src/api/clients/baseClient.ts) is retained as scaffolding for future ATS integrations; no production client currently consumes it.

**Key Selectors:**
- `selectCurrentCompanyJobsRtk` (src/frontend/src/features/jobs/jobsSelectors.ts) - Jobs for selected company
- `selectGraphFilteredJobs` (src/frontend/src/features/filters/selectors/graphFiltersSelectors.ts) - Apply graph filters
- `selectGraphFilteredJobsSorted` (src/frontend/src/features/filters/selectors/graphFiltersSelectors.ts) - Graph-filtered jobs sorted most-recent-first; feeds the job list view
- `selectGraphBucketData` (src/frontend/src/features/filters/selectors/graphFiltersSelectors.ts) - Filtered jobs + time bucketing

**Key Algorithms:**
- Time Bucketing: src/frontend/src/lib/timeBucketing.ts (dynamic bucket sizing for graph visualization)

## Common Tasks

**Adding a Company:**
Use the `add-company` skill (`.claude/skills/add-company/`, `/add-company`) — the single source of truth for onboarding a company end-to-end: the `companies.ts` entry + `COMPANY_IDS`, the single-head-safe backend `companies` seed migration (Greenhouse/Ashby/Lever/Gem, plus the Eightfold/Workday `provider_config` variants), the `changelog.ts` announcement, and brand logos via the `fetch-company-logo` skill.

**Checking Scraper Health:**
Use the `scraper-health-watch` skill (`.claude/skills/scraper-health-watch/`) — detects dead/stale scrape sources, mass closures, and worker death against prod; researches moved boards and opens a fix PR (never merges); texts Brendan only when something is wrong. Runs daily via launchd (`com.bp.jvn-health-watch`); ops runbook in `scripts/health_watch/README.md`.

**Adding ATS Provider:**
1. Create transformer in `src/frontend/src/api/transformers/[provider]Transformer.ts`
2. Create client using `createAPIClient` factory (~15 lines)
3. Add Vercel serverless proxy in `api/[provider].ts`
4. Add to company configs and client selection logic

**Adding Filters:**
1. Add field to `GraphFilters` type (src/frontend/src/types/index.ts)
2. Update `createFilterSlice` factory (src/frontend/src/features/filters/slices/createFilterSlice.ts)
3. Update filtering logic (src/frontend/src/features/filters/selectors/graphFiltersSelectors.ts)
4. Add UI control (src/frontend/src/components/companies-page/GraphFilters.tsx)

**Deploying a Vercel Preview:**
Automatic per-PR preview deploys are **off** — root `vercel.json` sets `git.deploymentEnabled` to `{ "main": true, "**": false }`, so merging to `main` still auto-deploys production but no other branch auto-deploys on push. For a one-off preview that posts the native Vercel comment on the open PR, use the `deploy-to-vercel` skill (`.claude/skills/deploy-to-vercel/`, `/deploy-to-vercel`) — say "deploy to vercel".

**Debugging:**
- Redux DevTools for state inspection
- Selector tests: src/frontend/src/__tests__/features/filters/
- API transformer tests: src/frontend/src/__tests__/api/transformers/
- Time bucketing tests: src/frontend/src/__tests__/lib/timeBucketing.test.ts

## Critical Gotchas

1. **Use Vercel Dev**: Must run `npm run dev:vercel -w src/frontend` (not `npm run dev`) - Vercel serverless functions in `api/` directory proxy ATS API calls to avoid CORS issues
2. **Single Filter Source (companies page)**: The graph and the job list share one filter slice (`graphFilters`) — the list reflects the graph. There is no separate list-filter slice and no sync buttons.
3. **Empty Buckets Matter**: Time bucketing creates empty buckets for full range - don't filter them out
4. **Factory Patterns**: When modifying API or filter logic, update the factory functions, not individual implementations
5. **Zero TypeScript Errors Required**: Run `npm run type-check` before committing
6. **Test Coverage**: Maintain >80% coverage (1300+ tests passing)
7. **Memory Management with Large Datasets**: When rendering large job lists:
   - Always use pagination for tables with 100+ rows (see QAPage pattern)
   - Use `useMemo` for derived data and avoid creating large arrays in render methods
   - Never render unbounded lists - Chrome can consume 50+ GB memory with large unpaginated tables
8. **Postgres MCP timezone bug**: When debugging time-sensitive state through `mcp__postgres-prod__query`, `now() AT TIME ZONE 'UTC'` (and any `timestamptz → timestamp without time zone` cast) drops the timezone tag and the MCP's JSON serializer then re-renders the naked timestamp **as if it were already local time**. The visible result is a phantom shift equal to your local UTC offset (CDT = +5h, CST = +6h, PDT = +7h, UTC = 0). Always cross-check elapsed time with `EXTRACT(EPOCH FROM now())::bigint` or compare against bare `now()` which renders correctly as `…Z`. This one-time confusion produced a phantom "5h hang" investigation in May 2026 on a CDT machine that wasn't real.

## Vercel Serverless Functions (api/)

- `api/jobs.ts` - Backend jobs API proxy for both `GET /api/jobs` and `GET /api/jobs/search` (the Recent page's server-side filtered read path; see `src/backend/CLAUDE.md`). Note it **allow-lists** sub-paths AND query params (an unforwarded param is silently dropped, not an error) and must **explicitly re-emit any response header** — the shared `forwardResponse` helper copies status + body only. `X-Next-Cursor` (keyset pagination) is forwarded for exactly this reason; see the keyset section in `src/backend/CLAUDE.md`.
- `api/jobs-qa.ts` - Backend QA endpoints proxy
- `api/users.ts` - Backend users API proxy (forwards Authorization header)
- `api/features.ts` - Feature voting API proxy (forwards Authorization header)
- `api/admin.ts` - Admin API proxy (forwards Authorization header; admin-only endpoints)
- `api/companies.ts` - Curated-companies directory proxy (public, unauthenticated)
- `api/feedback.ts` - User feedback submission proxy (public, optional auth — stores anonymous if token missing/invalid)
- `api/locations.ts` - Canonical-location search proxy (public, internal-key auth; feeds Location filter dropdowns)

## See Also

- **src/frontend/docs/architecture.md** - Comprehensive Mermaid diagrams for data flow, state shape, factory patterns
- **src/frontend/docs/IMPLEMENTATION.md** - Detailed implementation notes
- **src/frontend/CLAUDE.md** - Frontend-specific documentation
- **src/backend/CLAUDE.md** - Backend API documentation
- **scripts/CLAUDE.md** - Python scraper documentation
- **Greenhouse API**: https://developers.greenhouse.io/job-board.html
- **Lever Postings API** (used by backend client): https://github.com/lever/postings-api
