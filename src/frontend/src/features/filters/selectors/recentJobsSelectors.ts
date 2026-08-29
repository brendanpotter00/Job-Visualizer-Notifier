import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../../app/store.ts';
import { jobsApi } from '../../jobs/jobsApi.ts';
import { filterJobsByFilters } from '../utils/jobFilteringUtils.ts';
import { selectLocationCatalog } from '../../locations/locationCatalogSlice.ts';
import { isSoftwareOnlyEnabled } from '../../../constants/tags.ts';
import { getCompanyById } from '../../../config/companies.ts';
import { filterJobsByHours } from '../../../lib/date.ts';
import { selectEnabledCompanyIds } from '../../preferences/enabledCompaniesSlice.ts';
import { isCustomCompanyId } from '../../userCompanies/customJobsClient.ts';
import { selectDemoModeEnabled } from '../../ui/uiSlice.ts';
import { DEMO_JOBS } from '../../jobs/demoJobs.ts';
import { selectCompleteHorizon } from '../../jobs/jobsSelectors.ts';
import { clampToHorizon } from '../../jobs/keysetWalk.ts';

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
      // A user-added board is ALWAYS kept. `enabledIds` is the curated public
      // roster, so a `u-<id>` can never be a member — filtering on membership
      // alone made a user who had saved a company set see none of their own
      // private boards on Recent, while a user with the default empty set (=
      // "show all") saw them fine. The preference chooses among PUBLIC
      // companies; it is not a reason to hide the user's own.
      if (enabledSet.has(companyId) || isCustomCompanyId(companyId)) {
        filtered[companyId] = jobs;
      }
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
// The final step is the COMPLETE-PREFIX CLAMP. This is a filter, not sort
// logic: the keyset walk runs one cursor per company-chunk and the chunks
// reach different depths (measured on prod, page 1 of the three chunks cut off
// at 07-30 / 07-28 / 07-21, with 24 companies contributing zero rows). Below
// the shallowest still-walking chunk's floor the merged set is not "partial",
// it is BIASED — some companies present, others silently missing — so rendering
// it would show a plausible-looking list that is quietly wrong. Clamping here,
// at the single upstream source for the Recent page, is what makes every
// downstream consumer (filters, sort, dropdowns, metrics, and the `jobs.length`
// behind ALL_LOADED) agree on one honest set. Rows below the horizon stay
// cached and surface as later pages push it down.
export const selectAllJobsFromQuery = createSelector(
  [selectEnabledByCompanyId, selectDemoModeEnabled, selectCompleteHorizon],
  (byCompanyId, demoModeEnabled, completeHorizon) => {
    if (demoModeEnabled) return DEMO_JOBS;

    const allJobs = Object.values(byCompanyId).flat();

    // Deduplicate by job ID (in case same job appears multiple times)
    const jobsMap = new Map<string, (typeof allJobs)[0]>();
    allJobs.forEach((job) => {
      if (!jobsMap.has(job.id)) {
        jobsMap.set(job.id, job);
      }
    });

    return clampToHorizon(Array.from(jobsMap.values()), completeHorizon);
  }
);

/**
 * Apply filters to all jobs
 * Leverages existing filterJobsByFilters which gracefully handles missing optional filter fields
 */
export const selectRecentFilteredJobs = createSelector(
  [selectAllJobsFromQuery, selectRecentJobsFilters, selectLocationCatalog],
  (allJobs, filters, locationCatalog) => filterJobsByFilters(allJobs, filters, locationCatalog)
);

/**
 * Sort filtered jobs chronologically (most recent first).
 *
 * Ordered by `firstSeenAt` (when WE first saw the job), matching the time-window
 * filter — NOT the ATS posted date, which can be years stale on reposted
 * listings and would sink genuinely-fresh jobs to the bottom.
 */
export const selectRecentJobsSorted = createSelector([selectRecentFilteredJobs], (jobs) => {
  return [...jobs].sort((a, b) => {
    return new Date(b.firstSeenAt).getTime() - new Date(a.firstSeenAt).getTime();
  });
});

/**
 * Apply all filters EXCEPT company filter
 * This is used to determine which companies should appear in the company dropdown
 */
export const selectRecentJobsFilteredWithoutCompany = createSelector(
  [selectAllJobsFromQuery, selectRecentJobsFilters, selectLocationCatalog],
  (allJobs, filters, locationCatalog) => {
    // Create a copy of filters WITHOUT the company field
    const filtersWithoutCompany = { ...filters, company: undefined };
    return filterJobsByFilters(allJobs, filtersWithoutCompany, locationCatalog);
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
