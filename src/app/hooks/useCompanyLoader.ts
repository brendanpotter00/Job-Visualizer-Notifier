import { useEffect, useCallback } from 'react';
import { useAppDispatch, useAppSelector } from '../hooks';
import { setSelectedCompanyId } from '../../features/app/appSlice';
import { loadJobsForCompany } from '../../features/jobs/jobsThunks';
import {
  selectCurrentCompanyError,
  selectCurrentCompanyLoading,
} from '../../features/jobs/jobsSelectors';
import { getInitialCompanyId } from '../../utils/urlParams';

/**
 * Custom hook for managing company selection initialization and job loading
 *
 * Responsibilities:
 * - Initialize selected company from URL on mount
 * - Load jobs whenever the selected company changes
 * - Provide retry functionality for failed requests
 *
 * @returns Object containing loading state, error message, and retry handler
 */
export function useCompanyLoader() {
  const dispatch = useAppDispatch();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);
  const isLoading = useAppSelector(selectCurrentCompanyLoading);
  const error = useAppSelector(selectCurrentCompanyError);

  // Initialize company from URL on mount
  useEffect(() => {
    const initialCompanyId = getInitialCompanyId();
    if (initialCompanyId !== selectedCompanyId) {
      dispatch(setSelectedCompanyId(initialCompanyId));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run on mount

  // Load jobs when company changes
  useEffect(() => {
    dispatch(
      loadJobsForCompany({
        companyId: selectedCompanyId,
      })
    );
  }, [dispatch, selectedCompanyId]);

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
