import { describe, it, expect } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import type { RootState } from '../../../app/store';
import type { Job, RecentJobsFilters } from '../../../types';
import { jobsApi } from '../../../features/jobs/jobsApi';
import recentJobsFiltersReducer from '../../../features/filters/slices/recentJobsFiltersSlice';
import appReducer from '../../../features/app/appSlice';
import graphFiltersReducer from '../../../features/filters/slices/graphFiltersSlice';
import uiReducer from '../../../features/ui/uiSlice';
import enabledCompaniesReducer from '../../../features/preferences/enabledCompaniesSlice';
import {
  selectAllJobsFromQuery,
  selectRecentFilteredJobs,
  selectRecentAvailableCompanies,
  selectRecentJobsMetadata,
  selectRecentJobsTimeBasedCounts,
} from '../../../features/filters/selectors/recentJobsSelectors';
import { DEMO_JOBS } from '../../../features/jobs/demoJobs';

// Helper to create mock jobs.
// Derives a single canonical location tag from the raw `location` string
// (canonicalName === the string, country null so no implicit "United States"
// option) unless the caller passes `locations` explicitly. Lets the existing
// dropdown fixtures keep asserting on the same strings under the tag model.
const createMockJob = (overrides: Partial<Job> = {}): Job => {
  // Recency (time windows, last-3h/24h counts) keys off firstSeenAt; default it
  // to mirror the (possibly-overridden) createdAt so fixtures that set createdAt
  // to control recency keep working, while a test can still override firstSeenAt.
  const createdAt = overrides.createdAt ?? new Date().toISOString();
  const firstSeenAt = overrides.firstSeenAt ?? createdAt;
  const job: Job = {
    id: '1',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Software Engineer',
    department: 'Engineering',
    team: 'Backend',
    location: 'San Francisco, CA',
    employmentType: 'Full-time',
    createdAt,
    firstSeenAt,
    url: 'https://example.com/job/1',
    raw: {},
    ...overrides,
  };
  if (job.locations === undefined && job.location) {
    job.locations = [{ canonicalName: job.location, kind: 'city', country: null, isPrimary: true }];
  }
  return job;
};

// Helper to create a mock store with jobs
const createMockStoreWithJobs = (
  jobs: Job[],
  filters: RecentJobsFilters,
  enabledIds: string[] | null = null
) => {
  const store = configureStore({
    reducer: {
      app: appReducer,
      graphFilters: graphFiltersReducer,
      recentJobsFilters: recentJobsFiltersReducer,
      ui: uiReducer,
      enabledCompanies: enabledCompaniesReducer,
      [jobsApi.reducerPath]: jobsApi.reducer,
    },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(jobsApi.middleware),
  });

  // Manually populate the store with jobs data
  const state = store.getState();
  const jobsByCompanyId: Record<string, Job[]> = {};

  jobs.forEach((job) => {
    if (!jobsByCompanyId[job.company]) {
      jobsByCompanyId[job.company] = [];
    }
    jobsByCompanyId[job.company].push(job);
  });

  // Create a mock state with the jobs
  const mockState = {
    ...state,
    recentJobsFilters: {
      filters,
    },
    enabledCompanies: {
      ids: enabledIds,
      loading: false,
      error: null,
    },
    [jobsApi.reducerPath]: {
      ...state[jobsApi.reducerPath],
      queries: {
        'getAllJobs(undefined)': {
          status: 'fulfilled' as const,
          endpointName: 'getAllJobs',
          requestId: 'test',
          error: undefined,
          originalArgs: undefined,
          data: {
            byCompanyId: jobsByCompanyId,
            metadata: {
              totalCount: jobs.length,
              companiesCount: Object.keys(jobsByCompanyId).length,
              lastUpdated: new Date().toISOString(),
            },
          },
          startedTimeStamp: Date.now(),
          fulfilledTimeStamp: Date.now(),
        },
      },
      mutations: {},
      provided: {},
      subscriptions: {},
      config: {
        online: true,
        focused: true,
        middlewareRegistered: true,
        refetchOnFocus: false,
        refetchOnReconnect: false,
        refetchOnMountOrArgChange: false,
        keepUnusedDataFor: 60,
        reducerPath: jobsApi.reducerPath,
      },
    },
  } as any as RootState;

  return mockState;
};

