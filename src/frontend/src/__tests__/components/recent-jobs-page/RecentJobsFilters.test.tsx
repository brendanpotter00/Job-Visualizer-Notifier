import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, createTestStore } from '../../../test/testUtils';
import { RecentJobsFilters } from '../../../components/recent-jobs-page/RecentJobsFilters';
import { jobsApi } from '../../../features/jobs/jobsApi';
import { SubcategoryRevealProvider } from '../../../features/settings/subcategoryReveal';

const { searchMock } = vi.hoisted(() => ({ searchMock: vi.fn() }));

// Whether the component sees a signed-in user. Mutable so a single mock can
// serve both the anonymous default (what every test below assumed before custom
// companies existed) and the signed-in case.
const { authState } = vi.hoisted(() => ({ authState: { isAuthenticated: false } }));

// The custom-companies feature flag, read once at module load — a getter keeps
// it flippable per test.
const { flagState } = vi.hoisted(() => ({ flagState: { isEnabled: true } }));
vi.mock('../../../config/customCompanies', () => ({
  CUSTOM_COMPANIES_CONFIG: {
    get isEnabled() {
      return flagState.isEnabled;
    },
    isDiscoveryProgressEnabled: false,
  },
}));

// Only `useAuth` is overridden — `NotAuthenticatedError` from the same module is
// what `getTokenOrNull` narrows on, so the real exports have to survive.
vi.mock('../../../features/auth/useAuth', async (importActual) => {
  const actual = await importActual<typeof import('../../../features/auth/useAuth')>();
  return {
    ...actual,
    useAuth: () => ({
      isEnabled: true,
      isAuthenticated: authState.isAuthenticated,
      isLoading: false,
      user: null,
      login: vi.fn(),
      logout: vi.fn(),
      getToken: vi.fn(),
    }),
  };
});

// The Location control is the server-backed AsyncMultiSelectAutocomplete; keep
// the real `locationsApi` object (store wiring needs its reducer/middleware)
// but override the hook so option-selection tests don't depend on a real
// network round-trip.
vi.mock('../../../features/locations/locationsApi', async (importActual) => {
  const actual = await importActual<typeof import('../../../features/locations/locationsApi')>();
  return { ...actual, useSearchLocationsQuery: (...args: unknown[]) => searchMock(...args) };
});

beforeEach(() => {
  searchMock.mockReset();
  searchMock.mockReturnValue({ data: [], isFetching: false, isError: false, error: undefined });
  authState.isAuthenticated = false;
  flagState.isEnabled = true;
});

interface PreloadedOverrides {
  searchTags?: { text: string; mode: 'include' | 'exclude' }[];
  location?: string[];
  company?: string[];
  softwareOnly?: boolean;
}

/**
 * The Company dropdown's options come from `selectRecentCompanyOptions` — the
 * static company config intersected with the user's enabled-companies
 * preference — NOT from jobs in the RTK Query cache. The page filters
 * server-side now, so the rows on screen are already narrowed by every other
 * active filter and deriving options from them would make the dropdown shrink
 * as the reader searched. Seeding the preference is therefore the only setup
 * the dropdown needs; no jobs cache is involved.
 */
async function seedRecentStore(
  overrides: PreloadedOverrides = {},
  enabledCompanyIds: string[] = ['spacex']
) {
  return createTestStore({
    recentJobsFilters: {
      filters: {
        // Pin a non-default window so the reset test proves the slice's own
        // default ('all' — see `recentJobsFiltersSlice.ts`) is what gets restored,
        // not what was preloaded.
        timeWindow: '30d',
        softwareOnly: false,
        ...overrides,
      },
    },
    enabledCompanies: {
      ids: enabledCompanyIds,
      autoEnroll: false,
      loading: false,
      error: null,
      activeLoadRequestId: null,
    },
  });
}

