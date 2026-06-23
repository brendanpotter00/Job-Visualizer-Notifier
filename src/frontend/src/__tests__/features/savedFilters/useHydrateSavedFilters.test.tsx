import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import React from 'react';
import { Provider } from 'react-redux';
import { createTestStore } from '../../../test/testUtils';
import { addRecentJobsSearchTag } from '../../../features/filters/slices/recentJobsFiltersSlice';
import type { SavedFilters, KeywordList } from '../../../types';

// --- Mock the auth + RTK Query hooks the hydration hook depends on ----------
const mockAuthState = { isAuthenticated: false };
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
}));

// Mutable query results the mocked RTK Query hooks return per render.
const savedFiltersResult: { data: SavedFilters | undefined } = { data: undefined };
const keywordListsResult: { data: KeywordList[] | undefined } = { data: undefined };
const resetApiStateAction = { type: 'savedFiltersApi/resetApiState' } as const;
const resetApiStateSpy = vi.fn(() => resetApiStateAction);

vi.mock('../../../features/savedFilters/savedFiltersApi', async (importOriginal) => {
  // Keep the real api object (reducer/middleware/reducerPath are needed by the
  // test store), but override the two query hooks and spy on resetApiState.
  const actual =
    await importOriginal<typeof import('../../../features/savedFilters/savedFiltersApi')>();
  return {
    ...actual,
    useGetSavedFiltersQuery: () => savedFiltersResult,
    useGetKeywordListsQuery: () => keywordListsResult,
    savedFiltersApi: {
      ...actual.savedFiltersApi,
      util: { ...actual.savedFiltersApi.util, resetApiState: () => resetApiStateSpy() },
    },
  };
});

import { useHydrateSavedFilters } from '../../../features/savedFilters/useHydrateSavedFilters';

function makeWrapper(store: ReturnType<typeof createTestStore>) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider, { store, children } as React.ComponentProps<
      typeof Provider
    >);
  };
}

const LIST: KeywordList = {
  id: 'list-1',
  name: 'Backend',
  isBuiltin: false,
  position: 0,
  tags: [{ text: 'golang', mode: 'include' }],
};

function makeSavedFilters(overrides: Partial<SavedFilters> = {}): SavedFilters {
  return {
    recentTimeWindow: '24h',
    trendTimeWindow: '30d',
    locations: ['San Francisco, CA, US'],
    recentActiveKeywordListId: 'list-1',
    trendActiveKeywordListId: 'list-1',
    ...overrides,
  };
}

