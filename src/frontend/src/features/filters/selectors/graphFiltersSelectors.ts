import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../../app/store.ts';
import { selectCurrentCompanyJobsRtk } from '../../jobs/jobsSelectors.ts';
import { bucketJobsByTime } from '../../../lib/timeBucketing.ts';
import { isSoftwareOnlyEnabled } from '../../../constants/tags.ts';
import { filterJobsByFilters } from '../utils/jobFilteringUtils';
import { selectLocationCatalog } from '../../locations/locationCatalogSlice.ts';
import { CUSTOM_COMPANIES_CONFIG } from '../../../config/customCompanies.ts';
import { isCustomCompanyId } from '../../userCompanies/customJobsClient.ts';

/**
 * Select graph filters
 */
export const selectGraphFilters = (state: RootState) => state.graphFilters.filters;

/**
 * Select whether the software-only toggle is currently ON
 * (checks if all software engineering tags are present)
 */
export const selectGraphSoftwareOnlyState = createSelector([selectGraphFilters], (filters) => {
  return isSoftwareOnlyEnabled(filters.searchTags);
});

/**
 * Filter jobs based on graph filters
 */
export const selectGraphFilteredJobs = createSelector(
  [selectCurrentCompanyJobsRtk, selectGraphFilters, selectLocationCatalog],
  (jobs, filters, locationCatalog) => {
    return filterJobsByFilters(jobs, filters, locationCatalog);
  }
);

/**
 * Graph-filtered jobs sorted most-recent-first, for the job list view.
 *
 * The list view shares the graph's filters (single source of truth), but
 * displays them sorted by `firstSeenAt` descending (when WE first saw the job) —
 * matching the time-window filter and buckets, NOT the ATS posted date. Spread
 * before sorting so the array returned by `selectGraphFilteredJobs` (also
 * consumed by `selectGraphBucketData`) is not mutated.
 */
export const selectGraphFilteredJobsSorted = createSelector([selectGraphFilteredJobs], (jobs) =>
  [...jobs].sort((a, b) => new Date(b.firstSeenAt).getTime() - new Date(a.firstSeenAt).getTime())
);

/** How many jobs the enrichment-dependent filters are hiding, and out of how many. */
export interface PendingEnrichmentCount {
  /** Jobs that pass every OTHER filter and are hidden only for want of enrichment. */
  hidden: number;
  /** Jobs that pass every other filter — the denominator the note reads against. */
  total: number;
  /** Which filter(s) are doing the hiding, so the copy can name the right control. */
  blockedBy: 'category' | 'level' | 'both';
}

/** Returned by identity when there is nothing to say, so subscribers never re-render. */
const NO_PENDING_ENRICHMENT: PendingEnrichmentCount = Object.freeze({
  hidden: 0,
  total: 0,
  blockedBy: 'category' as const,
});

/**
 * Why a user-added board can look completely empty the day it is added.
 *
 * A category or level filter requires a job to CARRY that facet, so an
 * unenriched job (`category`/`level` null) is hidden — correctly; see
 * `matchesCategory`. The trouble is that enrichment lags a new board badly
 * (measured in production: 1,246 of one board's 1,250 jobs had no enrichment row
 * at all), so a user with a saved category filter adds a company, opens its
 * trend page, and is shown an empty chart with no hint that the jobs exist and
 * the filter is what is hiding them.
 *
 * This counts exactly that population — jobs that pass every other filter and
 * fail ONLY because they are not enriched yet — so the page can say so. It does
 * NOT change what is filtered; the filter is right and stays right.
 *
 * Scoped to custom boards for now (and to the flag): every curated company is
 * long since enriched, so for them this is permanently zero and the extra
 * `filterJobsByFilters` pass would be pure cost. `createSelector` means it runs
 * only when the jobs, the filters or the selected company actually change.
 */
export const selectPendingEnrichmentHidden = createSelector(
  [
    selectCurrentCompanyJobsRtk,
    selectGraphFilters,
    selectLocationCatalog,
    (state: RootState) => state.app.selectedCompanyId,
  ],
  (jobs, filters, locationCatalog, companyId): PendingEnrichmentCount => {
    if (!CUSTOM_COMPANIES_CONFIG.isEnabled || !isCustomCompanyId(companyId)) {
      return NO_PENDING_ENRICHMENT;
    }
    const categoryActive = (filters.category?.length ?? 0) > 0;
    const levelActive = (filters.level?.length ?? 0) > 0;
    if (!categoryActive && !levelActive) return NO_PENDING_ENRICHMENT;

    // Everything the user asked for EXCEPT the two enrichment facets, so the
    // count is about enrichment alone and never blames it for a time window or
    // a location that would have excluded the job anyway.
    const withoutEnrichmentFilters = { ...filters, category: undefined, level: undefined };
    const passesEverythingElse = filterJobsByFilters(
      jobs,
      withoutEnrichmentFilters,
      locationCatalog
    );
    const hidden = passesEverythingElse.filter(
      (job) => (categoryActive && job.category == null) || (levelActive && job.level == null)
    ).length;
    if (hidden === 0) return NO_PENDING_ENRICHMENT;
    return {
      hidden,
      total: passesEverythingElse.length,
      blockedBy: categoryActive && levelActive ? 'both' : categoryActive ? 'category' : 'level',
    };
  }
);

/**
 * Select bucketed data for graph visualization
 */
export const selectGraphBucketData = createSelector(
  [selectGraphFilteredJobs, selectGraphFilters],
  (jobs, filters) => {
    return bucketJobsByTime(jobs, filters.timeWindow);
  }
);
