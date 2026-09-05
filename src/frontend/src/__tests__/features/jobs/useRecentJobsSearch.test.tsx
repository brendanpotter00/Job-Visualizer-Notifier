import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { ReactNode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { Provider } from 'react-redux';

import { useRecentJobsSearch } from '../../../features/jobs/hooks/useRecentJobsSearch';
import {
  RECENT_SEARCH_PAGE_SIZE,
  SIGNED_OUT_FETCH_LIMIT,
} from '../../../features/jobs/searchJobsArgs';
import {
  setRecentJobsCategory,
  setRecentJobsTimeWindow,
} from '../../../features/filters/slices/recentJobsFiltersSlice';
import { saveEnabledCompanies } from '../../../features/preferences/enabledCompaniesSlice';
import { createTestStore } from '../../../test/testUtils';
import type { BackendJobListing } from '../../../api/types';
import type { RecentJobsFilters } from '../../../types';
import { ERROR_MESSAGES } from '../../../constants/messages';
import { SIGN_IN_OVERLAY_CONFIG } from '../../../constants/ui';

// `useAuth` is the seam that tells the hook whether it may fetch at all, so it
// is a mutable object rather than a per-test factory: several cases flip
// `isLoading` mid-render to reproduce "auth has not resolved yet".
const mockAuthState = {
  isEnabled: true,
  isAuthenticated: true,
  isLoading: false,
  user: null,
  login: vi.fn(),
  logout: vi.fn(),
  getToken: vi.fn(),
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
  NotAuthenticatedError: class NotAuthenticatedError extends Error {},
}));

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

const BASE_FILTERS: RecentJobsFilters = {
  timeWindow: '90d',
  searchTags: undefined,
  location: undefined,
  employmentType: undefined,
  softwareOnly: false,
  company: undefined,
  category: undefined,
  level: undefined,
};

function makeRow(id: string, company = 'google'): BackendJobListing {
  const firstSeenAt = new Date(Date.now() - HOUR_MS).toISOString();
  return {
    id,
    title: `Software Engineer ${id}`,
    company,
    location: 'Remote',
    locations: [],
    url: `https://example.com/${id}`,
    sourceId: 'greenhouse',
    details: '{}',
    createdAt: firstSeenAt,
    postedOn: firstSeenAt,
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt,
    lastSeenAt: firstSeenAt,
    consecutiveMisses: 0,
    detailsScraped: true,
  };
}

/**
 * A well-formed page-1 envelope (page 1 is the only page that carries `meta`).
 *
 * `filteredTotal` defaults to a number, but PRODUCTION sends `null` — #277 moved
 * the exact count off the page-1 critical path — so the cases about the header
 * figures pass `null` explicitly. The two recency counts are still exact.
 */
function page(
  ids: string[],
  nextCursor: string | null,
  withMeta = false,
  filteredTotal: number | null = 137
) {
  return {
    jobs: ids.map((id) => makeRow(id)),
    nextCursor,
    meta: withMeta ? { filteredTotal, countLast24h: 42, countLast3h: 7 } : null,
  };
}

interface MockResponse {
  status?: number;
  body?: unknown;
}

/**
 * URL-aware fetch double. Throws on anything that is not the search endpoint so
 * a stray request (the exact regression the demo-mode case exists to catch)
 * fails the test loudly instead of quietly returning `undefined`.
 */
function makeFetchMock(
  respond: (params: URLSearchParams, callIndex: number) => MockResponse | Promise<MockResponse>
) {
  let callIndex = 0;
  return vi.fn(async (input: unknown) => {
    const url = String(input);
    if (!url.startsWith('/api/jobs/search?')) {
      throw new Error(`unexpected fetch URL in useRecentJobsSearch test: ${url}`);
    }
    const params = new URLSearchParams(url.slice(url.indexOf('?') + 1));
    const { status = 200, body } = await respond(params, callIndex++);
    return {
      ok: status < 400,
      status,
      statusText: String(status),
      headers: new Headers(),
      json: async () => body,
      // A real `Response` serves both off one stream; the error path reads the
      // body with `text()` so it can log the payload verbatim.
      text: async () => (body === undefined ? '' : JSON.stringify(body)),
    } as unknown as Response;
  });
}

