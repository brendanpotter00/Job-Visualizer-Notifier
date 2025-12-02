/**
 * User-facing message constants
 *
 * Centralizes all user-facing messages for easier maintenance,
 * consistency, and potential future i18n support.
 */

/**
 * Empty state messages for job lists
 */
export const EMPTY_STATE_MESSAGES = {
  /**
   * Primary message when no jobs match filters
   */
  NO_JOBS_TITLE: 'No jobs found matching your filters',

  /**
   * Helpful hint suggesting user actions
   */
  NO_JOBS_HINT: 'Try adjusting your filters or extending the time window',

  /**
   * Message shown when all jobs have been loaded in infinite scroll
   * @param count - Total number of jobs loaded
   */
  ALL_LOADED: (count: number) => `All ${count} jobs loaded`,
} as const;

/**
 * ARIA labels for accessibility
 */
export const ARIA_LABELS = {
  /**
   * Loading skeleton during infinite scroll
   */
  LOADING_MORE_JOBS: 'Loading more jobs',

  /**
   * Back to top button
   */
  SCROLL_TO_TOP: 'Scroll to top',
} as const;

/**
 * Error messages
 */
export const ERROR_MESSAGES = {
  /**
   * Generic error message for failed job loading
   */
  LOAD_JOBS_FAILED: 'Failed to load job postings. Please try again later.',
} as const;
