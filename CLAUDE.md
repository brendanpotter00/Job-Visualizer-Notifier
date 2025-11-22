# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Job Posting Analytics SPA - A mobile-responsive TypeScript + React application that visualizes job posting activity over time for multiple companies using external ATS (Applicant Tracking System) job board APIs (Greenhouse and Lever).

**Current Status**: Steps 1-11 complete (79%), core app functional. Steps 12-14 remaining (theming, error handling, validation).

## Development Commands

### Development
```bash
npm run dev              # Start dev server (Vite) - http://localhost:5173
npm run preview          # Preview production build
```

### Build & Type Checking
```bash
npm run build            # Production build (runs tsc + vite build)
npm run type-check       # TypeScript validation only
```

### Testing
```bash
npm test                 # Run all tests (Vitest)
npm run test:watch       # Run tests in watch mode
npm run test:coverage    # Generate coverage report
npm run test:ui          # Open Vitest UI
```

### Code Quality
```bash
npm run lint             # ESLint
npm run format           # Prettier formatting
```

## Architecture Overview

### State Management Pattern
- **Redux Toolkit** with feature-based slices (jobs, filters, app, ui)
- **Independent Filter Systems**: Graph and list filters operate completely independently
- **Normalized State**: Jobs organized by company ID in `byCompany` map
- **Memoized Selectors**: Heavy use of `createSelector` from Reselect for performance
- **Async Thunks**: `loadJobsForCompany` handles API calls with proper loading/error states

### Data Flow Pattern
1. User selects company → `loadJobsForCompany` thunk dispatched
2. Thunk selects appropriate API client (Greenhouse/Lever) based on company ATS type
3. Raw API response → Transformer → Normalized Job model
4. Role classification algorithm runs (keyword-based categorization)
5. Redux state updates (jobs + metadata)
6. Memoized selectors filter/transform data for UI
7. Components re-render with filtered/bucketed data

### API Integration Architecture
- **Client Abstraction**: `greenhouseClient.ts` and `leverClient.ts` implement common `JobAPIClient` interface
- **Transformation Layer**: Transformers convert ATS-specific responses to unified `Job` model
- **Error Handling**: Custom `APIError` class with retry information
- **No Backend**: Client-side only, all API calls from browser

### Key Technical Patterns

#### Role Classification System
Located in `src/utils/roleClassification.ts` and `src/config/roleClassificationConfig.ts`:
- Keyword-based classification into 14 categories (frontend, backend, fullstack, mobile, data, ml, devops, platform, qa, security, graphics, embedded, otherTech, nonTech)
- Confidence scoring (0-1) for ambiguous titles
- Tech department pattern matching
- Exclusion patterns for non-tech roles
- **Critical**: This runs on every job during transformation

#### Time Bucketing Algorithm
Located in `src/utils/timeBucketing.ts`:
- Dynamic bucket sizing based on time window:
  - 30m → 5-minute buckets
  - 1h → 10-minute buckets
  - 3h → 30-minute buckets
  - 6h/12h/24h → 1-hour buckets
  - 3d → 6-hour buckets
  - 7d → 1-day buckets
- **Important**: Creates empty buckets for entire time range (needed for proper graph visualization)
- Cumulative count calculation for line graph
- Returns sorted TimeBucket array with job IDs for drill-down

#### Redux Selector Patterns
Critical selectors to understand:
- `selectCurrentCompanyJobs`: Gets jobs for currently selected company
- `selectGraphFilteredJobs`: Applies graph filters (time window, software-only, location, department, role category)
- `selectListFilteredJobs`: Applies list filters + search query (independent from graph)
- `selectGraphBucketData`: Combines filtered jobs + time bucketing for chart visualization
- `selectAvailableLocations/Departments/EmploymentTypes`: Dynamic filter options based on current data

**Key Point**: Graph and list selectors are completely independent - changing graph filters does NOT affect the list and vice versa.

### Component Architecture

