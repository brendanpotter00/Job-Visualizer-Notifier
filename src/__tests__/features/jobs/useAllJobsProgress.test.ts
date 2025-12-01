import { describe, it, expect, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useAllJobsProgress } from '../../../features/jobs/useAllJobsProgress';
import * as jobsApi from '../../../features/jobs/jobsApi';

// Mock the RTK Query hook
vi.mock('../../../features/jobs/jobsApi', () => ({
  useGetAllJobsQuery: vi.fn(),
}));

describe('useAllJobsProgress', () => {
  it('should return initial state when no data is available', () => {
    vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
      data: undefined,
      isLoading: true,
      isFetching: true,
      error: undefined,
      isError: false,
    } as any);

    const { result } = renderHook(() => useAllJobsProgress());

    expect(result.current.isLoading).toBe(true);
    expect(result.current.isError).toBe(false);
    expect(result.current.progress.completed).toBe(0);
    expect(result.current.progress.total).toBe(0);
    expect(result.current.progress.percentComplete).toBe(0);
    expect(result.current.progress.companies).toEqual([]);
  });

  it('should calculate percentComplete correctly', () => {
    vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
      data: {
        byCompanyId: {},
        metadata: {},
        errors: {},
        progress: {
          completed: 5,
          total: 10,
          companies: [],
        },
      },
      isLoading: true,
      isFetching: true,
      error: undefined,
      isError: false,
    } as any);

    const { result } = renderHook(() => useAllJobsProgress());

    expect(result.current.progress.percentComplete).toBe(50);
  });

  it('should filter completed companies correctly', () => {
    vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
      data: {
        byCompanyId: {},
        metadata: {},
        errors: {},
        progress: {
          completed: 3,
          total: 5,
          companies: [
            { companyId: 'company1', status: 'success', jobCount: 10 },
            { companyId: 'company2', status: 'success', jobCount: 5 },
            { companyId: 'company3', status: 'error', error: 'Failed' },
            { companyId: 'company4', status: 'loading' },
            { companyId: 'company5', status: 'pending' },
          ],
        },
      },
      isLoading: true,
      isFetching: true,
      error: undefined,
      isError: false,
    } as any);

    const { result } = renderHook(() => useAllJobsProgress());

    expect(result.current.progress.completedCompanies).toEqual(['company1', 'company2']);
    expect(result.current.progress.failedCompanies).toEqual(['company3']);
    expect(result.current.progress.pendingCompanies).toEqual(['company4', 'company5']);
  });

  it('should return data when available', () => {
    const mockData = {
      byCompanyId: {
        company1: [{ id: '1', title: 'Job 1' }],
      },
      metadata: {
        company1: {
          totalCount: 1,
          softwareCount: 1,
          fetchedAt: '2025-11-30T12:00:00Z',
        },
      },
      errors: {},
      progress: {
        completed: 1,
        total: 1,
        companies: [{ companyId: 'company1', status: 'success' as const, jobCount: 1 }],
      },
    };

    vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
      data: mockData,
      isLoading: false,
      isFetching: false,
      error: undefined,
      isError: false,
    } as any);

    const { result } = renderHook(() => useAllJobsProgress());

    expect(result.current.data.byCompanyId).toEqual(mockData.byCompanyId);
    expect(result.current.data.metadata).toEqual(mockData.metadata);
    expect(result.current.isLoading).toBe(false);
  });

  it('should handle error state', () => {
    const mockError = new Error('API Error');

    vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
      data: undefined,
      isLoading: false,
      isFetching: false,
      error: mockError,
      isError: true,
    } as any);

    const { result } = renderHook(() => useAllJobsProgress());

    expect(result.current.isError).toBe(true);
    expect(result.current.error).toBe(mockError);
  });

  it('should handle 100% completion', () => {
    vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
      data: {
        byCompanyId: {},
        metadata: {},
        errors: {},
        progress: {
          completed: 10,
          total: 10,
          companies: Array.from({ length: 10 }, (_, i) => ({
            companyId: `company${i}`,
            status: 'success' as const,
            jobCount: i * 5,
          })),
        },
      },
      isLoading: false,
      isFetching: false,
      error: undefined,
      isError: false,
    } as any);

    const { result } = renderHook(() => useAllJobsProgress());

    expect(result.current.progress.percentComplete).toBe(100);
    expect(result.current.progress.completedCompanies).toHaveLength(10);
  });

  it('should handle zero total correctly', () => {
    vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
      data: {
        byCompanyId: {},
        metadata: {},
        errors: {},
        progress: {
          completed: 0,
          total: 0,
          companies: [],
        },
      },
      isLoading: false,
      isFetching: false,
      error: undefined,
      isError: false,
    } as any);

    const { result } = renderHook(() => useAllJobsProgress());

    expect(result.current.progress.percentComplete).toBe(0);
  });

  it('should track loading during streaming (isLoading=false, isFetching=true)', () => {
    vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
      data: {
        byCompanyId: {},
        metadata: {},
        errors: {},
        progress: {
          completed: 5,
          total: 10,
          companies: [],
        },
      },
      isLoading: false, // Initial load complete
      isFetching: true, // Still streaming
      error: undefined,
      isError: false,
    } as any);

    const { result } = renderHook(() => useAllJobsProgress());

    // Should be true due to isFetching
    expect(result.current.isLoading).toBe(true);
    expect(result.current.progress.completed).toBe(5);
    expect(result.current.progress.total).toBe(10);
  });

  it('should not be loading when both isLoading and isFetching are false', () => {
    vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
      data: {
        byCompanyId: {},
        metadata: {},
        errors: {},
        progress: {
          completed: 10,
          total: 10,
          companies: [],
        },
        isStreaming: false,
      },
      isLoading: false,
      isFetching: false,
      error: undefined,
      isError: false,
    } as any);

    const { result } = renderHook(() => useAllJobsProgress());

    expect(result.current.isLoading).toBe(false);
  });

  it('should track loading during streaming via isStreaming flag', () => {
    vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
      data: {
        byCompanyId: {},
        metadata: {},
        errors: {},
        progress: {
          completed: 5,
          total: 10,
          companies: [
            { companyId: 'company1', status: 'success', jobCount: 10 },
            { companyId: 'company2', status: 'loading' },
          ],
        },
        isStreaming: true,
      },
      isLoading: false, // Initial queryFn complete
      isFetching: false, // RTK Query not tracking this phase
      error: undefined,
      isError: false,
    } as any);

    const { result } = renderHook(() => useAllJobsProgress());

    // Should be true due to isStreaming flag
    expect(result.current.isLoading).toBe(true);
    expect(result.current.progress.completed).toBe(5);
    expect(result.current.progress.total).toBe(10);
  });

  it('should handle undefined isStreaming gracefully', () => {
    vi.mocked(jobsApi.useGetAllJobsQuery).mockReturnValue({
      data: {
        byCompanyId: {},
        metadata: {},
        errors: {},
        progress: {
          completed: 5,
          total: 10,
          companies: [],
        },
        // isStreaming not present (backward compatibility)
      },
      isLoading: false,
      isFetching: false,
      error: undefined,
      isError: false,
    } as any);

    const { result } = renderHook(() => useAllJobsProgress());

    // Should default to false when undefined
    expect(result.current.isLoading).toBe(false);
  });
});
