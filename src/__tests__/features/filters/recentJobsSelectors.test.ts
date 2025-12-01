import { describe, it, expect } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import type { RootState } from '../../../app/store';
import type { Job, RecentJobsFilters, SearchTag } from '../../../types';
import { jobsApi } from '../../../features/jobs/jobsApi';
import recentJobsFiltersReducer from '../../../features/filters/recentJobsFiltersSlice';
import appReducer from '../../../features/app/appSlice';
import graphFiltersReducer from '../../../features/filters/graphFiltersSlice';
import listFiltersReducer from '../../../features/filters/listFiltersSlice';
import uiReducer from '../../../features/ui/uiSlice';
import {
  selectRecentJobsFilteredWithoutLocation,
  selectRecentAvailableLocations,
  selectRecentAvailableCompanies,
} from '../../../features/filters/recentJobsSelectors';

// Helper to create mock jobs
const createMockJob = (overrides: Partial<Job> = {}): Job => ({
  id: '1',
  source: 'greenhouse',
  company: 'spacex',
  title: 'Software Engineer',
  department: 'Engineering',
  team: 'Backend',
  location: 'San Francisco, CA',
  employmentType: 'Full-time',
  createdAt: new Date().toISOString(),
  url: 'https://example.com/job/1',
  classification: {
    isSoftwareAdjacent: true,
    category: 'fullstack',
    confidence: 0.9,
    matchedKeywords: ['software engineer'],
  },
  raw: {},
  ...overrides,
});

