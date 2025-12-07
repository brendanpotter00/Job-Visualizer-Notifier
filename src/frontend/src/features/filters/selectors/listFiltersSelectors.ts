import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../../app/store.ts';
import { selectCurrentCompanyJobsRtk } from '../../jobs/jobsSelectors.ts';
import { isSoftwareOnlyEnabled } from '../../../constants/tags.ts';
import { filterJobsByFilters } from '../utils/jobFilteringUtils';

/**
 * Select list filters
 */
export const selectListFilters = (state: RootState) => state.listFilters.filters;

/**
 * Select whether the software-only toggle is currently ON
 * (checks if all software engineering tags are present)
 */
export const selectListSoftwareOnlyState = createSelector([selectListFilters], (filters) => {
  return isSoftwareOnlyEnabled(filters.searchTags);
});

/**
 * Filter jobs based on list filters
 */
export const selectListFilteredJobs = createSelector(
  [selectCurrentCompanyJobsRtk, selectListFilters],
  (jobs, filters) => {
    return filterJobsByFilters(jobs, filters).sort((a, b) => {
      // Sort by createdAt descending (most recent first)
      return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
    });
  }
);
