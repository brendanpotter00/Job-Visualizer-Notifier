import type {
  Job,
  TimeWindow,
  SearchTag,
  SoftwareRoleCategory,
  GraphFilters,
  ListFilters,
  RecentJobsFilters,
} from '../../../types';
import { getTimeWindowDuration } from '../../../lib/date.ts';
import { isUnitedStatesLocation } from '../../../lib/location.ts';

/**
 * Shared utility functions for job filtering logic.
 * These pure functions can be used by both graph and list selectors.
 */

/**
 * Check if a job is within a specific time window
 */
export function isJobWithinTimeWindow(jobCreatedAt: string, timeWindow: TimeWindow): boolean {
  const now = new Date();
  const jobDate = new Date(jobCreatedAt);
  const durationMs = getTimeWindowDuration(timeWindow);
  const cutoffTime = now.getTime() - durationMs;

  return jobDate.getTime() >= cutoffTime;
}

/**
 * Check if a job matches search tags (include/exclude logic)
 */
export function matchesSearchTags(job: Job, searchTags: SearchTag[] | undefined): boolean {
  if (!searchTags || searchTags.length === 0) {
    return true;
  }

  const searchableText = [job.title, job.department, job.team, job.location, ...(job.tags || [])]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  const includeTags = searchTags.filter((t) => t.mode === 'include');
  const excludeTags = searchTags.filter((t) => t.mode === 'exclude');

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

  return true;
}

/**
 * Check if a job matches location filter (multi-select with OR logic)
 */
export function matchesLocation(job: Job, locations: string[] | undefined): boolean {
  if (!locations || locations.length === 0) {
    return true;
  }

  return locations.some((filterLoc) => {
    // Special handling for "United States" meta-filter
    if (filterLoc === 'United States') {
      return isUnitedStatesLocation(job.location);
    }
    // Exact match for specific locations
    return job.location === filterLoc;
  });
}

/**
 * Check if a job matches department filter (multi-select with OR logic)
 */
export function matchesDepartment(job: Job, departments: string[] | undefined): boolean {
  if (!departments || departments.length === 0) {
    return true;
  }

  return departments.some((filterDept) => job.department === filterDept);
}

/**
 * Check if a job matches employment type filter
 */
export function matchesEmploymentType(job: Job, employmentType: string | undefined): boolean {
  if (!employmentType) {
    return true;
  }

  return job.employmentType === employmentType;
}

/**
 * Check if a job matches role category filter (multi-select with OR logic)
 */
export function matchesRoleCategory(
  job: Job,
  roleCategories: SoftwareRoleCategory[] | undefined
): boolean {
  if (!roleCategories || roleCategories.length === 0) {
    return true;
  }

  return roleCategories.some((filterCat) => job.classification.category === filterCat);
}

/**
 * Check if a job matches company filter (multi-select with OR logic)
 */
export function matchesCompany(job: Job, companies: string[] | undefined): boolean {
  if (!companies || companies.length === 0) {
    return true;
  }

  return companies.some((filterCompany) => job.company === filterCompany);
}

/**
 * Filter jobs based on provided filters
 * Works with GraphFilters, ListFilters, and RecentJobsFilters
 */
export function filterJobsByFilters(
  jobs: Job[],
  filters: GraphFilters | ListFilters | RecentJobsFilters
): Job[] {
  return jobs.filter((job: Job) => {
    // Time window filter
    if (!isJobWithinTimeWindow(job.createdAt, filters.timeWindow)) {
      return false;
    }

    // Search tags filter (include/exclude logic)
    if (!matchesSearchTags(job, filters.searchTags)) {
      return false;
    }

    // Location filter (multi-select with OR logic)
    if (!matchesLocation(job, filters.location)) {
      return false;
    }

    // Department filter (multi-select with OR logic)
    // Only check if department exists on filters (GraphFilters/ListFilters only)
    if ('department' in filters && !matchesDepartment(job, filters.department)) {
      return false;
    }

    // Employment type filter
    if (!matchesEmploymentType(job, filters.employmentType)) {
      return false;
    }

    // Role category filter (multi-select with OR logic)
    // Only check if roleCategory exists on filters (GraphFilters/ListFilters only)
    if ('roleCategory' in filters && !matchesRoleCategory(job, filters.roleCategory)) {
      return false;
    }

    // Company filter (multi-select with OR logic)
    // Only check if company exists on filters (RecentJobsFilters only)
    if ('company' in filters && !matchesCompany(job, filters.company)) {
      return false;
    }

    return true;
  });
}