describe('RecentJobsFilters', () => {
  it('renders the merged KeywordFilterInput, TimeWindowSelect, Company, Location, Reset button', async () => {
    const store = await seedRecentStore();
    renderWithProviders(<RecentJobsFilters />, { store });

    expect(screen.getByRole('combobox', { name: 'Keywords' })).toBeInTheDocument();
    expect(screen.getAllByText('Time Window').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Company').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Location').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: /reset filters/i })).toBeInTheDocument();
  });

  it('dispatches setRecentJobsTimeWindow when TimeWindow option selected', async () => {
    const store = await seedRecentStore();
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    // Resolve the TimeWindowSelect by its accessible name rather than by
    // current textContent — the latter flakes the instant the default changes.
    const timeWindowCombo = screen.getByRole('combobox', { name: 'Time Window' });
    await user.click(timeWindowCombo);
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: '7 days' }));
    expect(store.getState().recentJobsFilters.filters.timeWindow).toBe('7d');
  });

  it('dispatches addRecentJobsSearchTag on Enter in search input', async () => {
    const store = await seedRecentStore();
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    const input = screen.getByRole('combobox', { name: 'Keywords' });
    await user.click(input);
    await user.type(input, 'senior{enter}');

    const tags = store.getState().recentJobsFilters.filters.searchTags;
    expect(tags).toEqual([{ text: 'senior', mode: 'include' }]);
  });

  it('dispatches removeRecentJobsSearchTag when chip removed via Backspace', async () => {
    const store = await seedRecentStore({
      searchTags: [{ text: 'senior', mode: 'include' }],
    });
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    const input = screen.getByRole('combobox', { name: 'Keywords' });
    await user.click(input);
    await user.keyboard('{Backspace}');

    const tags = store.getState().recentJobsFilters.filters.searchTags;
    expect(tags === undefined || tags.length === 0).toBe(true);
  });

  it('dispatches toggleRecentJobsSearchTagMode when chip clicked', async () => {
    const store = await seedRecentStore({
      searchTags: [{ text: 'senior', mode: 'include' }],
    });
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    await user.click(screen.getByText('senior'));
    const tags = store.getState().recentJobsFilters.filters.searchTags;
    expect(tags?.[0].mode).toBe('exclude');
  });

  it('dispatches addRecentJobsCompany (resolves name->id) when company option selected', async () => {
    const store = await seedRecentStore();
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    const companyInput = screen.getByPlaceholderText('Select company...');
    await user.click(companyInput);
    const listbox = await screen.findByRole('listbox');
    const firstOption = within(listbox).getAllByRole('option')[0];
    expect(firstOption).toBeDefined();
    await user.click(firstOption);

    // Should store company IDs (not names). The only enabled company is 'spacex'.
    expect(store.getState().recentJobsFilters.filters.company).toContain('spacex');
  });

  it('offers every followed company as an option, not just ones with jobs on screen', async () => {
    // Regression guard for the server-side-filtering cutover: options are the
    // user's enabled set, so the list stays stable no matter how narrow the
    // current result set is (here: no jobs loaded at all).
    const store = await seedRecentStore({}, ['spacex', 'airtable']);
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    await user.click(screen.getByPlaceholderText('Select company...'));
    const listbox = await screen.findByRole('listbox');
    const optionNames = within(listbox)
      .getAllByRole('option')
      .map((o) => o.textContent);
    // Sorted by display name.
    expect(optionNames).toEqual(['Airtable', 'SpaceX']);
  });

  it('dispatches addRecentJobsLocation when location option selected', async () => {
    // The Location control sources its options from the server-backed search
    // hook, not from loaded jobs — mock it with a couple of canned rows.
    searchMock.mockReturnValue({
      data: [
        {
          id: 1,
          canonicalName: 'Hawthorne, CA, US',
          kind: 'city',
          city: 'Hawthorne',
          region: 'CA',
          country: 'US',
          remoteScope: null,
        },
        {
          id: 2,
          canonicalName: 'Remote (US)',
          kind: 'remote',
          city: null,
          region: null,
          country: 'US',
          remoteScope: 'us',
        },
      ],
      isFetching: false,
      isError: false,
      error: undefined,
    });
    const store = await seedRecentStore();
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    const locationInput = screen.getByPlaceholderText('Search location...');
    await user.click(locationInput);
    const listbox = await screen.findByRole('listbox');
    const firstOption = within(listbox).getAllByRole('option')[0];
    expect(firstOption).toBeDefined();
    const chosenLocation = firstOption.textContent ?? '';
    await user.click(firstOption);

    expect(store.getState().recentJobsFilters.filters.location).toContain(chosenLocation);
  });

  it('clears searchTags via the merged control\'s "None" option', async () => {
    // Seed hand-added tags; opening the merged Keywords control offers a "None"
    // row. With no keyword lists loaded, selecting it clears the slice's tags.
    const store = await seedRecentStore({
      searchTags: [{ text: 'senior', mode: 'include' }],
    });
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    await user.click(screen.getByRole('combobox', { name: 'Keywords' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'None' }));

    const tags = store.getState().recentJobsFilters.filters.searchTags;
    expect(tags === undefined || tags.length === 0).toBe(true);
  });

  it('dispatches resetRecentJobsFilters when Reset Filters button clicked', async () => {
    const store = await seedRecentStore({
      searchTags: [{ text: 'senior', mode: 'include' }],
      location: ['SF'],
      company: ['spacex'],
    });
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    await user.click(screen.getByRole('button', { name: /reset filters/i }));

    const filters = store.getState().recentJobsFilters.filters;
    // After reset, the slice's initial state should be restored (timeWindow='all',
    // all other fields undefined/false).
    expect(filters.timeWindow).toBe('all');
    expect(filters.searchTags).toBeUndefined();
    expect(filters.location).toBeUndefined();
    expect(filters.company).toBeUndefined();
  });

  it('dispatches removeRecentJobsCompany when a selected company chip is removed', async () => {
    const store = await seedRecentStore({ company: ['spacex'] });
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    // Find the Company field's chip (SpaceX by display name). The chip has a
    // delete button (CancelIcon) rendered inside it.
    const spacexChip = screen.getByText('SpaceX').closest('.MuiChip-root') as HTMLElement;
    expect(spacexChip).not.toBeNull();
    const deleteBtn = within(spacexChip).getByTestId('CancelIcon');
    await user.click(deleteBtn);

    const company = store.getState().recentJobsFilters.filters.company;
    expect(company === undefined || company.length === 0).toBe(true);
  });

  it('dispatches removeRecentJobsLocation when a selected location chip is removed', async () => {
    const store = await seedRecentStore({ location: ['Hawthorne, CA'] });
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    const locChip = screen.getByText('Hawthorne, CA').closest('.MuiChip-root') as HTMLElement;
    expect(locChip).not.toBeNull();
    const deleteBtn = within(locChip).getByTestId('CancelIcon');
    await user.click(deleteBtn);

    const loc = store.getState().recentJobsFilters.filters.location;
    expect(loc === undefined || loc.length === 0).toBe(true);
  });

  it('preserves graphFilters slice when dispatching a recent-only action (filter independence)', async () => {
    const store = await seedRecentStore();
    const graphBefore = store.getState().graphFilters;
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    const timeWindowCombo = screen.getByRole('combobox', { name: 'Time Window' });
    await user.click(timeWindowCombo);
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: '7 days' }));

    // An action on recentJobsFilters should NOT touch the graph slice.
    expect(store.getState().graphFilters).toBe(graphBefore);
  });
});

