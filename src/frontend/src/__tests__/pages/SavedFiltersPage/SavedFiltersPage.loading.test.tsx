import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import type { KeywordList, SavedFilters } from '../../../types';

// First-load placeholders for the Saved Filters page: the whole page while the
// auth SDK resolves, then each independently-loading section on its own.

const mockAuthState = {
  isEnabled: true,
  isAuthenticated: true,
  isLoading: false,
  user: { name: 'Test' },
  login: vi.fn(),
  logout: vi.fn(),
  getToken: vi.fn(async () => null),
};
vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

// The heavy sibling sections are stubbed; their own loading states are covered
// by their own tests.
vi.mock('../../../components/saved-filters/EnabledCompaniesSection', () => ({
  EnabledCompaniesSection: () => <div data-testid="enabled-companies-stub" />,
}));
vi.mock('../../../components/saved-filters/KeywordListsEditor', () => ({
  KeywordListsEditor: () => <div data-testid="keyword-lists-stub" />,
}));
vi.mock('../../../components/saved-filters/TimeWindowDefaults', () => ({
  TimeWindowDefaults: () => <div data-testid="time-windows-stub" />,
}));
vi.mock('../../../components/saved-filters/CategoryLevelDefaults', () => ({
  CategoryLevelDefaults: () => <div data-testid="category-level-stub" />,
}));
vi.mock('../../../components/saved-filters/LocationDefaultsEditor', () => ({
  LocationDefaultsEditor: () => <div data-testid="locations-stub" />,
}));

const PREFS: SavedFilters = {
  recentTimeWindow: 'all',
  trendTimeWindow: '90d',
  locations: [],
  category: [],
  level: [],
  subcategory: [],
  recentActiveKeywordListId: null,
  trendActiveKeywordListId: null,
};

let prefsData: SavedFilters | undefined;
let listsData: KeywordList[] | undefined;

vi.mock('../../../features/savedFilters/savedFiltersApi', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../../../features/savedFilters/savedFiltersApi')>();
  return {
    ...actual,
    useGetSavedFiltersQuery: () => ({
      data: prefsData,
      isLoading: prefsData === undefined,
      isError: false,
      error: undefined,
      refetch: vi.fn(),
    }),
    useGetKeywordListsQuery: () => ({
      data: listsData,
      isLoading: listsData === undefined,
      isError: false,
      error: undefined,
      refetch: vi.fn(),
    }),
    useUpdateSavedFiltersMutation: () => [vi.fn(), { isLoading: false }],
  };
});

const { SavedFiltersPage } = await import('../../../pages/SavedFiltersPage/SavedFiltersPage');

describe('SavedFiltersPage — first-load skeletons', () => {
  beforeEach(() => {
    mockAuthState.isLoading = false;
    mockAuthState.isAuthenticated = true;
    prefsData = undefined;
    listsData = undefined;
  });

  it('shows the whole-page skeleton (every section, in order) while auth resolves', () => {
    mockAuthState.isLoading = true;
    renderWithProviders(<SavedFiltersPage />);

    const region = screen.getByRole('status', { name: 'Loading your saved filters…' });
    const sections = within(region).getAllByTestId('saved-filters-section-skeleton');
    expect(sections.map((s) => s.textContent)).toEqual([
      'Default time windows',
      'Default job category & level',
      'Default locations',
      'Keyword lists',
      'Saved companies',
    ]);
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    // The page's h1 arrives with the page, not with the placeholder.
    expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument();
    expect(screen.queryByTestId('enabled-companies-stub')).not.toBeInTheDocument();
  });

  it('holds the three prefs sections and the keyword lists while both requests load', () => {
    renderWithProviders(<SavedFiltersPage />);

    expect(screen.getByRole('heading', { name: 'Saved Filters', level: 1 })).toBeInTheDocument();
    const prefs = screen.getByRole('status', { name: 'Loading your saved filters…' });
    expect(within(prefs).getAllByTestId('saved-filters-section-skeleton')).toHaveLength(3);
    const lists = screen.getByRole('status', { name: 'Loading keyword lists…' });
    expect(within(lists).getByText('Keyword lists')).toBeInTheDocument();
    // The independently-loading companies section is already mounted.
    expect(screen.getByTestId('enabled-companies-stub')).toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('replaces only the prefs placeholder once prefs land', async () => {
    prefsData = PREFS;
    renderWithProviders(<SavedFiltersPage />);

    expect(await screen.findByTestId('time-windows-stub')).toBeInTheDocument();
    expect(screen.getByTestId('category-level-stub')).toBeInTheDocument();
    expect(screen.getByTestId('locations-stub')).toBeInTheDocument();
    expect(
      screen.queryByRole('status', { name: 'Loading your saved filters…' })
    ).not.toBeInTheDocument();
    expect(screen.getByRole('status', { name: 'Loading keyword lists…' })).toBeInTheDocument();
  });

  it('renders no skeleton once everything has loaded', async () => {
    prefsData = PREFS;
    listsData = [];
    renderWithProviders(<SavedFiltersPage />);

    expect(await screen.findByTestId('keyword-lists-stub')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