describe('recentJobsSelectors', () => {
  describe('demo mode (admin Demo toggle)', () => {
    const realJobs = [createMockJob({ id: 'real-1', company: 'spacex' })];
    const allWindow: RecentJobsFilters = { timeWindow: 'all', softwareOnly: false };

    // The helper seeds `ui` from uiReducer defaults; flip demoModeEnabled on.
    const enableDemo = (state: RootState): RootState =>
      ({ ...state, ui: { ...state.ui, demoModeEnabled: true } }) as RootState;

    it('returns the curated DEMO_JOBS (stable reference) and drops real data when enabled', () => {
      const state = enableDemo(createMockStoreWithJobs(realJobs, allWindow));
      const result = selectAllJobsFromQuery(state);
      // Reference equality proves the memoization-safe stable constant is returned.
      expect(result).toBe(DEMO_JOBS);
      expect(result).toHaveLength(DEMO_JOBS.length);
      expect(result.some((j) => j.id === 'real-1')).toBe(false);
    });

    it('returns real jobs (not demo data) when disabled', () => {
      const state = createMockStoreWithJobs(realJobs, allWindow);
      const result = selectAllJobsFromQuery(state);
      expect(result).not.toBe(DEMO_JOBS);
      expect(result.map((j) => j.id)).toEqual(['real-1']);
    });

    it('bypasses the enabled-companies prefilter when enabled', () => {
      // enabledIds excludes every demo company, yet demo data is still returned in full.
      const state = enableDemo(
        createMockStoreWithJobs(realJobs, allWindow, ['some-company-not-in-demo'])
      );
      expect(selectAllJobsFromQuery(state)).toBe(DEMO_JOBS);
    });

    it('feeds demo data through downstream company/metric/recency selectors', () => {
      const state = enableDemo(createMockStoreWithJobs(realJobs, allWindow));

      const companies = selectRecentAvailableCompanies(state);
      expect(companies.length).toBeGreaterThan(1);
      expect(companies.map((c) => c.id)).toContain('google');
      // Name resolves from config — proves logos/links will resolve for demo jobs too.
      expect(companies.find((c) => c.id === 'google')?.name).toBe('Google');

      expect(selectRecentJobsMetadata(state).totalJobs).toBe(DEMO_JOBS.length);

      const counts = selectRecentJobsTimeBasedCounts(state);
      expect(counts.jobsLast3Hours).toBeGreaterThan(0);
      expect(counts.jobsLast24Hours).toBeGreaterThanOrEqual(counts.jobsLast3Hours);
    });
  });

  describe('enabled-companies prefilter', () => {
    const now = Date.now();
    const makeJobs = (): Job[] => [
      createMockJob({
        id: '1',
        company: 'spacex',
        createdAt: new Date(now - 1 * 60 * 60 * 1000).toISOString(), // 1h ago
      }),
      createMockJob({
        id: '2',
        company: 'spotify',
        createdAt: new Date(now - 2 * 60 * 60 * 1000).toISOString(), // 2h ago
      }),
      createMockJob({
        id: '3',
        company: 'airbnb',
        createdAt: new Date(now - 3 * 60 * 60 * 1000).toISOString(), // 3h ago
      }),
    ];

    const baseFilters: RecentJobsFilters = {
      timeWindow: '7d',
      softwareOnly: false,
    };

    it('returns all jobs unchanged when ids === null', () => {
      const state = createMockStoreWithJobs(makeJobs(), baseFilters, null);
      const result = selectAllJobsFromQuery(state);

      expect(result).toHaveLength(3);
      expect(result.map((j) => j.company).sort()).toEqual(['airbnb', 'spacex', 'spotify']);
    });

    it('returns all jobs unchanged when ids === [] (empty = opt-out)', () => {
      const state = createMockStoreWithJobs(makeJobs(), baseFilters, []);
      const result = selectAllJobsFromQuery(state);

      expect(result).toHaveLength(3);
      expect(result.map((j) => j.company).sort()).toEqual(['airbnb', 'spacex', 'spotify']);
    });

    it('returns only jobs for enabled company ids', () => {
      const state = createMockStoreWithJobs(makeJobs(), baseFilters, ['spacex', 'spotify']);
      const result = selectAllJobsFromQuery(state);

      expect(result).toHaveLength(2);
      const companies = result.map((j) => j.company).sort();
      expect(companies).toEqual(['spacex', 'spotify']);
      expect(companies).not.toContain('airbnb');
    });

    it('returns empty and drops metadata to zero when ids reference no real companies', () => {
      const state = createMockStoreWithJobs(makeJobs(), baseFilters, ['nonexistent-id']);

      expect(selectAllJobsFromQuery(state)).toHaveLength(0);

      const metadata = selectRecentJobsMetadata(state);
      expect(metadata.totalJobs).toBe(0);
      expect(metadata.filteredCount).toBe(0);
    });

    it('propagates filter to selectRecentJobsMetadata and selectRecentJobsTimeBasedCounts', () => {
      const state = createMockStoreWithJobs(makeJobs(), baseFilters, ['spacex']);

      const metadata = selectRecentJobsMetadata(state);
      expect(metadata.totalJobs).toBe(1);
      expect(metadata.filteredCount).toBe(1);

      const counts = selectRecentJobsTimeBasedCounts(state);
      expect(counts.jobsLast24Hours).toBe(1);
      expect(counts.jobsLast3Hours).toBe(1);
    });

    it('memoizes when enabledCompanies.ids is unchanged', () => {
      const state = createMockStoreWithJobs(makeJobs(), baseFilters, ['spacex', 'spotify']);

      const r1 = selectAllJobsFromQuery(state);
      const r2 = selectAllJobsFromQuery(state);

      expect(r1).toBe(r2);
    });
  });

  describe('Selector memoization', () => {
    it('should return same reference when inputs unchanged', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          location: 'San Francisco, CA',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);

      const result1 = selectRecentFilteredJobs(state);
      const result2 = selectRecentFilteredJobs(state);

      // Should return same reference (memoized)
      expect(result1).toBe(result2);
    });

    it('should recalculate when filters change', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          location: 'San Francisco, CA',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '2',
          location: 'New York, NY',
          createdAt: new Date(now - 5 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ];

      let filters: RecentJobsFilters = {
        timeWindow: '7d',
        softwareOnly: false,
      };

      let state = createMockStoreWithJobs(jobs, filters);
      const result1 = selectRecentFilteredJobs(state);

      // Change filters
      filters = {
        timeWindow: '3d',
        softwareOnly: false,
      };

      state = createMockStoreWithJobs(jobs, filters);
      const result2 = selectRecentFilteredJobs(state);

      // Should be different references
      expect(result1).not.toBe(result2);
      // 7d window keeps both jobs; 3d window drops the 5-day-old NY job.
      expect(result1).toHaveLength(2);
      expect(result2).toHaveLength(1);
    });
  });
});
