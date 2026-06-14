import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders, createTestStore } from '../../../../test/testUtils';
import { ListSection } from '../../../../components/companies-page/JobList/ListSection';
import { jobsApi } from '../../../../features/jobs/jobsApi';
import { ATSConstants } from '../../../../api/types';
import { SIGN_IN_OVERLAY_CONFIG } from '../../../../constants/ui';
import type { Job } from '../../../../types';

// Mutable auth state: signed-in by default so list tests render unbounded;
// individual tests flip it to exercise the signed-out SignInOverlay cap.
const mockAuthState = {
  isEnabled: true,
  isAuthenticated: true,
  isLoading: false,
  user: undefined,
  login: vi.fn(),
  logout: vi.fn(),
  getToken: vi.fn(),
};

vi.mock('../../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

beforeEach(() => {
  mockAuthState.isEnabled = true;
  mockAuthState.isAuthenticated = true;
});

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

  it('caps the list and shows the sign-in overlay when signed out', async () => {
    mockAuthState.isAuthenticated = false;

    const limit = SIGN_IN_OVERLAY_CONFIG.SIGNED_OUT_JOB_LIMIT;
    const manyJobs: Job[] = Array.from({ length: limit + 1 }, (_, i) => ({
      id: `job-${i}`,
      source: 'backend-scraper',
      company: 'spacex',
      title: `Engineer ${i}`,
      createdAt: `2026-02-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
      url: `https://example.com/job-${i}`,
      location: 'Hawthorne, CA',
      department: 'Engineering',
      raw: {},
    }));

    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.BackendScraper as const,
        isInitialized: true,
      },
      graphFilters: { filters: { timeWindow: 'all', softwareOnly: false } },
    });
    await store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        {
          jobs: manyJobs,
          metadata: { totalCount: manyJobs.length, fetchedAt: '2026-04-01T00:00:00Z' },
        }
      )
    );
    renderWithProviders(<ListSection />, { store });

    // More jobs than the signed-out limit → list capped + overlay shown.
    expect(renderedTitles()).toHaveLength(limit);
    expect(screen.getByRole('region', { name: 'Sign in prompt' })).toBeInTheDocument();
  });
});
