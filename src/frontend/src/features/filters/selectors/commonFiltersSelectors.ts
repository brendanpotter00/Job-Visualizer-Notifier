import { createSelector } from '@reduxjs/toolkit';
import { selectCurrentCompanyJobsRtk } from '../../jobs/jobsSelectors.ts';
import { buildLocationOptions } from '../../../lib/location.ts';

/**
 * Get the selectable location options for the current company.
 * Built from normalized canonical tags via `buildLocationOptions`, which
 * collapses variants and SYNTHESIZES pickable parents ("United States", each
 * "<State>, US") so the hierarchy is navigable. Matching containment lives in
 * `matchesLocation`.
 */
export const selectAvailableLocations = createSelector([selectCurrentCompanyJobsRtk], (jobs) =>
  buildLocationOptions(jobs)
);

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
