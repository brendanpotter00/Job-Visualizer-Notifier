/**
 * Application route definitions
 *
 * Centralized routing configuration for type safety and maintainability.
 */

export const ROUTES = {
  COMPANIES: '/',
  RECENT_JOBS: '/recent-jobs',
  WHY: '/why',
} as const;

export const NAV_ITEMS = [
  {
    path: ROUTES.COMPANIES,
    label: 'Company Job Postings',
    icon: 'Business', // MUI Business icon
  },
  {
    path: ROUTES.RECENT_JOBS,
    label: 'Recent Job Postings',
    icon: 'Schedule', // MUI Schedule icon
  },
  {
    path: ROUTES.WHY,
    label: 'Why This Was Built',
    icon: 'Info', // MUI Info icon
  },
] as const;
