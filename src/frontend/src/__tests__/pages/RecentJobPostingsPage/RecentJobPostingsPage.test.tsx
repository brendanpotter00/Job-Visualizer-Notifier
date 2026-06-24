import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { RecentJobPostingsPage } from '../../../pages/RecentJobPostingsPage/RecentJobPostingsPage';
import * as jobsApi from '../../../features/jobs/jobsApi';
import { ERROR_MESSAGES } from '../../../constants/messages';

// Mutable auth mock state — mirrors AccountPage.test.tsx pattern so tests can
// override per-case without re-calling vi.mock.
const mockLogin = vi.fn();
const mockLogout = vi.fn();
const mockGetToken = vi.fn();
let mockAuthState = {
  isEnabled: false,
  isAuthenticated: false,
  isLoading: false,
  login: mockLogin,
  logout: mockLogout,
  getToken: mockGetToken,
  user: null,
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

vi.mock('../../../features/preferences/useEnabledCompanies', () => ({
  useEnabledCompanies: () => ({
    ids: null,
    loading: false,
    error: null,
    save: vi.fn().mockResolvedValue(undefined),
    reload: vi.fn(),
  }),
}));

// Preserve the real jobsApi slice so the store still wires reducers/middleware.
vi.mock('../../../features/jobs/jobsApi', async () => {
  const actual = await vi.importActual<typeof import('../../../features/jobs/jobsApi')>(
    '../../../features/jobs/jobsApi'
  );
  return {
    ...actual,
    useGetAllJobsQuery: vi.fn(),
    useGetJobsForCompanyQuery: vi.fn(),
  };
});

// Stub page children to keep assertions pinned to the page shell.
vi.mock('../../../components/companies-page/FetchProgressBar/FetchProgressBar', () => ({
  FetchProgressBar: ({ companyIdFilter }: { companyIdFilter?: Set<string> | null }) => (
    <div
      data-testid="fetch-progress-bar"
      data-filter={companyIdFilter ? [...companyIdFilter].join(',') : 'null'}
    />
  ),
}));

vi.mock('../../../components/companies-page/FetchProgressBar/FetchProgressBarSkeleton', () => ({
  FetchProgressBarSkeleton: () => <div data-testid="fetch-progress-bar-skeleton" />,
}));

interface RecentJobsMetricsProps {
  totalJobs: number;
  jobsLast24Hours: number;
  jobsLast3Hours: number;
}

vi.mock('../../../components/recent-jobs-page/RecentJobsMetrics/RecentJobsMetrics', () => ({
  RecentJobsMetrics: (props: RecentJobsMetricsProps) => (
    <div data-testid="recent-jobs-metrics" data-total={String(props.totalJobs)} />
  ),
}));

vi.mock('../../../components/recent-jobs-page/RecentJobsFilters', () => ({
  RecentJobsFilters: () => <div data-testid="recent-jobs-filters" />,
}));

vi.mock('../../../components/recent-jobs-page/RecentJobsList/RecentJobsList', () => ({
  RecentJobsList: () => <div data-testid="recent-jobs-list" />,
}));

vi.mock('../../../components/recent-jobs-page/EditCompanyPreferencesRow', () => ({
  EditCompanyPreferencesRow: () => <div data-testid="edit-company-preferences-row" />,
}));

// Minimal stub for the shape `useGetAllJobsQuery` returns that the page reads.
interface AllJobsQueryResult {
  data?: unknown;
  error?: unknown;
  isLoading?: boolean;
  isFetching?: boolean;
}

function mockAllJobsQuery(result: AllJobsQueryResult) {
  vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
    refetch: vi.fn(),
    isSuccess: !result.error && !!result.data,
    isError: !!result.error,
    isUninitialized: false,
    status: 'fulfilled',
    currentData: result.data,
    ...result,
  } as unknown as ReturnType<typeof jobsApi.useGetAllJobsQuery>);
}

const emptyJobsData = {
  byCompanyId: {},
  metadata: {},
  errors: {},
  progress: { completed: 0, total: 0, companies: [] },
  isStreaming: false,
};