const paramsOf = (url: unknown) =>
  new URLSearchParams(String(url).slice(String(url).indexOf('?') + 1));

interface StoreOptions {
  filters?: Partial<RecentJobsFilters>;
  enabledCompanyIds?: string[] | null;
  demoModeEnabled?: boolean;
}

function makeStore({
  filters = {},
  enabledCompanyIds = [],
  demoModeEnabled = false,
}: StoreOptions = {}) {
  return createTestStore({
    recentJobsFilters: {
      filters: { ...BASE_FILTERS, ...filters },
      hydrated: true,
      userModified: false,
    },
    enabledCompanies: {
      ids: enabledCompanyIds,
      autoEnroll: false,
      loading: false,
      error: null,
      activeLoadRequestId: null,
    },
    ui: {
      graphModal: { open: false },
      globalLoading: false,
      notifications: [],
      hideAdminFeatures: false,
      demoModeEnabled,
    },
    locationCatalog: { byName: {} },
  });
}

function renderSearch(store: ReturnType<typeof createTestStore>) {
  return renderHook(() => useRecentJobsSearch(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    ),
  });
}

/**
 * One animation frame, in ms.
 *
 * `configureStore` installs RTK's `autoBatchEnhancer`, which defers the store
 * notification for every RTK Query action to the next `requestAnimationFrame`.
 * A resolved page is therefore in the store but invisible to React until the
 * clock crosses a frame — so every flush advances one past whatever the test
 * asked for. Without this the hook simply never leaves `pending`.
 */
const FRAME_MS = 50;

/**
 * Advance the (fake) clock and let the query chain settle into a committed
 * render. One `act` per flush, so a debounce timer's state update and the RTK
 * Query result land in the same batch — the way a browser batches two
 * `setTimeout`s that come due together.
 */
async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms + FRAME_MS);
  });
}

let fetchMock: ReturnType<typeof makeFetchMock>;

/**
 * Restored in `afterEach`. A replaced global outlives the file otherwise, so
 * whichever test file the runner happens to schedule next in this worker
 * inherits this mock — a cross-file coupling that shows up as an unrelated
 * failure and depends on file order. `jobsApi.search.test.ts` gets this right.
 */
const originalFetch = globalThis.fetch;

