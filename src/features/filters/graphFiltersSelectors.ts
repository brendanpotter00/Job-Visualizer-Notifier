import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../app/store';
import { selectCurrentCompanyJobsRtk } from '../jobs/jobsSelectors';
import { bucketJobsByTime } from '../../utils/timeBucketing';
import { isSoftwareOnlyEnabled } from '../../constants/softwareEngineeringTags';
import { filterJobsByFilters } from '../../utils/jobFilteringUtils';

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
  [selectCurrentCompanyJobsRtk, selectGraphFilters],
  (jobs, filters) => {
    return filterJobsByFilters(jobs, filters);
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
