import type { TimeWindow, SoftwareRoleCategory } from '../types';

/**
 * Available time window options for filtering jobs
 */
export const TIME_WINDOWS: { value: TimeWindow; label: string }[] = [
  { value: '30m', label: '30 minutes' },
  { value: '1h', label: '1 hour' },
  { value: '3h', label: '3 hours' },
  { value: '6h', label: '6 hours' },
  { value: '12h', label: '12 hours' },
  { value: '24h', label: '24 hours' },
  { value: '3d', label: '3 days' },
  { value: '7d', label: '7 days' },
  { value: '14d', label: '14 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: '180d', label: '6 months' },
  { value: '1y', label: '1 year' },
  { value: '2y', label: '2 years' },
];

/**
 * Available software role categories for filtering
 */
export const ROLE_CATEGORIES: { value: SoftwareRoleCategory; label: string }[] = [
  { value: 'frontend', label: 'Frontend' },
  { value: 'backend', label: 'Backend' },
  { value: 'fullstack', label: 'Full Stack' },
  { value: 'mobile', label: 'Mobile' },
  { value: 'data', label: 'Data' },
  { value: 'ml', label: 'ML/AI' },
  { value: 'devops', label: 'DevOps' },
  { value: 'platform', label: 'Platform' },
  { value: 'qa', label: 'QA' },
  { value: 'security', label: 'Security' },
];
