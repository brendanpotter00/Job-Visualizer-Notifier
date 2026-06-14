/**
 * Configuration constants for infinite scrolling functionality
 * Used by RecentJobsList component and useInfiniteScroll hook
 */
export const INFINITE_SCROLL_CONFIG = {
  /**
   * Initial number of jobs to display on page load
   * Higher value = faster initial perceived performance but longer first render
   */
  INITIAL_BATCH_SIZE: 50,

  /**
   * Number of jobs to load on each scroll trigger
   * Lower value = more frequent loading, higher value = less frequent scrolling
   */
  SUBSEQUENT_BATCH_SIZE: 25,

  /**
   * Root margin for IntersectionObserver (prefetch distance)
   * Triggers loading before sentinel becomes visible
   */
  SENTINEL_ROOT_MARGIN: '200px',

  /**
   * Threshold for IntersectionObserver
   * 0.1 = trigger when 10% of sentinel is visible
   */
  SENTINEL_THRESHOLD: 0.1,

  /**
   * Number of skeleton cards to show while loading next batch
   */
  SKELETON_COUNT: 3,

  /**
   * Scroll position (in pixels) after which BackToTopButton appears
   */
  BACK_TO_TOP_THRESHOLD: 500,

  /**
   * Debounce delay for scroll event listener (in milliseconds)
   */
  SCROLL_DEBOUNCE_MS: 100,
} as const;

/**
 * Configuration for incremental (infinite-scroll) rendering of the feature
 * Changelog on the /vote-features page.
 *
 * The changelog data is static client-side config, so this is purely about how
 * many cards we render at once — not network loading. Batches are intentionally
 * smaller than INFINITE_SCROLL_CONFIG (which is tuned for compact job rows):
 * changelog cards are larger, and INITIAL_BATCH_SIZE: 50 would render the entire
 * list up front, defeating the purpose. The IntersectionObserver margin and
 * threshold are shared with INFINITE_SCROLL_CONFIG for consistent behavior.
 */
export const CHANGELOG_INFINITE_SCROLL_CONFIG = {
  /**
   * Number of changelog cards rendered on initial mount (and after the tag
   * filter changes).
   */
  INITIAL_BATCH_SIZE: 10,

  /**
   * Number of additional changelog cards revealed each time the sentinel
   * scrolls into view.
   */
  SUBSEQUENT_BATCH_SIZE: 10,

  /**
   * Number of skeleton cards shown while the next batch is being revealed.
   */
  SKELETON_COUNT: 2,
} as const;

/**
 * Configuration for the SignInOverlay shown on job lists when signed out.
 * Purpose: limit visible jobs to encourage sign-up while still providing a preview.
 */
export const SIGN_IN_OVERLAY_CONFIG = {
  /**
   * Maximum number of jobs a signed-out visitor can see on any list before the
   * SignInOverlay takes over. Applies uniformly to the recent jobs page, the
   * companies page list, and the graph-bucket modal.
   */
  SIGNED_OUT_JOB_LIMIT: 12,

  /**
   * Height (in pixels) of the gradient fade that sits above the CTA.
   * The gradient transitions from transparent to the container background color
   * so the last visible jobs appear to fade into the page.
   */
  GRADIENT_HEIGHT: 120,
} as const;
