import { describe, it, expect, vi } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, createTestStore } from '../../../test/testUtils';
import { RecentJobsFilters } from '../../../components/recent-jobs-page/RecentJobsFilters';
import { jobsApi } from '../../../features/jobs/jobsApi';
import type { Job } from '../../../types';

// getAllJobs has an onCacheEntryAdded side effect that iterates ALL companies
// and fetches via getClientForATS. In a jsdom test with no fetch available
// those fetches throw and clobber our seeded byCompanyId['spacex'] with an
// empty array, which breaks Location/Company dropdown assertions.
// Stub getClientForATS so each "fetch" returns a Promise that only resolves
// when the request is aborted (RTK Query aborts on cacheEntryRemoved). This
// keeps the seeded cache intact during the test and cleans up automatically
// when the store is discarded at test-end.
vi.mock('../../../api/utils', async () => {
  const actual = await vi.importActual<typeof import('../../../api/utils')>(
    '../../../api/utils'
  );
  return {
    ...actual,
    getClientForATS: () => ({
      fetchJobs: ({ signal }: { signal?: AbortSignal } = {}) =>
        new Promise((resolve) => {
          const done = () =>
            resolve({
              jobs: [],
              metadata: { totalCount: 0, fetchedAt: '2020-01-01T00:00:00Z' },
            });
          if (signal?.aborted) return done();
          signal?.addEventListener('abort', done, { once: true });
          // If no signal is provided, the promise remains pending for the
          // test's lifetime, which is fine — no timers are leaked.
        }),
    }),
  };
});

const seededJobs: Job[] = [
  {
    id: 'j1',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Senior Software Engineer',
    createdAt: '2026-04-18T10:00:00Z',
    url: 'https://example.com/j1',
    location: 'Hawthorne, CA',
    department: 'Engineering',
    raw: {},
  },
  {
    id: 'j2',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Recruiter',
    createdAt: '2026-04-18T11:00:00Z',
    url: 'https://example.com/j2',
    location: 'Remote',
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

async function seedRecentStore(
  overrides: PreloadedOverrides = {},
  jobs: Job[] = seededJobs
) {
  const store = createTestStore({
    recentJobsFilters: {
      filters: {
        // Preload a wide time window so the default '3h' doesn't filter
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
          fetchedAt: '2026-04-19T00:00:00Z',
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
  it('renders SearchTagsInput, TimeWindowSelect, Company, Location, SoftwareOnlyToggle, Reset button', async () => {
    const store = await seedRecentStore();
    renderWithProviders(<RecentJobsFilters />, { store });

    expect(screen.getByPlaceholderText(/Type to add search tags/)).toBeInTheDocument();
    expect(screen.getAllByText('Time Window').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Company').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Location').length).toBeGreaterThan(0);
    expect(
      screen.getByRole('switch', { name: 'Software engineering roles only' })
    ).toBeInTheDocument();
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

    const input = screen.getByPlaceholderText(/Type to add search tags/);
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

    const input = screen.getByPlaceholderText('Add another tag...');
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
    const store = await seedRecentStore();
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    const locationInput = screen.getByPlaceholderText('Select location...');
    await user.click(locationInput);
    const listbox = await screen.findByRole('listbox');
    const firstOption = within(listbox).getAllByRole('option')[0];
    expect(firstOption).toBeDefined();
    const chosenLocation = firstOption.textContent ?? '';
    await user.click(firstOption);

    expect(store.getState().recentJobsFilters.filters.location).toContain(chosenLocation);
  });

  it('dispatches toggleRecentJobsSoftwareOnly when switch clicked', async () => {
    const store = await seedRecentStore();
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    await user.click(screen.getByRole('switch', { name: 'Software engineering roles only' }));

    const tags = store.getState().recentJobsFilters.filters.searchTags ?? [];
    // SOFTWARE_ENGINEERING_TAGS has 6 entries
    expect(tags.length).toBe(6);
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
    // After reset, the slice's initial state should be restored (timeWindow='3h',
    // all other fields undefined/false).
    expect(filters.timeWindow).toBe('3h');
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

  it('preserves graphFilters and listFilters slices when dispatching a recent-only action (filter independence)', async () => {
    const store = await seedRecentStore();
    const graphBefore = store.getState().graphFilters;
    const listBefore = store.getState().listFilters;
    const user = userEvent.setup();
    renderWithProviders(<RecentJobsFilters />, { store });

    const timeWindowCombo = screen.getByRole('combobox', { name: 'Time Window' });
    await user.click(timeWindowCombo);
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: '7 days' }));

    // An action on recentJobsFilters should NOT touch graph or list slices.
    expect(store.getState().graphFilters).toBe(graphBefore);
    expect(store.getState().listFilters).toBe(listBefore);
  });
});
