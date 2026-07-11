import { createSelector } from '@reduxjs/toolkit';
import { selectCurrentCompanyJobsRtk } from '../../jobs/jobsSelectors.ts';

/**
 * Get unique departments from current company jobs
 */
export const selectAvailableDepartments = createSelector([selectCurrentCompanyJobsRtk], (jobs) => {
  const departments = jobs
    .map((job) => job.department)
    .filter((dept): dept is string => Boolean(dept));
  return Array.from(new Set(departments)).sort();
});

/**
 * Get unique employment types from current company jobs
 */
export const selectAvailableEmploymentTypes = createSelector(
  [selectCurrentCompanyJobsRtk],
  (jobs) => {
    const types = jobs
      .map((job) => job.employmentType)
      .filter((type): type is string => Boolean(type));
    return Array.from(new Set(types)).sort();
  }
);
