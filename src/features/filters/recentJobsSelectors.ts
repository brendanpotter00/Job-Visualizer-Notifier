import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../app/store';
import { jobsApi } from '../jobs/jobsApi';
import { filterJobsByFilters } from '../../utils/jobFilteringUtils';
import { isSoftwareOnlyEnabled } from '../../constants/softwareEngineeringTags';
import { getCompanyById } from '../../config/companies';

/**
 * Selectors for Recent Jobs page filters and data
 */

/**
 * Base selector for recent jobs filters
 */
export const selectRecentJobsFilters = (state: RootState) => state.recentJobsFilters.filters;

/**
 * Get all jobs from RTK Query (flatten byCompanyId structure)
 * Deduplicates jobs by ID to handle edge cases
 */
export const selectAllJobsFromQuery = createSelector(
  [(state: RootState) => jobsApi.endpoints.getAllJobs.select()(state).data],
  (data) => {
    if (!data?.byCompanyId) return [];
    const allJobs = Object.values(data.byCompanyId).flat();

    // Deduplicate by job ID (in case same job appears multiple times)
    const jobsMap = new Map<string, (typeof allJobs)[0]>();
    allJobs.forEach((job) => {
      if (!jobsMap.has(job.id)) {
        jobsMap.set(job.id, job);
      }
    });

    return Array.from(jobsMap.values());
  }
);

/**
 * Apply filters to all jobs
 * Leverages existing filterJobsByFilters which gracefully handles missing department/roleCategory
 */
export const selectRecentFilteredJobs = createSelector(
  [selectAllJobsFromQuery, selectRecentJobsFilters],
  (allJobs, filters) => filterJobsByFilters(allJobs, filters)
);

/**
 * Sort filtered jobs chronologically (most recent first)
 */
export const selectRecentJobsSorted = createSelector([selectRecentFilteredJobs], (jobs) => {
  return [...jobs].sort((a, b) => {
    return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
  });
});

/**
 * Apply all filters EXCEPT company filter
 * This is used to determine which companies should appear in the company dropdown
 */
export const selectRecentJobsFilteredWithoutCompany = createSelector(
  [selectAllJobsFromQuery, selectRecentJobsFilters],
  (allJobs, filters) => {
    // Create a copy of filters WITHOUT the company field
    const filtersWithoutCompany = { ...filters, company: undefined };
    return filterJobsByFilters(allJobs, filtersWithoutCompany);
  }
);

/**
 * Apply all filters EXCEPT location filter
 * Used to determine which locations should appear in the location dropdown
 *
 * Filters applied (in order):
 * 1. Time Window - required, always applied
 * 2. Company - if selected (multi-select OR logic)
 * 3. Search Tags - if any tags added (include/exclude logic)
 * 4. Employment Type - if selected
 * 5. Software-Only - if enabled
 * 6. Location - EXCLUDED (determining availability for this filter)
 */
export const selectRecentJobsFilteredWithoutLocation = createSelector(
  [selectAllJobsFromQuery, selectRecentJobsFilters],
  (allJobs, filters) => {
    // Create a copy of filters WITHOUT the location field
    const filtersWithoutLocation = { ...filters, location: undefined };
    return filterJobsByFilters(allJobs, filtersWithoutLocation);
  }
);

/**
 * Get available locations from filtered jobs (excluding location filter)
 * Only shows locations that have jobs matching all OTHER active filters
 * Creates dynamic, context-aware dropdown
 *
 * Example scenarios:
 * - If time window=1h, only shows locations with jobs in past hour
 * - If company selected, only shows locations for that company
 * - If employment type=Full-time, only shows locations with full-time jobs
 * - If software-only enabled, only shows locations with software eng. roles
 */
export const selectRecentAvailableLocations = createSelector(
  [selectRecentJobsFilteredWithoutLocation],
  (jobs) => {
    const locations = new Set<string>();
    jobs.forEach((job) => {
      if (job.location) locations.add(job.location);
    });
    return Array.from(locations).sort();
  }
);

/**
 * Get available employment types from all jobs
 */
export const selectRecentAvailableEmploymentTypes = createSelector(
  [selectAllJobsFromQuery],
  (jobs) => {
    const types = new Set<string>();
    jobs.forEach((job) => {
      if (job.employmentType) types.add(job.employmentType);
    });
    return Array.from(types).sort();
  }
);

/**
 * Get available companies from filtered jobs (excluding company filter)
 * Returns array of {id, name} objects for display in UI
 */
export const selectRecentAvailableCompanies = createSelector(
  [selectRecentJobsFilteredWithoutCompany],
  (jobs) => {
    const companyIds = new Set<string>();
    jobs.forEach((job) => {
      if (job.company) companyIds.add(job.company);
    });

    // Convert company IDs to {id, name} objects and sort by name
    return Array.from(companyIds)
      .map((id) => {
        const company = getCompanyById(id);
        return {
          id,
          name: company?.name || id,
        };
      })
      .sort((a, b) => a.name.localeCompare(b.name));
  }
);

/**
 * Check if software-only toggle is enabled
 */
export const selectRecentSoftwareOnlyState = createSelector([selectRecentJobsFilters], (filters) =>
  isSoftwareOnlyEnabled(filters.searchTags)
);

/**
 * Get metadata about filtered jobs
 */
export const selectRecentJobsMetadata = createSelector(
  [selectRecentJobsSorted, selectAllJobsFromQuery],
  (filteredJobs, allJobs) => ({
    totalJobs: allJobs.length,
    filteredCount: filteredJobs.length,
    companiesRepresented: new Set(filteredJobs.map((j) => j.company)).size,
  })
);
