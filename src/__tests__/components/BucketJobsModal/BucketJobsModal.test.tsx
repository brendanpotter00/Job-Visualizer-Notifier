import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BucketJobsModal } from '../../../components/BucketJobsModal/BucketJobsModal';
import { renderWithProviders, createTestStore } from '../../../test/testUtils';
import type { Job } from '../../../types';
import { ATSConstants } from '../../../api/types.ts';
import { jobsApi } from '../../../features/jobs/jobsApi';

const mockJobs: Job[] = [
  {
    id: '1',
    source: 'greenhouse',
    company: 'spacex',
    title: 'Frontend Engineer',
    createdAt: '2025-11-21T10:00:00Z',
    url: 'https://example.com/job/1',
    classification: {
      isSoftwareAdjacent: true,
      category: 'frontend',
      confidence: 0.9,
      matchedKeywords: ['react'],
    },
    raw: {},
  },
  {
    id: '2',
    source: 'greenhouse',
    company: 'spacex',
    title: 'Backend Engineer',
    createdAt: '2025-11-21T10:15:00Z',
    url: 'https://example.com/job/2',
    classification: {
      isSoftwareAdjacent: true,
      category: 'backend',
      confidence: 0.85,
      matchedKeywords: ['node'],
    },
    raw: {},
  },
  {
    id: '3',
    source: 'greenhouse',
    company: 'spacex',
    title: 'DevOps Engineer',
    createdAt: '2025-11-21T11:00:00Z',
    url: 'https://example.com/job/3',
    classification: {
      isSoftwareAdjacent: true,
      category: 'devops',
      confidence: 0.88,
      matchedKeywords: ['kubernetes'],
    },
    raw: {},
  },
];

