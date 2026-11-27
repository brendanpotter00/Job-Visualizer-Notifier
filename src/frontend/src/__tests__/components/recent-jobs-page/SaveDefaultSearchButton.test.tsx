import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createTestStore, renderWithProviders } from '../../../test/testUtils';
import type { KeywordList, SavedFilters } from '../../../types';
import {
  PENDING_DEFAULT_SEARCH_KEY,
  resetPendingDefaultSearchForTests,
} from '../../../features/defaultSearch/pendingDefaultSearch';

const { authState, loginWithReturnToMock, putMock, trackSignInClickMock } = vi.hoisted(() => ({
  authState: { isEnabled: true, isAuthenticated: true, isLoading: false },
  loginWithReturnToMock: vi.fn(),
  putMock: vi.fn(),
  trackSignInClickMock: vi.fn(),
}));

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
// cache, so a save's cache write is what grays the button out again.
vi.mock('../../../features/savedFilters/savedFiltersApi', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../features/savedFilters/savedFiltersApi')>();
  return {
    ...actual,
    useUpdateSavedFiltersMutation: () => [putMock, { isLoading: false }],
    useCreateKeywordListMutation: () => [vi.fn(), { isLoading: false }],
    useUpdateKeywordListMutation: () => [vi.fn(), { isLoading: false }],
  };
});

const { savedFiltersApi } = await import('../../../features/savedFilters/savedFiltersApi');
const { SaveDefaultSearchButton } = await import(
  '../../../components/recent-jobs-page/SaveDefaultSearchButton'
);
const {
  setRecentJobsLevel,
  setRecentJobsTimeWindow,
} = await import('../../../features/filters/slices/recentJobsFiltersSlice');

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
const LISTS: KeywordList[] = [];

async function renderSignedIn() {
  const store = createTestStore({
    recentJobsFilters: {
      filters: { timeWindow: '7d', softwareOnly: false, level: ['entry', 'senior'] },
      hydrated: true,
      userModified: false,
    },
  });
  await store.dispatch(savedFiltersApi.util.upsertQueryData('getSavedFilters', undefined, SAVED));
  await store.dispatch(savedFiltersApi.util.upsertQueryData('getKeywordLists', undefined, LISTS));
  renderWithProviders(<SaveDefaultSearchButton />, { store });
  return store;
}

function renderSignedOut() {
  authState.isAuthenticated = false;
  const store = createTestStore();
  renderWithProviders(<SaveDefaultSearchButton />, { store });
  return store;
}

const button = () => screen.getByRole('button', { name: 'Save default search' });

beforeEach(() => {
  authState.isEnabled = true;
  authState.isAuthenticated = true;
  authState.isLoading = false;
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

describe('SaveDefaultSearchButton — signed in', () => {
  it('is grayed out while the filters equal the saved default, and enabled once they differ', async () => {
    const store = await renderSignedIn();
    expect(button()).toBeDisabled();

    act(() => {
      store.dispatch(setRecentJobsLevel(['entry']));
    });
    expect(button()).toBeEnabled();

    // Back to the saved set, in the other order: unchanged again.
    act(() => {
      store.dispatch(setRecentJobsLevel(['senior', 'entry']));
    });
    expect(button()).toBeDisabled();
  });

  it('saves, says so, grays out, and drops the message on the next change', async () => {
    const user = userEvent.setup();
    const store = await renderSignedIn();
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    await user.click(button());

    expect(putMock).toHaveBeenCalledWith(expect.objectContaining({ recentTimeWindow: '24h' }));
    expect(await screen.findByText('Saved default search')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Saved default search');
    expect(button()).toBeDisabled();

    act(() => {
      store.dispatch(setRecentJobsTimeWindow('3d'));
    });
    expect(screen.queryByText('Saved default search')).not.toBeInTheDocument();
    expect(button()).toBeEnabled();
  });

  it('shows the error and stays enabled when the save fails', async () => {
    putMock.mockImplementation(() => ({ unwrap: () => Promise.reject({ status: 500 }) }));
    const user = userEvent.setup();
    const store = await renderSignedIn();
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    await user.click(button());

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Couldn't save your default search. Try again."
    );
    expect(button()).toBeEnabled();
  });

  it('is disabled until the saved filters have loaded', () => {
    const store = createTestStore({
      recentJobsFilters: {
        filters: { timeWindow: '24h', softwareOnly: false },
        hydrated: true,
        userModified: true,
      },
    });
    renderWithProviders(<SaveDefaultSearchButton />, { store });
    expect(button()).toBeDisabled();
  });

  it('is disabled while auth is loading', async () => {
    authState.isLoading = true;
    const store = await renderSignedIn();
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    expect(button()).toBeDisabled();
  });
});

describe('SaveDefaultSearchButton — signed out', () => {
  it('is grayed out at the site defaults', () => {
    renderSignedOut();
    expect(button()).toBeDisabled();
  });

  it('a click stores the search, counts the CTA, and goes to sign-in, back to /jobs', async () => {
    const user = userEvent.setup();
    const store = renderSignedOut();
    act(() => {
      store.dispatch(setRecentJobsTimeWindow('24h'));
    });
    expect(button()).toBeEnabled();
    await user.click(button());

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
    await user.click(button());

    expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't open sign-in. Try again.");
    expect(window.sessionStorage.getItem(PENDING_DEFAULT_SEARCH_KEY)).toBeNull();
    await waitFor(() => expect(button()).toBeEnabled());
  });
});

describe('SaveDefaultSearchButton — auth not configured', () => {
  it('renders nothing', () => {
    authState.isEnabled = false;
    renderWithProviders(<SaveDefaultSearchButton />, { store: createTestStore() });
    expect(screen.queryByRole('button', { name: 'Save default search' })).not.toBeInTheDocument();
  });
});
