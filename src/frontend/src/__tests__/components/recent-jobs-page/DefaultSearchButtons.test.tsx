import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createTestStore, renderWithProviders } from '../../../test/testUtils';
import type { KeywordList, RecentJobsFilters, SavedFilters, SearchTag } from '../../../types';
import {
  PENDING_DEFAULT_SEARCH_KEY,
  resetPendingDefaultSearchForTests,
} from '../../../features/defaultSearch/pendingDefaultSearch';

const { authState, queryState, loginWithReturnToMock, putMock, trackSignInClickMock } = vi.hoisted(
  () => ({
    authState: { isEnabled: true, isAuthenticated: true, isLoading: false },
    /** `savedFailed`: the saved-filters GET failed (the real hook can't be seeded with an error). */
    queryState: { savedFailed: false },
    loginWithReturnToMock: vi.fn(),
    putMock: vi.fn(),
    trackSignInClickMock: vi.fn(),
  })
);

vi.mock('../../../features/auth/useAuth', async (importActual) => {
  const actual = await importActual<typeof import('../../../features/auth/useAuth')>();
  return {
    ...actual,
    useAuth: () => ({
      ...authState,
      user: undefined,
      login: vi.fn(),
      loginWithReturnTo: loginWithReturnToMock,
      logout: vi.fn(),
      getToken: vi.fn(async () => 'token'),
    }),
  };
});

vi.mock('../../../features/analytics/events', async (importActual) => {
  const actual = await importActual<typeof import('../../../features/analytics/events')>();
  return { ...actual, trackSignInClick: trackSignInClickMock };
});

// Only the writes are stubbed. The two reads are the real hooks over a seeded
// cache, so a save's cache write is what puts the button back on "saved".
vi.mock('../../../features/savedFilters/savedFiltersApi', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../features/savedFilters/savedFiltersApi')>();
  return {
    ...actual,
    useGetSavedFiltersQuery: (...args: Parameters<typeof actual.useGetSavedFiltersQuery>) => {
      const real = actual.useGetSavedFiltersQuery(...args);
      return queryState.savedFailed ? { ...real, data: undefined, isError: true } : real;
    },
    useUpdateSavedFiltersMutation: () => [putMock, { isLoading: false }],
    useCreateKeywordListMutation: () => [vi.fn(), { isLoading: false }],
    useUpdateKeywordListMutation: () => [vi.fn(), { isLoading: false }],
  };
});

const { savedFiltersApi } = await import('../../../features/savedFilters/savedFiltersApi');
const { DefaultSearchButtons } =
  await import('../../../components/recent-jobs-page/DefaultSearchButtons');
const {
  setRecentJobsLevel,
  setRecentJobsLocation,
  setRecentJobsSearchTags,
  setRecentJobsTimeWindow,
} = await import('../../../features/filters/slices/recentJobsFiltersSlice');

const rust: SearchTag = { text: 'rust', mode: 'include' };

const SAVED: SavedFilters = {
  recentTimeWindow: '7d',
  trendTimeWindow: '90d',
  locations: [],
  category: [],
  level: ['entry', 'senior'],
  subcategory: [],
  recentActiveKeywordListId: null,
  trendActiveKeywordListId: null,
};
/** The Recent filters that equal {@link SAVED}. */
const ON_SAVED: RecentJobsFilters = {
  timeWindow: '7d',
  softwareOnly: false,
  level: ['entry', 'senior'],
};

async function renderSignedIn(
  saved: SavedFilters = SAVED,
  lists: KeywordList[] = [],
  filters: RecentJobsFilters = ON_SAVED
) {
  const store = createTestStore({
    recentJobsFilters: { filters, hydrated: true, userModified: false },
  });
  await store.dispatch(savedFiltersApi.util.upsertQueryData('getSavedFilters', undefined, saved));
  await store.dispatch(savedFiltersApi.util.upsertQueryData('getKeywordLists', undefined, lists));
  renderWithProviders(<DefaultSearchButtons />, { store });
  return store;
}

function renderSignedOut() {
  authState.isAuthenticated = false;
  const store = createTestStore();
  renderWithProviders(<DefaultSearchButtons />, { store });
  return store;
}

