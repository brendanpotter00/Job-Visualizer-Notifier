import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BucketJobsModal } from '../../../../components/modals/BucketJobsModal/BucketJobsModal';
import { renderWithProviders, createTestStore } from '../../../../test/testUtils';
import type { Job } from '../../../../types';
import { ATSConstants } from '../../../../api/types';
import { jobsApi } from '../../../../features/jobs/jobsApi';
import { SIGN_IN_OVERLAY_CONFIG } from '../../../../constants/ui';
import { SIGN_IN_OVERLAY_MESSAGES } from '../../../../constants/messages';

// Mock useAuth — default is "auth disabled" so the existing tests (which do not
// opt into auth) keep their prior behavior. Signed-out tests below override
// mockAuthState before rendering.
const mockAuthState = {
  isEnabled: false,
  isAuthenticated: false,
  isLoading: false,
  login: vi.fn(),
  logout: vi.fn(),
  getToken: vi.fn(),
  user: undefined,
};

vi.mock('../../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

beforeEach(() => {
  mockAuthState.isEnabled = false;
  mockAuthState.isAuthenticated = false;
  mockAuthState.isLoading = false;
});

const mockJobs: Job[] = [
  {
    id: '1',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Frontend Engineer',
    createdAt: '2025-11-21T10:00:00Z',
    url: 'https://example.com/job/1',
    raw: {},
  },
  {
    id: '2',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Backend Engineer',
    createdAt: '2025-11-21T10:15:00Z',
    url: 'https://example.com/job/2',
    raw: {},
  },
  {
    id: '3',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'DevOps Engineer',
    createdAt: '2025-11-21T11:00:00Z',
    url: 'https://example.com/job/3',
    raw: {},
  },
];

describe('BucketJobsModal', () => {
  it('does not render when modal is closed', () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.BackendScraper as const,
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
        selectedATS: ATSConstants.BackendScraper as const,
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
        selectedATS: ATSConstants.BackendScraper as const,
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
        selectedATS: ATSConstants.BackendScraper as const,
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
        selectedATS: ATSConstants.BackendScraper as const,
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
        selectedATS: ATSConstants.BackendScraper as const,
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
        selectedATS: ATSConstants.BackendScraper as const,
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
        selectedATS: ATSConstants.BackendScraper as const,
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
        selectedATS: ATSConstants.BackendScraper as const,
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

  describe('signed-out behavior', () => {
    // Build a synthetic set of bucket jobs larger than the signed-out cap so
    // we can assert both the slice and the overlay. The jobs live in the RTK
    // Query cache and are selected into the bucket via filteredJobIds.
    const overLimitJobs: Job[] = Array.from(
      { length: SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT + 2 },
      (_, i) => ({
        id: `bucket-${i}`,
        source: 'backend-scraper' as const,
        company: 'spacex',
        title: `Bucket Role ${i}`,
        createdAt: '2025-11-21T10:00:00Z',
        url: `https://example.com/job/${i}`,
        raw: {},
      })
    );
    const overLimitJobIds = overLimitJobs.map((job) => job.id);

    function buildSignedOutStore(jobs: Job[], filteredJobIds: string[]) {
      const store = createTestStore({
        app: {
          selectedCompanyId: 'spacex',
          selectedATS: ATSConstants.BackendScraper as const,
          isInitialized: true,
        },
        ui: {
          graphModal: {
            open: true,
            bucketStart: '2025-11-21T10:00:00Z',
            bucketEnd: '2025-11-21T11:00:00Z',
            filteredJobIds,
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
            jobs,
            metadata: {
              totalCount: jobs.length,
              fetchedAt: new Date().toISOString(),
            },
          }
        )
      );
      return store;
    }

    it('caps rendered jobs at the signed-out limit and shows the overlay', async () => {
      mockAuthState.isEnabled = true;
      mockAuthState.isAuthenticated = false;

      const store = buildSignedOutStore(overLimitJobs, overLimitJobIds);
      renderWithProviders(<BucketJobsModal />, { store });

      await waitFor(() => {
        expect(screen.getByText('Bucket Role 0')).toBeInTheDocument();
      });

      const visibleTitles = screen.getAllByText(/Bucket Role \d/);
      expect(visibleTitles.length).toBe(SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT);

      expect(screen.getByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: SIGN_IN_OVERLAY_MESSAGES.BUTTON_TEXT })
      ).toBeInTheDocument();
    });

    it('does not show the overlay when bucket jobs fit under the cap', async () => {
      mockAuthState.isEnabled = true;
      mockAuthState.isAuthenticated = false;

      const smallBucket = overLimitJobs.slice(0, SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT);
      const store = buildSignedOutStore(
        smallBucket,
        smallBucket.map((job) => job.id)
      );
      renderWithProviders(<BucketJobsModal />, { store });

      await waitFor(() => {
        expect(screen.getByText('Bucket Role 0')).toBeInTheDocument();
      });

      expect(screen.queryByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).not.toBeInTheDocument();
    });

    it('renders all jobs without gating when the user is signed in', async () => {
      mockAuthState.isEnabled = true;
      mockAuthState.isAuthenticated = true;

      const store = buildSignedOutStore(overLimitJobs, overLimitJobIds);
      renderWithProviders(<BucketJobsModal />, { store });

      await waitFor(() => {
        expect(screen.getByText('Bucket Role 0')).toBeInTheDocument();
      });

      const visibleTitles = screen.getAllByText(/Bucket Role \d/);
      expect(visibleTitles.length).toBe(overLimitJobs.length);
      expect(screen.queryByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).not.toBeInTheDocument();
    });

    it('does not gate when auth is disabled', async () => {
      mockAuthState.isEnabled = false;
      mockAuthState.isAuthenticated = false;

      const store = buildSignedOutStore(overLimitJobs, overLimitJobIds);
      renderWithProviders(<BucketJobsModal />, { store });

      await waitFor(() => {
        expect(screen.getByText('Bucket Role 0')).toBeInTheDocument();
      });

      const visibleTitles = screen.getAllByText(/Bucket Role \d/);
      expect(visibleTitles.length).toBe(overLimitJobs.length);
      expect(screen.queryByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).not.toBeInTheDocument();
    });
  });
});
