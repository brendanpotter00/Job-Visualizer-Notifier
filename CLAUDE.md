# CLAUDE.md

Job Posting Analytics - A monorepo containing a TypeScript + React frontend, .NET backend API, and Python scraping scripts. The frontend visualizes job posting activity over time for multiple companies using external ATS APIs (Greenhouse, Lever, Ashby, Workday). Built with Redux Toolkit, Recharts, and Material-UI.

## Project Structure

```
├── src/frontend/          # React SPA (see src/frontend/CLAUDE.md)
├── src/backend/JobsApi/   # .NET 8 API (see src/backend/CLAUDE.md)
├── scripts/               # Python scrapers (see scripts/CLAUDE.md)
├── api/                   # Vercel serverless functions (ATS proxies)
└── docs/                  # Architecture documentation
```

## Commands (run from project root)

```bash
# Development
npm run dev:vercel       # Start with Vercel Dev (REQUIRED - includes API proxies)
npm run dev              # Vite only (no API proxies, limited functionality)
npm run build            # Production build (runs tsc + vite build)
npm run type-check       # TypeScript validation only

# Testing
npm test                 # Run all tests (Vitest)
npm run test:coverage    # Generate coverage report

# Code Quality
npm run lint             # ESLint
npm run format           # Prettier formatting
```

## Backend Development

```bash
# Start PostgreSQL (required for backend)
docker compose up -d postgres

# Run backend API (from project root)
cd src/backend/JobsApi && dotnet run

# Backend runs on http://localhost:5000
# Swagger UI: http://localhost:5000/swagger
```

## Architecture Quick Reference

**State Management:**
- Redux Toolkit Query (RTK Query) for jobs data fetching with caching
- Traditional Redux slices for filters, app, and ui state
- Factory patterns: `createAPIClient` (src/frontend/src/api/clients/baseClient.ts) and `createFilterSlice` (src/frontend/src/features/filters/slices/createFilterSlice.ts)
- Graph and list filters operate independently (manual sync available)
- Jobs normalized by company ID in `byCompany` map for O(1) lookup

**Data Flow:**
User selects company → `getJobsForCompany` RTK Query endpoint (src/frontend/src/features/jobs/jobsApi.ts) → Factory selects API client → Transform to normalized Job model → RTK Query cache update → Memoized selectors filter data → Components render

**API Clients:**
All four ATS providers (Greenhouse, Lever, Ashby, Workday) use `createAPIClient` factory (src/frontend/src/api/clients/baseClient.ts). Factory handles: validation, fetch, error handling, filtering, transformation, metadata calculation. Only URL building and response extraction differ per provider.

**Key Selectors:**
- `selectCurrentCompanyJobs` (src/frontend/src/features/jobs/jobsSelectors.ts) - Jobs for selected company
- `selectGraphFilteredJobs` (src/frontend/src/features/filters/selectors/graphFiltersSelectors.ts) - Apply graph filters
- `selectListFilteredJobs` (src/frontend/src/features/filters/selectors/listFiltersSelectors.ts) - Apply list filters + search
- `selectGraphBucketData` (src/frontend/src/features/filters/selectors/graphFiltersSelectors.ts) - Filtered jobs + time bucketing

**Key Algorithms:**
- Time Bucketing: src/frontend/src/lib/timeBucketing.ts (dynamic bucket sizing for graph visualization)

## Common Tasks

**Adding a Company:**
Edit `src/frontend/src/config/companies.ts` and add company config with ATS type (greenhouse/lever/ashby/workday). System automatically uses correct client via factory pattern.

**Adding ATS Provider:**
1. Create transformer in `src/frontend/src/api/transformers/[provider]Transformer.ts`
2. Create client using `createAPIClient` factory (~15 lines)
3. Add Vercel serverless proxy in `api/[provider].ts`
4. Add to company configs and client selection logic

**Adding Filters:**
1. Add field to `GraphFilters` or `ListFilters` type (src/frontend/src/types/index.ts)
2. Update `createFilterSlice` factory (src/frontend/src/features/filters/slices/createFilterSlice.ts)
3. Update filtering logic (src/frontend/src/features/filters/selectors/graphFiltersSelectors.ts or listFiltersSelectors.ts)
4. Add UI control (src/frontend/src/components/companies-page/GraphFilters.tsx or ListFilters.tsx)

**Debugging:**
- Redux DevTools for state inspection
- Selector tests: src/frontend/src/__tests__/features/filters/
- API transformer tests: src/frontend/src/__tests__/api/transformers/
- Time bucketing tests: src/frontend/src/__tests__/lib/timeBucketing.test.ts

## Critical Gotchas

1. **Use Vercel Dev**: Must run `npm run dev:vercel` (not `npm run dev`) - Vercel serverless functions in `api/` directory proxy ATS API calls to avoid CORS issues
2. **Graph/List Filter Independence**: Separate by design - changing graph filters doesn't affect list
3. **Empty Buckets Matter**: Time bucketing creates empty buckets for full range - don't filter them out
4. **Factory Patterns**: When modifying API or filter logic, update the factory functions, not individual implementations
5. **Zero TypeScript Errors Required**: Run `npm run type-check` before committing
6. **Test Coverage**: Maintain >85% coverage (746+ tests passing)

## Key Files (Frontend)

- Redux Store: `src/frontend/src/app/store.ts`
- Type Definitions: `src/frontend/src/types/index.ts`
- Company Config: `src/frontend/src/config/companies.ts`
- API Client Factory: `src/frontend/src/api/clients/baseClient.ts`
- Filter Slice Factory: `src/frontend/src/features/filters/slices/createFilterSlice.ts`
- Jobs RTK Query API: `src/frontend/src/features/jobs/jobsApi.ts`, `jobsSelectors.ts`, `progressHelpers.ts`
- Time Bucketing: `src/frontend/src/lib/timeBucketing.ts`
- Main App: `src/frontend/src/app/App.tsx`

## Vercel Serverless Functions (api/)

- `api/greenhouse.ts` - Greenhouse API proxy
- `api/lever.ts` - Lever API proxy
- `api/ashby.ts` - Ashby API proxy
- `api/workday.ts` - Workday API proxy
- `api/jobs.ts` - Backend jobs API proxy
- `api/jobs-qa.ts` - Backend QA endpoints proxy

## See Also

- **docs/architecture.md** - Comprehensive Mermaid diagrams for data flow, state shape, factory patterns
- **docs/IMPLEMENTATION.md** - Detailed implementation notes
- **src/frontend/CLAUDE.md** - Frontend-specific documentation
- **src/backend/CLAUDE.md** - Backend API documentation
- **scripts/CLAUDE.md** - Python scraper documentation
- **Greenhouse API**: https://developers.greenhouse.io/job-board.html
- **Lever API**: https://github.com/lever/postings-api
