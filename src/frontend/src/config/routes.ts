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
} as const;

export const NAV_ITEMS = [
  {
    path: ROUTES.RECENT_JOBS,
    label: 'Recent Job Postings',
    icon: 'Schedule', // MUI Schedule icon
  },
  {
    path: ROUTES.COMPANIES,
    label: 'Company Job Postings',
    icon: 'Business', // MUI Business icon
  },
  {
    path: ROUTES.WHY,
    label: 'Why This Was Built',
    icon: 'Info', // MUI Info icon
  },
  {
    path: ROUTES.VOTE_FEATURES,
    label: 'Vote for features',
    icon: 'ThumbUp', // MUI ThumbUp icon
  },
  {
    path: ROUTES.QA,
    label: 'QA',
    icon: 'BugReport',
  },
] as const;
