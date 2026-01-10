import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../app/store';
import { jobsApi } from './jobsApi';

/**
 * Select jobs for currently selected company from RTK Query cache
 */
export const selectCurrentCompanyJobsRtk = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state],
  (companyId, state) => {
    const result = jobsApi.endpoints.getJobsForCompany.select({ companyId })(state);
    return result.data?.jobs || [];
  }
);

/**
 * Select loading state for current company
 */
export const selectCurrentCompanyLoadingRtk = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state],
  (companyId, state) => {
    const result = jobsApi.endpoints.getJobsForCompany.select({ companyId })(state);
    return result.isLoading;
  }
);

/**
 * Select error for current company
 */
export const selectCurrentCompanyError = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state],
  (companyId, state) => {
    const result = jobsApi.endpoints.getJobsForCompany.select({ companyId })(state);
    if (!result.error) return undefined;
    if (typeof result.error === 'string') {
      return result.error;
    }
    if (typeof result.error === 'object' && 'data' in result.error) {
      return String(result.error.data);
    }
    return 'Unknown error';
  }
);

/**
 * Select metadata for current company
 */
export const selectCurrentCompanyMetadataRtk = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state],
  (companyId, state) => {
    const result = jobsApi.endpoints.getJobsForCompany.select({ companyId })(state);
    return (
      result.data?.metadata || {
        totalCount: 0,
      }
    );
  }
);

/**
 * Select jobs for a specific company (parameterized selector)
 * Usage: useAppSelector(state => selectJobsForCompany(state, companyId))
 */
export const selectJobsForCompany = createSelector(
  [(_state: RootState, companyId: string) => companyId, (state: RootState) => state],
  (companyId, state) => {
    const result = jobsApi.endpoints.getJobsForCompany.select({ companyId })(state);
    return result.data?.jobs || [];
  }
);
