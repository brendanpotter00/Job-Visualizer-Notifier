import { useEffect, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../hooks';
import { setSelectedCompanyId } from '../../features/app/appSlice';
import { loadJobsForCompany } from '../../features/jobs/jobsThunks';
import {
  selectCurrentCompanyError,
  selectCurrentCompanyLoading,
} from '../../features/jobs/jobsSelectors';
import { getInitialCompanyId } from '../../utils/urlParams';
import { ROUTES } from '../../config/routes';

/**
 * Custom hook for managing company selection initialization and job loading
 *
 * Responsibilities:
 * - Initialize selected company from URL on mount (Companies page only)
 * - Load jobs whenever the selected company changes (Companies page only)
 * - Provide retry functionality for failed requests
 *
 * Note: This hook only runs on the Companies page to prevent
 * unnecessary API calls on other pages.
 *
 * @returns Object containing loading state, error message, and retry handler
 */
export function useCompanyLoader() {
  const location = useLocation();
  const dispatch = useAppDispatch();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);
  const isLoading = useAppSelector(selectCurrentCompanyLoading);
  const error = useAppSelector(selectCurrentCompanyError);

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

  // Load jobs when company changes (only on Companies page)
  useEffect(() => {
    if (!isCompaniesPage) return;

    dispatch(
      loadJobsForCompany({
        companyId: selectedCompanyId,
      })
    );
  }, [dispatch, selectedCompanyId, isCompaniesPage]);

  // Memoized retry handler to prevent unnecessary re-renders
  const handleRetry = useCallback(() => {
    dispatch(
      loadJobsForCompany({
        companyId: selectedCompanyId,
      })
    );
  }, [dispatch, selectedCompanyId]);

  return {
    isLoading,
    error,
    handleRetry,
  };
}
