/**
 * Application route definitions
 *
 * Centralized routing configuration for type safety and maintainability.
 */

export const ROUTES = {
  RECENT_JOBS: '/',
  COMPANIES: '/companies',
  WHY: '/why',
  QA: '/qa',
  ACCOUNT: '/account',
  VOTE_FEATURES: '/vote-features',
  ADMIN_USERS: '/admin/users',
} as const;

export const USER_NAV_ITEMS = [
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
    path: ROUTES.VOTE_FEATURES,
    label: 'Vote for features',
    icon: 'ThumbUp',
  },
  {
    path: ROUTES.WHY,
    label: 'Why This Was Built',
    icon: 'Info',
  },
] as const;

export const ADMIN_NAV_ITEMS = [
  {
    path: ROUTES.ADMIN_USERS,
    label: 'Users',
    icon: 'People',
  },
  {
    path: ROUTES.QA,
    label: 'Scraper Runs',
    icon: 'BugReport',
  },
] as const;

/**
 * Legacy combined export — non-admin items only. Kept for any incidental
 * consumer that iterates the full sidebar; admin items must come from
 * ADMIN_NAV_ITEMS and be gated on `user.isAdmin`.
 */
export const NAV_ITEMS = USER_NAV_ITEMS;
