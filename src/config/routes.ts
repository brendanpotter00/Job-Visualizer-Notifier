/**
 * Application route definitions
 *
 * Centralized routing configuration for type safety and maintainability.
 */

export const ROUTES = {
  COMPANIES: '/',
  RECENT_JOBS: '/recent-jobs',
} as const;

export const NAV_ITEMS = [
  {
    path: ROUTES.COMPANIES,
    label: 'Companies',
    icon: 'Business', // MUI Business icon
  },
  {
    path: ROUTES.RECENT_JOBS,
    label: 'Recent Job Postings',
    icon: 'Schedule', // MUI Schedule icon
  },
] as const;
