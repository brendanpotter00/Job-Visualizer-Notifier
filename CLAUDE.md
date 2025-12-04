# CLAUDE.md

Job Posting Analytics SPA - A TypeScript + React application that visualizes job posting activity over time for multiple companies using external ATS APIs (Greenhouse, Lever, Ashby). Built with Redux Toolkit, Recharts, and Material-UI.

## Commands

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

## Architecture Quick Reference

**State Management:**
- Redux Toolkit Query (RTK Query) for jobs data fetching with caching
- Traditional Redux slices for filters, app, and ui state
- Factory patterns: `createAPIClient` (src/api/clients/baseClient.ts) and `createFilterSlice` (src/features/filters/slices/createFilterSlice.ts)
- Graph and list filters operate independently (manual sync available)
- Jobs normalized by company ID in `byCompany` map for O(1) lookup

**Data Flow:**
User selects company → `getJobsForCompany` RTK Query endpoint (src/features/jobs/jobsApi.ts) → Factory selects API client → Transform to normalized Job model → RTK Query cache update → Memoized selectors filter data → Components render

**API Clients:**
All four ATS providers (Greenhouse, Lever, Ashby, Workday) use `createAPIClient` factory (src/api/clients/baseClient.ts). Factory handles: validation, fetch, error handling, filtering, transformation, metadata calculation. Only URL building and response extraction differ per provider.

**Key Selectors:**
- `selectCurrentCompanyJobs` (src/features/jobs/jobsSelectors.ts) - Jobs for selected company
- `selectGraphFilteredJobs` (src/features/filters/selectors/graphFiltersSelectors.ts) - Apply graph filters
- `selectListFilteredJobs` (src/features/filters/selectors/listFiltersSelectors.ts) - Apply list filters + search
- `selectGraphBucketData` (src/features/filters/selectors/graphFiltersSelectors.ts) - Filtered jobs + time bucketing

**Key Algorithms:**
- Time Bucketing: src/lib/timeBucketing.ts (dynamic bucket sizing for graph visualization)

## Common Tasks

**Adding a Company:**
Edit `src/config/companies.ts` and add company config with ATS type (greenhouse/lever/ashby). System automatically uses correct client via factory pattern.

**Adding ATS Provider:**
1. Create transformer in `src/api/transformers/[provider]Transformer.ts`
2. Create client using `createAPIClient` factory (~15 lines)
3. Add to company configs and client selection logic
See `docs/MIGRATION.md` for detailed guide.

**Adding Filters:**
1. Add field to `GraphFilters` or `ListFilters` type (src/types/index.ts)
2. Update `createFilterSlice` factory (src/features/filters/slices/createFilterSlice.ts)
3. Update filtering logic (src/features/filters/selectors/graphFiltersSelectors.ts or listFiltersSelectors.ts)
4. Add UI control (src/components/companies-page/GraphFilters.tsx or ListFilters.tsx, or src/components/shared/filters/)

**Debugging:**
- Redux DevTools for state inspection
- Selector tests: src/__tests__/features/filters/
- API transformer tests: src/__tests__/api/transformers/
- Time bucketing tests: src/__tests__/lib/timeBucketing.test.ts

## Critical Gotchas

1. **Use Vercel Dev**: Must run `npm run dev:vercel` (not `npm run dev`) - Vercel serverless functions in `api/` directory proxy ATS API calls to avoid CORS issues
2. **Graph/List Filter Independence**: Separate by design - changing graph filters doesn't affect list
3. **Empty Buckets Matter**: Time bucketing creates empty buckets for full range - don't filter them out
4. **Factory Patterns**: When modifying API or filter logic, update the factory functions, not individual implementations
5. **Zero TypeScript Errors Required**: Run `npm run type-check` before committing
6. **Test Coverage**: Maintain >85% coverage (422+ tests passing)

## Key Files

- Redux Store: `src/app/store.ts`
- Type Definitions: `src/types/index.ts`
- Company Config: `src/config/companies.ts`
- API Client Factory: `src/api/clients/baseClient.ts`
- Filter Slice Factory: `src/features/filters/slices/createFilterSlice.ts`
- Jobs RTK Query API: `src/features/jobs/jobsApi.ts`, `jobsSelectors.ts`, `progressHelpers.ts`
- Time Bucketing: `src/lib/timeBucketing.ts`
- Main App: `src/app/App.tsx`

## See Also

- **docs/architecture.md** - 9 comprehensive Mermaid diagrams including data flow, state shape, factory patterns, algorithm flowcharts, component hierarchy, and performance optimizations
- **docs/MIGRATION.md** - Migration guide for adding new ATS providers with before/after comparisons
- **Greenhouse API**: https://developers.greenhouse.io/job-board.html
- **Lever API**: https://github.com/lever/postings-api
