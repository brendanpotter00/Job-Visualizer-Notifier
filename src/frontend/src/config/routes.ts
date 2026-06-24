/**
 * Application route definitions
 *
 * Centralized routing configuration for type safety and maintainability.
 */

export const ROUTES = {
  RECENT_JOBS: '/',
  COMPANIES: '/companies',
  CURATED_COMPANIES: '/curated-companies',
  WHY: '/why',
  QA: '/qa',
  ACCOUNT: '/account',
  SAVED_FILTERS: '/saved-filters',
  VOTE_FEATURES: '/vote-features',
  ADMIN_USERS: '/admin/users',
  ADMIN_LOCATION_NORMALIZATION: '/admin/location-normalization',
  // Public route (not admin-gated). Admins still get a sidebar link via
  // ADMIN_NAV_ITEMS; everyone else reaches it from the Changelog card.
  LOCATION_PIPELINE: '/location-pipeline',
  ADMIN_FEEDBACK: '/admin/feedback',
} as const;

/**
 * Functional tabs — the core app features. Rendered above the "INFO" divider
 * in the sidebar.
 */
export const PRIMARY_NAV_ITEMS = [
  {
    path: ROUTES.RECENT_JOBS,
    label: 'Recent Job Postings',
    icon: 'Schedule',
  },
  {
    path: ROUTES.COMPANIES,
    label: 'Company Hiring Trends',
    icon: 'TrendingUp',
  },
  {
    path: ROUTES.SAVED_FILTERS,
    label: 'Saved Filters',
    icon: 'FilterListAlt',
  },
] as const;

/**
 * Info tabs — supplementary / informational pages. Rendered below the "INFO"
 * divider in the sidebar, mirroring the ADMIN group's divider + caption.
 */
export const INFO_NAV_ITEMS = [
  {
    path: ROUTES.CURATED_COMPANIES,
    label: 'Curated Companies',
    icon: 'Business',
  },
  {
    path: ROUTES.VOTE_FEATURES,
    label: 'Give Feedback',
    icon: 'ThumbUp',
  },
  {
    path: ROUTES.WHY,
    label: 'Why This Was Built',
    icon: 'Info',
  },
] as const;

/**
 * Combined customer-facing nav items (functional + info), in display order.
 * Retained for incidental consumers that iterate the full non-admin sidebar.
 */
export const USER_NAV_ITEMS = [...PRIMARY_NAV_ITEMS, ...INFO_NAV_ITEMS] as const;

export const ADMIN_NAV_ITEMS = [
  {
    path: ROUTES.ADMIN_USERS,
    label: 'Users',
    icon: 'People',
  },
  {
    path: ROUTES.ADMIN_LOCATION_NORMALIZATION,
    label: 'Location Normalization',
    icon: 'Place',
  },
  {
    path: ROUTES.LOCATION_PIPELINE,
    label: 'Location Pipeline',
    icon: 'AccountTree',
  },
  {
    path: ROUTES.QA,
    label: 'Scraper Runs',
    icon: 'BugReport',
  },
  {
    path: ROUTES.ADMIN_FEEDBACK,
    label: 'User Feedback',
    icon: 'Feedback',
  },
] as const;

/**
 * Legacy combined export — non-admin items only. Kept for any incidental
 * consumer that iterates the full sidebar; admin items must come from
 * ADMIN_NAV_ITEMS and be gated on `user.isAdmin`.
 */
export const NAV_ITEMS = USER_NAV_ITEMS;
