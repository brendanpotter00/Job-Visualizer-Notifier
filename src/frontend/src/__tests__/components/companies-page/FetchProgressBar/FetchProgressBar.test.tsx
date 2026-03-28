import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FetchProgressBar } from '../../../../components/companies-page/FetchProgressBar/FetchProgressBar';
import * as useAllJobsProgressHook from '../../../../features/jobs/hooks/useAllJobsProgress';

// Mock the custom hook
vi.mock('../../../../features/jobs/hooks/useAllJobsProgress');

const mockDefaults = {
  isError: false,
  error: undefined,
  data: { byCompanyId: {}, metadata: {}, errors: {} },
};

function mockHook(overrides: Partial<useAllJobsProgressHook.UseAllJobsProgressResult>) {
  vi.mocked(useAllJobsProgressHook.useAllJobsProgress).mockReturnValue({
    ...mockDefaults,
    isLoading: true,
    progress: {
      completed: 0,
      total: 0,
      percentComplete: 0,
      companies: [],
      completedCompanies: [],
      failedCompanies: [],
      pendingCompanies: [],
    },
    ...overrides,
  } as useAllJobsProgressHook.UseAllJobsProgressResult);
}

describe('FetchProgressBar', () => {
  it('should return null when progress.total is 0', () => {
    mockHook({ isLoading: false, progress: { completed: 0, total: 0, percentComplete: 0, companies: [], completedCompanies: [], failedCompanies: [], pendingCompanies: [] } });

    const { container } = render(<FetchProgressBar />);
    expect(container.firstChild).toBeNull();
  });

  it('should render progress bar with correct percentage while loading', () => {
    mockHook({
      isLoading: true,
      progress: {
        completed: 5,
        total: 10,
        percentComplete: 50,
        companies: Array.from({ length: 10 }, (_, i) => ({
          companyId: `company${i}`,
          status: i < 5 ? ('success' as const) : ('pending' as const),
          jobCount: i < 5 ? i * 10 : undefined,
        })),
        completedCompanies: [],
        failedCompanies: [],
        pendingCompanies: [],
      },
    });

    render(<FetchProgressBar />);

    expect(screen.getByText('Loading jobs from 5/10 companies')).toBeInTheDocument();
    expect(screen.getByText('50%')).toBeInTheDocument();
  });

  it('should render success chips with job counts when expanded', () => {
    mockHook({
      isLoading: true,
      progress: {
        completed: 2,
        total: 3,
        percentComplete: 66.67,
        companies: [
          { companyId: 'spacex', status: 'success' as const, jobCount: 25 },
          { companyId: 'anduril', status: 'success' as const, jobCount: 15 },
          { companyId: 'notion', status: 'pending' as const },
        ],
        completedCompanies: ['spacex', 'anduril'],
        failedCompanies: [],
        pendingCompanies: ['notion'],
      },
    });

    render(<FetchProgressBar />);

    expect(screen.getByText('spacex (25)')).toBeInTheDocument();
    expect(screen.getByText('anduril (15)')).toBeInTheDocument();
    expect(screen.getByText('notion')).toBeInTheDocument();
  });

  it('should render error chips with error indicator', () => {
    mockHook({
      isLoading: true,
      progress: {
        completed: 2,
        total: 2,
        percentComplete: 100,
        companies: [
          { companyId: 'company1', status: 'success' as const, jobCount: 10 },
          { companyId: 'company2', status: 'error' as const, error: 'Failed to fetch' },
        ],
        completedCompanies: ['company1'],
        failedCompanies: ['company2'],
        pendingCompanies: [],
      },
    });

    render(<FetchProgressBar />);

    const errorChip = screen.getByText('company2').closest('.MuiChip-root');
    expect(errorChip).toHaveAttribute('title', 'Failed to fetch');
  });

  it('should show collapsed summary when loading is complete', () => {
    mockHook({
      isLoading: false,
      progress: {
        completed: 10,
        total: 10,
        percentComplete: 100,
        companies: Array.from({ length: 10 }, (_, i) => ({
          companyId: `company${i}`,
          status: 'success' as const,
          jobCount: i * 5,
        })),
        completedCompanies: Array.from({ length: 10 }, (_, i) => `company${i}`),
        failedCompanies: [],
        pendingCompanies: [],
      },
    });

    const { container } = render(<FetchProgressBar />);

    // Component should still be rendered (not null)
    expect(container.firstChild).not.toBeNull();

    // Summary should show loaded text
    expect(screen.getByText('Loaded 10/10 companies')).toBeInTheDocument();

    // Summary should show success count chip
    expect(screen.getByText('10 loaded (225 jobs)')).toBeInTheDocument();

    // Detail chips should NOT be in DOM (unmountOnExit)
    expect(screen.queryByText('company0 (0)')).not.toBeInTheDocument();
  });

  it('should show success and error summary chips in collapsed state', () => {
    mockHook({
      isLoading: false,
      progress: {
        completed: 5,
        total: 5,
        percentComplete: 100,
        companies: [
          { companyId: 'spacex', status: 'success' as const, jobCount: 100 },
          { companyId: 'anduril', status: 'success' as const, jobCount: 50 },
          { companyId: 'notion', status: 'success' as const, jobCount: 30 },
          { companyId: 'palantir', status: 'error' as const, error: 'Network error' },
          { companyId: 'stripe', status: 'error' as const, error: 'Timeout' },
        ],
        completedCompanies: ['spacex', 'anduril', 'notion'],
        failedCompanies: ['palantir', 'stripe'],
        pendingCompanies: [],
      },
    });

    render(<FetchProgressBar />);

    expect(screen.getByText('Loaded 5/5 companies')).toBeInTheDocument();
    expect(screen.getByText('3 loaded (180 jobs)')).toBeInTheDocument();
    expect(screen.getByText('2 failed')).toBeInTheDocument();
  });

  it('should show during streaming (data exists, still fetching)', () => {
    mockHook({
      isLoading: true,
      data: { byCompanyId: { company1: [] }, metadata: {}, errors: {} },
      progress: {
        completed: 5,
        total: 10,
        percentComplete: 50,
        companies: Array.from({ length: 10 }, (_, i) => ({
          companyId: `company${i}`,
          status: i < 5 ? ('success' as const) : ('pending' as const),
          jobCount: i < 5 ? i * 10 : undefined,
        })),
        completedCompanies: [],
        failedCompanies: [],
        pendingCompanies: [],
      },
    });

    render(<FetchProgressBar />);

    expect(screen.getByText('Loading jobs from 5/10 companies')).toBeInTheDocument();
    expect(screen.getByText('50%')).toBeInTheDocument();
  });

  it('should show when loading is in progress', () => {
    mockHook({
      isLoading: true,
      progress: {
        completed: 0,
        total: 10,
        percentComplete: 0,
        companies: Array.from({ length: 10 }, (_, i) => ({
          companyId: `company${i}`,
          status: 'pending' as const,
        })),
        completedCompanies: [],
        failedCompanies: [],
        pendingCompanies: [],
      },
    });

    render(<FetchProgressBar />);

    expect(screen.getByText('Loading jobs from 0/10 companies')).toBeInTheDocument();
    expect(screen.getByText('0%')).toBeInTheDocument();
  });

  it('should render loading status chips', () => {
    mockHook({
      isLoading: true,
      progress: {
        completed: 1,
        total: 3,
        percentComplete: 33.33,
        companies: [
          { companyId: 'company1', status: 'success' as const, jobCount: 5 },
          { companyId: 'company2', status: 'loading' as const },
          { companyId: 'company3', status: 'pending' as const },
        ],
        completedCompanies: ['company1'],
        failedCompanies: [],
        pendingCompanies: ['company2', 'company3'],
      },
    });

    render(<FetchProgressBar />);

    expect(screen.getByText('company1 (5)')).toBeInTheDocument();
    expect(screen.getByText('company2')).toBeInTheDocument();
    expect(screen.getByText('company3')).toBeInTheDocument();
  });

  it('should handle mixed status companies', () => {
    mockHook({
      isLoading: true,
      progress: {
        completed: 3,
        total: 5,
        percentComplete: 60,
        companies: [
          { companyId: 'spacex', status: 'success' as const, jobCount: 100 },
          { companyId: 'anduril', status: 'success' as const, jobCount: 50 },
          { companyId: 'notion', status: 'error' as const, error: 'Network error' },
          { companyId: 'palantir', status: 'loading' as const },
          { companyId: 'stripe', status: 'pending' as const },
        ],
        completedCompanies: ['spacex', 'anduril'],
        failedCompanies: ['notion'],
        pendingCompanies: ['palantir', 'stripe'],
      },
    });

    render(<FetchProgressBar />);

    expect(screen.getByText('Loading jobs from 3/5 companies')).toBeInTheDocument();
    expect(screen.getByText('60%')).toBeInTheDocument();
    expect(screen.getByText('spacex (100)')).toBeInTheDocument();
    expect(screen.getByText('anduril (50)')).toBeInTheDocument();
    expect(screen.getByText('notion')).toBeInTheDocument();
    expect(screen.getByText('palantir')).toBeInTheDocument();
    expect(screen.getByText('stripe')).toBeInTheDocument();
  });

  it('should show during streaming phase (isLoading=true via isStreaming)', () => {
    mockHook({
      isLoading: true,
      progress: {
        completed: 7,
        total: 30,
        percentComplete: 23.33,
        companies: Array.from({ length: 30 }, (_, i) => ({
          companyId: `company${i}`,
          status: i < 7 ? ('success' as const) : ('pending' as const),
          jobCount: i < 7 ? i * 5 : undefined,
        })),
        completedCompanies: [],
        failedCompanies: [],
        pendingCompanies: [],
      },
    });

    render(<FetchProgressBar />);

    expect(screen.getByText('Loading jobs from 7/30 companies')).toBeInTheDocument();
    expect(screen.getByText('23%')).toBeInTheDocument();
  });

  it('should auto-collapse when loading transitions from true to false', async () => {
    const companies = [
      { companyId: 'spacex', status: 'success' as const, jobCount: 100 },
      { companyId: 'anduril', status: 'success' as const, jobCount: 50 },
    ];

    // Start loading
    mockHook({
      isLoading: true,
      progress: {
        completed: 1,
        total: 2,
        percentComplete: 50,
        companies: [
          companies[0],
          { companyId: 'anduril', status: 'pending' as const },
        ],
        completedCompanies: ['spacex'],
        failedCompanies: [],
        pendingCompanies: ['anduril'],
      },
    });

    const { rerender } = render(<FetchProgressBar />);

    // Should be expanded - detail chips visible
    expect(screen.getByText('Loading jobs from 1/2 companies')).toBeInTheDocument();
    expect(screen.getByText('spacex (100)')).toBeInTheDocument();

    // Loading finishes
    mockHook({
      isLoading: false,
      progress: {
        completed: 2,
        total: 2,
        percentComplete: 100,
        companies,
        completedCompanies: ['spacex', 'anduril'],
        failedCompanies: [],
        pendingCompanies: [],
      },
    });

    rerender(<FetchProgressBar />);

    // Should show collapsed summary
    expect(screen.getByText('Loaded 2/2 companies')).toBeInTheDocument();
    expect(screen.getByText('2 loaded (150 jobs)')).toBeInTheDocument();

    // Detail chips should not be in DOM (unmountOnExit) - wait for transition
    await waitFor(() => {
      expect(screen.queryByText('spacex (100)')).not.toBeInTheDocument();
    });
  });

  it('should allow user to toggle accordion', async () => {
    const user = userEvent.setup();

    mockHook({
      isLoading: false,
      progress: {
        completed: 2,
        total: 2,
        percentComplete: 100,
        companies: [
          { companyId: 'spacex', status: 'success' as const, jobCount: 100 },
          { companyId: 'anduril', status: 'success' as const, jobCount: 50 },
        ],
        completedCompanies: ['spacex', 'anduril'],
        failedCompanies: [],
        pendingCompanies: [],
      },
    });

    render(<FetchProgressBar />);

    // Starts collapsed (isLoading is false on mount)
    expect(screen.queryByText('spacex (100)')).not.toBeInTheDocument();

    // Click to expand
    const summary = screen.getByText('Loaded 2/2 companies');
    await user.click(summary);

    // Detail chips should now be visible
    expect(screen.getByText('spacex (100)')).toBeInTheDocument();
    expect(screen.getByText('anduril (50)')).toBeInTheDocument();

    // Click to collapse again
    await user.click(summary);

    // Detail chips should be gone (unmountOnExit)
    expect(screen.queryByText('spacex (100)')).not.toBeInTheDocument();
  });
});
