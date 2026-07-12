import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, createTestStore } from '../../../test/testUtils';
import { RecentJobsFilters } from '../../../components/recent-jobs-page/RecentJobsFilters';
import { jobsApi } from '../../../features/jobs/jobsApi';
import type { Job } from '../../../types';

const { searchMock } = vi.hoisted(() => ({ searchMock: vi.fn() }));

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
});

// getAllJobs has an onCacheEntryAdded side effect that iterates ALL companies
// and fetches via getClientForATS (non-backend-scraper) and
// fetchJobsForCompanies (backend-scraper, batched). In a jsdom test with no
// fetch available those calls throw and clobber our seeded
// byCompanyId['spacex'] with an empty array, which breaks Location/Company
// dropdown assertions. Stub both entry points so they return pending
// Promises that resolve only on abort — RTK Query aborts on
// cacheEntryRemoved, so the seeded cache stays intact for the test's
// lifetime and the stub cleans up automatically at teardown.
const pendingUntilAbort = (signal?: AbortSignal) =>
  new Promise((resolve) => {
    const done = () => resolve(undefined);
    if (signal?.aborted) return done();
    signal?.addEventListener('abort', done, { once: true });
  });

vi.mock('../../../api/utils', async () => {
  const actual = await vi.importActual<typeof import('../../../api/utils')>('../../../api/utils');
  return {
    ...actual,
    getClientForATS: () => ({
      fetchJobs: ({ signal }: { signal?: AbortSignal } = {}) =>
        pendingUntilAbort(signal).then(() => ({
          jobs: [],
          metadata: { totalCount: 0, fetchedAt: '2020-01-01T00:00:00Z' },
        })),
    }),
  };
});

vi.mock('../../../api/clients/backendScraperClient', async () => {
  const actual = await vi.importActual<typeof import('../../../api/clients/backendScraperClient')>(
    '../../../api/clients/backendScraperClient'
  );
  return {
    ...actual,
    fetchJobsForCompanies: (_ids: string[], opts: { signal?: AbortSignal } = {}) =>
      pendingUntilAbort(opts.signal).then(() => ({})),
  };
});

// Compute job timestamps relative to "now" so seeded jobs always fall inside
// the seedRecentStore default 30d timeWindow, even as the clock advances. The
// previous hardcoded '2026-04-18' rotted past the boundary 30 days after this
// test was written and broke CI.
const NOW_MS = Date.now();
const ONE_HOUR_MS = 60 * 60 * 1000;
const ONE_DAY_MS = 24 * ONE_HOUR_MS;
const recentISO = (msAgo: number) => new Date(NOW_MS - msAgo).toISOString();

const seededJobs: Job[] = [
  {
    id: 'j1',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Senior Software Engineer',
    createdAt: recentISO(ONE_DAY_MS),
    firstSeenAt: recentISO(ONE_DAY_MS),
    url: 'https://example.com/j1',
    location: 'Hawthorne, CA',
    locations: [
      {
        canonicalName: 'Hawthorne, CA, US',
        kind: 'city',
        city: 'Hawthorne',
        region: 'CA',
        country: 'US',
        remoteScope: null,
        isPrimary: true,
      },
    ],
    department: 'Engineering',
    raw: {},
  },
  {
    id: 'j2',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Recruiter',
    createdAt: recentISO(ONE_DAY_MS - ONE_HOUR_MS),
    firstSeenAt: recentISO(ONE_DAY_MS - ONE_HOUR_MS),
    url: 'https://example.com/j2',
    location: 'Remote',
    locations: [
      {
        canonicalName: 'Remote (US)',
        kind: 'remote',
        city: null,
        region: null,
        country: 'US',
        remoteScope: 'us',
        isPrimary: true,
      },
    ],
    department: 'People',
    raw: {},
  },
];

interface PreloadedOverrides {
  searchTags?: { text: string; mode: 'include' | 'exclude' }[];
  location?: string[];
  company?: string[];
  softwareOnly?: boolean;
}

async function seedRecentStore(overrides: PreloadedOverrides = {}, jobs: Job[] = seededJobs) {
  const store = createTestStore({
    recentJobsFilters: {
      filters: {
        // Preload a wide time window so the default '14d' doesn't filter
        // seeded jobs out and make Location/Company dropdowns empty.
        timeWindow: '30d',
        softwareOnly: false,
        ...overrides,
      },
    },
  });
  // upsertQueryData dispatches a thunk — await it so the cache is fulfilled
  // before selectors read from it.
  await store.dispatch(
    jobsApi.util.upsertQueryData('getAllJobs', undefined, {
      byCompanyId: { spacex: jobs },
      metadata: {
        spacex: {
          totalCount: jobs.length,
          fetchedAt: recentISO(0),
        },
      },
      errors: {},
      progress: { completed: 1, total: 1, companies: [] },
      isStreaming: false,
    })
  );
  return store;
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

    // Should store company IDs (not names). The seeded company is 'spacex'.
    expect(store.getState().recentJobsFilters.filters.company).toContain('spacex');
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
    // After reset, the slice's initial state should be restored (timeWindow='14d',
    // all other fields undefined/false).
    expect(filters.timeWindow).toBe('14d');
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