#### Main Component Structure
```
App.tsx (Redux Provider + MUI ThemeProvider + main layout)
├── CompanySelector (header dropdown)
├── GraphSection (chart + filters)
│   ├── GraphFilters (time window, location, department, role category, software-only)
│   └── JobPostingsChart (Recharts line chart)
├── ListSection (list + filters)
│   ├── ListFilters (search, time window, filters)
│   └── JobList → JobCard (repeated)
└── BucketJobsModal (MUI Dialog, opens on graph point click)
```

#### Important Component Details
- **JobPostingsChart**: Uses Recharts `LineChart`, click handler opens modal via `openGraphModal` action
- **JobCard**: Displays job with MUI Card, chips for metadata, external link handling
- **BucketJobsModal**: Fullscreen on mobile via `useMediaQuery`, reads `ui.graphModal` state
- **CompanySelector**: Auto-loads jobs on company change via `useEffect`

### File Organization Principles
- **Feature-based**: `src/features/{jobs,filters,ui,app}` - each has slice + selectors + thunks
- **API Layer**: `src/api/` - clients + transformers + types separated
- **Utils**: `src/utils/` - pure functions (role classification, time bucketing, date utils)
- **Config**: `src/config/` - static configuration (companies, classification rules, theme)
- **Types**: `src/types/index.ts` - central type definitions
- **Tests Mirror Structure**: `src/__tests__/` follows same structure as `src/`

## Common Development Tasks

### Adding a New Company
1. Edit `src/config/companies.ts`
2. Add company config with ATS type (greenhouse/lever)
3. No code changes needed - system automatically uses correct client

### Modifying Role Classification
1. Edit keyword mappings in `src/config/roleClassificationConfig.ts`
2. Update `categoryKeywords`, `techDepartments`, or `exclusionPatterns`
3. Run tests: `npm test -- roleClassification.test.ts`
4. Classification runs automatically during API transformation

### Adding New Filters
1. Add filter field to `GraphFilters` or `ListFilters` type in `src/types/index.ts`
2. Add action in `src/features/filters/filtersSlice.ts`
3. Update filtering logic in `src/features/filters/filtersSelectors.ts`
4. Add UI control in `src/components/filters/GraphFilters.tsx` or `ListFilters.tsx`
5. Write tests in `src/__tests__/features/filters/`

### Debugging Data Flow
1. Check Redux DevTools for state shape
2. Use selector tests to verify filtering logic
3. Check API transformer tests for data normalization
4. Verify time bucketing output with bucketing tests
5. Look at component tests for UI integration

## Testing Architecture

**Total Tests**: 140 passing (see PROGRESS.md for breakdown)

### Test Categories
- **Store**: Redux store initialization (5 tests)
- **Role Classification**: Keyword detection, confidence scoring (35 tests)
- **API Layer**: Transformers for Greenhouse + Lever (15 tests)
- **Redux Slices**: Jobs + filters reducers + selectors (42 tests)
- **Time Bucketing**: Bucket algorithm, edge cases (11 tests)
- **UI Components**: JobCard, JobList, BucketJobsModal, CompanySelector (32 tests)

### Testing Utilities
- **MSW**: Mock Service Worker for API mocking (not yet used, plan for integration tests)
- **Testing Library**: React Testing Library for component tests
- **Vitest**: Test runner with coverage

### Running Specific Tests
```bash
npm test -- roleClassification.test.ts    # Run single file
npm test -- -t "classifies frontend"      # Run tests matching pattern
npm test -- --coverage                     # Coverage report
```

## Critical Implementation Details

### Type Safety
- **Strict TypeScript**: No `any` types allowed (enforced by tsconfig.json)
- **Type Inference**: Heavy use of type inference from RTK
- **Type Guards**: Used in transformers for ATS-specific logic
- **Zero Type Errors**: `npm run type-check` must always pass

### API Rate Limiting
- **None Currently Implemented**: Public APIs have no documented rate limits
- **Future**: Consider exponential backoff in APIError handling
- **Caching**: Per-company caching in Redux prevents unnecessary refetches

### Performance Considerations
- **Memoization**: All selectors use `createSelector` for automatic memoization
- **Large Datasets**: Tested with 1000+ jobs (see IMPLEMENTATION.md STEP-14)
- **Bucket Count**: Max ~1440 buckets for 7d window with 10min buckets
- **Re-renders**: Selectors prevent unnecessary re-renders by reference equality