describe('useHydrateSavedFilters', () => {
  beforeEach(() => {
    mockAuthState.isAuthenticated = false;
    savedFiltersResult.data = undefined;
    keywordListsResult.data = undefined;
    resetApiStateSpy.mockClear();
  });

  it('does NOT hydrate until BOTH queries have resolved (line-49 guard)', () => {
    // Authenticated, saved filters present but keyword lists still loading.
    mockAuthState.isAuthenticated = true;
    savedFiltersResult.data = makeSavedFilters();
    keywordListsResult.data = undefined; // lists not yet loaded

    const store = createTestStore();
    renderHook(() => useHydrateSavedFilters(), { wrapper: makeWrapper(store) });

    // Slices stay un-hydrated; a non-null active pointer must NOT clear tags.
    expect(store.getState().graphFilters.hydrated).toBe(false);
    expect(store.getState().recentJobsFilters.hydrated).toBe(false);
    expect(store.getState().graphFilters.filters.searchTags).toBeUndefined();
    expect(store.getState().recentJobsFilters.filters.searchTags).toBeUndefined();
  });

  it('hydrates both slices from server data once both queries resolve', () => {
    mockAuthState.isAuthenticated = true;
    savedFiltersResult.data = makeSavedFilters();
    keywordListsResult.data = [LIST];

    const store = createTestStore();
    renderHook(() => useHydrateSavedFilters(), { wrapper: makeWrapper(store) });

    const graph = store.getState().graphFilters;
    const recent = store.getState().recentJobsFilters;

    expect(graph.hydrated).toBe(true);
    expect(recent.hydrated).toBe(true);
    // Graph (Company) reads the trend defaults; Recent reads the recent ones.
    expect(graph.filters.timeWindow).toBe('30d');
    expect(recent.filters.timeWindow).toBe('24h');
    expect(graph.filters.location).toEqual(['San Francisco, CA, US']);
    expect(recent.filters.location).toEqual(['San Francisco, CA, US']);
    // Active pointer resolved to the matching list's tags.
    expect(graph.filters.searchTags).toEqual([{ text: 'golang', mode: 'include' }]);
    expect(recent.filters.searchTags).toEqual([{ text: 'golang', mode: 'include' }]);
  });

  it('fires the logout reset exactly once on the auth true->false transition and resets API cache', () => {
    // First render: authenticated + fully resolved -> hydrate.
    mockAuthState.isAuthenticated = true;
    savedFiltersResult.data = makeSavedFilters();
    keywordListsResult.data = [LIST];

    const store = createTestStore();
    const { rerender } = renderHook(() => useHydrateSavedFilters(), {
      wrapper: makeWrapper(store),
    });
    expect(store.getState().graphFilters.hydrated).toBe(true);

    // Transition to logged out.
    mockAuthState.isAuthenticated = false;
    savedFiltersResult.data = undefined;
    keywordListsResult.data = undefined;
    rerender();

    // Slices reset, hydrated cleared, API cache wiped exactly once.
    expect(store.getState().graphFilters.hydrated).toBe(false);
    expect(store.getState().recentJobsFilters.hydrated).toBe(false);
    expect(store.getState().graphFilters.filters.searchTags).toBeUndefined();
    expect(resetApiStateSpy).toHaveBeenCalledTimes(1);

    // A further logged-out re-render must NOT fire the reset again.
    rerender();
    expect(resetApiStateSpy).toHaveBeenCalledTimes(1);
  });

  it('does not clobber a filter edit the user made before the queries resolved', () => {
    // Signed in, saved filters present, but the keyword-lists query is still
    // pending — the cold-start window where the filter UI is already interactive
    // but hydration has not run yet.
    mockAuthState.isAuthenticated = true;
    savedFiltersResult.data = makeSavedFilters();
    keywordListsResult.data = undefined;

    const store = createTestStore();
    const { rerender } = renderHook(() => useHydrateSavedFilters(), {
      wrapper: makeWrapper(store),
    });

    // Nothing hydrated yet (both queries must resolve first).
    expect(store.getState().recentJobsFilters.hydrated).toBe(false);

    // User adds a keyword on the Recent Jobs page during that window.
    store.dispatch(addRecentJobsSearchTag({ text: 'rust', mode: 'include' }));
    expect(store.getState().recentJobsFilters.filters.searchTags).toEqual([
      { text: 'rust', mode: 'include' },
    ]);

    // Keyword lists finally resolve -> the hydration effect runs.
    keywordListsResult.data = [LIST];
    rerender();

    // The user's keyword survives — it is NOT overwritten by the saved
    // 'golang' list (the bug: a late hydration used to wipe it).
    expect(store.getState().recentJobsFilters.filters.searchTags).toEqual([
      { text: 'rust', mode: 'include' },
    ]);
    // The untouched graph slice still hydrates normally from saved filters.
    expect(store.getState().graphFilters.hydrated).toBe(true);
    expect(store.getState().graphFilters.filters.searchTags).toEqual([
      { text: 'golang', mode: 'include' },
    ]);
  });

  it('does not reset on the first render when already logged out', () => {
    mockAuthState.isAuthenticated = false;
    const store = createTestStore();
    renderHook(() => useHydrateSavedFilters(), { wrapper: makeWrapper(store) });
    // No prior authenticated state -> no reset (don't stomp anonymous tweaks).
    expect(resetApiStateSpy).not.toHaveBeenCalled();
  });
});
