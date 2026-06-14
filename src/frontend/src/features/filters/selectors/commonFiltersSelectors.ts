import { createSelector } from '@reduxjs/toolkit';
import { selectCurrentCompanyJobsRtk } from '../../jobs/jobsSelectors.ts';

/**
 * Get unique location tags from current company jobs.
 * Built from normalized canonical tags (not raw strings), so variants collapse
 * into one option each. Prepends "United States" when any job has a US tag.
 */
export const selectAvailableLocations = createSelector([selectCurrentCompanyJobsRtk], (jobs) => {
  const locations = new Set<string>();
  let hasUSLocations = false;
  jobs.forEach((job) => {
    job.locations?.forEach((loc) => {
      locations.add(loc.canonicalName);
      if (loc.country === 'US') hasUSLocations = true;
    });
  });
  const sorted = Array.from(locations).sort();
  // Dedupe: a canonical "United States" country tag (raw location was "US")
  // collides with the prepended meta-option — keep one (the meta, at front).
  return hasUSLocations ? Array.from(new Set(['United States', ...sorted])) : sorted;
});

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
