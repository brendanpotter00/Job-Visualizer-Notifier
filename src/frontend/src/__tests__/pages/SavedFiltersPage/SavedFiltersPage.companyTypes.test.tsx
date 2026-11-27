import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createTestStore, renderWithProviders } from '../../../test/testUtils';
import type { KeywordList, SavedFilters } from '../../../types';

/**
 * The "Default company types" section. The field is OPTIONAL on
 * `SavedFilters`: absent means the backend does not know it (an older backend
 * during the deploy window). Then the section is hidden and no PUT carries the
 * key, because that backend 422s unknown keys.
 */

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: true,
    isLoading: false,
    user: { name: 'Test' },
    login: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn(async () => null),
  }),
}));

vi.mock('../../../components/saved-filters/EnabledCompaniesSection', () => ({
  EnabledCompaniesSection: () => <div data-testid="enabled-companies-stub" />,
}));
vi.mock('../../../components/saved-filters/KeywordListsEditor', () => ({
  KeywordListsEditor: () => <div data-testid="keyword-lists-stub" />,
}));

/** An older backend: no `companyCategory` key. */
const OLD_PREFS: SavedFilters = {
  recentTimeWindow: 'all',
  trendTimeWindow: '90d',
  locations: [],
  category: [],
  level: [],
  subcategory: [],
  recentActiveKeywordListId: null,
  trendActiveKeywordListId: null,
};

const NEW_PREFS: SavedFilters = { ...OLD_PREFS, companyCategory: ['big_tech'] };

const updateMock = vi.fn();
let serverPrefs: SavedFilters = NEW_PREFS;
const lists: KeywordList[] = [];

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

const { SavedFiltersPage } = await import('../../../pages/SavedFiltersPage/SavedFiltersPage');

function renderPage() {
  const store = createTestStore();
  renderWithProviders(<SavedFiltersPage />, { store });
  return store;
}

describe('SavedFiltersPage — Default company types', () => {
  beforeEach(() => {
    serverPrefs = NEW_PREFS;
    updateMock.mockReset();
    updateMock.mockImplementation((body: SavedFilters) => ({
      unwrap: () => Promise.resolve(body),
    }));
  });

  it('renders the section with the stored types when the backend sends the field', async () => {
    renderPage();
    expect(await screen.findByText('Default company types')).toBeInTheDocument();
    expect(
      screen.getByText(
        'Applied when you open Recent Job Postings. Only jobs at these kinds of companies are shown.'
      )
    ).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Company type' })).toHaveTextContent('Big Tech');
    expect(screen.getByRole('button', { name: 'Save company types' })).toBeDisabled();
  });

  it('saves a change: the PUT carries companyCategory and the Recent slice gets it', async () => {
    const user = userEvent.setup();
    const store = renderPage();

    await user.click(await screen.findByRole('combobox', { name: 'Company type' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'Fintech & Trading' }));
    await user.keyboard('{Escape}');

    const save = screen.getByRole('button', { name: 'Save company types' });
    await waitFor(() => expect(save).toBeEnabled());
    await user.click(save);

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(updateMock.mock.calls[0][0].companyCategory).toEqual(['big_tech', 'fintech']);
    await waitFor(() =>
      expect(store.getState().recentJobsFilters.filters.companyCategory).toEqual([
        'big_tech',
        'fintech',
      ])
    );
    // Never the graph slice: the trend page is one company.
    expect('companyCategory' in store.getState().graphFilters.filters).toBe(false);
  });

  it("another section's save still carries companyCategory (full replace)", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole('combobox', { name: 'Level' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getAllByRole('option')[0]);
    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', { name: /Save job category & level/i }));

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(updateMock.mock.calls[0][0].companyCategory).toEqual(['big_tech']);
  });

  it('is hidden on an older backend, and no PUT carries the key', async () => {
    serverPrefs = OLD_PREFS;
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText('Default job category & level')).toBeInTheDocument();
    expect(screen.queryByText('Default company types')).not.toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Company type' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('combobox', { name: 'Level' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getAllByRole('option')[0]);
    await user.keyboard('{Escape}');
    await user.click(screen.getByRole('button', { name: /Save job category & level/i }));

    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(updateMock.mock.calls[0][0]).not.toHaveProperty('companyCategory');
  });
});
