import { useEffect, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../app/hooks';
import { setSelectedCompanyId } from '../features/app/appSlice';
import { useGetJobsForCompanyQuery } from '../features/jobs/jobsApi';
import { getInitialCompanyId } from '../lib/url';
import { ROUTES } from '../config/routes';
import { extractErrorMessage } from '../lib/errors';

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

  // Initialize selected company from the URL on transition onto the Companies
  // page. We intentionally do NOT read `selectedCompanyId` inside this effect:
  // dispatching `setSelectedCompanyId` with the already-selected id is
  // idempotent for subscribers (useAppSelector returns the same string, so no
  // component re-renders), and reading `selectedCompanyId` would force the
  // effect to re-run on every company change and undo the user's selection.
  // `dispatch` has stable identity (react-redux guarantee). This pattern lets
  // the exhaustive-deps rule stay at `error` globally with no per-site disable.
  useEffect(() => {
    if (!isCompaniesPage) return;
    dispatch(setSelectedCompanyId(getInitialCompanyId()));
  }, [isCompaniesPage, dispatch]);

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
    error: error ? extractErrorMessage(error, 'Unknown error') : undefined,
    handleRetry,
    jobs: data?.jobs || [],
    metadata: data?.metadata,
  };
}
