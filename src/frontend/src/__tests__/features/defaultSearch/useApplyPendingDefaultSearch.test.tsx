import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { ReactNode } from 'react';
import { render, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { createTestStore } from '../../../test/testUtils';
import type { KeywordList, SavedFilters } from '../../../types';
import type { User } from '../../../features/auth/authService';
import type { DefaultSearch } from '../../../features/defaultSearch/defaultSearch';
import {
  PENDING_DEFAULT_SEARCH_KEY,
  resetPendingDefaultSearchForTests,
  writePendingDefaultSearch,
} from '../../../features/defaultSearch/pendingDefaultSearch';

const { state, completeMock, putMock, setUserMock } = vi.hoisted(() => ({
  state: {
    isAuthenticated: true,
    isLoading: false,
    user: null as unknown,
    userError: null as string | null,
    saved: undefined as unknown,
    lists: undefined as unknown,
  },
  completeMock: vi.fn(),
  putMock: vi.fn(),
  setUserMock: vi.fn(),
}));

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: state.isAuthenticated,
    isLoading: state.isLoading,
    user: undefined,
    login: vi.fn(),
    loginWithReturnTo: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn(async () => 'token'),
  }),
}));

vi.mock('../../../features/auth/useCurrentUser', () => ({
  useCurrentUser: () => ({
    user: state.user,
    setUser: setUserMock,
    loading: false,
    error: state.userError,
    reload: vi.fn(),
  }),
}));

vi.mock('../../../features/savedFilters/savedFiltersApi', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../features/savedFilters/savedFiltersApi')>();
  return {
    ...actual,
    useGetSavedFiltersQuery: (_arg: unknown, opts?: { skip?: boolean }) => ({
      data: opts?.skip ? undefined : state.saved,
    }),
    useGetKeywordListsQuery: (_arg: unknown, opts?: { skip?: boolean }) => ({
      data: opts?.skip ? undefined : state.lists,
    }),
    useCompleteOnboardingMutation: () => [completeMock, { isLoading: false }],
    useUpdateSavedFiltersMutation: () => [putMock, { isLoading: false }],
    useCreateKeywordListMutation: () => [vi.fn(), { isLoading: false }],
    useUpdateKeywordListMutation: () => [vi.fn(), { isLoading: false }],
  };
});

const { useApplyPendingDefaultSearch } = await import(
  '../../../features/defaultSearch/useApplyPendingDefaultSearch'
);
const { useHydrateSavedFilters } = await import(
  '../../../features/savedFilters/useHydrateSavedFilters'
);

const PENDING: DefaultSearch = {
  timeWindow: '24h',
  searchTags: [],
  location: ['San Francisco, CA, US'],
  category: ['software_engineering'],
  level: ['entry'],
  subcategory: ['backend'],
  companyCategory: [],
};

/** A different, older saved default: the one the pending search replaces. */
const OLD_SAVED: SavedFilters = {
  recentTimeWindow: '7d',
  trendTimeWindow: '90d',
  locations: ['New York, NY, US'],
  category: ['product_manager'],
  level: ['senior'],
  subcategory: [],
  recentActiveKeywordListId: null,
  trendActiveKeywordListId: null,
};

const LISTS: KeywordList[] = [];
const STAMP = '2026-11-26T10:00:00+00:00';

function makeUser(onboardingCompletedAt: string | null): User {
  return {
    id: 'u1',
    providerSubject: 'auth0|u1',
    email: 'a@example.com',
    displayName: null,
    givenName: null,
    familyName: null,
    pictureUrl: null,
    createdAt: '2026-11-26T09:00:00Z',
    updatedAt: '2026-11-26T09:00:00Z',
    isAdmin: false,
    onboardingCompletedAt,
  };
}

/** The two hooks in `AppContent`'s order. */
function Harness() {
  useApplyPendingDefaultSearch();
  useHydrateSavedFilters();
  return null;
}

function mount() {
  const store = createTestStore();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <Provider store={store}>{children}</Provider>
  );
  const view = render(<Harness />, { wrapper });
  return { store, ...view };
}

const pendingStored = () => window.sessionStorage.getItem(PENDING_DEFAULT_SEARCH_KEY);

