import { describe, it, expect } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import type { RootState } from '../../../app/store';
import type { Job, RecentJobsFilters, SearchTag } from '../../../types';
import { jobsApi } from '../../../features/jobs/jobsApi';
import recentJobsFiltersReducer from '../../../features/filters/slices/recentJobsFiltersSlice';
import appReducer from '../../../features/app/appSlice';
import graphFiltersReducer from '../../../features/filters/slices/graphFiltersSlice';
import uiReducer from '../../../features/ui/uiSlice';
import enabledCompaniesReducer from '../../../features/preferences/enabledCompaniesSlice';
import {
  selectAllJobsFromQuery,
  selectRecentJobsFilteredWithoutLocation,
  selectRecentAvailableLocations,
  selectRecentAvailableCompanies,
  selectRecentJobsMetadata,
  selectRecentJobsTimeBasedCounts,
} from '../../../features/filters/selectors/recentJobsSelectors';

// Helper to create mock jobs.
// Derives a single canonical location tag from the raw `location` string
// (canonicalName === the string, country null so no implicit "United States"
// option) unless the caller passes `locations` explicitly. Lets the existing
// dropdown fixtures keep asserting on the same strings under the tag model.
const createMockJob = (overrides: Partial<Job> = {}): Job => {
  const job: Job = {
    id: '1',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Software Engineer',
    department: 'Engineering',
    team: 'Backend',
    location: 'San Francisco, CA',
    employmentType: 'Full-time',
    createdAt: new Date().toISOString(),
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

    it('should include jobs of any age when time window is "all"', () => {
      const now = Date.now();
      const jobs: Job[] = [
        createMockJob({
          id: 'recent',
          createdAt: new Date(now - 1 * 24 * 60 * 60 * 1000).toISOString(),
        }),
        createMockJob({
          id: 'ancient',
          createdAt: new Date(now - 5 * 365 * 24 * 60 * 60 * 1000).toISOString(), // 5 years ago
        }),
      ];

      const filters: RecentJobsFilters = {
        timeWindow: 'all',
        location: ['San Francisco, CA'],
        softwareOnly: false,
      };

      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentJobsFilteredWithoutLocation(state);

      expect(result).toHaveLength(2);
      expect(result.map((j) => j.id).sort()).toEqual(['ancient', 'recent']);
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
          company: 'spotify',
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
          company: 'spotify',
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
          company: 'spotify',
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
          company: 'spotify',
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

    it('collapses raw location variants into a single canonical tag option', () => {
      // Three different raw strings + a multi-location string, all normalizing to
      // the same Austin tag, must yield exactly ONE "Austin, TX, US" option.
      const austinTag = {
        canonicalName: 'Austin, TX, US',
        kind: 'city',
        city: 'Austin',
        region: 'TX',
        country: 'US',
        remoteScope: null,
        isPrimary: true,
      };
      const atlantaTag = {
        canonicalName: 'Atlanta, GA, US',
        kind: 'city',
        city: 'Atlanta',
        region: 'GA',
        country: 'US',
        remoteScope: null,
        isPrimary: false,
      };
      const jobs: Job[] = [
        createMockJob({ id: '1', location: 'Austin - 5323', locations: [austinTag] }),
        createMockJob({
          id: '2',
          location: 'Austin, Texas, United States',
          locations: [austinTag],
        }),
        createMockJob({
          id: '3',
          location: 'Austin, TX, USA; Atlanta, GA, USA',
          locations: [austinTag, atlantaTag],
        }),
      ];

      const filters: RecentJobsFilters = { timeWindow: 'all', softwareOnly: false };
      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentAvailableLocations(state);

      // "United States" meta + synthesized state parents (Georgia, Texas) + the
      // two distinct canonical city tags. "Austin, TX, US" appears exactly once
      // despite 3 source rows / raw strings.
      expect(result).toEqual([
        'United States',
        'Georgia, US',
        'Texas, US',
        'Atlanta, GA, US',
        'Austin, TX, US',
      ]);
      expect(result.filter((l) => l === 'Austin, TX, US')).toHaveLength(1);
    });

    it('prepends "United States" only when a job carries a US-country tag', () => {
      const londonTag = {
        canonicalName: 'London, GB',
        kind: 'city',
        city: 'London',
        region: null,
        country: 'GB',
        remoteScope: null,
        isPrimary: true,
      };
      const jobs: Job[] = [createMockJob({ id: '1', location: 'London', locations: [londonTag] })];

      const filters: RecentJobsFilters = { timeWindow: 'all', softwareOnly: false };
      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentAvailableLocations(state);

      expect(result).toEqual(['London, GB']);
      expect(result).not.toContain('United States');
    });

    it('does not duplicate "United States" when a canonical country tag already says so', () => {
      // Raw "US" normalizes to a country-kind tag whose canonicalName IS
      // "United States"; it must not collide with the prepended meta-option.
      const usCountryTag = {
        canonicalName: 'United States',
        kind: 'country',
        city: null,
        region: null,
        country: 'US',
        remoteScope: null,
        isPrimary: true,
      };
      const austinTag = {
        canonicalName: 'Austin, TX, US',
        kind: 'city',
        city: 'Austin',
        region: 'TX',
        country: 'US',
        remoteScope: null,
        isPrimary: true,
      };
      const jobs: Job[] = [
        createMockJob({ id: '1', location: 'US', locations: [usCountryTag] }),
        createMockJob({ id: '2', location: 'Austin, TX, USA', locations: [austinTag] }),
      ];

      const filters: RecentJobsFilters = { timeWindow: 'all', softwareOnly: false };
      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentAvailableLocations(state);

      expect(result.filter((l) => l === 'United States')).toHaveLength(1);
      // The country-only tag synthesizes no state; the Austin tag synthesizes "Texas, US".
      expect(result).toEqual(['United States', 'Texas, US', 'Austin, TX, US']);
    });

    it('synthesizes a state parent option even when no job is tagged at state level', () => {
      const cupertinoTag = {
        canonicalName: 'Cupertino, CA, US',
        kind: 'city',
        city: 'Cupertino',
        region: 'CA',
        country: 'US',
        remoteScope: null,
        isPrimary: true,
      };
      const jobs: Job[] = [
        createMockJob({ id: '1', location: 'Cupertino, CA', locations: [cupertinoTag] }),
      ];
      const filters: RecentJobsFilters = { timeWindow: 'all', softwareOnly: false };
      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentAvailableLocations(state);

      // "California, US" is offered as a pickable parent even though no job is
      // tagged at state level — paired with hierarchical matching.
      expect(result).toEqual(['United States', 'California, US', 'Cupertino, CA, US']);
    });

    it('does not synthesize US-state options for non-US regions', () => {
      const torontoTag = {
        canonicalName: 'Toronto, ON, CA',
        kind: 'city',
        city: 'Toronto',
        region: 'ON',
        country: 'CA',
        remoteScope: null,
        isPrimary: true,
      };
      const jobs: Job[] = [
        createMockJob({ id: '1', location: 'Toronto, ON', locations: [torontoTag] }),
      ];
      const filters: RecentJobsFilters = { timeWindow: 'all', softwareOnly: false };
      const state = createMockStoreWithJobs(jobs, filters);
      const result = selectRecentAvailableLocations(state);

      expect(result).toEqual(['Toronto, ON, CA']);
      expect(result).not.toContain('United States');
      expect(result).not.toContain('Ontario, US');
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
      expect(metadata.companiesRepresented).toBe(0);
    });

    it('propagates filter to selectRecentJobsMetadata and selectRecentJobsTimeBasedCounts', () => {
      const state = createMockStoreWithJobs(makeJobs(), baseFilters, ['spacex']);

      const metadata = selectRecentJobsMetadata(state);
      expect(metadata.totalJobs).toBe(1);
      expect(metadata.filteredCount).toBe(1);
      expect(metadata.companiesRepresented).toBe(1);

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
