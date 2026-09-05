import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { RecentJobsList } from '../../../../components/recent-jobs-page/RecentJobsList/RecentJobsList';
import { createTestStore } from '../../../../test/testUtils';
import { SIGN_IN_OVERLAY_CONFIG } from '../../../../constants/ui';
import { SIGN_IN_OVERLAY_MESSAGES, EMPTY_STATE_MESSAGES } from '../../../../constants/messages';
import type { Job } from '../../../../types';
import type { RecentJobsSearch } from '../../../../features/jobs/hooks/useRecentJobsSearch';
import { resolveResultTotal } from '../../../../features/jobs/resultTotal';
import type { UseInfiniteScrollOptions } from '../../../../hooks/useInfiniteScroll';

/**
 * `RecentJobsList` is now a pure view over one `RecentJobsSearch` object — the
 * whole `/api/jobs/search` walk lives in `useRecentJobsSearch` and is tested
 * there. So every test here drives the component by handing it a search state
 * directly, which is the only way to reach the states that matter (a page in
 * flight over zero rows, a latched next-page error, an exhausted walk) without
 * choreographing a network.
 */

// Capture the options the list hands the infinite-scroll hook so tests can
// drive the sentinel directly instead of faking an IntersectionObserver.
let infiniteScrollOptions: UseInfiniteScrollOptions | null = null;
vi.mock('../../../../hooks/useInfiniteScroll', () => ({
  useInfiniteScroll: (options: UseInfiniteScrollOptions) => {
    infiniteScrollOptions = options;
    return { sentinelRef: { current: null } };
  },
}));

// Auth is a mutable object rather than a per-test factory so a test can flip a
// single field (signed out, auth disabled) without restating the whole shape.
type MockAuthState = {
  isEnabled: boolean;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: ReturnType<typeof vi.fn>;
  logout: ReturnType<typeof vi.fn>;
  getToken: ReturnType<typeof vi.fn>;
  user: null;
};

const mockAuthState: MockAuthState = {
  isEnabled: true,
  isAuthenticated: true,
  isLoading: false,
  login: vi.fn(),
  logout: vi.fn(),
  getToken: vi.fn(),
  user: null,
};

vi.mock('../../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

/**
 * jsdom performs no layout, so every element reports `offsetHeight: 0` and the
 * virtualizer would conclude that all rows fit on screen — rendering the whole
 * list and hiding the very regression these tests exist to catch. Pinning a
 * height makes the windowing math real: with jsdom's 768px viewport the range
 * is a handful of rows plus the overscan buffer, exactly as in a browser.
 */
const MOCK_CARD_HEIGHT = 200;
let originalOffsetHeight: PropertyDescriptor | undefined;

beforeAll(() => {
  originalOffsetHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight');
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get: () => MOCK_CARD_HEIGHT,
  });
});

afterAll(() => {
  if (originalOffsetHeight) {
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', originalOffsetHeight);
  } else {
    Reflect.deleteProperty(HTMLElement.prototype, 'offsetHeight');
  }
});

beforeEach(() => {
  window.scrollTo = vi.fn();
  mockAuthState.isEnabled = true;
  mockAuthState.isAuthenticated = true;
  mockAuthState.isLoading = false;
  infiniteScrollOptions = null;
});

/** The 1px sentinel div the list mounts inside its Stack. */
const SENTINEL_SELECTOR = '.MuiStack-root > div[aria-hidden="true"][style*="height: 1px"]';

function createMockJobs(count: number, idPrefix = 'job'): Job[] {
  return Array.from({ length: count }, (_, i) => {
    const createdAt = new Date(Date.now() - i * 1000).toISOString();
    return {
      id: `${idPrefix}-${i}`,
      title: `Software Engineer ${i}`,
      // A REAL first-party id, not a synthetic one. `JobListingCard` resolves an
      // unrecognized id against the signed-in user's own boards, which needs the
      // userCompanies RTK Query slice in the store — a dependency this list test
      // has no reason to take on, and which production never hits here (the
      // Recent Jobs feed only fans out over `COMPANIES`).
      company: 'spacex',
      location: 'Remote',
      employmentType: 'Full-time',
      createdAt,
      firstSeenAt: createdAt,
      url: `https://example.com/${idPrefix}-${i}`,
      team: 'Backend',
      tags: [],
      isRemote: true,
      source: 'backend-scraper' as const,
      raw: {},
    };
  });
}

