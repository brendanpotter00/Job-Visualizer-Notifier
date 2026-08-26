import { describe, it, expect, vi, beforeEach, beforeAll, afterAll } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { RecentJobsList } from '../../../../components/recent-jobs-page/RecentJobsList/RecentJobsList';
import {
  INFINITE_SCROLL_CONFIG,
  SIGN_IN_OVERLAY_CONFIG,
  VIRTUAL_LIST_CONFIG,
} from '../../../../constants/ui';
import { SIGN_IN_OVERLAY_MESSAGES, EMPTY_STATE_MESSAGES } from '../../../../constants/messages';
import type { Job } from '../../../../types';
import * as recentJobsSelectors from '../../../../features/filters/selectors/recentJobsSelectors';
import * as filterSignature from '../../../../features/filters/selectors/recentJobsFilterSignature';
import type { UseInfiniteScrollOptions } from '../../../../hooks/useInfiniteScroll';

// Capture the options the list hands the infinite-scroll hook so tests can
// drive the sentinel directly instead of faking an IntersectionObserver.
let infiniteScrollOptions: UseInfiniteScrollOptions | null = null;
vi.mock('../../../../hooks/useInfiniteScroll', () => ({
  useInfiniteScroll: (options: UseInfiniteScrollOptions) => {
    infiniteScrollOptions = options;
    return { sentinelRef: { current: null } };
  },
}));

// The keyset walk is exercised against the real store in
// `useRecentJobsPaging.test.tsx`; here it is a controllable stub so the list's
// own client-window logic can be tested in isolation.
const mockPaging = {
  hasMoreServer: false,
  isFetchingNextPage: false,
  error: null as string | null,
  loadNextServerPage: vi.fn(),
  retryServerPage: vi.fn(),
};
vi.mock('../../../../components/recent-jobs-page/RecentJobsList/useRecentJobsPaging', () => ({
  useRecentJobsPaging: () => mockPaging,
}));

// Mock the selectors
vi.mock('../../../../features/filters/selectors/recentJobsSelectors');
vi.mock('../../../../features/filters/selectors/recentJobsFilterSignature');

// Mock useAuth - default to authenticated so existing tests pass unchanged.
// Signed-out tests below override mockAuthState before rendering.
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

// Reset auth mock and window.scrollTo before each test
beforeEach(() => {
  window.scrollTo = vi.fn();
  mockAuthState.isEnabled = true;
  mockAuthState.isAuthenticated = true;
  mockAuthState.isLoading = false;
  mockPaging.hasMoreServer = false;
  mockPaging.isFetchingNextPage = false;
  mockPaging.error = null;
  mockPaging.loadNextServerPage = vi.fn();
  mockPaging.retryServerPage = vi.fn();
  infiniteScrollOptions = null;
  scrollWindowTo(0);
  vi.mocked(filterSignature.selectRecentJobsFilterSignature).mockReturnValue('signature-a');
});

/** Move the document scroll and let the window virtualizer observe it. */
function scrollWindowTo(scrollY: number) {
  Object.defineProperty(window, 'scrollY', { configurable: true, value: scrollY });
  window.dispatchEvent(new Event('scroll'));
}

// Helper to create mock jobs
function createMockJobs(count: number, idPrefix = 'job'): Job[] {
  return Array.from({ length: count }, (_, i) => {
    const createdAt = new Date(Date.now() - i * 1000).toISOString();
    return {
      id: `${idPrefix}-${i}`,
      title: `Software Engineer ${i}`,
      company: 'test-company',
      location: 'Remote',
      employmentType: 'Full-time',
      createdAt,
      firstSeenAt: createdAt,
      url: `https://example.com/${idPrefix}-${i}`,
      department: 'Engineering',
      team: 'Backend',
      tags: [],
      isRemote: true,
      source: 'backend-scraper' as const,
      raw: {},
    };
  });
}

// Helper to create mock store
function createMockStore() {
  return configureStore({
    reducer: {
      recentJobsFilters: () => ({
        timeWindow: '24h',
        searchTags: [],
        location: [],
        employmentType: undefined,
        softwareOnly: false,
        company: [],
      }),
    },
    preloadedState: {},
  });
}

function renderList() {
  const store = createMockStore();
  return render(
    <Provider store={store}>
      <RecentJobsList />
    </Provider>
  );
}

