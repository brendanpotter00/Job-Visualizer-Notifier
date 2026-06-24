import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../../app/store.ts';
import { jobsApi } from '../../jobs/jobsApi.ts';
import { filterJobsByFilters } from '../utils/jobFilteringUtils.ts';
import { buildLocationOptions } from '../../../lib/location.ts';
import { isSoftwareOnlyEnabled } from '../../../constants/tags.ts';
import { getCompanyById } from '../../../config/companies.ts';
import { filterJobsByHours } from '../../../lib/date.ts';
import { selectEnabledCompanyIds } from '../../preferences/enabledCompaniesSlice.ts';
import { selectDemoModeEnabled } from '../../ui/uiSlice.ts';
import { DEMO_JOBS } from '../../jobs/demoJobs.ts';

export const selectRecentJobsFilters = (state: RootState) => state.recentJobsFilters.filters;

const selectByCompanyIdFromQuery = createSelector(
  [(state: RootState) => jobsApi.endpoints.getAllJobs.select()(state).data],
  (data) => data?.byCompanyId ?? {}
);

const selectEnabledByCompanyId = createSelector(
  [selectByCompanyIdFromQuery, selectEnabledCompanyIds],
  (byCompanyId, enabledIds) => {
    if (!enabledIds || enabledIds.length === 0) return byCompanyId;
    const enabledSet = new Set(enabledIds);
    const filtered: typeof byCompanyId = {};
    for (const [companyId, jobs] of Object.entries(byCompanyId)) {
      if (enabledSet.has(companyId)) filtered[companyId] = jobs;
    }
    return filtered;
  }
);

// Pre-filters by the user's enabled-companies preference (null or [] = all).
// When admin "Demo mode" is on, returns the curated DEMO_JOBS instead. This is the single
// upstream source for the Recent page, so every downstream filter/sort/metric/dropdown
// operates on demo data unchanged. Demo mode intentionally bypasses both the RTK Query cache
// AND the enabled-companies prefilter (it shows all curated jobs regardless of the user's set).
// Note: the flag is only set by the admin-gated Account toggle, but this selector does not
// re-check admin status (admin lives in the useCurrentUser hook, not Redux) — same UI-only
// enforcement as hideAdminFeatures. DEMO_JOBS is a stable module-level constant, so returning
// it preserves reselect's reference-equality memoization.
export const selectAllJobsFromQuery = createSelector(
  [selectEnabledByCompanyId, selectDemoModeEnabled],
  (byCompanyId, demoModeEnabled) => {
    if (demoModeEnabled) return DEMO_JOBS;

    const allJobs = Object.values(byCompanyId).flat();

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
  // Build options from normalized canonical tags via `buildLocationOptions`:
  // variants collapse into single tags, and pickable parents ("United States",
  // each "<State>, US") are synthesized so the hierarchy is navigable.
  (jobs) => buildLocationOptions(jobs)
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
  })
);

/**
 * Calculate time-based job counts for Recent Jobs page
 * Returns counts for jobs posted in last 24 hours and last 3 hours
 * Uses memoized selector pattern for optimal performance
 *
 * @returns Object with jobsLast24Hours and jobsLast3Hours counts
 */
export const selectRecentJobsTimeBasedCounts = createSelector(
  [selectAllJobsFromQuery],
  (allJobs) => ({
    jobsLast24Hours: filterJobsByHours(allJobs, 24).length,
    jobsLast3Hours: filterJobsByHours(allJobs, 3).length,
  })
);