/**
 * The subcategory tree, on the bar that is SERVER-filtered.
 *
 * The facets-seeding idiom is NEW in this file: #252's rewrite removed the
 * `upsertQueryData` call it used to carry (the endpoint it seeded, `getAllJobs`,
 * no longer exists). The reveal flag is seeded the same way, and the component
 * is rendered INSIDE `<SubcategoryRevealProvider>` — matching how `App.tsx`
 * mounts it. `renderWithProviders` takes NO `wrapper` option (its
 * `CustomRenderOptions` is `Omit<RenderOptions, 'wrapper'>`), so the provider
 * wraps the ELEMENT, not the options.
 */
describe('RecentJobsFilters — the subcategory tree', () => {
  const FACETS = {
    categories: [
      { slug: 'software_engineering', label: 'Software Engineering', sortOrder: 0 },
      { slug: 'growth', label: 'Growth', sortOrder: 1 },
    ],
    levels: [{ slug: 'senior', label: 'Senior', sortOrder: 0, parentSlug: null }],
    subcategories: [
      { slug: 'backend', label: 'Backend', sortOrder: 1, parentSlug: 'software_engineering' },
      { slug: 'frontend', label: 'Frontend', sortOrder: 6, parentSlug: 'software_engineering' },
    ],
  };

  async function seedFacetsAndFlag(
    store: ReturnType<typeof createTestStore>,
    { reveal }: { reveal: boolean }
  ) {
    await store.dispatch(jobsApi.util.upsertQueryData('getFacets', undefined, FACETS));
    await store.dispatch(
      jobsApi.util.upsertQueryData('getPublicSettings', undefined, {
        sweSubcategoriesEnabled: reveal,
      })
    );
  }

  function renderBar(store: ReturnType<typeof createTestStore>) {
    return renderWithProviders(
      <SubcategoryRevealProvider>
        <RecentJobsFilters />
      </SubcategoryRevealProvider>,
      { store }
    );
  }

  it('(a) exposes the control as a combobox named "Job category"', async () => {
    const store = await seedRecentStore();
    await seedFacetsAndFlag(store, { reveal: true });
    renderBar(store);

    expect(screen.getByRole('combobox', { name: 'Job category' })).toBeInTheDocument();
  });

  it('(b) shows a chevron on the SWE row and expands to its children', async () => {
    const store = await seedRecentStore();
    await seedFacetsAndFlag(store, { reveal: true });
    const user = userEvent.setup();
    renderBar(store);

    await user.click(screen.getByRole('combobox', { name: 'Job category' }));
    const listbox = await screen.findByRole('listbox');
    const swe = within(listbox).getByRole('option', { name: /Software Engineering/ });

    await user.click(within(swe).getByRole('button'));

    expect(within(listbox).getByRole('option', { name: /Backend/ })).toBeInTheDocument();
    expect(within(listbox).getByRole('option', { name: /Frontend/ })).toBeInTheDocument();
    // Growth has no children, so it has no chevron.
    const growth = within(listbox).getByRole('option', { name: /Growth/ });
    expect(within(growth).queryByRole('button')).toBeNull();
  });

  it('(c) ticking a child dispatches BOTH setters onto the slice', async () => {
    const store = await seedRecentStore();
    await seedFacetsAndFlag(store, { reveal: true });
    const user = userEvent.setup();
    renderBar(store);

    await user.click(screen.getByRole('combobox', { name: 'Job category' }));
    const listbox = await screen.findByRole('listbox');
    const swe = within(listbox).getByRole('option', { name: /Software Engineering/ });
    await user.click(within(swe).getByRole('button'));
    await user.click(within(listbox).getByRole('option', { name: /Backend/ }));

    const filters = store.getState().recentJobsFilters.filters;
    expect(filters.subcategory).toEqual(['backend']);
    // The parent is auto-checked, so the two dimensions stay consistent.
    expect(filters.category).toEqual(['software_engineering']);
  });

  it('(d) shows NO chevron with the flag off', async () => {
    const store = await seedRecentStore();
    await seedFacetsAndFlag(store, { reveal: false });
    const user = userEvent.setup();
    renderBar(store);

    await user.click(screen.getByRole('combobox', { name: 'Job category' }));
    const listbox = await screen.findByRole('listbox');

    expect(within(listbox).queryByRole('button')).toBeNull();
    expect(within(listbox).queryByRole('option', { name: /Backend/ })).toBeNull();
  });

  it('shows NO chevron when the flag is ON but the facets catalog is empty', async () => {
    // The warm-cache case the `?? []` gate exists for: a facets response seeded
    // before the dimension was published, plus a freshly flipped flag, must not
    // render a parent that expands into nothing.
    const store = await seedRecentStore();
    await store.dispatch(
      jobsApi.util.upsertQueryData('getFacets', undefined, {
        categories: FACETS.categories,
        levels: FACETS.levels,
        subcategories: [],
      })
    );
    await store.dispatch(
      jobsApi.util.upsertQueryData('getPublicSettings', undefined, {
        sweSubcategoriesEnabled: true,
      })
    );
    const user = userEvent.setup();
    renderBar(store);

    await user.click(screen.getByRole('combobox', { name: 'Job category' }));
    const listbox = await screen.findByRole('listbox');

    expect(within(listbox).queryByRole('button')).toBeNull();
  });
});
