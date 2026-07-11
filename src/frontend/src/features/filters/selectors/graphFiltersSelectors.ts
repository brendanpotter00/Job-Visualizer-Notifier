import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../../app/store.ts';
import { selectCurrentCompanyJobsRtk } from '../../jobs/jobsSelectors.ts';
import { bucketJobsByTime } from '../../../lib/timeBucketing.ts';
import { isSoftwareOnlyEnabled } from '../../../constants/tags.ts';
import { filterJobsByFilters } from '../utils/jobFilteringUtils';
import { selectLocationCatalog } from '../../locations/locationCatalogSlice.ts';

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
 * displays them sorted by creation date descending. Spread before sorting so
 * the array returned by `selectGraphFilteredJobs` (also consumed by
 * `selectGraphBucketData`) is not mutated.
 */
export const selectGraphFilteredJobsSorted = createSelector([selectGraphFilteredJobs], (jobs) =>
  [...jobs].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
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
