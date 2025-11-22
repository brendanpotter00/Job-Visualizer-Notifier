import { describe, it, expect } from 'vitest';
import {
  selectCurrentCompanyJobs,
  selectCurrentCompanyLoading,
  selectCurrentCompanyError,
  selectCurrentCompanyMetadata,
  selectCurrentCompanySoftwareJobs,
  selectJobsForCompany,
} from '../../../features/jobs/jobsSelectors';
import type { RootState } from '../../../app/store';
import type { Job } from '../../../types';

describe('jobsSelectors', () => {
  const mockSoftwareJob: Job = {
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

  const mockNonTechJob: Job = {
    id: '2',
    source: 'greenhouse',
    company: 'spacex',
    title: 'HR Manager',
    createdAt: '2025-11-20T11:00:00Z',
    url: 'https://example.com/job/2',
    classification: {
      isSoftwareAdjacent: false,
      category: 'nonTech',
      confidence: 0.9,
      matchedKeywords: [],
    },
    raw: {},
  };

  const mockState: RootState = {
    app: {
      selectedCompanyId: 'spacex',
      selectedView: 'greenhouse',
      isInitialized: true,
    },
    jobs: {
      byCompany: {
        spacex: {
          items: [mockSoftwareJob, mockNonTechJob],
          isLoading: false,
          error: undefined,
          lastFetchedAt: '2025-11-20T12:00:00Z',
          metadata: {
            totalCount: 2,
            softwareCount: 1,
            oldestJobDate: '2025-11-20T11:00:00Z',
            newestJobDate: '2025-11-20T12:00:00Z',
          },
        },
        nominal: {
          items: [],
          isLoading: true,
          metadata: {
            totalCount: 0,
            softwareCount: 0,
          },
        },
      },
    },
    filters: {
      graph: {
        timeWindow: '24h',
        softwareOnly: true,
        roleCategory: 'all',
      },
      list: {
        timeWindow: '24h',
        searchQuery: '',
        softwareOnly: true,
        roleCategory: 'all',
      },
    },
    ui: {
      graphModal: {
        open: false,
      },
      globalLoading: false,
      notifications: [],
    },
  };

  describe('selectCurrentCompanyJobs', () => {
    it('should return jobs for the selected company', () => {
      const jobs = selectCurrentCompanyJobs(mockState);

      expect(jobs).toHaveLength(2);
      expect(jobs).toEqual([mockSoftwareJob, mockNonTechJob]);
    });

    it('should return empty array if no jobs exist', () => {
      const stateWithNoJobs = {
        ...mockState,
        app: { ...mockState.app, selectedCompanyId: 'nonexistent' },
      };

      const jobs = selectCurrentCompanyJobs(stateWithNoJobs);

      expect(jobs).toEqual([]);
    });
  });

  describe('selectCurrentCompanyLoading', () => {
    it('should return loading state for selected company', () => {
      const loading = selectCurrentCompanyLoading(mockState);

      expect(loading).toBe(false);
    });

    it('should return true when company is loading', () => {
      const stateWithLoading = {
        ...mockState,
        app: { ...mockState.app, selectedCompanyId: 'nominal' },
      };

      const loading = selectCurrentCompanyLoading(stateWithLoading);

      expect(loading).toBe(true);
    });

    it('should return false if company not found', () => {
      const stateWithMissingCompany = {
        ...mockState,
        app: { ...mockState.app, selectedCompanyId: 'nonexistent' },
      };

      const loading = selectCurrentCompanyLoading(stateWithMissingCompany);

      expect(loading).toBe(false);
    });
  });

  describe('selectCurrentCompanyError', () => {
    it('should return undefined when no error', () => {
      const error = selectCurrentCompanyError(mockState);

      expect(error).toBeUndefined();
    });

    it('should return error message when present', () => {
      const stateWithError = {
        ...mockState,
        jobs: {
          byCompany: {
            spacex: {
              ...mockState.jobs.byCompany.spacex,
              error: 'Network error',
            },
          },
        },
      };

      const error = selectCurrentCompanyError(stateWithError);

      expect(error).toBe('Network error');
    });
  });

  describe('selectCurrentCompanyMetadata', () => {
    it('should return metadata for selected company', () => {
      const metadata = selectCurrentCompanyMetadata(mockState);

      expect(metadata).toEqual({
        totalCount: 2,
        softwareCount: 1,
        oldestJobDate: '2025-11-20T11:00:00Z',
        newestJobDate: '2025-11-20T12:00:00Z',
      });
    });

    it('should return default metadata if company not found', () => {
      const stateWithMissingCompany = {
        ...mockState,
        app: { ...mockState.app, selectedCompanyId: 'nonexistent' },
      };

      const metadata = selectCurrentCompanyMetadata(stateWithMissingCompany);

      expect(metadata).toEqual({
        totalCount: 0,
        softwareCount: 0,
      });
    });
  });

  describe('selectCurrentCompanySoftwareJobs', () => {
    it('should return only software jobs', () => {
      const jobs = selectCurrentCompanySoftwareJobs(mockState);

      expect(jobs).toHaveLength(1);
      expect(jobs[0]).toEqual(mockSoftwareJob);
      expect(jobs[0].classification.isSoftwareAdjacent).toBe(true);
    });

    it('should return empty array if no software jobs', () => {
      const stateWithOnlyNonTech = {
        ...mockState,
        jobs: {
          byCompany: {
            spacex: {
              ...mockState.jobs.byCompany.spacex,
              items: [mockNonTechJob],
            },
          },
        },
      };

      const jobs = selectCurrentCompanySoftwareJobs(stateWithOnlyNonTech);

      expect(jobs).toEqual([]);
    });
  });

  describe('selectJobsForCompany', () => {
    it('should return jobs for a specific company', () => {
      const selector = selectJobsForCompany('spacex');
      const jobs = selector(mockState);

      expect(jobs).toHaveLength(2);
      expect(jobs).toEqual([mockSoftwareJob, mockNonTechJob]);
    });

    it('should return empty array for nonexistent company', () => {
      const selector = selectJobsForCompany('nonexistent');
      const jobs = selector(mockState);

      expect(jobs).toEqual([]);
    });
  });
});
