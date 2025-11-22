import { describe, it, expect } from 'vitest';
import jobsReducer, { clearJobs } from '../../../features/jobs/jobsSlice';
import { loadJobsForCompany } from '../../../features/jobs/jobsThunks';
import type { JobsState } from '../../../features/jobs/jobsSlice';
import type { Job } from '../../../types';

describe('jobsSlice', () => {
  const initialState: JobsState = {
    byCompany: {},
  };

  const mockJob: Job = {
    id: '1',
    source: 'greenhouse',
    company: 'spacex',
    title: 'Software Engineer',
    createdAt: '2025-11-20T12:00:00Z',
    url: 'https://example.com/job/1',
    classification: {
      isSoftwareAdjacent: true,
      category: 'fullstack',
      confidence: 0.9,
      matchedKeywords: ['software engineer'],
    },
    raw: {},
  };

  describe('clearJobs', () => {
    it('should clear jobs for a company', () => {
      const stateWithJobs: JobsState = {
        byCompany: {
          spacex: {
            items: [mockJob],
            isLoading: false,
            metadata: {
              totalCount: 1,
              softwareCount: 1,
            },
          },
        },
      };

      const newState = jobsReducer(stateWithJobs, clearJobs('spacex'));

      expect(newState.byCompany.spacex.items).toEqual([]);
      expect(newState.byCompany.spacex.metadata.totalCount).toBe(0);
      expect(newState.byCompany.spacex.metadata.softwareCount).toBe(0);
    });

    it('should not error if company does not exist', () => {
      const newState = jobsReducer(initialState, clearJobs('nonexistent'));

      expect(newState).toEqual(initialState);
    });
  });

  describe('loadJobsForCompany', () => {
    it('should set loading state when pending', () => {
      const action = {
        type: loadJobsForCompany.pending.type,
        meta: { arg: { companyId: 'spacex', timeWindow: '24h' as const } },
      };

      const newState = jobsReducer(initialState, action);

      expect(newState.byCompany.spacex.isLoading).toBe(true);
      expect(newState.byCompany.spacex.error).toBeUndefined();
      expect(newState.byCompany.spacex.items).toEqual([]);
    });

    it('should preserve existing jobs when loading starts again', () => {
      const stateWithJobs: JobsState = {
        byCompany: {
          spacex: {
            items: [mockJob],
            isLoading: false,
            metadata: {
              totalCount: 1,
              softwareCount: 1,
            },
          },
        },
      };

      const action = {
        type: loadJobsForCompany.pending.type,
        meta: { arg: { companyId: 'spacex', timeWindow: '24h' as const } },
      };

      const newState = jobsReducer(stateWithJobs, action);

      expect(newState.byCompany.spacex.isLoading).toBe(true);
      expect(newState.byCompany.spacex.items).toEqual([mockJob]);
    });

    it('should store jobs when fulfilled', () => {
      const action = {
        type: loadJobsForCompany.fulfilled.type,
        payload: {
          companyId: 'spacex',
          jobs: [mockJob],
          metadata: {
            totalCount: 1,
            softwareCount: 1,
            fetchedAt: '2025-11-20T12:00:00Z',
            oldestJobDate: '2025-11-20T10:00:00Z',
            newestJobDate: '2025-11-20T12:00:00Z',
          },
        },
        meta: { arg: { companyId: 'spacex', timeWindow: '24h' as const } },
      };

      const newState = jobsReducer(initialState, action);

      expect(newState.byCompany.spacex.items).toEqual([mockJob]);
      expect(newState.byCompany.spacex.isLoading).toBe(false);
      expect(newState.byCompany.spacex.error).toBeUndefined();
      expect(newState.byCompany.spacex.metadata.totalCount).toBe(1);
      expect(newState.byCompany.spacex.metadata.softwareCount).toBe(1);
      expect(newState.byCompany.spacex.lastFetchedAt).toBeDefined();
    });

    it('should set error when rejected', () => {
      const action = {
        type: loadJobsForCompany.rejected.type,
        error: { message: 'Network error' },
        meta: { arg: { companyId: 'spacex', timeWindow: '24h' as const } },
      };

      const newState = jobsReducer(initialState, action);

      expect(newState.byCompany.spacex.isLoading).toBe(false);
      expect(newState.byCompany.spacex.error).toBe('Network error');
      expect(newState.byCompany.spacex.items).toEqual([]);
    });

    it('should preserve existing jobs when request fails', () => {
      const stateWithJobs: JobsState = {
        byCompany: {
          spacex: {
            items: [mockJob],
            isLoading: false,
            metadata: {
              totalCount: 1,
              softwareCount: 1,
            },
          },
        },
      };

      const action = {
        type: loadJobsForCompany.rejected.type,
        error: { message: 'Network error' },
        meta: { arg: { companyId: 'spacex', timeWindow: '24h' as const } },
      };

      const newState = jobsReducer(stateWithJobs, action);

      expect(newState.byCompany.spacex.items).toEqual([mockJob]);
      expect(newState.byCompany.spacex.error).toBe('Network error');
    });
  });
});