function install(
  respond: (params: URLSearchParams, callIndex: number) => MockResponse | Promise<MockResponse>
) {
  fetchMock = makeFetchMock(respond);
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

beforeEach(() => {
  vi.useFakeTimers();
  mockAuthState.isEnabled = true;
  mockAuthState.isAuthenticated = true;
  mockAuthState.isLoading = false;
  install(() => ({ body: page([], null, true) }));
});

afterEach(() => {
  vi.useRealTimers();
  globalThis.fetch = originalFetch;
  vi.resetAllMocks();
});

describe('useRecentJobsSearch — when it is allowed to fetch', () => {
  it('serves the curated demo fixture without issuing a single request', async () => {
    // Regression: the old page kept the real query subscribed underneath demo
    // mode, so every scroll fired a page nobody would ever read. Demo mode must
    // be network-silent, not merely network-ignored.
    const store = makeStore({ demoModeEnabled: true });
    const { result } = renderSearch(store);
    await flush();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.jobs.length).toBeGreaterThan(0);
    expect(result.current.jobs.every((job) => job.id.startsWith('demo-'))).toBe(true);
    expect(result.current.counts?.total).toBe(result.current.jobs.length);
    // Nothing is in flight and nothing can be paged, so the list must not render
    // skeletons or a "load more" sentinel over a fixture that is already whole.
    expect(result.current.isInitialLoading).toBe(false);
    expect(result.current.hasNextPage).toBe(false);
    expect(result.current.isSkippedEmpty).toBe(false);
  });

  it('scopes the demo recency tiles to the companies in play, like the server does', async () => {
    // The server's two recency counts honour `company` and nothing else (see
    // `_header_counts_where`, Ledger #3). Demo mode counted the WHOLE fixture, so
    // narrowing to one company left the tiles frozen at the corpus-wide number
    // while the rows below shrank — the same inflation the server-side count was
    // re-scoped to remove, reintroduced on the one path with no request to check.
    const wide = renderSearch(makeStore({ demoModeEnabled: true }));
    await flush();
    const wideCounts = wide.result.current.counts;

    const scoped = renderSearch(
      makeStore({ demoModeEnabled: true, filters: { company: ['google'] } })
    );
    await flush();
    const scopedCounts = scoped.result.current.counts;

    // Precondition: the fixture actually has recent google rows AND recent rows
    // elsewhere, or "scoped is smaller" would be vacuous.
    expect(wideCounts?.last24h).toBeGreaterThan(0);
    expect(scopedCounts?.last24h).toBeGreaterThan(0);
    expect(scopedCounts?.last24h).toBeLessThan(wideCounts?.last24h as number);
    expect(scopedCounts?.last3h).toBeLessThanOrEqual(wideCounts?.last3h as number);
    // ...and the tiles agree with the rows they sit above.
    expect(scoped.result.current.jobs.every((job) => job.company === 'google')).toBe(true);
  });

  it("waits for auth to resolve and for the signed-in user's companies to load", async () => {
    // Fetching before preferences arrive would show other people's companies for
    // a frame and then throw the page away — the flash the old page avoided.
    mockAuthState.isLoading = true;
    const store = makeStore({ enabledCompanyIds: null });
    const { result, rerender } = renderSearch(store);
    await flush();

    expect(fetchMock).not.toHaveBeenCalled();
    // Gated, not finished: the page must read as loading, because a hook that
    // reported zero jobs / no next page / no error here would make the list
    // render "No jobs found" for a search it never ran. That is the exact shape
    // of the 2026-08-10 failure.
    expect(result.current.isInitialLoading).toBe(true);
    expect(result.current.isSkippedEmpty).toBe(false);
    expect(result.current.error).toBeNull();

    // Auth resolved, but this user's enabled-company list is still in flight.
    mockAuthState.isLoading = false;
    rerender();
    await flush();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.isInitialLoading).toBe(true);

    // Preferences land — now, and only now, exactly one request goes out, scoped
    // to those companies.
    act(() => {
      store.dispatch(
        saveEnabledCompanies.fulfilled(
          { companyIds: ['google', 'apple'], autoEnroll: false },
          'req-1',
          { token: 't', companyIds: ['google', 'apple'], autoEnroll: false }
        )
      );
    });
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const params = paramsOf(fetchMock.mock.calls[0][0]);
    expect(params.getAll('company')).toEqual(['apple', 'google']);
    expect(params.get('limit')).toBe(String(RECENT_SEARCH_PAGE_SIZE));
    expect(params.get('limit')).not.toBe(String(SIGNED_OUT_FETCH_LIMIT));
  });

  it('makes no request at all when the company filter and the enabled companies are disjoint', async () => {
    // An empty company list cannot be expressed on the wire (an omitted param
    // means "all companies"), so the only correct request here is no request.
    const store = makeStore({
      enabledCompanyIds: ['google'],
      filters: { company: ['apple'] },
    });
    const { result } = renderSearch(store);
    await flush();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.isSkippedEmpty).toBe(true);
    expect(result.current.jobs).toEqual([]);
    expect(result.current.counts).toBeNull();
    // The page renders a terminal empty state, so it must not also claim to be
    // loading or to hold another page.
    expect(result.current.isInitialLoading).toBe(false);
    expect(result.current.hasNextPage).toBe(false);
    expect(result.current.error).toBeNull();
  });
});