const byName = (name: string) => screen.getByRole('button', { name });
const queryByName = (name: string) => screen.queryByRole('button', { name });
const saved = () => byName('Default search saved');
const update = () => byName('Update default search');
const save = () => byName('Save default search');
const reset = () => byName('Reset to default search');
const noReset = () => expect(queryByName('Reset to default search')).not.toBeInTheDocument();

beforeEach(() => {
  authState.isEnabled = true;
  authState.isAuthenticated = true;
  authState.isLoading = false;
  queryState.savedFailed = false;
  loginWithReturnToMock.mockReset();
  loginWithReturnToMock.mockResolvedValue(undefined);
  trackSignInClickMock.mockReset();
  putMock.mockReset();
  putMock.mockImplementation((body: SavedFilters) => ({ unwrap: () => Promise.resolve(body) }));
  window.sessionStorage.clear();
  resetPendingDefaultSearchForTests();
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('DefaultSearchButtons — signed in', () => {
  it('on the saved default: one grayed-out "Default search saved" button, no Reset', async () => {
    await renderSignedIn();
    expect(saved()).toBeDisabled();
    expect(queryByName('Update default search')).not.toBeInTheDocument();
    noReset();
    // The confirmation is the button: no visible message beside it.
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it('a change offers Update, then Reset to its right; back on the default, both go', async () => {
    const store = await renderSignedIn();
    act(() => {
      store.dispatch(setRecentJobsLevel(['entry']));
    });
    expect(update()).toBeEnabled();
    expect(reset()).toBeEnabled();
    expect(
      update().compareDocumentPosition(reset()) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();

    // Back to the saved set, in the other order: on the default again.
    act(() => {
      store.dispatch(setRecentJobsLevel(['senior', 'entry']));
    });
    expect(saved()).toBeDisabled();
    noReset();
  });

  it('Reset puts the SAVED default back, not the site defaults', async () => {
    const user = userEvent.setup();
    const store = await renderSignedIn();
    act(() => {
      store.dispatch(setRecentJobsLevel(['entry']));
      store.dispatch(setRecentJobsTimeWindow('24h'));
      store.dispatch(setRecentJobsLocation(['San Francisco, CA, US']));
    });
    await user.click(reset());

    expect(store.getState().recentJobsFilters.filters).toMatchObject({
      timeWindow: '7d',
      level: ['entry', 'senior'],
      location: undefined,
    });
    expect(saved()).toBeDisabled();
    noReset();
    expect(putMock).not.toHaveBeenCalled();
  });

  it("Reset brings back the saved default's keywords (from its keyword list)", async () => {
    const user = userEvent.setup();
    const list: KeywordList = {
      id: 'kw1',
      name: 'Default search',
      tags: [rust],
      isBuiltin: false,
      position: 0,
    };
    const store = await renderSignedIn(
      { ...SAVED, recentActiveKeywordListId: 'kw1', trendActiveKeywordListId: 'kw1' },
      [list],
      { ...ON_SAVED, searchTags: [rust] }
    );
    expect(saved()).toBeDisabled();
    act(() => {
      store.dispatch(setRecentJobsSearchTags(undefined));
    });
    await user.click(reset());

    expect(store.getState().recentJobsFilters.filters.searchTags).toEqual([rust]);
    expect(saved()).toBeDisabled();
  });

  it('Update saves, and the button becomes "Default search saved" (announced, not shown)', async () => {
    const user = userEvent.setup();
    const store = await renderSignedIn();
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    await user.click(update());

    expect(putMock).toHaveBeenCalledWith(expect.objectContaining({ recentTimeWindow: '24h' }));
    expect(await screen.findByRole('button', { name: 'Default search saved' })).toBeDisabled();
    noReset();
    expect(screen.getByRole('status')).toHaveTextContent('Default search saved');

    act(() => {
      store.dispatch(setRecentJobsTimeWindow('3d'));
    });
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
    expect(update()).toBeEnabled();
    expect(reset()).toBeEnabled();
  });

  it('while saving: "Saving…", grayed out, and no Reset', async () => {
    let finish: (body: SavedFilters) => void = () => {};
    putMock.mockImplementation(() => ({
      unwrap: () => new Promise<SavedFilters>((resolve) => (finish = resolve)),
    }));
    const user = userEvent.setup();
    const store = await renderSignedIn();
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    await user.click(update());

    expect(byName('Saving…')).toBeDisabled();
    noReset();
    await act(async () => finish(putMock.mock.calls[0][0]));
    expect(await screen.findByRole('button', { name: 'Default search saved' })).toBeDisabled();
  });

  it('shows the error and keeps both buttons when the save fails', async () => {
    putMock.mockImplementation(() => ({ unwrap: () => Promise.reject({ status: 500 }) }));
    const user = userEvent.setup();
    const store = await renderSignedIn();
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    await user.click(update());

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Couldn't save your default search. Try again."
    );
    expect(update()).toBeEnabled();
    expect(reset()).toBeEnabled();
  });

  /** The save button, found even while it is invisible. */
  const anySaveButton = () => screen.getByRole('button', { hidden: true });

  it('until the saved filters load: invisible (its space kept), disabled, no Reset', () => {
    const store = createTestStore({
      recentJobsFilters: {
        filters: { timeWindow: '24h', softwareOnly: false },
        hydrated: true,
        userModified: true,
      },
    });
    renderWithProviders(<DefaultSearchButtons />, { store });
    // No label is a guess: nothing is on screen yet, but the slot is.
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(anySaveButton()).toBeInTheDocument();
    expect(anySaveButton()).toBeDisabled();
    expect(anySaveButton()).not.toBeVisible();
  });

  it('a failed saved-filters load: a visible, grayed-out Update, no Reset', async () => {
    queryState.savedFailed = true;
    await renderSignedIn();
    expect(update()).toBeDisabled();
    expect(update()).toBeVisible();
    noReset();
  });

  it('while auth is loading: invisible, disabled, no Reset', async () => {
    authState.isLoading = true;
    const store = await renderSignedIn();
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(anySaveButton()).toBeDisabled();
    expect(anySaveButton()).not.toBeVisible();
  });
});

describe('DefaultSearchButtons — signed out', () => {
  it('on the site defaults: a grayed-out "Save default search", never the check', () => {
    renderSignedOut();
    expect(save()).toBeDisabled();
    expect(queryByName('Default search saved')).not.toBeInTheDocument();
    noReset();
  });

  it('a change offers Save and Reset; Reset goes back to the site defaults', async () => {
    const user = userEvent.setup();
    const store = renderSignedOut();
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
      store.dispatch(setRecentJobsLevel(['entry']));
    });
    expect(save()).toBeEnabled();
    await user.click(reset());

    expect(store.getState().recentJobsFilters.filters).toMatchObject({
      timeWindow: 'all',
      level: undefined,
    });
    expect(save()).toBeDisabled();
    noReset();
  });

  it('a click stores the search, counts the CTA, and goes to sign-in, back to /jobs', async () => {
    const user = userEvent.setup();
    const store = renderSignedOut();
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    await user.click(save());

    const stored = JSON.parse(window.sessionStorage.getItem(PENDING_DEFAULT_SEARCH_KEY) ?? 'null');
    expect(stored).toMatchObject({ v: 1, search: { timeWindow: '24h' } });
    expect(trackSignInClickMock).toHaveBeenCalledWith('save_default_search');
    expect(loginWithReturnToMock).toHaveBeenCalledWith('/jobs');
    expect(putMock).not.toHaveBeenCalled();
  });

  it('a sign-in redirect that throws drops the stored search and says so', async () => {
    loginWithReturnToMock.mockRejectedValue(new Error('popup blocked'));
    const user = userEvent.setup();
    const store = renderSignedOut();
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    await user.click(save());

    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't open sign-in. Try again.");
    expect(window.sessionStorage.getItem(PENDING_DEFAULT_SEARCH_KEY)).toBeNull();
    await waitFor(() => expect(save()).toBeEnabled());
  });
});

describe('DefaultSearchButtons — auth not configured', () => {
  it('no Save button; Reset appears on a change and goes back to the site defaults', async () => {
    authState.isEnabled = false;
    authState.isAuthenticated = false;
    const user = userEvent.setup();
    const store = createTestStore();
    renderWithProviders(<DefaultSearchButtons />, { store });
    expect(screen.queryAllByRole('button')).toHaveLength(0);

    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    expect(screen.getAllByRole('button')).toEqual([reset()]);
    await user.click(reset());
    expect(store.getState().recentJobsFilters.filters.timeWindow).toBe('all');
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });
});
