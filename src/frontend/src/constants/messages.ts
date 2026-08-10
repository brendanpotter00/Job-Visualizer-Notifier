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

  /**
   * Shown when several consecutive pages of older jobs were fetched and NONE of
   * them matched the active filters, so the list stopped fetching on its own.
   * Deliberately explicit about what happened: the alternative is a list that
   * looks finished but is not, or one that silently walks the whole corpus.
   */
  NO_MATCHES_IN_RECENT_PAGES: 'No more matches in the jobs loaded so far.',

  /**
   * Shown in place of the list while the filter matches nothing loaded so far
   * but the keyset walk still holds older pages and is auto-deepening. The
   * terminal "no jobs found" state is reserved for an exhausted walk — showing
   * it here was the 2026-08-10 empty-filter deadlock.
   */
  SEARCHING_OLDER_JOBS_IN_PROGRESS: 'No matches in the newest postings yet — searching older jobs…',

  /** Label for the manual continue affordance that follows the message above. */
  SEARCH_OLDER_JOBS: 'Search older jobs',

  /** Label for the same affordance after a failed fetch. */
  RETRY_OLDER_JOBS: 'Try again',
} as const;

/**
 * Messages for the feature Changelog on the /vote-features page
 */
export const CHANGELOG_MESSAGES = {
  /**
   * End-of-list message shown when every changelog entry has been revealed via
   * infinite scroll.
   * @param count - Total number of entries shown
   */
  ALL_LOADED: (count: number) => `You're all caught up — showing all ${count} updates`,
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
   * Loading skeleton while revealing more changelog entries
   */
  LOADING_MORE_CHANGELOG: 'Loading more changelog entries',

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

/**
 * Sign-in prompt overlay messages
 * Shown to signed-out users on job list views to encourage sign-up
 */
export const SIGN_IN_OVERLAY_MESSAGES = {
  /**
   * Primary CTA headline
   */
  TITLE: 'Sign in to view more jobs.',

  /**
   * Supporting subtitle emphasizing zero cost
   */
  SUBTITLE: 'No spam emails and free.',

  /**
   * Sign-in button label
   */
  BUTTON_TEXT: 'Sign In',

  /**
   * ARIA label for the overlay region
   */
  ARIA_LABEL: 'Sign in prompt',
} as const;

/**
 * Sign-in prompt modal messages
 * Shown to signed-out users in modal contexts (e.g. feature voting) where
 * an inline overlay is not appropriate. Kept separate from
 * SIGN_IN_OVERLAY_MESSAGES so modal copy can differ without coupling.
 */
export const SIGN_IN_MODAL_MESSAGES = {
  TITLE: 'Sign in to vote',
  SUBTITLE: 'Your upvote helps prioritize what we build next.',
  BUTTON_TEXT: 'Sign In',
} as const;