beforeEach(() => {
  window.sessionStorage.clear();
  resetPendingDefaultSearchForTests();
  writePendingDefaultSearch(PENDING);
  state.isAuthenticated = true;
  state.isLoading = false;
  state.user = makeUser('2026-01-01T00:00:00Z');
  state.userError = null;
  state.saved = OLD_SAVED;
  state.lists = LISTS;
  completeMock.mockReset();
  putMock.mockReset();
  setUserMock.mockReset();
  putMock.mockImplementation((body: SavedFilters) => ({ unwrap: () => Promise.resolve(body) }));
  completeMock.mockImplementation(() => ({
    unwrap: () =>
      Promise.resolve({
        onboardingCompletedAt: STAMP,
        savedFilters: { ...OLD_SAVED, category: ['software_engineering'] },
      }),
  }));
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useApplyPendingDefaultSearch', () => {
  it('restores the pending search before saved-filters hydration can apply the old default', async () => {
    const { store } = mount();
    const recent = store.getState().recentJobsFilters;
    expect(recent.hydrated).toBe(true);
    expect(recent.filters).toMatchObject({
      timeWindow: '24h',
      location: ['San Francisco, CA, US'],
      category: ['software_engineering'],
      level: ['entry'],
      subcategory: ['backend'],
      searchTags: undefined,
    });
    // The Companies page did hydrate from the old row; the save then moves it.
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(store.getState().graphFilters.filters.level).toEqual(['entry'])
    );
  });

  it('a stamped account: one PUT, no onboarding call, pending cleared', async () => {
    mount();
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    expect(completeMock).not.toHaveBeenCalled();
    expect(putMock.mock.calls[0][0]).toMatchObject({
      recentTimeWindow: '24h',
      trendTimeWindow: '90d',
      locations: ['San Francisco, CA, US'],
      category: ['software_engineering'],
      level: ['entry'],
      subcategory: ['backend'],
    });
    await waitFor(() => expect(pendingStored()).toBeNull());
  });

  it('a new account: stamped with the search as its answers, then the PUT', async () => {
    state.user = makeUser(null);
    mount();
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    expect(completeMock).toHaveBeenCalledTimes(1);
    expect(completeMock.mock.calls[0][0]).toMatchObject({
      category: ['software_engineering'],
      subcategory: ['backend'],
      level: ['entry'],
      locations: ['San Francisco, CA, US'],
      skipped: false,
    });
    expect(completeMock.mock.calls[0][0]).not.toHaveProperty('step');
    expect(completeMock.mock.invocationCallOrder[0]).toBeLessThan(
      putMock.mock.invocationCallOrder[0]
    );
    // The stamp is recorded locally (no refetch).
    const update = setUserMock.mock.calls[0][0] as (u: User | null) => User | null;
    expect(update(makeUser(null))?.onboardingCompletedAt).toBe(STAMP);
  });

  it('a failed stamp still saves the search', async () => {
    state.user = makeUser(null);
    completeMock.mockImplementation(() => ({ unwrap: () => Promise.reject({ status: 500 }) }));
    mount();
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    expect(setUserMock).not.toHaveBeenCalled();
    await waitFor(() => expect(pendingStored()).toBeNull());
  });

  it('waits for the current user (loaded or failed) before saving', async () => {
    state.user = null;
    const { rerender } = mount();
    await new Promise((r) => setTimeout(r, 20));
    expect(putMock).not.toHaveBeenCalled();
    state.userError = 'Failed to load profile';
    rerender(<Harness />);
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    expect(completeMock).not.toHaveBeenCalled();
  });

  it('a load that ends signed out shows the search once, then drops it and sends nothing', async () => {
    state.isAuthenticated = false;
    const { store } = mount();
    expect(store.getState().recentJobsFilters.filters.level).toEqual(['entry']);
    await waitFor(() => expect(pendingStored()).toBeNull());
    expect(putMock).not.toHaveBeenCalled();
    expect(completeMock).not.toHaveBeenCalled();
  });

  describe('Back from the sign-in page restores this page from the back/forward cache', () => {
    /** A `pageshow` like the browser's: `persisted` is true for a cache restore. */
    const pageShow = (persisted: boolean) => {
      const event = new Event('pageshow');
      Object.defineProperty(event, 'persisted', { value: persisted });
      window.dispatchEvent(event);
    };

    /** Signed out with no pending search at load, then the click stores one. */
    function clickedThenLeft() {
      window.sessionStorage.clear();
      resetPendingDefaultSearchForTests();
      state.isAuthenticated = false;
      const view = mount();
      writePendingDefaultSearch(PENDING);
      return view;
    }

    it('drops the abandoned search, so a later sign-in cannot save it', () => {
      clickedThenLeft();
      expect(pendingStored()).not.toBeNull();
      pageShow(true);
      expect(pendingStored()).toBeNull();
    });

    it('mirror: an ordinary pageshow (a real load) keeps it', () => {
      clickedThenLeft();
      pageShow(false);
      expect(pendingStored()).not.toBeNull();
    });

    it('stops listening once unmounted', () => {
      const { unmount } = clickedThenLeft();
      unmount();
      pageShow(true);
      expect(pendingStored()).not.toBeNull();
    });
  });

  it('keeps the pending search while auth is still loading', async () => {
    state.isAuthenticated = false;
    state.isLoading = true;
    mount();
    await new Promise((r) => setTimeout(r, 20));
    expect(pendingStored()).not.toBeNull();
  });

  it('saves only once, however often it re-renders', async () => {
    const { rerender } = mount();
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    state.saved = { ...OLD_SAVED };
    state.lists = [...LISTS];
    rerender(<Harness />);
    rerender(<Harness />);
    await new Promise((r) => setTimeout(r, 20));
    expect(putMock).toHaveBeenCalledTimes(1);
  });

  it('does nothing without a pending search', async () => {
    window.sessionStorage.clear();
    resetPendingDefaultSearchForTests();
    const { store } = mount();
    await new Promise((r) => setTimeout(r, 20));
    expect(putMock).not.toHaveBeenCalled();
    // Ordinary hydration from the saved row.
    expect(store.getState().recentJobsFilters.filters.level).toEqual(['senior']);
  });
});
