import { createSelector } from '@reduxjs/toolkit';
import { selectCurrentCompanyJobsRtk } from '../jobs/jobsSelectors';
import { isUnitedStatesLocation } from '../../utils/locationUtils';

/**
 * Get unique locations from current company jobs
 * Prepends "United States" as first option if any US locations exist
 */
export const selectAvailableLocations = createSelector([selectCurrentCompanyJobsRtk], (jobs) => {
  const locations = jobs.map((job) => job.location).filter((loc): loc is string => Boolean(loc));
  const uniqueLocations = Array.from(new Set(locations)).sort();

  // Add "United States" as first option if there are any US locations
  const hasUSLocations = uniqueLocations.some(isUnitedStatesLocation);
  if (hasUSLocations) {
    return ['United States', ...uniqueLocations];
  }

  return uniqueLocations;
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
export const selectAvailableEmploymentTypes = createSelector([selectCurrentCompanyJobsRtk], (jobs) => {
  const types = jobs
    .map((job) => job.employmentType)
    .filter((type): type is string => Boolean(type));
  return Array.from(new Set(types)).sort();
});
