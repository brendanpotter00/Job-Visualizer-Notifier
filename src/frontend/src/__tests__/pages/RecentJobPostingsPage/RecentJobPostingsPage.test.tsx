import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { RecentJobPostingsPage } from '../../../pages/RecentJobPostingsPage/RecentJobPostingsPage';
import { useRecentJobsSearch } from '../../../features/jobs/hooks/useRecentJobsSearch';
import type { RecentJobsSearch } from '../../../features/jobs/hooks/useRecentJobsSearch';
import type { Job } from '../../../types';

/**
 * The page is now a shell over ONE `useRecentJobsSearch()` call: it picks between
 * "awaiting deploy", "initial error", and "data", and hands the whole search
 * object to the list. So the hook is the seam these tests mock — every branch is
 * a different return value from it, and nothing here touches the network.
 */
vi.mock('../../../features/jobs/hooks/useRecentJobsSearch', () => ({
  useRecentJobsSearch: vi.fn(),
}));

// Children with their own test files are stubbed so assertions stay pinned to
// the page shell. `RecentJobsMetrics` is deliberately NOT stubbed: the counts
// wiring is one of the things this file is here to prove, and the real component
// renders the numbers next to their labels.
vi.mock('../../../components/recent-jobs-page/RecentJobsFilters', () => ({
  RecentJobsFilters: () => <div data-testid="recent-jobs-filters" />,
}));

vi.mock('../../../components/recent-jobs-page/EditCompanyPreferencesRow', () => ({
  EditCompanyPreferencesRow: () => <div data-testid="edit-company-preferences-row" />,
}));

/** The `search` object the list stub was handed on its last render. */
let listSearchProp: RecentJobsSearch | null = null;

vi.mock('../../../components/recent-jobs-page/RecentJobsList/RecentJobsList', () => ({
  RecentJobsList: ({ search }: { search: RecentJobsSearch }) => {
    listSearchProp = search;
    return <div data-testid="recent-jobs-list" data-job-count={String(search.jobs.length)} />;
  },
}));

const retry = vi.fn();
const fetchNextPage = vi.fn();

function makeJob(id: string): Job {
  const seen = new Date().toISOString();
  return {
    id,
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Software Engineer',
    location: 'Hawthorne, CA',
    createdAt: seen,
    firstSeenAt: seen,
    url: `https://example.com/job/${id}`,
    raw: {},
  };
}

/** A healthy, idle search result; each test overrides only what it is about. */
function mockSearch(overrides: Partial<RecentJobsSearch> = {}): RecentJobsSearch {
  const result: RecentJobsSearch = {
    jobs: [],
    counts: null,
    isInitialLoading: false,
    isRefreshing: false,
    isFetchingNextPage: false,
    hasNextPage: false,
    fetchNextPage,
    error: null,
    errorScope: null,
    isAwaitingDeploy: false,
    retry,
    isSkippedEmpty: false,
    ...overrides,
  };
  vi.mocked(useRecentJobsSearch).mockReturnValue(result);
  return result;
}

/** The MetricCard box wrapping a labeled tile, so a value can be tied to its label. */
function tile(label: string): HTMLElement {
  const labelNode = screen.getByText(label);
  if (!labelNode.parentElement) throw new Error(`metric tile for "${label}" has no container`);
  return labelNode.parentElement;
}

