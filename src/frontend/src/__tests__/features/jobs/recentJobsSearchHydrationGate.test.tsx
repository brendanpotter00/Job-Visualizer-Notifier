import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, render } from '@testing-library/react';
import { Provider } from 'react-redux';
import type { ReactNode } from 'react';

import { createTestStore } from '../../../test/testUtils';
import type { SavedFilters, KeywordList } from '../../../types';

/**
 * The gate between "the saved filters arrived" and "the first search may go out".
 *
 * This file is separate from `useRecentJobsSearch.test.tsx` because the bug it
 * pins is invisible from inside the hook: it is an EFFECT-ORDER bug spanning two
 * components. `useHydrateSavedFilters()` is mounted at the app root
 * (`app/App.tsx:51`), the Recent page is its descendant, and React flushes a
 * commit's effects CHILD-FIRST. So on the render where the saved-filters queries
 * resolve, the page's RTK Query subscription effect runs BEFORE the root's
 * hydration effect — and a gate that opens on "the queries settled" opens one
 * effect too early, while the slice still holds its pre-hydration defaults.
 *
 * The cost is not theoretical. Page 1 is the only request that pays for
 * `filteredTotal` and both recency tiles, and the pre-hydration filter set is the
 * widest shape the endpoint can be asked for: the slice's default `timeWindow` is
 * `'all'`, so `since` is the EPOCH and `filteredTotal` counts every OPEN row of
 * every followed company, with no category, level, location or keyword to narrow
 * it. So the wasted search is the most expensive one available, the real
 * search follows ~300ms later once the debounced snapshot re-stamps, and in
 * between the reader sees a flash of rows they did not ask for — on every cold
 * load, for every signed-in reader whose saved filters differ from the defaults.
 *
 * The gate is therefore the slice's own `hydrated` flag (with an error escape
 * hatch), which flips in the SAME store update that writes the saved values, so
 * no frame exists in which the gate is open and the filters are stale.
 */

const mockAuthState = { isAuthenticated: true, isLoading: false };
vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: mockAuthState.isAuthenticated,
    isLoading: mockAuthState.isLoading,
    user: undefined,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn(),
  }),
  NotAuthenticatedError: class NotAuthenticatedError extends Error {},
}));

/**
 * Mutable stand-ins for the two RTK Query hooks, flipped between renders to
 * reproduce "the responses just landed". Same seam the existing
 * `useHydrateSavedFilters` test uses — the real `fetchBaseQuery` cannot run here
 * (Node's `Request` rejects the relative `/api/users` base URL), and driving the
 * hooks directly is what makes the render at which they resolve observable.
 */
interface QueryResult<T> {
  data: T | undefined;
  isSuccess: boolean;
  isError: boolean;
}
const savedFiltersResult: QueryResult<SavedFilters> = {
  data: undefined,
  isSuccess: false,
  isError: false,
};
const keywordListsResult: QueryResult<KeywordList[]> = {
  data: undefined,
  isSuccess: false,
  isError: false,
};

vi.mock('../../../features/savedFilters/savedFiltersApi', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../features/savedFilters/savedFiltersApi')>();
  return {
    ...actual,
    useGetSavedFiltersQuery: () => savedFiltersResult,
    useGetKeywordListsQuery: () => keywordListsResult,
  };
});

import { useRecentJobsSearch } from '../../../features/jobs/hooks/useRecentJobsSearch';
import { useHydrateSavedFilters } from '../../../features/savedFilters/useHydrateSavedFilters';

const LIST: KeywordList = {
  id: 'list-1',
  name: 'Mine',
  isBuiltin: false,
  position: 0,
  tags: [{ text: 'rust', mode: 'include' }],
};

/** Saved filters that differ from the slice defaults on every hydrated field. */
const SAVED: SavedFilters = {
  recentTimeWindow: '24h',
  trendTimeWindow: '24h',
  locations: ['Austin, TX, US'],
  category: ['software_engineering'],
  level: ['senior'],
  recentActiveKeywordListId: 'list-1',
  trendActiveKeywordListId: null,
};

const SEARCH_PAGE = {
  jobs: [],
  nextCursor: null,
  meta: { filteredTotal: 0, countLast24h: 0, countLast3h: 0 },
};

/** Every `/api/jobs/search` query string the tree issued, in order. */
let searchQueries: URLSearchParams[];

/** Restored in `afterEach` — a replaced global outlives the file otherwise. */
const originalFetch = globalThis.fetch;

function installFetch() {
  searchQueries = [];
  globalThis.fetch = vi.fn(async (input: unknown) => {
    const url = String(input);
    if (!url.startsWith('/api/jobs/search?')) {
      throw new Error(`unexpected fetch URL in hydration-gate test: ${url}`);
    }
    searchQueries.push(new URLSearchParams(url.slice(url.indexOf('?') + 1)));
    return {
      ok: true,
      status: 200,
      statusText: '200',
      headers: new Headers(),
      json: async () => SEARCH_PAGE,
    } as unknown as Response;
  }) as unknown as typeof fetch;
}