/**
 * A settled, empty, exhausted search: no rows, no next page, nothing in flight,
 * no error. Every test states only the fields whose values it is actually about.
 */
function makeSearch(overrides: Partial<RecentJobsSearch> = {}): RecentJobsSearch {
  const base: RecentJobsSearch = {
    jobs: [],
    counts: null,
    isInitialLoading: false,
    isRefreshing: false,
    isFetchingNextPage: false,
    hasNextPage: false,
    fetchNextPage: vi.fn(),
    error: null,
    errorScope: null,
    isAwaitingDeploy: false,
    retry: vi.fn(),
    isSkippedEmpty: false,
    displayedJobs: [],
    resultTotal: { kind: 'unknown' },
    ...overrides,
  };

  // `displayedJobs` and `resultTotal` are DERIVED by `useRecentJobsSearch`, never
  // stated by its callers, so the helper derives them the same way rather than
  // letting a test hand the list a combination the hook cannot produce. That
  // includes the signed-out cap, which moved into the hook because the header's
  // "Displayed Jobs" tile counts the same rows this list renders. A test may
  // still state either field explicitly to reach a state directly.
  const isSignedOut = mockAuthState.isEnabled && !mockAuthState.isAuthenticated;
  const displayedJobs =
    overrides.displayedJobs ??
    (isSignedOut ? base.jobs.slice(0, SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT) : base.jobs);

  return {
    ...base,
    displayedJobs,
    resultTotal:
      overrides.resultTotal ??
      resolveResultTotal(base.counts, displayedJobs.length, !isSignedOut && !base.hasNextPage),
  };
}

function renderList(overrides: Partial<RecentJobsSearch> = {}) {
  const search = makeSearch(overrides);
  const store = createTestStore();
  const result = render(
    <Provider store={store}>
      <RecentJobsList search={search} />
    </Provider>
  );

  return {
    ...result,
    search,
    /** Advance the search state (e.g. the walk finishing) and re-render. */
    update(next: Partial<RecentJobsSearch>) {
      Object.assign(search, next);
      result.rerender(
        <Provider store={store}>
          <RecentJobsList search={{ ...search }} />
        </Provider>
      );
    },
  };
}

/** Rows actually mounted in the DOM (both the virtualized and signed-out paths). */
function mountedRowCount() {
  return screen.queryAllByRole('listitem').length;
}

/**
 * Fire the infinite-scroll callback, but ONLY while the sentinel is genuinely in
 * the DOM.
 *
 * Load-bearing, not ceremony: `useInfiniteScroll` is mocked, so calling
 * `onLoadMore()` blind would simulate an intersection the browser can never
 * produce once the list has unmounted the sentinel — which is precisely the
 * broken state several tests below exist to detect. Routing every fire through
 * this helper means an unmounted sentinel yields zero fires and the assertion
 * fails, exactly as production would stall.
 */
async function fireSentinelWhileMounted(container: HTMLElement, maxFires: number) {
  let fires = 0;
  while (fires < maxFires && container.querySelector(SENTINEL_SELECTOR)) {
    await act(async () => {
      infiniteScrollOptions?.onLoadMore();
    });
    fires++;
  }
  return fires;
}

