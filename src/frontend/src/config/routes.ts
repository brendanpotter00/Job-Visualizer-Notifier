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
  DESIGN_SYSTEM: '/design-system',
} as const;

export type NavIconName = 'Business' | 'Schedule' | 'Info' | 'BugReport' | 'Palette';

export interface NavItem {
  path: string;
  label: string;
  icon: NavIconName;
  devOnly?: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  {
    path: ROUTES.RECENT_JOBS,
    label: 'Recent Job Postings',
    icon: 'Schedule',
  },
  {
    path: ROUTES.COMPANIES,
    label: 'Company Job Postings',
    icon: 'Business',
  },
  {
    path: ROUTES.WHY,
    label: 'Why This Was Built',
    icon: 'Info',
  },
  {
    path: ROUTES.QA,
    label: 'QA',
    icon: 'BugReport',
    devOnly: true,
  },
  {
    path: ROUTES.DESIGN_SYSTEM,
    label: 'Design System',
    icon: 'Palette',
    devOnly: true,
  },
];