describe('RecentJobPostingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState = {
      isEnabled: false,
      isAuthenticated: false,
      isLoading: false,
      login: mockLogin,
      logout: mockLogout,
      getToken: mockGetToken,
      user: null,
    };
  });

  describe('error branch', () => {
    it('renders ErrorState with the decoded error message when query errors', () => {
      // RTK Query shape: { data: 'boom' } → extractErrorMessage returns 'boom'.
      mockAllJobsQuery({
        data: undefined,
        error: { status: 500, data: 'boom' },
        isLoading: false,
        isFetching: false,
      });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(screen.getByText('boom')).toBeInTheDocument();
      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.queryByTestId('recent-jobs-metrics')).not.toBeInTheDocument();
    });

    it('falls back to LOAD_JOBS_FAILED when the error has no decodable message', () => {
      // Unknown shape (no data, no message) → fallback is used.
      mockAllJobsQuery({
        data: undefined,
        error: { status: 500 },
        isLoading: false,
        isFetching: false,
      });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(screen.getByText(ERROR_MESSAGES.LOAD_JOBS_FAILED)).toBeInTheDocument();
      expect(screen.getByRole('alert')).toBeInTheDocument();
    });

    it('does not render metrics/filters/list when error is present', () => {
      mockAllJobsQuery({
        data: undefined,
        error: { status: 500, data: 'boom' },
        isLoading: false,
        isFetching: false,
      });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(screen.queryByTestId('recent-jobs-metrics')).not.toBeInTheDocument();
      expect(screen.queryByTestId('recent-jobs-filters')).not.toBeInTheDocument();
      expect(screen.queryByTestId('recent-jobs-list')).not.toBeInTheDocument();
      expect(screen.queryByTestId('fetch-progress-bar')).not.toBeInTheDocument();
    });
  });

  describe('data branch', () => {
    it('renders metrics, filters, and list when data is present and no error', () => {
      mockAllJobsQuery({
        data: emptyJobsData,
        error: undefined,
        isLoading: false,
        isFetching: false,
      });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(screen.getByTestId('recent-jobs-metrics')).toBeInTheDocument();
      expect(screen.getByTestId('recent-jobs-metrics').getAttribute('data-total')).toBe('0');
      expect(screen.getByTestId('recent-jobs-filters')).toBeInTheDocument();
      expect(screen.getByTestId('recent-jobs-list')).toBeInTheDocument();
    });

    it('renders FetchProgressBarSkeleton while auth is loading', () => {
      mockAuthState.isLoading = true;
      mockAllJobsQuery({
        data: emptyJobsData,
        error: undefined,
        isLoading: false,
        isFetching: false,
      });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(screen.getByTestId('fetch-progress-bar-skeleton')).toBeInTheDocument();
      expect(screen.queryByTestId('fetch-progress-bar')).not.toBeInTheDocument();
    });

    it('renders FetchProgressBarSkeleton while authenticated user has not yet loaded enabled ids', () => {
      mockAuthState.isAuthenticated = true;
      mockAuthState.isLoading = false;
      mockAllJobsQuery({
        data: emptyJobsData,
        error: undefined,
        isLoading: false,
        isFetching: false,
      });
      renderWithProviders(<RecentJobPostingsPage />, {
        initialEntries: ['/'],
        preloadedState: {
          enabledCompanies: {
            ids: null,
            autoEnroll: null,
            loading: true,
            error: null,
            activeLoadRequestId: 'r1',
          },
        },
      });

      expect(screen.getByTestId('fetch-progress-bar-skeleton')).toBeInTheDocument();
      expect(screen.queryByTestId('fetch-progress-bar')).not.toBeInTheDocument();
    });

    it('renders FetchProgressBar with null filter when no enabled ids set (all)', () => {
      mockAuthState.isAuthenticated = false;
      mockAllJobsQuery({
        data: emptyJobsData,
        error: undefined,
        isLoading: false,
        isFetching: false,
      });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      const bar = screen.getByTestId('fetch-progress-bar');
      expect(bar).toBeInTheDocument();
      expect(bar.getAttribute('data-filter')).toBe('null');
    });

    it('renders FetchProgressBar with Set of enabled ids when preferences resolve to a non-empty list', () => {
      mockAuthState.isAuthenticated = true;
      mockAllJobsQuery({
        data: emptyJobsData,
        error: undefined,
        isLoading: false,
        isFetching: false,
      });
      renderWithProviders(<RecentJobPostingsPage />, {
        initialEntries: ['/'],
        preloadedState: {
          enabledCompanies: {
            ids: ['spacex', 'google'],
            autoEnroll: true,
            loading: false,
            error: null,
            activeLoadRequestId: null,
          },
        },
      });

      const bar = screen.getByTestId('fetch-progress-bar');
      const filterAttr = bar.getAttribute('data-filter') ?? '';
      expect(filterAttr).toContain('spacex');
      expect(filterAttr).toContain('google');
    });

    it('renders the heading "Recent Job Postings"', () => {
      mockAllJobsQuery({
        data: undefined,
        error: undefined,
        isLoading: false,
        isFetching: false,
      });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(
        screen.getByRole('heading', { name: /Recent Job Postings/i, level: 1 })
      ).toBeInTheDocument();
    });
  });

  describe('demo mode branch', () => {
    // Full UIState shape — RTK preloadedState replaces the slice's initial state
    // for any slice provided, so we must supply every field, not just the flag.
    const demoUiState = {
      graphModal: { open: false },
      globalLoading: false,
      notifications: [],
      hideAdminFeatures: false,
      demoModeEnabled: true,
    };

    it('renders metrics/filters/list AND suppresses the error banner when demo mode is on and the live query errors', () => {
      // Backend is down (live query errors) — demo mode must still render curated
      // content and must NOT surface the live-error alert. (Ledger #1 regression guard.)
      mockAllJobsQuery({
        data: undefined,
        error: { status: 500, data: 'boom' },
        isLoading: false,
        isFetching: false,
      });
      renderWithProviders(<RecentJobPostingsPage />, {
        initialEntries: ['/'],
        preloadedState: { ui: demoUiState },
      });

      expect(screen.getByTestId('recent-jobs-metrics')).toBeInTheDocument();
      expect(screen.getByTestId('recent-jobs-filters')).toBeInTheDocument();
      expect(screen.getByTestId('recent-jobs-list')).toBeInTheDocument();
      // Error banner must be suppressed in demo mode.
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.queryByText('boom')).not.toBeInTheDocument();
    });

    it('renders metrics/filters/list when demo mode is on and the live query is still loading', () => {
      // Live query has not resolved (data undefined, no error) — demo mode bypasses
      // the live-query loading gate and renders curated content immediately.
      mockAllJobsQuery({
        data: undefined,
        error: undefined,
        isLoading: true,
        isFetching: true,
      });
      renderWithProviders(<RecentJobPostingsPage />, {
        initialEntries: ['/'],
        preloadedState: { ui: demoUiState },
      });

      expect(screen.getByTestId('recent-jobs-metrics')).toBeInTheDocument();
      expect(screen.getByTestId('recent-jobs-filters')).toBeInTheDocument();
      expect(screen.getByTestId('recent-jobs-list')).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('does not render the FetchProgressBar in demo mode even when healthy live data is present', () => {
      // Live fetch-progress is meaningless against curated demo data, so the bar
      // (and its skeleton) must never render while demo mode is on.
      mockAllJobsQuery({
        data: emptyJobsData,
        error: undefined,
        isLoading: false,
        isFetching: false,
      });
      renderWithProviders(<RecentJobPostingsPage />, {
        initialEntries: ['/'],
        preloadedState: { ui: demoUiState },
      });

      expect(screen.getByTestId('recent-jobs-metrics')).toBeInTheDocument();
      expect(screen.queryByTestId('fetch-progress-bar')).not.toBeInTheDocument();
      expect(screen.queryByTestId('fetch-progress-bar-skeleton')).not.toBeInTheDocument();
    });
  });

  describe('initial / empty branch', () => {
    it('renders only the heading + preferences row when data is undefined and no error', () => {
      mockAllJobsQuery({
        data: undefined,
        error: undefined,
        isLoading: true,
        isFetching: true,
      });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(
        screen.getByRole('heading', { name: /Recent Job Postings/i, level: 1 })
      ).toBeInTheDocument();
      expect(screen.getByTestId('edit-company-preferences-row')).toBeInTheDocument();
      expect(screen.queryByTestId('recent-jobs-metrics')).not.toBeInTheDocument();
      expect(screen.queryByTestId('recent-jobs-filters')).not.toBeInTheDocument();
      expect(screen.queryByTestId('recent-jobs-list')).not.toBeInTheDocument();
      expect(screen.queryByTestId('fetch-progress-bar')).not.toBeInTheDocument();
      expect(screen.queryByTestId('fetch-progress-bar-skeleton')).not.toBeInTheDocument();
    });
  });
});