// Helper to create a mock store with jobs
const createMockStoreWithJobs = (jobs: Job[], filters: RecentJobsFilters) => {
  const store = configureStore({
    reducer: {
      app: appReducer,
      graphFilters: graphFiltersReducer,
      listFilters: listFiltersReducer,
      recentJobsFilters: recentJobsFiltersReducer,
      ui: uiReducer,
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
  describe('selectRecentJobsFilteredWithoutLocation', () => {
    it('should filter jobs by all filters except location', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          location: 'San Francisco, CA',
          company: 'spacex',
          createdAt: new Date(now - 1 * 60 * 60 * 1000).toISOString(), // 1 hour ago
        }),
        createMockJob({
          id: '2',
          location: 'New York, NY',
          company: 'spacex',
          createdAt: new Date(now - 2 * 60 * 60 * 1000).toISOString(), // 2 hours ago
        }),
        createMockJob({
          id: '3',
          location: 'Austin, TX',
          company: 'spacex',
          createdAt: new Date(now - 25 * 60 * 60 * 1000).toISOString(), // 25 hours ago
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '24h',
        location: ['San Francisco, CA'], // This should be ignored
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentJobsFilteredWithoutLocation(state);

      // Should return jobs within 24h, regardless of location filter
      expect(result).toHaveLength(2);
      expect(result.map((j) => j.id)).toContain('1');
      expect(result.map((j) => j.id)).toContain('2');
      expect(result.map((j) => j.id)).not.toContain('3');
    });

    it('should apply time window filter', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(), // 1 day ago
        }),
        createMockJob({
          id: '2',
          createdAt: new Date(now - 8 * 24 * 60 * 60 * 1000).toISOString(), // 8 days ago
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        location: ['San Francisco, CA'],
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentJobsFilteredWithoutLocation(state);

      expect(result).toHaveLength(1);
      expect(result[0].id).toBe('1');
    });

    it('should apply company filter', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          company: 'spacex',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '2',
          company: 'nominal',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        company: ['spacex'],
        location: ['San Francisco, CA'], // Should be ignored
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentJobsFilteredWithoutLocation(state);

      expect(result).toHaveLength(1);
      expect(result[0].company).toBe('spacex');
    });

    it('should apply employment type filter', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          employmentType: 'Full-time',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '2',
          employmentType: 'Contract',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        employmentType: 'Full-time',
        location: ['San Francisco, CA'], // Should be ignored
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentJobsFilteredWithoutLocation(state);

      expect(result).toHaveLength(1);
      expect(result[0].employmentType).toBe('Full-time');
    });

    it('should apply search tags filter', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          title: 'Senior Software Engineer',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '2',
          title: 'Product Manager',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ];

      const searchTags: SearchTag[] = [{ text: 'software', mode: 'include' }];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        searchTags,
        location: ['San Francisco, CA'], // Should be ignored
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentJobsFilteredWithoutLocation(state);

      expect(result).toHaveLength(1);
      expect(result[0].title).toContain('Software');
    });

    it('should return empty array when no jobs match other filters', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          createdAt: new Date(now - 10 * 24 * 60 * 60 * 1000).toISOString(), // 10 days ago
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        location: ['San Francisco, CA'],
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentJobsFilteredWithoutLocation(state);

      expect(result).toHaveLength(0);
    });

    it('should preserve all jobs when location is the only active filter', () => {
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
          createdAt: new Date(now - 2 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '3',
          location: 'Austin, TX',
          createdAt: new Date(now - 3 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        location: ['San Francisco, CA'], // Only filter active (besides time window)
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentJobsFilteredWithoutLocation(state);

      // Should return all jobs within time window, location filter ignored
      expect(result).toHaveLength(3);
    });
  });

  describe('selectRecentAvailableLocations', () => {
    it('should return only locations from filtered jobs', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          location: 'San Francisco, CA',
          company: 'spacex',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '2',
          location: 'New York, NY',
          company: 'nominal',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '3',
          location: 'Austin, TX',
          company: 'spacex',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        company: ['spacex'],
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentAvailableLocations(state);

      // Should only show locations from spacex jobs
      expect(result).toHaveLength(2);
      expect(result).toContain('San Francisco, CA');
      expect(result).toContain('Austin, TX');
      expect(result).not.toContain('New York, NY');
    });

    it('should return sorted unique locations', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          location: 'San Francisco, CA',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '2',
          location: 'Austin, TX',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '3',
          location: 'San Francisco, CA', // Duplicate
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentAvailableLocations(state);

      expect(result).toHaveLength(2);
      expect(result).toEqual(['Austin, TX', 'San Francisco, CA']); // Sorted alphabetically
    });

    it('should return empty array when no jobs match other filters', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          location: 'San Francisco, CA',
          createdAt: new Date(now - 10 * 24 * 60 * 60 * 1000).toISOString(), // 10 days ago
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentAvailableLocations(state);

      expect(result).toHaveLength(0);
    });

    it('should update when time window changes', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          location: 'San Francisco, CA',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(), // 1 day ago
        }),
        createMockJob({
          id: '2',
          location: 'New York, NY',
          createdAt: new Date(now - 5 * 24 * 60 * 60 * 1000).toISOString(), // 5 days ago
        }),
      ];

      // First with 7d window
      let filters: RecentJobsFilters = {
        timeWindow: '7d',
        softwareOnly: false,
      };

      let state = createMockStoreWithJobs(jobs, filters);
      let result = selectRecentAvailableLocations(state);

      expect(result).toHaveLength(2);
      expect(result).toContain('San Francisco, CA');
      expect(result).toContain('New York, NY');

      // Now with 3d window
      filters = {
        timeWindow: '3d',
        softwareOnly: false,
      };

      state = createMockStoreWithJobs(jobs, filters);
      result = selectRecentAvailableLocations(state);

      expect(result).toHaveLength(1);
      expect(result).toContain('San Francisco, CA');
      expect(result).not.toContain('New York, NY');
    });

    it('should update when company selection changes', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          company: 'spacex',
          location: 'San Francisco, CA',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '2',
          company: 'nominal',
          location: 'New York, NY',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ];

      // First with no company filter
      let filters: RecentJobsFilters = {
        timeWindow: '7d',
        softwareOnly: false,
      };

      let state = createMockStoreWithJobs(jobs, filters);
      let result = selectRecentAvailableLocations(state);

      expect(result).toHaveLength(2);

      // Now filter by company
      filters = {
        timeWindow: '7d',
        company: ['spacex'],
        softwareOnly: false,
      };

      state = createMockStoreWithJobs(jobs, filters);
      result = selectRecentAvailableLocations(state);

      expect(result).toHaveLength(1);
      expect(result).toContain('San Francisco, CA');
      expect(result).not.toContain('New York, NY');
    });

    it('should update when employment type changes', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          employmentType: 'Full-time',
          location: 'San Francisco, CA',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '2',
          employmentType: 'Contract',
          location: 'New York, NY',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        employmentType: 'Full-time',
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentAvailableLocations(state);

      expect(result).toHaveLength(1);
      expect(result).toContain('San Francisco, CA');
      expect(result).not.toContain('New York, NY');
    });

    it('should work independently from company dropdown', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: '1',
          company: 'spacex',
          location: 'San Francisco, CA',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: '2',
          company: 'nominal',
          location: 'New York, NY',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: '7d',
        company: ['spacex'],
        location: ['San Francisco, CA'],
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);

      // Location dropdown should ignore location filter
      const locations = selectRecentAvailableLocations(state);
      expect(locations).toHaveLength(1);
      expect(locations).toContain('San Francisco, CA');

      // Company dropdown should ignore company filter
      const companies = selectRecentAvailableCompanies(state);
      expect(companies).toHaveLength(1);
      expect(companies[0].id).toBe('spacex');
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

      const result1 = selectRecentAvailableLocations(state);
      const result2 = selectRecentAvailableLocations(state);

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
      const result1 = selectRecentAvailableLocations(state);

      // Change filters
      filters = {
        timeWindow: '3d',
        softwareOnly: false,
      };

      state = createMockStoreWithJobs(jobs, filters);
      const result2 = selectRecentAvailableLocations(state);

      // Should be different references
      expect(result1).not.toBe(result2);
      expect(result1).toHaveLength(2);
      expect(result2).toHaveLength(1);
    });
  });
});
