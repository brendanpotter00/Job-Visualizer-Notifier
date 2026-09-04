import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from '@testing-library/react';
import { Provider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';

import { createTestStore } from '../../../test/testUtils';
import type { SavedFilters, KeywordList } from '../../../types';

/**
 * "A shared URL wins for that visit" — proven in the composition it relies on.
 *
 * This is the PR's headline claim and it is a claim about two hooks, not one.
 * `useRecentJobsUrlSync` is declared BEFORE `useHydrateSavedFilters` in
 * `app/App.tsx`, and the hook's own comment calls that ordering load-bearing:
 * the URL read is synchronous on mount while the saved filters need a round
 * trip, so the URL reaches the slice's one-shot `hydrated` guard first and the
 * later saved-filters dispatch is a no-op. Nothing exercised that. The sibling
 * file mounts the sync hook ALONE and simulates the competing hydration by
 * dispatching `hydrateRecentJobsFilters` by hand, which proves the reducer's
 * guard works and says nothing about whether the two hooks are wired up in an
 * order that reaches it. `App.test.tsx` mocks `isAuthenticated: false`, so the
 * saved-filters path never runs there either.
 *
 * So: the real hooks, the real store, the App.tsx declaration order, a signed-in
 * reader, and query responses that land AFTER mount — which is when they land in
 * production.
 */

const mockAuthState = { isAuthenticated: true };
vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: mockAuthState.isAuthenticated,
    isLoading: false,
    user: undefined,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn(),
  }),
  NotAuthenticatedError: class NotAuthenticatedError extends Error {},
}));

/**
 * Mutable stand-ins for the two RTK Query hooks, flipped between renders to
 * reproduce "the responses just landed". Same seam the hydration-gate test uses:
 * the real `fetchBaseQuery` cannot run here (Node's `Request` rejects the
 * relative `/api/users` base URL), and driving the hooks directly is what makes
 * the render at which they resolve observable.
 */
const savedFiltersResult: { data: SavedFilters | undefined } = { data: undefined };
const keywordListsResult: { data: KeywordList[] | undefined } = { data: undefined };

vi.mock('../../../features/savedFilters/savedFiltersApi', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../features/savedFilters/savedFiltersApi')>();
  return {
    ...actual,
    useGetSavedFiltersQuery: () => savedFiltersResult,
    useGetKeywordListsQuery: () => keywordListsResult,
  };
});

import { useRecentJobsUrlSync } from '../../../features/filters/useRecentJobsUrlSync';
import { useHydrateSavedFilters } from '../../../features/savedFilters/useHydrateSavedFilters';

const LIST: KeywordList = {
  id: 'list-1',
  name: 'Mine',
  isBuiltin: false,
  position: 0,
  tags: [{ text: 'rust', mode: 'include' }],
};

/** Saved filters that differ from BOTH the slice defaults and the shared link. */
const SAVED: SavedFilters = {
  recentTimeWindow: '90d',
  trendTimeWindow: '90d',
  locations: ['Austin, TX, US'],
  category: ['software_engineering'],
  subcategory: [],
  level: ['senior'],
  recentActiveKeywordListId: 'list-1',
  trendActiveKeywordListId: null,
};

/** Mirrors `app/App.tsx`: the URL sync hook FIRST, the hydration hook second. */
function AppRoot() {
  useRecentJobsUrlSync();
  useHydrateSavedFilters();
  return null;
}

function tree(store: ReturnType<typeof createTestStore>) {
  return (
    <Provider store={store}>
      <BrowserRouter>
        <AppRoot />
      </BrowserRouter>
    </Provider>
  );
}

function mountAt(search: string) {
  window.history.replaceState({}, '', `/${search}`);
  const store = createTestStore();
  const view = render(tree(store));
  return { store, view };
}

/** Land both saved-filters responses, as one render, after mount. */
function landSavedFilters(
  view: ReturnType<typeof render>,
  store: ReturnType<typeof createTestStore>
) {
  savedFiltersResult.data = SAVED;
  keywordListsResult.data = [LIST];
  view.rerender(tree(store));
}

beforeEach(() => {
  mockAuthState.isAuthenticated = true;
  savedFiltersResult.data = undefined;
  keywordListsResult.data = undefined;
});

afterEach(() => {
  window.history.replaceState({}, '', '/');
});

describe('a shared link beats the reader’s own saved filters', () => {
  it('keeps the URL’s filters when the saved-filters responses land after mount', () => {
    const { store, view } = mountAt('?time=24h&tag=backend');

    // Precondition: the URL is already in the slice and the saved filters have
    // NOT arrived — otherwise the assertions below could pass by accident.
    expect(store.getState().recentJobsFilters.filters.timeWindow).toBe('24h');
    expect(savedFiltersResult.data).toBeUndefined();

    landSavedFilters(view, store);

    const filters = store.getState().recentJobsFilters.filters;
    expect(filters.timeWindow).toBe('24h');
    expect(filters.searchTags).toEqual([{ text: 'backend', mode: 'include' }]);
    // None of the saved values leaked in — that is what "the reader's saved
    // filters are neither read nor written on such a visit" means.
    expect(filters.category).toBeUndefined();
    expect(filters.level).toBeUndefined();
    expect(filters.location).toBeUndefined();
    expect(window.location.search).toBe('?time=24h&tag=backend');
  });

  it('still hydrates from saved filters on an ordinary visit, and mirrors them', () => {
    // The other side of the same coin: with no params in the URL the saved
    // filters must win, and the address bar must then show them so the reader
    // can copy the link they are actually looking at.
    const { store, view } = mountAt('');
    expect(store.getState().recentJobsFilters.hydrated).toBe(false);

    landSavedFilters(view, store);

    expect(store.getState().recentJobsFilters.filters.timeWindow).toBe('90d');
    expect(window.location.search).toContain('time=90d');
    expect(window.location.search).toContain('category=software_engineering');
  });
});

describe('signing out takes the filters out of the address bar too', () => {
  it('clears the owned params when the session ends WITHOUT a page load', () => {
    // The Logout button redirects through `auth0Logout` and takes the URL with
    // it, so it never showed this. A silent Auth0 session expiry or a failed
    // refresh does not: `isAuthenticated` simply flips false,
    // `useHydrateSavedFilters` resets the slices, and the ex-user's filters were
    // left sitting in the address bar above a defaults page — where the next
    // reload re-applied them verbatim.
    const { store, view } = mountAt('?time=24h&tag=backend');
    landSavedFilters(view, store);
    expect(window.location.search).toBe('?time=24h&tag=backend');

    mockAuthState.isAuthenticated = false;
    view.rerender(tree(store));

    expect(store.getState().recentJobsFilters.filters.timeWindow).toBe('all');
    expect(window.location.search).toBe('');
  });

  it('leaves query params it does not own alone on the way out', () => {
    const { store, view } = mountAt('?time=24h&utm_source=slack');
    landSavedFilters(view, store);

    mockAuthState.isAuthenticated = false;
    view.rerender(tree(store));

    expect(window.location.search).toBe('?utm_source=slack');
  });
});