### Time Handling
- **All Timestamps ISO 8601**: Stored as strings in format `2025-11-20T10:30:00Z`
- **date-fns**: Used for all date formatting and manipulation
- **Timezone**: All times handled in UTC, displayed in local timezone
- **Bucket Boundaries**: Inclusive start, exclusive end

## Known Limitations & Gotchas

1. **Client-Side Only**: No backend means no caching, rate limiting, or private API access
2. **Public APIs Only**: Can only access public job boards (Greenhouse board token, Lever company postings)
3. **No RTK Query**: Manual fetch implementation (migration path documented in IMPLEMENTATION.md)
4. **Graph Filter Independence**: Graph and list filters are separate by design - don't try to sync them
5. **Time Window Changes**: Changing time window triggers full data reload (could be optimized with smarter filtering)
6. **Empty Buckets Matter**: Time bucketing creates empty buckets for full range - don't filter them out
7. **Role Classification is Heuristic**: Not perfect, confidence scoring helps identify uncertain classifications

## Future Migration Path

### RTK Query (Documented in IMPLEMENTATION.md)
- Keep existing clients + transformers unchanged
- Replace thunks with `createApi` endpoints
- Use generated hooks (`useGetGreenhouseJobsQuery`)
- Benefits: automatic caching, request deduplication, refetching

### Planned Enhancements (see README.md)
- Email notifications for new postings
- Job comparison features
- Export to CSV/Excel
- Dark mode support
- Saved filter presets

## Important Files Reference

| Concept | Primary File(s) |
|---------|----------------|
| Redux Store Config | `src/app/store.ts` |
| Type Definitions | `src/types/index.ts` |
| Company Config | `src/config/companies.ts` |
| Role Classification | `src/utils/roleClassification.ts`, `src/config/roleClassificationConfig.ts` |
| Time Bucketing | `src/utils/timeBucketing.ts` |
| API Clients | `src/api/greenhouseClient.ts`, `src/api/leverClient.ts` |
| API Transformers | `src/api/transformers/greenhouseTransformer.ts`, `src/api/transformers/leverTransformer.ts` |
| Jobs State | `src/features/jobs/jobsSlice.ts`, `jobsSelectors.ts`, `jobsThunks.ts` |
| Filter State | `src/features/filters/filtersSlice.ts`, `filtersSelectors.ts` |
| UI State | `src/features/ui/uiSlice.ts` |
| Main App | `src/app/App.tsx` |
| Graph Component | `src/components/JobPostingsChart/JobPostingsChart.tsx` |
| List Component | `src/components/JobList/JobList.tsx`, `JobCard.tsx` |
| Modal | `src/components/BucketJobsModal/BucketJobsModal.tsx` |

## Development Workflow Notes

- **Zero TypeScript Errors Required**: Run `npm run type-check` before committing
- **Test Coverage**: Maintain >80% coverage (check with `npm run test:coverage`)
- **Strict ESLint**: Follow existing patterns, no warnings tolerated
- **Prettier Formatting**: Auto-format with `npm run format`
- **Feature Branch Development**: See README.md Contributing section
- **Implementation Follows IMPLEMENTATION.md**: 14-step plan with validation checklists
- **Progress Tracked in PROGRESS.md**: Update after completing steps

## API Documentation References

- **Greenhouse Job Board API**: https://developers.greenhouse.io/job-board.html
- **Lever Postings API**: https://github.com/lever/postings-api

## Troubleshooting

### TypeScript Errors
Run `npm run type-check` to see detailed errors. Most common issues:
- Missing type imports from `src/types/index.ts`
- Incorrect selector return types (check with Redux DevTools)
- Transformer type mismatches (verify ATS response types in `src/api/types.ts`)

### Test Failures
- Check test isolation (each test should be independent)
- Verify mock data matches expected types
- Use `npm run test:ui` for visual debugging
- Check that selectors use correct state shape

### Dev Server Issues
```bash
lsof -ti:5173 | xargs kill -9    # Kill process on port 5173
npm run dev                       # Restart server
```

### Build Errors
```bash
rm -rf node_modules package-lock.json
npm install
npm run build
```
