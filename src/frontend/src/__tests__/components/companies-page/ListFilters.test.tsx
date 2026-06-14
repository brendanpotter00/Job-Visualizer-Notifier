import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, createTestStore } from '../../../test/testUtils';
import { ListFilters } from '../../../components/companies-page/ListFilters';
import { jobsApi } from '../../../features/jobs/jobsApi';
import { ATSConstants } from '../../../api/types';
import type { Job } from '../../../types';

const seededJobs: Job[] = [
  {
    id: 'j1',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Senior Software Engineer',
    createdAt: '2026-04-10T10:00:00Z',
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

describe('ListFilters', () => {
  it('renders SearchTagsInput, TimeWindowSelect, Location, Department, SoftwareOnlyToggle, SyncFiltersButton', async () => {
    const store = await seedStore();
    renderWithProviders(<ListFilters />, { store });

    expect(screen.getByPlaceholderText(/Type to add search tags/)).toBeInTheDocument();
    expect(screen.getAllByText('Time Window').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Location').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Department').length).toBeGreaterThan(0);
    expect(
      screen.getByRole('switch', { name: 'Software engineering roles only' })
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sync to graph/i })).toBeInTheDocument();
  });

  it('does NOT render Location control when availableLocations is empty', async () => {
    const jobsNoLocation: Job[] = [
      {
        id: 'x1',
        source: 'backend-scraper',
        company: 'spacex',
        title: 'Engineer',
        createdAt: '2026-04-10T10:00:00Z',
        url: 'https://example.com/x1',
        department: 'Engineering',
        raw: {},
      },
    ];
    const store = await seedStore(jobsNoLocation);
    renderWithProviders(<ListFilters />, { store });

    expect(screen.queryByText('Location')).not.toBeInTheDocument();
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
    renderWithProviders(<ListFilters />, { store });

    expect(screen.queryByText('Department')).not.toBeInTheDocument();
    expect(screen.getAllByText('Location').length).toBeGreaterThan(0);
  });

  it('dispatches setListTimeWindow when TimeWindow option selected', async () => {
    const store = await seedStore();
    const user = userEvent.setup();
    renderWithProviders(<ListFilters />, { store });

    // Resolve the TimeWindowSelect by its accessible name rather than by
    // current textContent — the latter flakes the instant the default changes.
    const timeWindowCombo = screen.getByRole('combobox', { name: 'Time Window' });
    await user.click(timeWindowCombo);
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: '7 days' }));
    expect(store.getState().listFilters.filters.timeWindow).toBe('7d');
  });

  it('dispatches addListSearchTag on Enter in search input', async () => {
    const store = await seedStore();
    const user = userEvent.setup();
    renderWithProviders(<ListFilters />, { store });

    const input = screen.getByPlaceholderText(/Type to add search tags/);
    await user.click(input);
    await user.type(input, 'senior{enter}');

    const tags = store.getState().listFilters.filters.searchTags;
    expect(tags).toEqual([{ text: 'senior', mode: 'include' }]);
  });

  it('dispatches removeListSearchTag when chip removed via Backspace', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.BackendScraper as const,
        isInitialized: true,
      },
      listFilters: {
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
    renderWithProviders(<ListFilters />, { store });

    const input = screen.getByPlaceholderText('Add another tag...');
    await user.click(input);
    await user.keyboard('{Backspace}');

    const tags = store.getState().listFilters.filters.searchTags;
    expect(tags === undefined || tags.length === 0).toBe(true);
  });

  it('dispatches toggleListSearchTagMode when chip clicked', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.BackendScraper as const,
        isInitialized: true,
      },
      listFilters: {
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
    renderWithProviders(<ListFilters />, { store });

    await user.click(screen.getByText('senior'));
    const tags = store.getState().listFilters.filters.searchTags;
    expect(tags?.[0].mode).toBe('exclude');
  });

  it('dispatches addListLocation when location option selected', async () => {
    const store = await seedStore();
    const user = userEvent.setup();
    renderWithProviders(<ListFilters />, { store });

    const locationInput = screen.getByPlaceholderText('Select location...');
    await user.click(locationInput);
    const listbox = await screen.findByRole('listbox');
    const options = within(listbox).getAllByRole('option');
    const firstOption = options[0];
    expect(firstOption).toBeDefined();
    const chosenLocation = firstOption.textContent ?? '';
    await user.click(firstOption);

    expect(store.getState().listFilters.filters.location).toContain(chosenLocation);
  });

  it('dispatches addListDepartment when department option selected', async () => {
    const store = await seedStore();
    const user = userEvent.setup();
    renderWithProviders(<ListFilters />, { store });

    const deptInput = screen.getByPlaceholderText('Select department...');
    await user.click(deptInput);
    const listbox = await screen.findByRole('listbox');
    const firstOption = within(listbox).getAllByRole('option')[0];
    const chosenDept = firstOption.textContent ?? '';
    await user.click(firstOption);

    expect(store.getState().listFilters.filters.department).toContain(chosenDept);
  });

  it('dispatches toggleListSoftwareOnly when switch clicked', async () => {
    const store = await seedStore();
    const user = userEvent.setup();
    renderWithProviders(<ListFilters />, { store });

    await user.click(screen.getByRole('switch', { name: 'Software engineering roles only' }));

    const tags = store.getState().listFilters.filters.searchTags ?? [];
    // SOFTWARE_ENGINEERING_TAGS has 6 entries
    expect(tags.length).toBe(6);
  });

  it('dispatches syncListToGraph thunk when Sync button clicked — copies list filters to graph slice', async () => {
    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.BackendScraper as const,
        isInitialized: true,
      },
      listFilters: {
        filters: {
          timeWindow: '7d',
          searchTags: [{ text: 'senior', mode: 'include' }],
          location: ['SF'],
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
    renderWithProviders(<ListFilters />, { store });

    await user.click(screen.getByRole('button', { name: /sync to graph/i }));

    const graphFilters = store.getState().graphFilters.filters;
    expect(graphFilters.timeWindow).toBe('7d');
    expect(graphFilters.searchTags).toEqual([{ text: 'senior', mode: 'include' }]);
    expect(graphFilters.location).toEqual(['SF']);
  });

  it('preserves graphFilters slice when dispatching a list-only action (filter independence)', async () => {
    const store = await seedStore();
    const graphBefore = store.getState().graphFilters;
    const user = userEvent.setup();
    renderWithProviders(<ListFilters />, { store });

    const timeWindowCombo = screen.getByRole('combobox', { name: 'Time Window' });
    await user.click(timeWindowCombo);
    const listbox = await screen.findByRole('listbox');
    await user.click(within(listbox).getByRole('option', { name: '7 days' }));

    // Reducer-identity: an action that only touches listFilters must leave
    // graphFilters reference-identical (proves the graph reducer never ran).
    expect(store.getState().graphFilters).toBe(graphBefore);
  });
});