describe('RecentJobsList', () => {
  describe('paging', () => {
    it('asks for the next page when the sentinel fires and the walk has one', async () => {
      const { container, search } = renderList({
        jobs: createMockJobs(30),
        hasNextPage: true,
      });

      const fires = await fireSentinelWhileMounted(container, 1);

      expect(fires).toBe(1);
      expect(search.fetchNextPage).toHaveBeenCalledTimes(1);
    });

    it('does not fire a second time while a page is already in flight', async () => {
      const { container, search } = renderList({
        jobs: createMockJobs(30),
        hasNextPage: true,
        isFetchingNextPage: true,
      });

      // Two independent brakes, both asserted: the sentinel is unmounted (so no
      // intersection can occur) and the hook is told a load is in progress (so
      // even a mounted sentinel would not be observed).
      expect(container.querySelector(SENTINEL_SELECTOR)).not.toBeInTheDocument();
      expect(infiniteScrollOptions?.isLoadingMore).toBe(true);

      const fires = await fireSentinelWhileMounted(container, 5);

      expect(fires).toBe(0);
      expect(search.fetchNextPage).not.toHaveBeenCalled();
    });

    it('shows skeletons while the next page is in flight', () => {
      renderList({ jobs: createMockJobs(30), hasNextPage: true, isFetchingNextPage: true });

      expect(screen.getByLabelText('Loading more jobs')).toBeInTheDocument();
    });

    it('keeps the sentinel mounted at zero rows so an empty first page can still advance', async () => {
      // The 2026-08-10 shape in miniature: page 1 came back with no matches but
      // the walk holds another cursor. The machinery must stay mounted.
      const { container, search } = renderList({ jobs: [], hasNextPage: true });

      expect(container.querySelector(SENTINEL_SELECTOR)).toBeInTheDocument();
      const fires = await fireSentinelWhileMounted(container, 1);

      expect(fires).toBe(1);
      expect(search.fetchNextPage).toHaveBeenCalledTimes(1);
    });
  });

  /**
   * The 2026-08-10 regression, pinned clause by clause.
   *
   * `EmptyJobListState` is an EARLY RETURN: rendering it unmounts the sentinel,
   * which is the only thing that could ever disprove "no jobs found". So each of
   * the four conditions that suppress it gets its own test — a single combined
   * test would still pass if three of the four clauses were deleted.
   */
  describe('terminal empty state', () => {
    const EMPTY_TITLE = /No jobs found matching your filters/;

    it('renders only when the walk is exhausted, nothing is in flight, and there is no error', () => {
      renderList({ jobs: [] });

      expect(screen.getByText(EMPTY_TITLE)).toBeInTheDocument();
      expect(
        screen.getByText(/Try adjusting your filters or extending the time window/)
      ).toBeInTheDocument();
    });

    it('is suppressed while the walk still holds another page', () => {
      // More pages could hold every match; declaring "none" here is the bug.
      renderList({ jobs: [], hasNextPage: true });

      expect(screen.queryByText(EMPTY_TITLE)).not.toBeInTheDocument();
    });

    it('is suppressed while the first page is still loading', () => {
      // Nothing has come back yet, so "no jobs" is a claim about no evidence.
      renderList({ jobs: [], isInitialLoading: true });

      expect(screen.queryByText(EMPTY_TITLE)).not.toBeInTheDocument();
      expect(screen.getByLabelText('Loading more jobs')).toBeInTheDocument();
    });

    it('is suppressed while a filter change is refetching page one', () => {
      // Rows are about to arrive for the new filters; flashing the empty state
      // over the gap makes every filter edit look like it matched nothing.
      renderList({ jobs: [], isRefreshing: true });

      expect(screen.queryByText(EMPTY_TITLE)).not.toBeInTheDocument();
      expect(screen.getByLabelText('Loading more jobs')).toBeInTheDocument();
    });

    it('is suppressed while a next page is in flight', () => {
      renderList({ jobs: [], isFetchingNextPage: true });

      expect(screen.queryByText(EMPTY_TITLE)).not.toBeInTheDocument();
      expect(screen.getByLabelText('Loading more jobs')).toBeInTheDocument();
    });

    it('is suppressed when the search failed — a failure is not an empty result', () => {
      renderList({ jobs: [], error: 'Failed to load job postings. Please try again later.' });

      expect(screen.queryByText(EMPTY_TITLE)).not.toBeInTheDocument();
    });

    it('renders with no request at all when the filter set provably matches nothing', () => {
      // `isSkippedEmpty` is the one terminal case reached without asking the
      // server anything: the company filter and the user's enabled companies are
      // disjoint. Terminal, so the empty state is honest — and no fetch may fire.
      const { container, search } = renderList({ jobs: [], isSkippedEmpty: true });

      expect(screen.getByText(EMPTY_TITLE)).toBeInTheDocument();
      expect(container.querySelector(SENTINEL_SELECTOR)).not.toBeInTheDocument();
      expect(search.fetchNextPage).not.toHaveBeenCalled();
    });

    it('renders once a walk that started with pages outstanding runs dry', () => {
      const { update } = renderList({ jobs: [], hasNextPage: true });
      expect(screen.queryByText(EMPTY_TITLE)).not.toBeInTheDocument();

      update({ hasNextPage: false });

      expect(screen.getByText(EMPTY_TITLE)).toBeInTheDocument();
    });
  });

  describe('failed next page', () => {
    const ERROR_TEXT = 'Failed to load job postings. Please try again later.';

    function renderWithNextPageError() {
      return renderList({
        jobs: createMockJobs(30),
        hasNextPage: true,
        error: ERROR_TEXT,
        errorScope: 'nextPage',
      });
    }

    it('shows an inline retry without discarding the rows already loaded', () => {
      renderWithNextPageError();

      expect(screen.getByText(ERROR_TEXT)).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: EMPTY_STATE_MESSAGES.RETRY_NEXT_PAGE })
      ).toBeInTheDocument();
      // Losing the loaded rows would punish the reader for a transient blip.
      expect(mountedRowCount()).toBeGreaterThan(0);
    });

    it('re-runs the failed fetch when the retry is clicked', () => {
      const { search } = renderWithNextPageError();

      fireEvent.click(screen.getByRole('button', { name: EMPTY_STATE_MESSAGES.RETRY_NEXT_PAGE }));

      expect(search.retry).toHaveBeenCalledTimes(1);
    });

    it('drops the sentinel while the error is latched, instead of retrying forever', async () => {
      // With the sentinel mounted, a reader parked at the bottom would re-issue
      // the same failing request on every intersection, silently and forever.
      const { container, search } = renderWithNextPageError();

      expect(container.querySelector(SENTINEL_SELECTOR)).not.toBeInTheDocument();
      expect(infiniteScrollOptions?.hasMore).toBe(false);

      const fires = await fireSentinelWhileMounted(container, 5);

      expect(fires).toBe(0);
      expect(search.fetchNextPage).not.toHaveBeenCalled();
    });

    it('offers the retry even when no rows landed before the failure', () => {
      // The bare empty state here would strand the reader with no way forward.
      renderList({ jobs: [], hasNextPage: true, error: ERROR_TEXT, errorScope: 'nextPage' });

      expect(screen.queryByText(/No jobs found matching your filters/)).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: EMPTY_STATE_MESSAGES.RETRY_NEXT_PAGE })
      ).toBeInTheDocument();
    });
  });

  describe('end of list', () => {
    it('announces the loaded total only once the walk is truly exhausted', () => {
      const { update } = renderList({ jobs: createMockJobs(30), hasNextPage: true });

      expect(screen.queryByText(EMPTY_STATE_MESSAGES.ALL_LOADED(30))).not.toBeInTheDocument();

      update({ hasNextPage: false });

      expect(screen.getByText(EMPTY_STATE_MESSAGES.ALL_LOADED(30))).toBeInTheDocument();
    });

    it('withholds the total while a page is still in flight', () => {
      // `hasNextPage` can already be false while the final page is landing;
      // announcing a count then would name a number about to change.
      renderList({ jobs: createMockJobs(30), hasNextPage: false, isFetchingNextPage: true });

      expect(screen.queryByText(EMPTY_STATE_MESSAGES.ALL_LOADED(30))).not.toBeInTheDocument();
    });

    it('withholds the total when the walk ended on an error', () => {
      renderList({
        jobs: createMockJobs(30),
        error: 'Network unreachable',
        errorScope: 'nextPage',
      });

      expect(screen.queryByText(EMPTY_STATE_MESSAGES.ALL_LOADED(30))).not.toBeInTheDocument();
    });

    it('drops the sentinel at the end of the walk', () => {
      const { container } = renderList({ jobs: createMockJobs(30) });

      expect(container.querySelector(SENTINEL_SELECTOR)).not.toBeInTheDocument();
    });
  });

  describe('signed in', () => {
    it('renders rows through the virtualizer rather than mounting the whole list', () => {
      const jobs = createMockJobs(500);
      const { container } = renderList({
        jobs,
        counts: { total: 4137, last24h: 42, last3h: 7 },
      });

      const list = container.querySelector('[role="list"]');
      // `data-client-window` is published by VirtualJobRows alone — the
      // signed-out path renders a plain container without it.
      expect(list).toHaveAttribute('data-client-window', '500');
      expect(mountedRowCount()).toBeGreaterThan(0);
      expect(mountedRowCount()).toBeLessThanOrEqual(60);
      // a11y hears the SERVER's count of the filter set, not the 500 rows the
      // keyset walk happens to have fetched. Passing the loaded count made a
      // screen reader announce "item 20 of 500" a tenth of the way through a
      // 4,137-row result set, and "item 500 of 500" at a point that is not the
      // end of anything.
      expect(container.querySelector('[role="listitem"]')).toHaveAttribute('aria-setsize', '4137');
    });

    it('announces an unmeasured total as unknown, never as the rows in hand', () => {
      // `counts: null` is the hook saying "page 1 has not landed" (or that an
      // initial error nulled them — see the counts-on-error rule). -1 is ARIA's
      // own "total unknown"; 500 would be a claim nothing measured.
      const { container } = renderList({ jobs: createMockJobs(500), counts: null });

      expect(container.querySelector('[role="listitem"]')).toHaveAttribute('aria-setsize', '-1');
    });

    it('never announces fewer items than are already on screen', () => {
      // The corpus can gain matching rows between page 1 and page N, so a stale
      // `counts.total` can fall BELOW the rows walked. "item 51 of 30" is worse
      // than either number alone, so the announced set size floors at the rows
      // rendered.
      const { container } = renderList({
        jobs: createMockJobs(50),
        counts: { total: 30, last24h: 1, last3h: 0 },
      });

      expect(container.querySelector('[role="listitem"]')).toHaveAttribute('aria-setsize', '50');
    });

    it('renders the back-to-top affordance alongside the list', () => {
      const { container } = renderList({ jobs: createMockJobs(30) });

      expect(container.querySelector('.MuiFab-root')).toBeInTheDocument();
    });
  });

  describe('signed out', () => {
    beforeEach(() => {
      mockAuthState.isAuthenticated = false;
    });

    it('caps the list at the signed-out job limit', () => {
      renderList({ jobs: createMockJobs(200) });

      // Not virtualized on this path: a hard-capped dozen is already bounded, so
      // the cards render in full and the overlay's gradient meets a real bottom.
      expect(mountedRowCount()).toBe(SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT);
    });

    it('shows the sign-in overlay as soon as a job exists beyond the cap', () => {
      renderList({ jobs: createMockJobs(SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT + 1) });

      expect(screen.getByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: SIGN_IN_OVERLAY_MESSAGES.BUTTON_TEXT })
      ).toBeInTheDocument();
    });

    it('does not show the overlay when every job fits under the cap', () => {
      renderList({ jobs: createMockJobs(SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT) });

      expect(screen.queryByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).not.toBeInTheDocument();
    });

    it('never pages, even when the search reports another page waiting', async () => {
      const { container, search } = renderList({
        jobs: createMockJobs(200),
        hasNextPage: true,
      });

      expect(container.querySelector(SENTINEL_SELECTOR)).not.toBeInTheDocument();
      const fires = await fireSentinelWhileMounted(container, 5);

      expect(fires).toBe(0);
      expect(search.fetchNextPage).not.toHaveBeenCalled();
    });

    it('does not show the overlay when auth is disabled entirely', () => {
      mockAuthState.isEnabled = false;
      renderList({ jobs: createMockJobs(100) });

      expect(screen.queryByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).not.toBeInTheDocument();
    });
  });
});

