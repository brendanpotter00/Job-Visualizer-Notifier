import { createSelector } from '@reduxjs/toolkit';
import type { RootState } from '../../app/store';
import { selectCurrentCompanyJobs } from '../jobs/jobsSelectors';
import type { Job, TimeWindow } from '../../types';
import { bucketJobsByTime } from '../../utils/timeBucketing';
import { getTimeWindowDuration } from '../../utils/dateUtils';

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

      // Search query filter (multi-tag with OR logic)
      if (filters.searchQuery && filters.searchQuery.length > 0) {
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

        // Job matches if ANY tag matches (OR logic)
        const matchesAnyTag = filters.searchQuery.some(tag =>
          searchableText.includes(tag.toLowerCase())
        );

        if (!matchesAnyTag) {
          return false;
        }
      }

      // Software-only filter
      if (filters.softwareOnly && !job.classification.isSoftwareAdjacent) {
        return false;
      }

      // Location filter
      if (filters.location && job.location !== filters.location) {
        return false;
      }

      // Department filter
      if (filters.department && job.department !== filters.department) {
        return false;
      }

      // Employment type filter
      if (filters.employmentType && job.employmentType !== filters.employmentType) {
        return false;
      }

      // Role category filter
      if (filters.roleCategory && filters.roleCategory !== 'all') {
        if (job.classification.category !== filters.roleCategory) {
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
    return jobs.filter((job: Job) => {
      // Time window filter
      if (!isWithinTimeWindow(job.createdAt, filters.timeWindow)) {
        return false;
      }

      // Search query filter (multi-tag with OR logic)
      if (filters.searchQuery && filters.searchQuery.length > 0) {
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

        // Job matches if ANY tag matches (OR logic)
        const matchesAnyTag = filters.searchQuery.some(tag =>
          searchableText.includes(tag.toLowerCase())
        );

        if (!matchesAnyTag) {
          return false;
        }
      }

      // Software-only filter
      if (filters.softwareOnly && !job.classification.isSoftwareAdjacent) {
        return false;
      }

      // Location filter
      if (filters.location && job.location !== filters.location) {
        return false;
      }

      // Department filter
      if (filters.department && job.department !== filters.department) {
        return false;
      }

      // Employment type filter
      if (filters.employmentType && job.employmentType !== filters.employmentType) {
        return false;
      }

      // Role category filter
      if (filters.roleCategory && filters.roleCategory !== 'all') {
        if (job.classification.category !== filters.roleCategory) {
          return false;
        }
      }

      return true;
    });
  }
);

/**
 * Get unique locations from current company jobs
 */
export const selectAvailableLocations = createSelector(
  [selectCurrentCompanyJobs],
  (jobs) => {
    const locations = jobs
      .map((job) => job.location)
      .filter((loc): loc is string => Boolean(loc));
    return Array.from(new Set(locations)).sort();
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