function makeStore() {
  // `recentJobsFilters` is deliberately NOT preloaded: the slice must start
  // un-hydrated on its all-time / no-category defaults, which is the state a
  // cold load actually begins in.
  return createTestStore({
    enabledCompanies: {
      ids: ['google'],
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
      demoModeEnabled: false,
    },
    locationCatalog: { byName: {} },
  });
}

/** Mirrors `app/App.tsx`: hydration at the root, the search hook in a descendant. */
function Child() {
  useRecentJobsSearch();
  return null;
}
function AppRoot() {
  useHydrateSavedFilters();
  return <Child />;
}

function renderTree(store: ReturnType<typeof createTestStore>) {
  const wrapper = ({ children }: { children: ReactNode }) => (
    <Provider store={store}>{children}</Provider>
  );
  return render(<AppRoot />, { wrapper });
}

/** Past the 300ms filter debounce and RTK's autoBatch animation frame. */
async function flush(ms = 1000) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  mockAuthState.isAuthenticated = true;
  mockAuthState.isLoading = false;
  savedFiltersResult.data = undefined;
  savedFiltersResult.isSuccess = false;
  savedFiltersResult.isError = false;
  keywordListsResult.data = undefined;
  keywordListsResult.isSuccess = false;
  keywordListsResult.isError = false;
  installFetch();
});

afterEach(() => {
  vi.useRealTimers();
  globalThis.fetch = originalFetch;
  vi.resetAllMocks();
});

describe('the Recent page waits for saved filters to HYDRATE, not merely to arrive', () => {
  it('issues exactly one search, and it already carries the hydrated filters', async () => {
    const store = makeStore();
    const { rerender } = renderTree(store);
    await flush();
    expect(searchQueries).toHaveLength(0);

    // Both responses land on the same render — the frame in which a
    // settled-based gate opens one effect ahead of the hydration dispatch.
    savedFiltersResult.data = SAVED;
    savedFiltersResult.isSuccess = true;
    keywordListsResult.data = [LIST];
    keywordListsResult.isSuccess = true;
    rerender(<AppRoot />);
    await flush();

    expect(store.getState().recentJobsFilters.hydrated).toBe(true);
    // The regression: TWO requests, the first of them unfiltered.
    expect(searchQueries).toHaveLength(1);

    const query = searchQueries[0];
    expect(query.getAll('category')).toEqual(['software_engineering']);
    expect(query.getAll('level')).toEqual(['senior']);
    expect(query.getAll('location')).toEqual(['Austin, TX, US']);
    expect(query.getAll('include')).toEqual(['rust']);
    // The saved 24h window, not the slice's all-time default (`since` = EPOCH).
    const since = new Date(query.get('since') as string).getTime();
    expect(Date.now() - since).toBeLessThanOrEqual(25 * 60 * 60 * 1000);
  });

  it('still searches when only the KEYWORD-LISTS request fails', async () => {
    // The other half of the escape hatch, and the half nothing else covers:
    // `savedFiltersReady` ORs `savedFilters.isError` with `keywordLists.isError`,
    // and `useHydrateSavedFilters` needs BOTH bodies (the active-list id in the
    // saved filters is resolved against the lists), so a lone
    // `GET /api/users/saved-filters/keyword-lists` failure leaves `hydrated`
    // false forever. Without this disjunct the reader sits on skeletons with no
    // rows, no error and no retry — while the endpoint that actually serves the
    // page is perfectly healthy.
    const store = makeStore();
    const { rerender } = renderTree(store);
    await flush();
    expect(searchQueries).toHaveLength(0);

    savedFiltersResult.data = SAVED;
    savedFiltersResult.isSuccess = true;
    keywordListsResult.isError = true;
    rerender(<AppRoot />);
    await flush();

    // Precondition: hydration genuinely could not run, so the gate is being held
    // open by `isError` alone and not by a hydration that happened anyway.
    expect(store.getState().recentJobsFilters.hydrated).toBe(false);
    expect(searchQueries).toHaveLength(1);
    expect(searchQueries[0].getAll('category')).toEqual([]);
  });

  it('still searches when the saved-filters request fails, so a 500 cannot strand the page', async () => {
    // `hydrated` alone would deadlock: `useHydrateSavedFilters` only flips it on
    // a successful PAIR of responses, so one failing endpoint would leave the
    // reader on skeletons with no rows, no error and no retry — the failure the
    // enabled-companies gate already carries an escape hatch for.
    const store = makeStore();
    const { rerender } = renderTree(store);
    await flush();
    expect(searchQueries).toHaveLength(0);

    savedFiltersResult.isError = true;
    keywordListsResult.data = [LIST];
    keywordListsResult.isSuccess = true;
    rerender(<AppRoot />);
    await flush();

    expect(store.getState().recentJobsFilters.hydrated).toBe(false);
    expect(searchQueries).toHaveLength(1);
    // Falls back to the slice defaults, which is what "no saved filters" means.
    expect(searchQueries[0].getAll('category')).toEqual([]);
  });
});
