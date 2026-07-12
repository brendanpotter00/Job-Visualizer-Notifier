import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, createTestStore } from '../../../test/testUtils';
import { GraphFilters } from '../../../components/companies-page/GraphFilters';
import { jobsApi } from '../../../features/jobs/jobsApi';
import { ATSConstants } from '../../../api/types';
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

const seededJobs: Job[] = [
  {
    id: 'j1',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Senior Software Engineer',
    createdAt: '2026-04-10T10:00:00Z',
    firstSeenAt: '2026-04-10T10:00:00Z',
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
    createdAt: '2026-04-11T10:00:00Z',
    firstSeenAt: '2026-04-11T10:00:00Z',
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

async function seedStore(jobs: Job[] = seededJobs) {
  const store = createTestStore({
    app: {
      selectedCompanyId: 'spacex',
      selectedATS: ATSConstants.BackendScraper as const,
      isInitialized: true,
    },
  });
  // upsertQueryData dispatches a thunk that resolves on the next microtask;
  // await it so the cache entry is fulfilled before the component reads it.
  await store.dispatch(
    jobsApi.util.upsertQueryData(
      'getJobsForCompany',
      { companyId: 'spacex' },
      {
        jobs,
        metadata: {
          totalCount: jobs.length,
          fetchedAt: '2026-04-12T00:00:00Z',
        },
      }
    )
  );
  return store;
}

describe('GraphFilters', () => {
  it('renders the merged KeywordFilterInput, TimeWindowSelect, Location, Department', async () => {
    const store = await seedStore();
    renderWithProviders(<GraphFilters />, { store });

    expect(screen.getByRole('combobox', { name: 'Keywords' })).toBeInTheDocument();
    expect(screen.getAllByText('Time Window').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Location').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Department').length).toBeGreaterThan(0);
  });

  it('renders Location control unconditionally, even when no job has location data', async () => {
    const jobsNoLocation: Job[] = [
      {
        id: 'x1',
        source: 'backend-scraper',
        company: 'spacex',
        title: 'Engineer',
        createdAt: '2026-04-10T10:00:00Z',
        firstSeenAt: '2026-04-10T10:00:00Z',
        url: 'https://example.com/x1',
        department: 'Engineering',
        raw: {},
      },
    ];
    const store = await seedStore(jobsNoLocation);
    renderWithProviders(<GraphFilters />, { store });

    // Unlike Department (still gated on availableDepartments), Location is the
    // server-backed AsyncMultiSelectAutocomplete: it doesn't depend on any
    // locally-derived "available locations" set, so it always renders.
    expect(screen.getByPlaceholderText('Search location...')).toBeInTheDocument();
    expect(screen.getAllByText('Department').length).toBeGreaterThan(0);
  });

  it('does NOT render Department control when availableDepartments is empty', async () => {
    const jobsNoDept: Job[] = [
      {
        id: 'y1',
        source: 'backend-scraper',
        company: 'spacex',
        title: 'Engineer',
        createdAt: '2026-04-10T10:00:00Z',
        firstSeenAt: '2026-04-10T10:00:00Z',
        url: 'https://example.com/y1',
        location: 'SF',
        locations: [
          {
            canonicalName: 'San Francisco, CA, US',
            kind: 'city',
            city: 'San Francisco',
            region: 'CA',
            country: 'US',
            remoteScope: null,
            isPrimary: true,
          },
        ],
        raw: {},
      },
    ];
    const store = await seedStore(jobsNoDept);
    renderWithProviders(<GraphFilters />, { store });

    expect(screen.queryByText('Department')).not.toBeInTheDocument();
    expect(screen.getAllByText('Location').length).toBeGreaterThan(0);
  });

  it('dispatches setGraphTimeWindow when TimeWindow option selected', async () => {
    const store = await seedStore();
    const user = userEvent.setup();
    renderWithProviders(<GraphFilters />, { store });

    // Resolve the TimeWindowSelect by its accessible name rather than by
    // current textContent — the latter flakes the instant the default changes.
    const timeWindowCombo = screen.getByRole('combobox', { name: 'Time Window' });
    await user.click(timeWindowCombo);
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: '7 days' }));
    expect(store.getState().graphFilters.filters.timeWindow).toBe('7d');
  });

  it('dispatches addGraphSearchTag on Enter in search input', async () => {
    const store = await seedStore();
    const user = userEvent.setup();
    renderWithProviders(<GraphFilters />, { store });

    const input = screen.getByRole('combobox', { name: 'Keywords' });
    await user.click(input);
    await user.type(input, 'senior{enter}');

    const tags = store.getState().graphFilters.filters.searchTags;
    expect(tags).toEqual([{ text: 'senior', mode: 'include' }]);
  });

  it('dispatches removeGraphSearchTag when chip removed via Backspace', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.BackendScraper as const,
        isInitialized: true,
      },
      graphFilters: {
        filters: {
          timeWindow: '30d',
          searchTags: [{ text: 'senior', mode: 'include' }],
          softwareOnly: false,
        },
      },
    });
    await store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: seededJobs,
          metadata: { totalCount: seededJobs.length, fetchedAt: '2026-04-12T00:00:00Z' },
        }
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<GraphFilters />, { store });

    const input = screen.getByRole('combobox', { name: 'Keywords' });
    await user.click(input);
    await user.keyboard('{Backspace}');

    const tags = store.getState().graphFilters.filters.searchTags;
    expect(tags === undefined || tags.length === 0).toBe(true);
  });

  it('dispatches toggleGraphSearchTagMode when chip clicked', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.BackendScraper as const,
        isInitialized: true,
      },
      graphFilters: {
        filters: {
          timeWindow: '30d',
          searchTags: [{ text: 'senior', mode: 'include' }],
          softwareOnly: false,
        },
      },
    });
    await store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: seededJobs,
          metadata: { totalCount: seededJobs.length, fetchedAt: '2026-04-12T00:00:00Z' },
        }
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<GraphFilters />, { store });

    await user.click(screen.getByText('senior'));
    const tags = store.getState().graphFilters.filters.searchTags;
    expect(tags?.[0].mode).toBe('exclude');
  });

  it('dispatches addGraphLocation when location option selected', async () => {
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
    const store = await seedStore();
    const user = userEvent.setup();
    renderWithProviders(<GraphFilters />, { store });

    // Find the Location autocomplete by its (async) text-input placeholder.
    const locationInput = screen.getByPlaceholderText('Search location...');
    await user.click(locationInput);
    const listbox = await screen.findByRole('listbox');
    const options = within(listbox).getAllByRole('option');
    const firstOption = options[0];
    expect(firstOption).toBeDefined();
    const chosenLocation = firstOption.textContent ?? '';
    await user.click(firstOption);

    expect(store.getState().graphFilters.filters.location).toContain(chosenLocation);
  });

  it('dispatches addGraphDepartment when department option selected', async () => {
    const store = await seedStore();
    const user = userEvent.setup();
    renderWithProviders(<GraphFilters />, { store });

    const deptInput = screen.getByPlaceholderText('Select department...');
    await user.click(deptInput);
    const listbox = await screen.findByRole('listbox');
    const firstOption = within(listbox).getAllByRole('option')[0];
    const chosenDept = firstOption.textContent ?? '';
    await user.click(firstOption);

    expect(store.getState().graphFilters.filters.department).toContain(chosenDept);
  });

  it('clears searchTags via the merged control\'s "None" option', async () => {
    // Seed with hand-added tags; opening the merged Keywords control lists the
    // presets plus a "None" row. With no keyword lists loaded in the test store,
    // selecting "None" clears the slice's tags.
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.BackendScraper as const,
        isInitialized: true,
      },
      graphFilters: {
        filters: {
          timeWindow: '30d',
          searchTags: [{ text: 'senior', mode: 'include' }],
          softwareOnly: false,
        },
        hydrated: false,
      },
    });
    await store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: seededJobs,
          metadata: { totalCount: seededJobs.length, fetchedAt: '2026-04-12T00:00:00Z' },
        }
      )
    );
    const user = userEvent.setup();
    renderWithProviders(<GraphFilters />, { store });

    await user.click(screen.getByRole('combobox', { name: 'Keywords' }));
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: 'None' }));

    const tags = store.getState().graphFilters.filters.searchTags;
    expect(tags === undefined || tags.length === 0).toBe(true);
  });
});