describe('RecentJobPostingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listSearchProp = null;
  });

  describe('awaiting the backend deploy', () => {
    it('renders the waiting copy instead of an error banner', () => {
      // Frontend and backend deploy independently; a 404 in that window is a wait,
      // not a failure, and must never read as one.
      mockSearch({ isAwaitingDeploy: true, isInitialLoading: true });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(screen.getByText(/Finishing an update/i)).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.queryByTestId('recent-jobs-list')).not.toBeInTheDocument();
      expect(screen.queryByText('Displayed Jobs')).not.toBeInTheDocument();
    });

    it('still suppresses the banner if an error survives alongside the grace window', () => {
      // The hook nulls `error` while the grace window is open, but the page must
      // not depend on that: `isAwaitingDeploy` alone decides this branch, so a
      // regression upstream degrades to "still loading", never to a false outage.
      mockSearch({ isAwaitingDeploy: true, error: 'Not Found', errorScope: 'initial' });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(screen.getByText(/Finishing an update/i)).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.queryByText('Not Found')).not.toBeInTheDocument();
    });
  });

  describe('initial error', () => {
    it('renders the decoded message as a real error, not an empty result', () => {
      // "No jobs found" for what is actually an outage sends the reader off to
      // change filters that were never the problem (2026-08-10 follow-up), so the
      // list — which owns the empty state — must not render at all here.
      mockSearch({ error: 'boom', errorScope: 'initial', jobs: [] });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(screen.getByRole('alert')).toHaveTextContent('boom');
      expect(screen.queryByTestId('recent-jobs-list')).not.toBeInTheDocument();
      expect(screen.queryByTestId('recent-jobs-filters')).not.toBeInTheDocument();
      expect(screen.queryByText('Displayed Jobs')).not.toBeInTheDocument();
    });

    it('retries through the hook when the banner’s Retry is pressed', async () => {
      mockSearch({ error: 'boom', errorScope: 'initial' });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      await userEvent.click(screen.getByRole('button', { name: /retry/i }));

      expect(retry).toHaveBeenCalledTimes(1);
    });

    it('keeps the rows and skips the banner when a LATER page fails', () => {
      // A next-page failure is the list's business: it shows an inline retry under
      // the rows already loaded. Swapping the whole page for a banner would throw
      // away everything the reader had scrolled through.
      mockSearch({ jobs: [makeJob('1')], error: 'boom', errorScope: 'nextPage' });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(screen.getByTestId('recent-jobs-list')).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });

  describe('metrics', () => {
    it('feeds the hook’s counts into the total / 24h / 3h tiles', () => {
      // `total` counts the active filter set; the two recency figures count the
      // whole open corpus. Three distinct numbers so a mis-wire cannot pass.
      mockSearch({ counts: { total: 42, last24h: 7, last3h: 3 } });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(within(tile('Displayed Jobs')).getByText('42')).toBeInTheDocument();
      expect(within(tile('Past 24 Hours')).getByText('7')).toBeInTheDocument();
      expect(within(tile('Past 3 Hours')).getByText('3')).toBeInTheDocument();
    });

    it('shows zeros while page 1 (which carries the counts) is still in flight', () => {
      mockSearch({ counts: null, isInitialLoading: true });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(within(tile('Displayed Jobs')).getByText('0')).toBeInTheDocument();
      expect(within(tile('Past 24 Hours')).getByText('0')).toBeInTheDocument();
      expect(within(tile('Past 3 Hours')).getByText('0')).toBeInTheDocument();
    });
  });

  describe('data', () => {
    it('renders the heading, metrics, filters, and list', () => {
      mockSearch({ jobs: [makeJob('1'), makeJob('2')], counts: { total: 2, last24h: 2, last3h: 1 } });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(
        screen.getByRole('heading', { name: /Recent Job Postings/i, level: 1 })
      ).toBeInTheDocument();
      expect(screen.getByTestId('edit-company-preferences-row')).toBeInTheDocument();
      expect(screen.getByTestId('recent-jobs-filters')).toBeInTheDocument();
      expect(screen.getByTestId('recent-jobs-list')).toHaveAttribute('data-job-count', '2');
    });

    it('hands the list the very object the hook returned', () => {
      // One `useRecentJobsSearch()` call for the page, passed down. A second
      // instance would keep its own debounce timers and mint a competing cache
      // entry, doubling every request for the same view.
      const search = mockSearch({ jobs: [makeJob('1')] });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(listSearchProp).toBe(search);
    });

    it('never renders the retired per-company fetch progress bar', () => {
      // FetchProgressBar reported a client-side fan-out across every company. The
      // page fetches one server-filtered page at a time now, so there is no fan-out
      // to report and nothing should render a progress indicator in this branch.
      mockSearch({ jobs: [makeJob('1')], counts: { total: 1, last24h: 1, last3h: 0 } });
      renderWithProviders(<RecentJobPostingsPage />, { initialEntries: ['/'] });

      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
      expect(screen.queryByText(/Loading jobs from \d+\/\d+ companies/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Loaded \d+\/\d+ companies/)).not.toBeInTheDocument();
    });
  });

  describe('demo mode', () => {
    // Full UIState shape — RTK preloadedState replaces the slice's initial state
    // for any slice provided, so every field has to be supplied, not just the flag.
    const demoUiState = {
      graphModal: { open: false },
      globalLoading: false,
      notifications: [],
      hideAdminFeatures: false,
      demoModeEnabled: true,
    };

    it('renders metrics and the list from the hook’s curated result', () => {
      // Demo mode lives entirely inside the hook, which serves the fixture without
      // touching the network. The page has no demo branch by design — this pins
      // that the shell is not gated on anything live.
      mockSearch({
        jobs: [makeJob('demo-0'), makeJob('demo-1'), makeJob('demo-2')],
        counts: { total: 3, last24h: 3, last3h: 2 },
      });
      renderWithProviders(<RecentJobPostingsPage />, {
        initialEntries: ['/'],
        preloadedState: { ui: demoUiState },
      });

      expect(within(tile('Displayed Jobs')).getByText('3')).toBeInTheDocument();
      expect(within(tile('Past 3 Hours')).getByText('2')).toBeInTheDocument();
      expect(screen.getByTestId('recent-jobs-list')).toHaveAttribute('data-job-count', '3');
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });
});