/** Number of JobListingCards actually mounted in the DOM. */
function mountedCardCount() {
  return screen.queryAllByText(/Software Engineer/).length;
}

/**
 * How many jobs the client window is currently willing to show. Published on
 * the list container, so it is observable even though only a fraction of the
 * window is mounted. (`aria-setsize` deliberately reports the FULL list length
 * instead — see the a11y test below.)
 */
function clientWindowSize(container: HTMLElement) {
  const list = container.querySelector('[role="list"]');
  return list ? Number(list.getAttribute('data-client-window')) : 0;
}

/** Fire the infinite-scroll sentinel and flush the batch-reveal timeout. */
async function triggerLoadMore() {
  await act(async () => {
    infiniteScrollOptions?.onLoadMore();
    await new Promise((resolve) => setTimeout(resolve, 5));
  });
}

describe('RecentJobsList', () => {
  // Boundedness against the FULL array is VirtualJobRows' own contract and is
  // tested there (VirtualJobRows.test.tsx) — asserting it here against a
  // pre-sliced 50-row window would pass no matter what the component did.
  // What belongs here is that the list stays bounded as its own window GROWS.
  it('keeps the mounted card count bounded as the client window grows past a screenful', async () => {
    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(5000));
    const { container } = renderList();

    for (let i = 0; i < 8; i++) await triggerLoadMore();

    // The window has grown well past what fits on screen...
    expect(clientWindowSize(container)).toBeGreaterThan(200);
    // ...but the mounted count has not followed it.
    expect(mountedCardCount()).toBeGreaterThan(0);
    expect(mountedCardCount()).toBeLessThanOrEqual(60);
  });

  it('keeps the mounted card count bounded when scrolled deep into the list', async () => {
    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(5000));
    renderList();

    // Grow the client window well past a screenful, then jump to the bottom.
    for (let i = 0; i < 6; i++) await triggerLoadMore();

    await act(async () => {
      scrollWindowTo(150 * MOCK_CARD_HEIGHT);
    });

    expect(mountedCardCount()).toBeGreaterThan(0);
    expect(mountedCardCount()).toBeLessThanOrEqual(60);
  });

  it('advertises the full list length to assistive tech, not the client window', () => {
    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(100));
    const { container } = renderList();

    expect(container.querySelector('[role="list"]')).toBeInTheDocument();
    // The reveal window is 50 of 100 — screen readers hear 100.
    expect(clientWindowSize(container)).toBe(INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE);
    const firstRow = container.querySelector('[role="listitem"]');
    expect(firstRow).toHaveAttribute('aria-setsize', '100');
    expect(firstRow).toHaveAttribute('aria-posinset', '1');
  });

  it('shows empty state when no jobs AND the walk is exhausted', () => {
    // hasMoreServer is false (beforeEach default): nothing left to fetch, so
    // "no jobs found" is honest and terminal.
    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue([]);

    renderList();

    expect(screen.getByText(/No jobs found matching your filters/)).toBeInTheDocument();
    expect(
      screen.getByText(/Try adjusting your filters or extending the time window/)
    ).toBeInTheDocument();
  });

  it('renders all jobs when count is less than initial batch size', () => {
    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(25));

    const { container } = renderList();

    expect(clientWindowSize(container)).toBe(25);
    expect(screen.getByText('Software Engineer 0')).toBeInTheDocument();
  });

  it('renders BackToTopButton', () => {
    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(100));

    const { container } = renderList();

    // Check that BackToTopButton renders by looking for the FAB
    expect(container.querySelector('.MuiFab-root')).toBeInTheDocument();
  });

  it('does not show sentinel when all jobs are displayed and the walk is finished', () => {
    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(30));

    const { container } = renderList();

    const sentinelInStack = container.querySelector(
      '.MuiStack-root > div[aria-hidden="true"][style*="height: 1px"]'
    );
    expect(sentinelInStack).not.toBeInTheDocument();
  });

  it('keeps the sentinel while the server walk still has cursors, even with every loaded job shown', () => {
    mockPaging.hasMoreServer = true;
    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(30));

    const { container } = renderList();

    const sentinelInStack = container.querySelector(
      '.MuiStack-root > div[aria-hidden="true"][style*="height: 1px"]'
    );
    expect(sentinelInStack).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('shows the ALL_LOADED message only at the true end of the list', async () => {
    const jobs = createMockJobs(60);
    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(jobs);
    mockPaging.hasMoreServer = true;

    const { rerender } = renderList();

    // Client window not exhausted AND cursors outstanding -> no message.
    expect(screen.queryByText(EMPTY_STATE_MESSAGES.ALL_LOADED(60))).not.toBeInTheDocument();

    // Reveal the rest of the loaded rows: still no message, cursors remain.
    await triggerLoadMore();
    expect(screen.queryByText(EMPTY_STATE_MESSAGES.ALL_LOADED(60))).not.toBeInTheDocument();

    // Cursors exhausted as well -> true end of the list.
    mockPaging.hasMoreServer = false;
    const store = createMockStore();
    rerender(
      <Provider store={store}>
        <RecentJobsList />
      </Provider>
    );

    expect(screen.getByText(EMPTY_STATE_MESSAGES.ALL_LOADED(60))).toBeInTheDocument();
  });

  it('does not scroll to top when jobs change (filter change)', () => {
    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(100));

    const { rerender } = renderList();
    vi.mocked(window.scrollTo).mockClear();

    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(50));
    const store = createMockStore();
    rerender(
      <Provider store={store}>
        <RecentJobsList />
      </Provider>
    );

    // Verify scroll was NOT called - user stays at current position
    expect(window.scrollTo).not.toHaveBeenCalled();
  });

  it('renders job cards with correct props', () => {
    vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(5));

    renderList();

    expect(screen.getByText('Software Engineer 0')).toBeInTheDocument();
    expect(screen.getAllByText('Remote').length).toBeGreaterThan(0);
  });

  describe('client window reset', () => {
    it('resets to the initial batch when the filters change, even if the result count is identical', async () => {
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(200));
      const { container, rerender } = renderList();

      await triggerLoadMore();
      const grown =
        INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE + INFINITE_SCROLL_CONFIG.SUBSEQUENT_BATCH_SIZE;
      expect(clientWindowSize(container)).toBe(grown);

      // Same length, different filter: a different set of 200 jobs.
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(
        createMockJobs(200, 'other')
      );
      vi.mocked(filterSignature.selectRecentJobsFilterSignature).mockReturnValue('signature-b');
      const store = createMockStore();
      rerender(
        <Provider store={store}>
          <RecentJobsList />
        </Provider>
      );

      expect(clientWindowSize(container)).toBe(INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE);
    });

    it('does NOT reset when a data tick changes the job count under an unchanged filter', async () => {
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(200));
      const { container, rerender } = renderList();

      await triggerLoadMore();
      const grown =
        INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE + INFINITE_SCROLL_CONFIG.SUBSEQUENT_BATCH_SIZE;
      expect(clientWindowSize(container)).toBe(grown);

      // A scrape tick / appended page: more jobs, same filter signature.
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(260));
      const store = createMockStore();
      rerender(
        <Provider store={store}>
          <RecentJobsList />
        </Provider>
      );

      expect(clientWindowSize(container)).toBe(grown);
    });
  });

  describe('incremental server loading', () => {
    it('reveals already-loaded rows before touching the network', async () => {
      mockPaging.hasMoreServer = true;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(200));

      const { container } = renderList();
      await triggerLoadMore();

      expect(mockPaging.loadNextServerPage).not.toHaveBeenCalled();
      expect(clientWindowSize(container)).toBe(
        INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE + INFINITE_SCROLL_CONFIG.SUBSEQUENT_BATCH_SIZE
      );
    });

    it('dispatches the next page once the client window has shown every loaded row', async () => {
      mockPaging.hasMoreServer = true;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(30));

      renderList();
      await triggerLoadMore();

      expect(mockPaging.loadNextServerPage).toHaveBeenCalledTimes(1);
    });

    it('does not dispatch a second page while one is in flight', async () => {
      mockPaging.hasMoreServer = true;
      mockPaging.isFetchingNextPage = true;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(30));

      renderList();
      await triggerLoadMore();
      await triggerLoadMore();

      expect(mockPaging.loadNextServerPage).not.toHaveBeenCalled();
    });

    it('shows the loading affordance while a page (or a window widening) is in flight', () => {
      mockPaging.hasMoreServer = true;
      mockPaging.isFetchingNextPage = true;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(30));

      renderList();

      expect(screen.getByLabelText('Loading more jobs')).toBeInTheDocument();
    });

    it('shows skeletons instead of the empty state while a widening walk restarts', () => {
      mockPaging.isFetchingNextPage = true;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue([]);

      renderList();

      expect(screen.queryByText(/No jobs found matching your filters/)).not.toBeInTheDocument();
      expect(screen.getByLabelText('Loading more jobs')).toBeInTheDocument();
    });

    it('survives the visible list SHRINKING when a widening restart re-clamps', async () => {
      // Widening clears cursors/floors (clamp drops, list grows), then the
      // restarted pages land and a tighter horizon re-applies (list shrinks).
      mockPaging.hasMoreServer = true;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(400));
      const { container, rerender } = renderList();

      await triggerLoadMore();
      expect(clientWindowSize(container)).toBeGreaterThan(
        INFINITE_SCROLL_CONFIG.INITIAL_BATCH_SIZE
      );

      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(12));
      const store = createMockStore();
      expect(() =>
        rerender(
          <Provider store={store}>
            <RecentJobsList />
          </Provider>
        )
      ).not.toThrow();

      // Window follows the shrunken list; no ghost rows left behind.
      expect(clientWindowSize(container)).toBe(12);
      expect(mountedCardCount()).toBeGreaterThan(0);
      expect(mountedCardCount()).toBeLessThanOrEqual(12);
    });
  });

  describe('bounded auto-fetching', () => {
    // A filter matching nothing in the older pages: every fetch leaves the
    // visible list unchanged, so the sentinel never leaves the viewport.
    function renderWithNoVisibleProgress() {
      mockPaging.hasMoreServer = true;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(30));
      return renderList();
    }

    it('stops auto-fetching after MAX_EMPTY_AUTO_FETCHES pages that add no visible row', async () => {
      renderWithNoVisibleProgress();

      // Far more scroll triggers than the cap allows.
      for (let i = 0; i < 10; i++) await triggerLoadMore();

      expect(mockPaging.loadNextServerPage).toHaveBeenCalledTimes(
        VIRTUAL_LIST_CONFIG.MAX_EMPTY_AUTO_FETCHES
      );
    });

    it('offers an explicit continue affordance once it stops, and drops the sentinel', async () => {
      const { container } = renderWithNoVisibleProgress();

      for (let i = 0; i < 10; i++) await triggerLoadMore();

      expect(
        screen.getByText(EMPTY_STATE_MESSAGES.NO_MATCHES_IN_RECENT_PAGES)
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: EMPTY_STATE_MESSAGES.SEARCH_OLDER_JOBS })
      ).toBeInTheDocument();
      expect(
        container.querySelector('.MuiStack-root > div[aria-hidden="true"][style*="height: 1px"]')
      ).not.toBeInTheDocument();
      // Not the end of the list — that message would be a lie here.
      expect(screen.queryByText(EMPTY_STATE_MESSAGES.ALL_LOADED(30))).not.toBeInTheDocument();
    });

    it('resumes on a manual continue and re-arms the automatic budget', async () => {
      const { container } = renderWithNoVisibleProgress();
      for (let i = 0; i < 10; i++) await triggerLoadMore();

      await act(async () => {
        fireEvent.click(
          screen.getByRole('button', { name: EMPTY_STATE_MESSAGES.SEARCH_OLDER_JOBS })
        );
      });

      expect(mockPaging.retryServerPage).toHaveBeenCalledTimes(1);
      // The sentinel is back, so scrolling works again.
      expect(
        container.querySelector('.MuiStack-root > div[aria-hidden="true"][style*="height: 1px"]')
      ).toBeInTheDocument();
    });

    it('resets the budget when the filters change', async () => {
      renderWithNoVisibleProgress();
      for (let i = 0; i < 10; i++) await triggerLoadMore();
      expect(mockPaging.loadNextServerPage).toHaveBeenCalledTimes(
        VIRTUAL_LIST_CONFIG.MAX_EMPTY_AUTO_FETCHES
      );

      vi.mocked(filterSignature.selectRecentJobsFilterSignature).mockReturnValue('signature-b');
      const store = createMockStore();
      render(
        <Provider store={store}>
          <RecentJobsList />
        </Provider>
      );
      await triggerLoadMore();

      expect(mockPaging.loadNextServerPage).toHaveBeenCalledTimes(
        VIRTUAL_LIST_CONFIG.MAX_EMPTY_AUTO_FETCHES + 1
      );
    });

    it('keeps auto-fetching while each page DOES add visible rows', async () => {
      mockPaging.hasMoreServer = true;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(5000));

      renderList();
      // Every trigger reveals loaded rows, so the empty-streak never builds.
      for (let i = 0; i < 10; i++) await triggerLoadMore();

      expect(mockPaging.loadNextServerPage).not.toHaveBeenCalled();
      expect(
        screen.queryByRole('button', { name: EMPTY_STATE_MESSAGES.SEARCH_OLDER_JOBS })
      ).not.toBeInTheDocument();
    });
  });

  describe('empty filter with pages still outstanding (2026-08-10 deadlock)', () => {
    // The incident: page 1 matched nothing, the terminal empty state rendered,
    // and its early return unmounted the sentinel — the only thing that can
    // advance the walk. 116 matching jobs sat one page deeper, permanently
    // unreachable. These tests pin the machinery staying mounted at zero rows.
    //
    // Load-bearing harness rule: `useInfiniteScroll` is mocked, so
    // `triggerLoadMore()` could simulate fires the browser can never produce
    // when the sentinel is unmounted — which is exactly the pre-fix state.
    // Every fire below therefore goes through `fireSentinelWhileMounted`,
    // which fires ONLY while the sentinel is genuinely in the DOM; on the
    // pre-fix component it fires zero times and these tests fail.
    const SENTINEL_SELECTOR =
      '.MuiStack-root > div[aria-hidden="true"][style*="height: 1px"]';

    function renderEmptyWithMorePages() {
      mockPaging.hasMoreServer = true;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue([]);
      return renderList();
    }

    /** Fire the sentinel repeatedly, but only while it is actually mounted. */
    async function fireSentinelWhileMounted(container: HTMLElement, maxFires: number) {
      let fires = 0;
      while (fires < maxFires && container.querySelector(SENTINEL_SELECTOR)) {
        await triggerLoadMore();
        fires++;
      }
      return fires;
    }

    it('does NOT show the terminal empty state while the walk has more pages', () => {
      renderEmptyWithMorePages();

      expect(screen.queryByText(/No jobs found matching your filters/)).not.toBeInTheDocument();
      expect(
        screen.getByText(EMPTY_STATE_MESSAGES.SEARCHING_OLDER_JOBS_IN_PROGRESS)
      ).toBeInTheDocument();
    });

    it('keeps the sentinel mounted at zero rows so the walk can advance', () => {
      const { container } = renderEmptyWithMorePages();

      expect(container.querySelector(SENTINEL_SELECTOR)).toBeInTheDocument();
    });

    it('advances the walk from the sentinel with zero visible rows', async () => {
      const { container } = renderEmptyWithMorePages();

      const fires = await fireSentinelWhileMounted(container, 1);

      expect(fires).toBe(1);
      expect(mockPaging.loadNextServerPage).toHaveBeenCalledTimes(1);
    });

    it('spends the auto-fetch budget then offers the continue affordance, never the empty state', async () => {
      const { container } = renderEmptyWithMorePages();

      // Unbounded upper limit; the component's own budget must stop the loop
      // by unmounting the sentinel after MAX_EMPTY_AUTO_FETCHES fires.
      const fires = await fireSentinelWhileMounted(container, 10);

      expect(fires).toBe(VIRTUAL_LIST_CONFIG.MAX_EMPTY_AUTO_FETCHES);
      expect(mockPaging.loadNextServerPage).toHaveBeenCalledTimes(
        VIRTUAL_LIST_CONFIG.MAX_EMPTY_AUTO_FETCHES
      );
      expect(
        screen.getByText(EMPTY_STATE_MESSAGES.NO_MATCHES_IN_RECENT_PAGES)
      ).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: EMPTY_STATE_MESSAGES.SEARCH_OLDER_JOBS })
      ).toBeInTheDocument();
      expect(screen.queryByText(/No jobs found matching your filters/)).not.toBeInTheDocument();
      // The in-progress line yields to the stopped-short message.
      expect(
        screen.queryByText(EMPTY_STATE_MESSAGES.SEARCHING_OLDER_JOBS_IN_PROGRESS)
      ).not.toBeInTheDocument();
    });

    it('shows the terminal empty state once the walk exhausts with still no matches', () => {
      const { rerender } = renderEmptyWithMorePages();

      mockPaging.hasMoreServer = false;
      const store = createMockStore();
      rerender(
        <Provider store={store}>
          <RecentJobsList />
        </Provider>
      );

      expect(screen.getByText(/No jobs found matching your filters/)).toBeInTheDocument();
    });

    it('never mounts the sentinel or the searching line at zero rows when signed out', () => {
      mockAuthState.isAuthenticated = false;
      const { container } = renderEmptyWithMorePages();

      expect(container.querySelector(SENTINEL_SELECTOR)).not.toBeInTheDocument();
      // The searching line claims the walk is deepening; signed-out users
      // never page, so it must not render for them either.
      expect(
        screen.queryByText(EMPTY_STATE_MESSAGES.SEARCHING_OLDER_JOBS_IN_PROGRESS)
      ).not.toBeInTheDocument();
    });
  });

  describe('failed page fetches', () => {
    it('stops auto-fetching and surfaces the error instead of retrying forever', async () => {
      mockPaging.hasMoreServer = true;
      mockPaging.error = 'Failed to load job postings. Please try again later.';
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(30));

      const { container } = renderList();
      for (let i = 0; i < 10; i++) await triggerLoadMore();

      expect(mockPaging.loadNextServerPage).not.toHaveBeenCalled();
      expect(screen.getByText(mockPaging.error)).toBeInTheDocument();
      expect(
        container.querySelector('.MuiStack-root > div[aria-hidden="true"][style*="height: 1px"]')
      ).not.toBeInTheDocument();
    });

    it('offers a retry that dispatches exactly one more fetch', async () => {
      mockPaging.hasMoreServer = true;
      mockPaging.error = 'Network unreachable';
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(30));

      renderList();

      await act(async () => {
        fireEvent.click(
          screen.getByRole('button', { name: EMPTY_STATE_MESSAGES.RETRY_OLDER_JOBS })
        );
      });

      expect(mockPaging.retryServerPage).toHaveBeenCalledTimes(1);
    });

    it('offers the retry even when the filter matches nothing at all', () => {
      mockPaging.hasMoreServer = true;
      mockPaging.error = 'Network unreachable';
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue([]);

      renderList();

      // The bare empty state would strand the user with no way to continue.
      expect(screen.queryByText(/No jobs found matching your filters/)).not.toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: EMPTY_STATE_MESSAGES.RETRY_OLDER_JOBS })
      ).toBeInTheDocument();
    });
  });

  describe('signed-out behavior', () => {
    beforeEach(() => {
      mockAuthState.isAuthenticated = false;
    });

    it('shows the SignInOverlay when signed out and more jobs are available', () => {
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(100));

      renderList();

      expect(screen.getByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).toBeInTheDocument();
      expect(
        screen.getByRole('button', { name: SIGN_IN_OVERLAY_MESSAGES.BUTTON_TEXT })
      ).toBeInTheDocument();
    });

    it('does not show the SignInOverlay when all jobs fit under the signed-out cap', () => {
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(
        createMockJobs(SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT)
      );

      renderList();

      expect(screen.queryByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).not.toBeInTheDocument();
    });

    it('does not render the infinite-scroll sentinel when signed out', () => {
      mockPaging.hasMoreServer = true;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(100));

      const { container } = renderList();

      // Sentinel is a 1px div inside the Stack with aria-hidden="true".
      // Filter out any overlay elements that also use aria-hidden.
      const sentinelInStack = container.querySelector(
        '.MuiStack-root > div[aria-hidden="true"][style*="height: 1px"]'
      );
      expect(sentinelInStack).not.toBeInTheDocument();
    });

    it('caps rendered jobs at the signed-out job limit when signed out', () => {
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(200));

      renderList();

      // Not virtualized on this path: the capped dozen render in full.
      expect(mountedCardCount()).toBe(SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT);
    });

    it('never advances the server walk when signed out', async () => {
      mockPaging.hasMoreServer = true;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(200));

      renderList();
      await triggerLoadMore();

      expect(mockPaging.loadNextServerPage).not.toHaveBeenCalled();
    });

    it('does not show the SignInOverlay when auth is disabled', () => {
      mockAuthState.isEnabled = false;
      vi.mocked(recentJobsSelectors.selectRecentJobsSorted).mockReturnValue(createMockJobs(100));

      renderList();

      expect(screen.queryByText(SIGN_IN_OVERLAY_MESSAGES.TITLE)).not.toBeInTheDocument();
    });
  });
});