describe('useRecentJobsSearch — filter edits', () => {
  it('collapses a burst of filter edits into one request', async () => {
    const store = makeStore();
    renderSearch(store);
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Three edits inside the 300ms quiet period. Without the debounce this is
    // three server-side searches for two filter states the user never saw.
    act(() => {
      store.dispatch(setRecentJobsCategory(['backend']));
    });
    await flush(50);
    act(() => {
      store.dispatch(setRecentJobsCategory(['backend', 'frontend']));
    });
    await flush(50);
    act(() => {
      store.dispatch(setRecentJobsCategory(['backend', 'frontend', 'ml']));
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await flush(400);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(paramsOf(fetchMock.mock.calls[1][0]).getAll('category')).toEqual([
      'backend',
      'frontend',
      'ml',
    ]);
  });

  it("keeps the previous rows readable while the new filter's first page is in flight", async () => {
    // The anti-flash guarantee: on a filter change the list must show stale rows
    // with a refresh affordance, never an empty state that resolves back to rows.
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    install((_params, index) => {
      if (index === 0) return { body: page(['a', 'b', 'c'], null, true) };
      return gate.then(() => ({ body: page(['d'], null, true) }));
    });

    const store = makeStore();
    const { result } = renderSearch(store);
    await flush();
    expect(result.current.jobs.map((job) => job.id)).toEqual(['a', 'b', 'c']);

    act(() => {
      store.dispatch(setRecentJobsCategory(['backend']));
    });
    await flush(400);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.isRefreshing).toBe(true);
    expect(result.current.jobs.map((job) => job.id)).toEqual(['a', 'b', 'c']);
    // Refreshing is not initial loading — skeletons here would blank the list.
    expect(result.current.isInitialLoading).toBe(false);
    expect(result.current.error).toBeNull();

    release();
    await flush();

    expect(result.current.isRefreshing).toBe(false);
    expect(result.current.jobs.map((job) => job.id)).toEqual(['d']);
  });
});

describe('useRecentJobsSearch — the frozen recency bound', () => {
  it('re-renders without changing the request', async () => {
    // `since` is part of the cache key AND of the server's cursor fingerprint, so
    // reading the clock per render would discard every page already paid for.
    const store = makeStore();
    const { rerender } = renderSearch(store);
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const firstUrl = String(fetchMock.mock.calls[0][0]);
    const firstSince = paramsOf(firstUrl).get('since');
    expect(firstSince).toMatch(/Z$/);
    expect(
      Math.abs(new Date(firstSince as string).getTime() - (Date.now() - 90 * DAY_MS))
    ).toBeLessThan(120_000);

    rerender();
    await flush(1_000);
    rerender();
    await flush(1_000);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('mints a new bound when the time window changes', async () => {
    const store = makeStore();
    renderSearch(store);
    await flush();
    const firstSince = paramsOf(fetchMock.mock.calls[0][0]).get('since');

    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    await flush(400);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const secondSince = paramsOf(fetchMock.mock.calls[1][0]).get('since');
    expect(secondSince).not.toBe(firstSince);
    expect(
      Math.abs(new Date(secondSince as string).getTime() - (Date.now() - DAY_MS))
    ).toBeLessThan(120_000);
  });
});

describe('useRecentJobsSearch — failures', () => {
  it('treats a 404 inside the grace window as a pending deploy and retries it', async () => {
    // Frontend and backend ship together but deploy apart; a 404 in the overlap
    // is "not there yet", and showing an error would train users to reload.
    install((_params, index) =>
      index === 0 ? { status: 404, body: {} } : { body: page(['a'], null, true) }
    );

    const store = makeStore();
    const { result } = renderSearch(store);
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.isAwaitingDeploy).toBe(true);
    expect(result.current.error).toBeNull();
    expect(result.current.errorScope).toBeNull();

    // The first backoff step is 5s; nothing before it, exactly one call after it.
    await flush(4_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await flush(2_000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.current.isAwaitingDeploy).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.jobs.map((job) => job.id)).toEqual(['a']);
  });

  it('reports a first-page failure as an initial error', async () => {
    install(() => ({ status: 500, body: {} }));

    const store = makeStore();
    const { result } = renderSearch(store);
    await flush();

    expect(result.current.errorScope).toBe('initial');
    expect(result.current.error).toBe(ERROR_MESSAGES.LOAD_JOBS_FAILED);
    // A 500 is not the deploy race, so the page must show the error, not a spinner.
    expect(result.current.isAwaitingDeploy).toBe(false);
    expect(result.current.isInitialLoading).toBe(false);
    expect(result.current.jobs).toEqual([]);
  });

  it('reports a later-page failure as a next-page error and keeps the loaded rows', async () => {
    // Losing page 3 must not cost the reader pages 1 and 2 — the failure belongs
    // to the footer, not to the list.
    install((params) =>
      params.get('cursor') === null
        ? { body: page(['a', 'b', 'c'], 'cursor-2', true) }
        : { status: 500, body: {} }
    );

    const store = makeStore();
    const { result } = renderSearch(store);
    await flush();

    expect(result.current.hasNextPage).toBe(true);
    expect(result.current.errorScope).toBeNull();

    act(() => {
      result.current.fetchNextPage();
    });
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(paramsOf(fetchMock.mock.calls[1][0]).get('cursor')).toBe('cursor-2');
    expect(result.current.errorScope).toBe('nextPage');
    expect(result.current.error).toBe(ERROR_MESSAGES.LOAD_JOBS_FAILED);
    expect(result.current.jobs.map((job) => job.id)).toEqual(['a', 'b', 'c']);
    expect(result.current.counts?.total).toBe(137);
  });

  it('RESTARTS the walk when the next page is refused for a stale cursor', async () => {
    // The endpoint answers a cursor minted under a different filter set (or an
    // older cursor format) with 409 and the words "drop the cursor and restart the
    // walk from page 1". That instruction is addressed to the CLIENT — no reader
    // can act on it — and the ordinary next-page `retry` is `fetchNextPage()`,
    // which derives the SAME cursor from the SAME cached page. Every press would
    // replay the identical rejected request, forever, on the one error whose fix
    // is mechanical.
    //
    // Reachable only after a deploy moves `_SEARCH_CURSOR_VERSION` or the
    // fingerprint inputs mid-session; this client cannot mint the mismatch itself,
    // because RTK Query keys the cache by the whole filter set.
    let cursorAccepted = false;
    const fetch = install((params) => {
      const cursor = params.get('cursor');
      if (cursor === null) {
        // After the restart, page 1 hands back a cursor this build DOES accept.
        cursorAccepted = true;
        return { body: page(['a', 'b'], 'cursor-fresh', true) };
      }
      if (cursor === 'cursor-fresh' && cursorAccepted) {
        return { body: page(['c'], null) };
      }
      return {
        status: 409,
        body: { detail: "Stale 'cursor': cursor was minted under a different filter set" },
      };
    });

    const store = makeStore();
    const { result } = renderSearch(store);
    await flush();
    expect(result.current.jobs.map((job) => job.id)).toEqual(['a', 'b']);

    // Poison the walk: the first next-page attempt is refused as stale.
    cursorAccepted = false;
    act(() => {
      result.current.fetchNextPage();
    });
    await flush();
    expect(result.current.errorScope).toBe('nextPage');
    // The reason is NOT put on screen — it is an instruction to the client.
    expect(result.current.error).toBe(ERROR_MESSAGES.LOAD_JOBS_FAILED);

    const callsBeforeRetry = fetch.mock.calls.length;
    act(() => {
      result.current.retry();
    });
    await flush();

    // The recovery IS the assertion: retry re-requested page 1 (no cursor) rather
    // than replaying the rejected token.
    const retryCursors = fetch.mock.calls
      .slice(callsBeforeRetry)
      .map((call) => paramsOf(call[0]).get('cursor'));
    expect(retryCursors[0]).toBeNull();
    expect(result.current.errorScope).toBeNull();
    expect(result.current.jobs.map((job) => job.id)).toEqual(['a', 'b']);
  });
});

describe('useRecentJobsSearch — when a prerequisite fails', () => {
  it('still searches when the enabled-companies preference fails to load', async () => {
    // Regression, and the incident's failure shape wearing a spinner: the gate
    // used to be "ids !== null", but `null` means BOTH "still loading" and "the
    // request failed". A 500 from /api/users/enabled-companies therefore left a
    // signed-in reader on skeletons forever — no rows, no error, nothing to
    // retry. A settled-but-failed preference must degrade to "all companies",
    // which is what a null list has always meant downstream.
    const store = createTestStore({
      recentJobsFilters: { filters: BASE_FILTERS, hydrated: true, userModified: false },
      enabledCompanies: {
        ids: null,
        autoEnroll: false,
        loading: false,
        error: 'Failed to load enabled companies',
        activeLoadRequestId: null,
      },
      ui: {
        graphModal: { open: false },
        globalLoading: false,
        notifications: [],
        hideAdminFeatures: false,
        demoModeEnabled: false,
      },
      locationCatalog: { byName: {} },
    });
    const fetch = install(() => ({ body: page(['a'], null, true) }));

    const { result } = renderSearch(store);
    await flush();

    expect(fetch).toHaveBeenCalledTimes(1);
    // No company constraint: the failed preference means "everything".
    expect(paramsOf(fetch.mock.calls[0][0]).getAll('company')).toEqual([]);
    expect(result.current.jobs.map((job) => job.id)).toEqual(['a']);
    expect(result.current.isInitialLoading).toBe(false);
  });

  it('reports a failed FILTER CHANGE as an initial error, not a next-page one', async () => {
    // RTK deliberately keeps the previous filter's pages in `data` so the list
    // does not blank while refetching. Scoping the error by "do we have rows"
    // therefore mis-classified a failed filter change as a next-page failure —
    // and the page went on rendering the OLD rows and the OLD counts underneath
    // the NEW filter chips. A plausible, fully-populated, wrong result set is a
    // worse outcome than an error, so the scope keys off the CURRENT arg.
    const store = makeStore();
    const fetch = install((params) =>
      params.getAll('category').length > 0
        ? { status: 500, body: { detail: 'boom' } }
        : { body: page(['a', 'b'], null, true) }
    );

    const { result } = renderSearch(store);
    await flush();
    expect(result.current.jobs).toHaveLength(2);
    expect(result.current.errorScope).toBeNull();

    // Change the filter; its first page fails.
    act(() => {
      store.dispatch(setRecentJobsCategory(['software_engineering']));
    });
    await flush(400);
    // The debounce, the new subscription and the rejected page each need their
    // own frame to land; one flush only gets as far as "in flight".
    await flush();

    expect(fetch.mock.calls.length).toBeGreaterThan(1);
    expect(result.current.errorScope).toBe('initial');
    expect(result.current.error).toBeTruthy();
  });

  it("drops the previous filter set's counts when the new first page fails", async () => {
    // The other half of the same bug. The page hides the rows on an initial
    // error but goes on rendering `counts` — which still describes the OLD
    // filters, because `data` retains their pages. The header tiles are the part
    // of the screen a reader cannot sanity-check by eye, so "247 matches" over
    // an error message is a worse lie than the stale rows ever were.
    const store = makeStore();
    const fetch = install((params) =>
      params.getAll('category').length > 0
        ? { status: 500, body: { detail: 'boom' } }
        : { body: page(['a', 'b'], null, true) }
    );

    const { result } = renderSearch(store);
    await flush();
    expect(result.current.counts).toEqual({ total: 137, last24h: 42, last3h: 7 });

    act(() => {
      store.dispatch(setRecentJobsCategory(['software_engineering']));
    });
    await flush(400);
    await flush();

    expect(fetch.mock.calls.length).toBeGreaterThan(1);
    expect(result.current.errorScope).toBe('initial');
    expect(result.current.counts).toBeNull();
  });

  it("surfaces the endpoint's reason so the reader can see which filter to relax", async () => {
    // Every cap on this endpoint is client-fixable, and the page's only
    // affordance is a Retry that reissues the identical rejected request. A
    // generic "Failed to load jobs" leaves the reader pressing it forever.
    install(() => ({
      status: 400,
      body: { detail: "'include' accepts at most 20 values." },
    }));

    const store = makeStore();
    const { result } = renderSearch(store);
    await flush();

    expect(result.current.errorScope).toBe('initial');
    expect(result.current.error).toBe("'include' accepts at most 20 values.");
  });

  it('does NOT show stock server text — only the statuses that mean "your filters"', async () => {
    // FastAPI's default `detail` for a 500 is the words "Internal Server Error",
    // and for a 404 it is "Not Found". Both are strictly worse than the generic
    // message they would replace: they name nothing the reader can act on and
    // they read like the page is broken in a way they caused. The 404 case is not
    // hypothetical — it is the deploy-race status this hook spends ~4 minutes
    // waiting out on every release, and it surfaces once the budget is spent.
    install(() => ({ status: 500, body: { detail: 'Internal Server Error' } }));

    const store = makeStore();
    const { result } = renderSearch(store);
    await flush();

    expect(result.current.errorScope).toBe('initial');
    expect(result.current.error).toBe(ERROR_MESSAGES.LOAD_JOBS_FAILED);
  });

  it('falls back to the generic message once the deploy-race budget is spent', async () => {
    install(() => ({ status: 404, body: { detail: 'Not Found' } }));

    const store = makeStore();
    const { result } = renderSearch(store);
    // Every backoff delay plus a margin, so the grace window is provably over.
    await flush(300_000);

    expect(result.current.isAwaitingDeploy).toBe(false);
    expect(result.current.errorScope).toBe('initial');
    expect(result.current.error).toBe(ERROR_MESSAGES.LOAD_JOBS_FAILED);
  });
});

describe('useRecentJobsSearch — the result-total derivation (aria-setsize)', () => {
  // The bug: #277 moved `filtered_total` off the page-1 critical path, so the
  // server sends `filteredTotal: null` on every real search. The client was
  // taught to TOLERATE that (the tile fell back to an em-dash) but never to
  // answer it, so the header read "—" over a screen full of jobs. The rows
  // walked so far were the answer the whole time.
  it('reports the rows in hand as a lower bound when the server defers the total', async () => {
    install(() => ({ body: page(['a', 'b', 'c'], 'cursor-1', true, null) }));

    const store = makeStore();
    const { result } = renderSearch(store);
    await flush();

    expect(result.current.counts?.total).toBeNull();
    expect(result.current.resultTotal).toEqual({ kind: 'atLeast', value: 3 });
  });

  it('becomes exact once the walk is exhausted', async () => {
    // `nextCursor: null` is the endpoint's end-of-walk signal, so the rows in
    // hand ARE the whole filter set and the tile may drop the "+".
    install(() => ({ body: page(['a', 'b', 'c'], null, true, null) }));

    const store = makeStore();
    const { result } = renderSearch(store);
    await flush();

    expect(result.current.hasNextPage).toBe(false);
    expect(result.current.resultTotal).toEqual({ kind: 'exact', value: 3 });
  });

  it('is unknown before page 1 lands, never a zero', async () => {
    const store = makeStore();
    const { result } = renderSearch(store);

    expect(result.current.resultTotal).toEqual({ kind: 'unknown' });
    await flush();
  });

  it('counts the rows a signed-out reader can SEE, not the extra one fetched to detect the overlay', async () => {
    // Signed out, the hook asks for one row MORE than may be shown so the list
    // knows a further job exists. Counting `jobs` would overstate the visible
    // list by exactly that row.
    const ids = Array.from({ length: SIGNED_OUT_FETCH_LIMIT }, (_, i) => `job-${i}`);
    install(() => ({ body: page(ids, null, true, null) }));

    mockAuthState.isAuthenticated = false;
    const store = makeStore();
    const { result } = renderSearch(store);
    await flush();

    expect(result.current.jobs).toHaveLength(SIGNED_OUT_FETCH_LIMIT);
    expect(result.current.displayedJobs).toHaveLength(SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT);
    // A CAP is not an exhausted walk: those dozen cards are a floor under
    // thousands, so the tile must keep the "+" rather than announce the whole
    // corpus as twelve jobs.
    expect(result.current.resultTotal).toEqual({
      kind: 'atLeast',
      value: SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT,
    });
  });

  it('does NOT claim a lower bound for a signed-out reader whose results fit under the cap', async () => {
    // Being signed out is not the same as being truncated. Five matches come back
    // as five rows and no cursor — nothing was withheld — so the honest answer is
    // "5", not "5+". Gating exhaustion on `isSignedOut` instead of on truncation
    // rendered "5+" over exactly five cards, with no overlay and nothing else on
    // the page to corroborate the "+".
    install(() => ({ body: page(['a', 'b', 'c', 'd', 'e'], null, true, null) }));

    mockAuthState.isAuthenticated = false;
    const store = makeStore();
    const { result } = renderSearch(store);
    await flush();

    expect(result.current.jobs).toHaveLength(5);
    expect(result.current.displayedJobs).toHaveLength(5);
    expect(result.current.resultTotal).toEqual({ kind: 'exact', value: 5 });
  });
});
