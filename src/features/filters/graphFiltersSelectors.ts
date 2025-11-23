import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../app/store';
import { selectCurrentCompanyJobs } from '../jobs/jobsSelectors';
import type { Job, TimeWindow } from '../../types';
import { bucketJobsByTime } from '../../utils/timeBucketing';
import { getTimeWindowDuration } from '../../utils/dateUtils';
import { isUnitedStatesLocation } from '../../utils/locationUtils';

/**
 * Select graph filters
 */
export const selectGraphFilters = (state: RootState) => state.graphFilters.filters;

/**
 * Helper function to check if a job is within a time window
 */
function isWithinTimeWindow(jobCreatedAt: string, timeWindow: TimeWindow): boolean {
  const now = new Date();
  const jobDate = new Date(jobCreatedAt);
  const durationMs = getTimeWindowDuration(timeWindow);
  const cutoffTime = now.getTime() - durationMs;

  return jobDate.getTime() >= cutoffTime;
}

/**
 * Filter jobs based on graph filters
 */
export const selectGraphFilteredJobs = createSelector(
  [selectCurrentCompanyJobs, selectGraphFilters],
  (jobs, filters) => {
    return jobs.filter((job: Job) => {
      // Time window filter
      if (!isWithinTimeWindow(job.createdAt, filters.timeWindow)) {
        return false;
      }

      // Search tags filter (include/exclude logic)
      if (filters.searchTags && filters.searchTags.length > 0) {
        const searchableText = [
          job.title,
          job.department,
          job.team,
          job.location,
          ...(job.tags || []),
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase();

        const includeTags = filters.searchTags.filter((t) => t.mode === 'include');
        const excludeTags = filters.searchTags.filter((t) => t.mode === 'exclude');

        // Include logic: If include tags exist, job must match at least one (OR logic)
        if (includeTags.length > 0) {
          const matchesAnyIncludeTag = includeTags.some((tag) =>
            searchableText.includes(tag.text.toLowerCase())
          );

          if (!matchesAnyIncludeTag) {
            return false;
          }
        }

        // Exclude logic: Job must NOT match any exclude tags (AND NOT logic)
        if (excludeTags.length > 0) {
          const matchesAnyExcludeTag = excludeTags.some((tag) =>
            searchableText.includes(tag.text.toLowerCase())
          );

          if (matchesAnyExcludeTag) {
            return false;
          }
        }
      }

      // Software-only filter
      if (filters.softwareOnly && !job.classification.isSoftwareAdjacent) {
        return false;
      }

      // Location filter (multi-select with OR logic)
      if (filters.location && filters.location.length > 0) {
        const matchesLocation = filters.location.some((filterLoc) => {
          // Special handling for "United States" meta-filter
          if (filterLoc === 'United States') {
            return isUnitedStatesLocation(job.location);
          }
          // Exact match for specific locations
          return job.location === filterLoc;
        });

        if (!matchesLocation) {
          return false;
        }
      }

      // Department filter (multi-select with OR logic)
      if (filters.department && filters.department.length > 0) {
        const matchesDepartment = filters.department.some((filterDept) => job.department === filterDept);

        if (!matchesDepartment) {
          return false;
        }
      }

      // Employment type filter
      if (filters.employmentType && job.employmentType !== filters.employmentType) {
        return false;
      }

      // Role category filter (multi-select with OR logic)
      if (filters.roleCategory && filters.roleCategory.length > 0) {
        const matchesCategory = filters.roleCategory.some(
          (filterCat) => job.classification.category === filterCat
        );

        if (!matchesCategory) {
          return false;
        }
      }

      return true;
    });
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