describe('BucketJobsModal', () => {
  it('does not render when modal is closed', () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.Greenhouse as const,
        isInitialized: true,
      },
      ui: {
        graphModal: { open: false },
        globalLoading: false,
        notifications: [],
      },
    });

    // Populate RTK Query cache with jobs data
    store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: mockJobs,
          metadata: {
            totalCount: mockJobs.length,
            softwareCount: mockJobs.length,
            fetchedAt: new Date().toISOString(),
          },
        }
      )
    );

    renderWithProviders(<BucketJobsModal />, { store });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('renders modal when open with bucket data', () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.Greenhouse as const,
        isInitialized: true,
      },
      ui: {
        graphModal: {
          open: true,
          bucketStart: '2025-11-21T10:00:00Z',
          bucketEnd: '2025-11-21T10:30:00Z',
          filteredJobIds: ['1', '2'],
        },
        globalLoading: false,
        notifications: [],
      },
    });

    store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: mockJobs,
          metadata: {
            totalCount: mockJobs.length,
            softwareCount: mockJobs.length,
            fetchedAt: new Date().toISOString(),
          },
        }
      )
    );

    renderWithProviders(<BucketJobsModal />, { store });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('displays bucket time range in title', () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.Greenhouse as const,
        isInitialized: true,
      },
      ui: {
        graphModal: {
          open: true,
          bucketStart: '2025-11-21T10:00:00Z',
          bucketEnd: '2025-11-21T10:30:00Z',
          filteredJobIds: ['1', '2'],
        },
        globalLoading: false,
        notifications: [],
      },
    });

    store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: mockJobs,
          metadata: {
            totalCount: mockJobs.length,
            softwareCount: mockJobs.length,
            fetchedAt: new Date().toISOString(),
          },
        }
      )
    );

    renderWithProviders(<BucketJobsModal />, { store });
    expect(screen.getByText('Jobs Posted')).toBeInTheDocument();
    // Time will be converted to local timezone, just check that it exists
    expect(screen.getByText(/Nov 21, 2025/)).toBeInTheDocument();
  });

  it('displays only jobs in the filtered job IDs', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.Greenhouse as const,
        isInitialized: true,
      },
      ui: {
        graphModal: {
          open: true,
          bucketStart: '2025-11-21T10:00:00Z',
          bucketEnd: '2025-11-21T10:30:00Z',
          filteredJobIds: ['1', '2'],
        },
        globalLoading: false,
        notifications: [],
      },
    });

    store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: mockJobs,
          metadata: {
            totalCount: mockJobs.length,
            softwareCount: mockJobs.length,
            oldestJobDate: mockJobs[0]?.createdAt,
            newestJobDate: mockJobs[mockJobs.length - 1]?.createdAt,
            fetchedAt: new Date().toISOString(),
          },
        }
      )
    );

    renderWithProviders(<BucketJobsModal />, { store });

    await waitFor(() => {
      expect(screen.getByText('Frontend Engineer')).toBeInTheDocument();
    });
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument();
    expect(screen.queryByText('DevOps Engineer')).not.toBeInTheDocument();
  });

  it('displays job count', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.Greenhouse as const,
        isInitialized: true,
      },
      ui: {
        graphModal: {
          open: true,
          bucketStart: '2025-11-21T10:00:00Z',
          bucketEnd: '2025-11-21T10:30:00Z',
          filteredJobIds: ['1', '2'],
        },
        globalLoading: false,
        notifications: [],
      },
    });

    store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: mockJobs,
          metadata: {
            totalCount: mockJobs.length,
            softwareCount: mockJobs.length,
            oldestJobDate: mockJobs[0]?.createdAt,
            newestJobDate: mockJobs[mockJobs.length - 1]?.createdAt,
            fetchedAt: new Date().toISOString(),
          },
        }
      )
    );

    renderWithProviders(<BucketJobsModal />, { store });

    await waitFor(() => {
      expect(screen.getByText('2 jobs found')).toBeInTheDocument();
    });
  });

  it('closes modal when close button is clicked', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.Greenhouse as const,
        isInitialized: true,
      },
      ui: {
        graphModal: {
          open: true,
          bucketStart: '2025-11-21T10:00:00Z',
          bucketEnd: '2025-11-21T10:30:00Z',
          filteredJobIds: ['1', '2'],
        },
        globalLoading: false,
        notifications: [],
      },
    });
    const user = userEvent.setup();

    store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: mockJobs,
          metadata: {
            totalCount: mockJobs.length,
            softwareCount: mockJobs.length,
            fetchedAt: new Date().toISOString(),
          },
        }
      )
    );

    renderWithProviders(<BucketJobsModal />, { store });

    const closeButton = screen.getByLabelText('close');
    await user.click(closeButton);

    // Check that closeGraphModal action was dispatched
    const state = store.getState();
    expect(state.ui.graphModal.open).toBe(false);
  });

  it('handles empty bucket (no jobs)', () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.Greenhouse as const,
        isInitialized: true,
      },
      ui: {
        graphModal: {
          open: true,
          bucketStart: '2025-11-21T10:00:00Z',
          bucketEnd: '2025-11-21T10:30:00Z',
          filteredJobIds: [],
        },
        globalLoading: false,
        notifications: [],
      },
    });

    store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: mockJobs,
          metadata: {
            totalCount: mockJobs.length,
            softwareCount: mockJobs.length,
            fetchedAt: new Date().toISOString(),
          },
        }
      )
    );

    renderWithProviders(<BucketJobsModal />, { store });
    expect(screen.getByText(/no jobs found matching your filters/i)).toBeInTheDocument();
  });

  it('handles missing bucket times gracefully', () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.Greenhouse as const,
        isInitialized: true,
      },
      ui: {
        graphModal: {
          open: true,
          bucketStart: undefined,
          bucketEnd: undefined,
          filteredJobIds: ['1', '2'],
        },
        globalLoading: false,
        notifications: [],
      },
    });

    store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: mockJobs,
          metadata: {
            totalCount: mockJobs.length,
            softwareCount: mockJobs.length,
            fetchedAt: new Date().toISOString(),
          },
        }
      )
    );

    const { container } = renderWithProviders(<BucketJobsModal />, { store });
    expect(container.querySelector('[role="dialog"]')).not.toBeInTheDocument();
  });

  it('displays all jobs when filteredJobIds includes all IDs', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.Greenhouse as const,
        isInitialized: true,
      },
      ui: {
        graphModal: {
          open: true,
          bucketStart: '2025-11-21T10:00:00Z',
          bucketEnd: '2025-11-21T12:00:00Z',
          filteredJobIds: ['1', '2', '3'],
        },
        globalLoading: false,
        notifications: [],
      },
    });

    store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: mockJobs,
          metadata: {
            totalCount: mockJobs.length,
            softwareCount: mockJobs.length,
            oldestJobDate: mockJobs[0]?.createdAt,
            newestJobDate: mockJobs[mockJobs.length - 1]?.createdAt,
            fetchedAt: new Date().toISOString(),
          },
        }
      )
    );

    renderWithProviders(<BucketJobsModal />, { store });

    await waitFor(() => {
      expect(screen.getByText('Frontend Engineer')).toBeInTheDocument();
    });
    expect(screen.getByText('Backend Engineer')).toBeInTheDocument();
    expect(screen.getByText('DevOps Engineer')).toBeInTheDocument();
    expect(screen.getByText('3 jobs found')).toBeInTheDocument();
  });
});
