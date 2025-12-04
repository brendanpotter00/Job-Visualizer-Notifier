import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FetchProgressBar } from '../../../components/FetchProgressBar/FetchProgressBar';
import * as useAllJobsProgressHook from '../../../features/jobs/useAllJobsProgress';

// Mock the custom hook
vi.mock('../../../features/jobs/useAllJobsProgress');

describe('FetchProgressBar', () => {
  it('should render progress bar with correct percentage', () => {
    vi.mocked(useAllJobsProgressHook.useAllJobsProgress).mockReturnValue({
      isLoading: true,
      isError: false,
      error: undefined,
      data: { byCompanyId: {}, metadata: {}, errors: {} },
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

  it('should render success chips with job counts', () => {
    vi.mocked(useAllJobsProgressHook.useAllJobsProgress).mockReturnValue({
      isLoading: true,
      isError: false,
      error: undefined,
      data: { byCompanyId: {}, metadata: {}, errors: {} },
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
    vi.mocked(useAllJobsProgressHook.useAllJobsProgress).mockReturnValue({
      isLoading: true,
      isError: false,
      error: undefined,
      data: { byCompanyId: {}, metadata: {}, errors: {} },
      progress: {
        completed: 2,
        total: 2,
        percentComplete: 100,
        companies: [
          { companyId: 'company1', status: 'success' as const, jobCount: 10 },
          {
            companyId: 'company2',
            status: 'error' as const,
            error: 'Failed to fetch',
          },
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

  it('should hide when loading is complete', () => {
    vi.mocked(useAllJobsProgressHook.useAllJobsProgress).mockReturnValue({
      isLoading: false,
      isError: false,
      error: undefined,
      data: { byCompanyId: {}, metadata: {}, errors: {} },
      progress: {
        completed: 10,
        total: 10,
        percentComplete: 100,
        companies: Array.from({ length: 10 }, (_, i) => ({
          companyId: `company${i}`,
          status: 'success' as const,
          jobCount: i * 5,
        })),
        completedCompanies: [],
        failedCompanies: [],
        pendingCompanies: [],
      },
    });

    const { container } = render(<FetchProgressBar />);

    expect(container.firstChild).toBeNull();
  });

  it('should show during streaming (data exists, still fetching)', () => {
    vi.mocked(useAllJobsProgressHook.useAllJobsProgress).mockReturnValue({
      isLoading: true, // This now includes isFetching
      isError: false,
      error: undefined,
      data: {
        byCompanyId: { company1: [] },
        metadata: {},
        errors: {},
      },
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

    // Should show progress bar even though some data exists
    expect(screen.getByText('Loading jobs from 5/10 companies')).toBeInTheDocument();
    expect(screen.getByText('50%')).toBeInTheDocument();
  });

  it('should show when loading is in progress', () => {
    vi.mocked(useAllJobsProgressHook.useAllJobsProgress).mockReturnValue({
      isLoading: true,
      isError: false,
      error: undefined,
      data: { byCompanyId: {}, metadata: {}, errors: {} },
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
    vi.mocked(useAllJobsProgressHook.useAllJobsProgress).mockReturnValue({
      isLoading: true,
      isError: false,
      error: undefined,
      data: { byCompanyId: {}, metadata: {}, errors: {} },
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
    vi.mocked(useAllJobsProgressHook.useAllJobsProgress).mockReturnValue({
      isLoading: true,
      isError: false,
      error: undefined,
      data: { byCompanyId: {}, metadata: {}, errors: {} },
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
    // This test verifies the fix: hook returns isLoading=true when isStreaming=true
    vi.mocked(useAllJobsProgressHook.useAllJobsProgress).mockReturnValue({
      isLoading: true, // True because isStreaming=true in hook logic
      isError: false,
      error: undefined,
      data: { byCompanyId: {}, metadata: {}, errors: {} },
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

    // Progress bar should be visible during streaming
    expect(screen.getByText('Loading jobs from 7/30 companies')).toBeInTheDocument();
    expect(screen.getByText('23%')).toBeInTheDocument();
  });
});
