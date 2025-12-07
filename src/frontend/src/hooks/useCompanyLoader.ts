import { useEffect, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../app/hooks';
import { setSelectedCompanyId } from '../features/app/appSlice';
import { useGetJobsForCompanyQuery } from '../features/jobs/jobsApi';
import { getInitialCompanyId } from '../lib/url';
import { ROUTES } from '../config/routes';

/**
 * Custom hook for managing company selection initialization and job loading
 *
 * Responsibilities:
 * - Initialize selected company from URL on mount (Companies page only)
 * - Load jobs whenever the selected company changes (Companies page only)
 * - Provide retry functionality for failed requests
 *
 * Note: This hook only runs on the Companies page to prevent
 * unnecessary API calls on other pages. Uses RTK Query for automatic
 * caching and request deduplication.
 *
 * @returns Object containing loading state, error message, retry handler, jobs, and metadata
 */
export function useCompanyLoader() {
  const location = useLocation();
  const dispatch = useAppDispatch();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);

  // Only run on Companies page
  const isCompaniesPage = location.pathname === ROUTES.COMPANIES;

  // Initialize company from URL on mount (only on Companies page)
  useEffect(() => {
    if (!isCompaniesPage) return;

    const initialCompanyId = getInitialCompanyId();
    if (initialCompanyId !== selectedCompanyId) {
      dispatch(setSelectedCompanyId(initialCompanyId));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isCompaniesPage]); // Only run on mount or when page changes

  // RTK Query hook - automatically fetches on mount and when companyId changes
  // Skip fetching if not on Companies page
  const { data, isLoading, error, refetch } = useGetJobsForCompanyQuery(
    { companyId: selectedCompanyId },
    { skip: !isCompaniesPage }
  );

  // Memoized retry handler
  const handleRetry = useCallback(() => {
    refetch();
  }, [refetch]);

  return {
    isLoading,
    error: error
      ? typeof error === 'string'
        ? error
        : typeof error === 'object' && error !== null && 'data' in error
          ? String(error.data)
          : 'Unknown error'
      : undefined,
    handleRetry,
    jobs: data?.jobs || [],
    metadata: data?.metadata,
  };
}
