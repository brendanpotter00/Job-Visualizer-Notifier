import { useMemo } from 'react';
import { useGetAllJobsQuery } from '../jobsApi.ts';
import type { Job, CompanyFetchProgress } from '../../../types';

/**
 * Result returned by useAllJobsProgress hook
 */
export interface UseAllJobsProgressResult {
  /** Is the query currently loading */
  isLoading: boolean;

  /** Did the query encounter an error */
  isError: boolean;

  /** Error object if query failed */
  error: unknown;

  /** Job data organized by company ID */
  data: {
    byCompanyId: Record<string, Job[]>;
    metadata: Record<
      string,
      {
        totalCount: number;
        softwareCount: number;
        oldestJobDate?: string;
        newestJobDate?: string;
        fetchedAt: string;
      }
    >;
    errors: Record<string, string>;
  };

  /** Progress tracking information */
  progress: {
    /** Number of companies completed (success or error) */
    completed: number;

    /** Total number of companies to fetch */
    total: number;

    /** Percentage complete (0-100) */
    percentComplete: number;

    /** Per-company progress details */
    companies: CompanyFetchProgress[];

    /** List of company IDs that completed successfully */
    completedCompanies: string[];

    /** List of company IDs that failed */
    failedCompanies: string[];

    /** List of company IDs still pending or loading */
    pendingCompanies: string[];
  };
}

/**
 * Custom hook for consuming getAllJobs query with progress tracking
 *
 * Provides a clean interface for accessing job data and detailed progress
 * information as companies load incrementally.
 *
 * @returns Job data and progress tracking information
 *
 * @example
 * ```tsx
 * function MyComponent() {
 *   const { progress, data, isLoading } = useAllJobsProgress();
 *
 *   return (
 *     <div>
 *       <p>Loaded {progress.completed} of {progress.total} companies</p>
 *       <p>{progress.percentComplete}% complete</p>
 *     </div>
 *   );
 * }
 * ```
 */
export function useAllJobsProgress(): UseAllJobsProgressResult {
  const { data, isLoading, isFetching, error, isError } = useGetAllJobsQuery();

  // Combine loading states: RTK Query states + custom streaming flag
  const isStillLoading = isLoading || isFetching || (data?.isStreaming ?? false);

  // Extract progress or use defaults
  const progress = data?.progress || {
    completed: 0,
    total: 0,
    companies: [],
  };

  // Derive filtered company lists (memoized to avoid recalculation on every render)
  const completedCompanies = useMemo(
    () => progress.companies.filter((c) => c.status === 'success').map((c) => c.companyId),
    [progress.companies]
  );

  const failedCompanies = useMemo(
    () => progress.companies.filter((c) => c.status === 'error').map((c) => c.companyId),
    [progress.companies]
  );

  const pendingCompanies = useMemo(
    () =>
      progress.companies
        .filter((c) => c.status === 'pending' || c.status === 'loading')
        .map((c) => c.companyId),
    [progress.companies]
  );

  // Calculate percentage (memoized)
  const percentComplete = useMemo(
    () => (progress.total > 0 ? (progress.completed / progress.total) * 100 : 0),
    [progress.completed, progress.total]
  );

  return {
    isLoading: isStillLoading,
    isError,
    error,
    data: {
      byCompanyId: data?.byCompanyId || {},
      metadata: data?.metadata || {},
      errors: data?.errors || {},
    },
    progress: {
      completed: progress.completed,
      total: progress.total,
      percentComplete,
      companies: progress.companies,
      completedCompanies,
      failedCompanies,
      pendingCompanies,
    },
  };
}
