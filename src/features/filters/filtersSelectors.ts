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
export const selectGraphFilters = (state: RootState) => state.filters.graph;

/**
 * Select list filters
 */
export const selectListFilters = (state: RootState) => state.filters.list;

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

        const includeTags = filters.searchTags.filter(t => t.mode === 'include');
        const excludeTags = filters.searchTags.filter(t => t.mode === 'exclude');

        // Include logic: If include tags exist, job must match at least one (OR logic)
        if (includeTags.length > 0) {
          const matchesAnyIncludeTag = includeTags.some(tag =>
            searchableText.includes(tag.text.toLowerCase())
          );

          if (!matchesAnyIncludeTag) {
            return false;
          }
        }

        // Exclude logic: Job must NOT match any exclude tags (AND NOT logic)
        if (excludeTags.length > 0) {
          const matchesAnyExcludeTag = excludeTags.some(tag =>
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
        const matchesLocation = filters.location.some(filterLoc => {
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
        const matchesDepartment = filters.department.some(
          filterDept => job.department === filterDept
        );

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
          filterCat => job.classification.category === filterCat
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
 * Filter jobs based on list filters
 */
export const selectListFilteredJobs = createSelector(
  [selectCurrentCompanyJobs, selectListFilters],
  (jobs, filters) => {
    return jobs
      .filter((job: Job) => {
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

          const includeTags = filters.searchTags.filter(t => t.mode === 'include');
          const excludeTags = filters.searchTags.filter(t => t.mode === 'exclude');

          // Include logic: If include tags exist, job must match at least one (OR logic)
          if (includeTags.length > 0) {
            const matchesAnyIncludeTag = includeTags.some(tag =>
              searchableText.includes(tag.text.toLowerCase())
            );

            if (!matchesAnyIncludeTag) {
              return false;
            }
          }

          // Exclude logic: Job must NOT match any exclude tags (AND NOT logic)
          if (excludeTags.length > 0) {
            const matchesAnyExcludeTag = excludeTags.some(tag =>
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
          const matchesLocation = filters.location.some(filterLoc => {
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
          const matchesDepartment = filters.department.some(
            filterDept => job.department === filterDept
          );

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
            filterCat => job.classification.category === filterCat
          );

          if (!matchesCategory) {
            return false;
          }
        }

        return true;
      })
      .sort((a, b) => {
        // Sort by createdAt descending (most recent first)
        return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime();
      });
  }
);

/**
 * Get unique locations from current company jobs
 * Prepends "United States" as first option if any US locations exist
 */
export const selectAvailableLocations = createSelector(
  [selectCurrentCompanyJobs],
  (jobs) => {
    const locations = jobs
      .map((job) => job.location)
      .filter((loc): loc is string => Boolean(loc));
    const uniqueLocations = Array.from(new Set(locations)).sort();

    // Add "United States" as first option if there are any US locations
    const hasUSLocations = uniqueLocations.some(isUnitedStatesLocation);
    if (hasUSLocations) {
      return ['United States', ...uniqueLocations];
    }

    return uniqueLocations;
  }
);

/**
 * Get unique departments from current company jobs
 */
export const selectAvailableDepartments = createSelector(
  [selectCurrentCompanyJobs],
  (jobs) => {
    const departments = jobs
      .map((job) => job.department)
      .filter((dept): dept is string => Boolean(dept));
    return Array.from(new Set(departments)).sort();
  }
);

/**
 * Get unique employment types from current company jobs
 */
export const selectAvailableEmploymentTypes = createSelector(
  [selectCurrentCompanyJobs],
  (jobs) => {
    const types = jobs
      .map((job) => job.employmentType)
      .filter((type): type is string => Boolean(type));
    return Array.from(new Set(types)).sort();
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