describe('RecentJobsList — states the list must not be able to misread on its own', () => {
  it('does not claim "no jobs found" while a pending deploy is being retried', () => {
    // The page currently renders a spinner instead of this list during the
    // deploy-grace window, so in practice the list is never mounted in this
    // state. That is exactly why this test exists: the 2026-08-10 incident's
    // first lesson is that a terminal state must be terminal by the component's
    // OWN conditions, not because some caller happened to guard it. If the page
    // ever stops guarding, this must not silently become "No jobs found".
    renderList({
      jobs: [],
      isAwaitingDeploy: true,
      hasNextPage: false,
      isInitialLoading: false,
      isRefreshing: false,
      isFetchingNextPage: false,
      error: null,
    });

    expect(screen.queryByText(EMPTY_STATE_MESSAGES.NO_JOBS_TITLE)).not.toBeInTheDocument();
  });

  it('does not tell a signed-out reader the corpus is exhausted at the cap', () => {
    // Signed out the hook forces hasNextPage false and fetches one row MORE than
    // the visible cap (the extra row is how the overlay decides to render), so a
    // naive end-of-list check announces "All 13 jobs loaded" over twelve cards
    // and thousands of unseen jobs. Capped is not finished.
    mockAuthState.isAuthenticated = false;
    renderList({ jobs: createMockJobs(13), hasNextPage: false });

    expect(screen.queryByText(/All 13 jobs loaded/)).not.toBeInTheDocument();
    expect(screen.queryByText(/jobs loaded/)).not.toBeInTheDocument();
  });
});
