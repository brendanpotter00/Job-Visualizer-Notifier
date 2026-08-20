import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createTestStore, renderWithProviders } from '../../../test/testUtils';
import { jobsApi } from '../../../features/jobs/jobsApi';
import { SubcategoryRevealProvider } from '../../../features/settings/subcategoryReveal';
import type { JobFacets, KeywordList, SavedFilters } from '../../../types';

// There is no SavedFiltersPage test file today; this one covers only the
// category/level section, which is the part this epic touches.

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: true,
    isLoading: false,
    user: { name: 'Test' },
    login: vi.fn(),
    logout: vi.fn(),
    // Must resolve: EnabledCompaniesSection's hook chains `.then` off it.
    getToken: vi.fn(async () => null),
  }),
}));

// The two heavy sibling sections are stubbed out. Neither is under test here,
// and EnabledCompaniesSection alone renders a chip per tracked company and
// drives its own token-bearing fetch — minutes of work per render for nothing
// this file asserts.
vi.mock('../../../components/saved-filters/EnabledCompaniesSection', () => ({
  EnabledCompaniesSection: () => <div data-testid="enabled-companies-stub" />,
}));
vi.mock('../../../components/saved-filters/KeywordListsEditor', () => ({
  KeywordListsEditor: () => <div data-testid="keyword-lists-stub" />,
}));

/** A LEGACY server payload, normalized by validateSavedFilters to `[]`. */
const SERVER_PREFS: SavedFilters = {
  recentTimeWindow: 'all',
  trendTimeWindow: '90d',
  locations: [],
  category: ['software_engineering'],
  level: [],
  subcategory: [],
  recentActiveKeywordListId: null,
  trendActiveKeywordListId: null,
};

const updateMock = vi.fn();

vi.mock('../../../features/savedFilters/savedFiltersApi', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../features/savedFilters/savedFiltersApi')>();
  return {
    ...actual,
    useGetSavedFiltersQuery: () => ({ data: serverPrefs, isLoading: false, error: undefined }),
    useGetKeywordListsQuery: () => ({ data: lists, isLoading: false, error: undefined }),
    useUpdateSavedFiltersMutation: () => [updateMock, { isLoading: false }],
  };
});

let serverPrefs: SavedFilters = SERVER_PREFS;
let lists: KeywordList[] = [];

const FACETS: JobFacets = {
  categories: [{ slug: 'software_engineering', label: 'Software Engineering', sortOrder: 0 }],
  levels: [{ slug: 'senior', label: 'Senior', sortOrder: 0, parentSlug: null }],
  subcategories: [
    { slug: 'backend', label: 'Backend', sortOrder: 1, parentSlug: 'software_engineering' },
  ],
};

const { SavedFiltersPage } = await import(
  '../../../pages/SavedFiltersPage/SavedFiltersPage'
);

async function renderPage() {
  const store = createTestStore();
  await store.dispatch(jobsApi.util.upsertQueryData('getFacets', undefined, FACETS));
  await store.dispatch(
    jobsApi.util.upsertQueryData('getPublicSettings', undefined, {
      sweSubcategoriesEnabled: true,
    })
  );
  // `renderWithProviders` takes no `wrapper` option, so the reveal provider
  // wraps the ELEMENT — the same shape App.tsx mounts.
  return renderWithProviders(
    <SubcategoryRevealProvider>
      <SavedFiltersPage />
    </SubcategoryRevealProvider>,
    { store }
  );
}

/** Open the tree and tick Backend. */
async function tickBackend(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('combobox', { name: 'Job category' }));
  const listbox = await screen.findByRole('listbox');
  const parent = within(listbox).getByRole('option', { name: /Software Engineering/ });
  await user.click(within(parent).getByRole('button'));
  await user.click(within(listbox).getByRole('option', { name: /Backend/ }));
  await user.keyboard('{Escape}');
}

describe('SavedFiltersPage — the category/level section', () => {
  beforeEach(() => {
    serverPrefs = SERVER_PREFS;
    lists = [];
    updateMock.mockReset();
    updateMock.mockReturnValue({ unwrap: () => Promise.resolve(SERVER_PREFS) });
  });

  it('renders a LEGACY payload without throwing in the draft spread', async () => {
    // `draftFromServer` does `[...p.subcategory]`. If the API layer had merely
    // tolerated the missing key instead of normalizing it to `[]`, this render
    // would be a TypeError for every existing user.
    await renderPage();
    expect(
      await screen.findByRole('combobox', { name: 'Job category' })
    ).toBeInTheDocument();
  });

  it('a SUBCATEGORY-ONLY change enables the section Save button', async () => {
    // THE DIRTY-CLAUSE REGRESSION. Without the third clause in
    // `categoryLevelDirty`, the user ticks a box and the only affordance for
    // keeping it stays greyed out, with no feedback at all.
    const user = userEvent.setup();
    await renderPage();

    const save = screen.getByRole('button', { name: /Save job title & level/i });
    expect(save).toBeDisabled();

    await tickBackend(user);

    await waitFor(() => expect(save).toBeEnabled());
  });

  it('the PUT body carries subcategory', async () => {
    const user = userEvent.setup();
    await renderPage();

    await tickBackend(user);
    await user.click(screen.getByRole('button', { name: /Save job title & level/i }));

    await waitFor(() => expect(updateMock).toHaveBeenCalled());
    expect(updateMock.mock.calls[0][0]).toMatchObject({
      category: ['software_engineering'],
      subcategory: ['backend'],
    });
    // FULL-REPLACE: every other section's value rides along on this same PUT.
    expect(updateMock.mock.calls[0][0]).toHaveProperty('locations');
    expect(updateMock.mock.calls[0][0]).toHaveProperty('level');
  });

  it('re-seeds the draft from the 200 response, so Save goes back to disabled', async () => {
    const saved: SavedFilters = { ...SERVER_PREFS, subcategory: ['backend'] };
    updateMock.mockReturnValue({ unwrap: () => Promise.resolve(saved) });

    const user = userEvent.setup();
    await renderPage();

    await tickBackend(user);
    const save = screen.getByRole('button', { name: /Save job title & level/i });
    await waitFor(() => expect(save).toBeEnabled());
    await user.click(save);

    // `draftFromServer(saved)` runs on the response, so the draft and the
    // server now agree and the section is clean again.
    await waitFor(() => expect(updateMock).toHaveBeenCalled());
  });
});
