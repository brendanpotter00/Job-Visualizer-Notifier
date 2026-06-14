import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders, createTestStore } from '../../../../test/testUtils';
import { ListSection } from '../../../../components/companies-page/JobList/ListSection';
import { jobsApi } from '../../../../features/jobs/jobsApi';
import { ATSConstants } from '../../../../api/types';
import type { Job } from '../../../../types';

// Signed-in so the list renders unbounded (no SignInOverlay cap interfering
// with the assertions). The cap behavior itself is covered elsewhere.
vi.mock('../../../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: true,
    isAuthenticated: true,
    isLoading: false,
    user: undefined,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn(),
  }),
}));

const jobs: Job[] = [
  {
    id: 'j-jan',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Backend Engineer',
    createdAt: '2026-01-01T00:00:00Z',
    url: 'https://example.com/j-jan',
    location: 'Hawthorne, CA',
    department: 'Engineering',
    raw: {},
  },
  {
    id: 'j-mar',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Recruiter',
    createdAt: '2026-03-01T00:00:00Z',
    url: 'https://example.com/j-mar',
    location: 'Remote',
    department: 'People',
    raw: {},
  },
  {
    id: 'j-feb',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Frontend Engineer',
    createdAt: '2026-02-01T00:00:00Z',
    url: 'https://example.com/j-feb',
    location: 'Hawthorne, CA',
    department: 'Engineering',
    raw: {},
  },
];

async function seedStore(graphFilters: Record<string, unknown>) {
  const store = createTestStore({
    app: {
      selectedCompanyId: 'spacex',
      selectedATS: ATSConstants.BackendScraper as const,
      isInitialized: true,
    },
    graphFilters: { filters: graphFilters },
  });
  await store.dispatch(
    jobsApi.util.upsertQueryData(
      'getJobsForCompany',
      { companyId: 'spacex' },
      { jobs, metadata: { totalCount: jobs.length, fetchedAt: '2026-04-01T00:00:00Z' } }
    )
  );
  return store;
}

// Job titles are rendered by JobCard as level-3 headings; the section's own
// "Job Listings" title is a level-2 heading, so it does not collide.
const renderedTitles = () =>
  screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);

describe('ListSection', () => {
  it('reflects the graph filters: renders matching jobs sorted most-recent-first', async () => {
    const store = await seedStore({ timeWindow: 'all', softwareOnly: false });
    renderWithProviders(<ListSection />, { store });

    expect(screen.getByText('3 jobs found')).toBeInTheDocument();
    expect(renderedTitles()).toEqual(['Recruiter', 'Frontend Engineer', 'Backend Engineer']);
  });

  it('narrows the list when the graph search-tag filter is applied (single source of truth)', async () => {
    const store = await seedStore({
      timeWindow: 'all',
      searchTags: [{ text: 'engineer', mode: 'include' }],
      softwareOnly: false,
    });
    renderWithProviders(<ListSection />, { store });

    expect(screen.getByText('2 jobs found')).toBeInTheDocument();
    expect(renderedTitles()).toEqual(['Frontend Engineer', 'Backend Engineer']);
    expect(screen.queryByText('Recruiter')).not.toBeInTheDocument();
  });
});
