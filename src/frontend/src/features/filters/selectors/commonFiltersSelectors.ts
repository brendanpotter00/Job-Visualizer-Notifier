import { createSelector } from '@reduxjs/toolkit';
import { selectCurrentCompanyJobsRtk } from '../../jobs/jobsSelectors.ts';

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
