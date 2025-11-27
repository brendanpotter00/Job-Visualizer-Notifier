import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../app/store';

/**
 * Select all jobs for a specific company (parameterized selector)
 * Usage: useAppSelector(state => selectJobsForCompany(state, companyId))
 */
export const selectJobsForCompany = createSelector(
  [(state: RootState) => state.jobs.byCompany, (_state: RootState, companyId: string) => companyId],
  (byCompany, companyId) => byCompany[companyId]?.items || []
);

/**
 * Select jobs for the currently selected company
 */
export const selectCurrentCompanyJobs = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state.jobs.byCompany],
  (companyId, byCompany) => byCompany[companyId]?.items || []
);

/**
 * Select loading state for current company
 */
export const selectCurrentCompanyLoading = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state.jobs.byCompany],
  (companyId, byCompany) => byCompany[companyId]?.isLoading || false
);

/**
 * Select error for current company
 */
export const selectCurrentCompanyError = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state.jobs.byCompany],
  (companyId, byCompany) => byCompany[companyId]?.error
);

/**
 * Select metadata for current company
 */
export const selectCurrentCompanyMetadata = createSelector(
  [(state: RootState) => state.app.selectedCompanyId, (state: RootState) => state.jobs.byCompany],
  (companyId, byCompany) =>
    byCompany[companyId]?.metadata || {
      totalCount: 0,
      softwareCount: 0,
    }
);

/**
 * Select software jobs only for current company
 */
export const selectCurrentCompanySoftwareJobs = createSelector([selectCurrentCompanyJobs], (jobs) =>
  jobs.filter((job) => job.classification.isSoftwareAdjacent)
);
