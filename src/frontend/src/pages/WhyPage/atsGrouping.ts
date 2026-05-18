import type { Company } from '../../types';

/**
 * Greenhouse boards now flow through the backend `/api/jobs` endpoint, so they
 * share the `backend-scraper` ATS type with the true custom scrapers (Google,
 * Apple, Microsoft). Detect them by URL prefix so the Why page can show them in
 * their own column instead of lumping them in with the custom scrapers.
 */
const GREENHOUSE_BOARD_URL_PREFIX = 'https://boards.greenhouse.io/';

export type ATSGroupKey = Company['ats'] | 'greenhouse';

export function getATSGroupKey(company: Company): ATSGroupKey {
  if (
    company.ats === 'backend-scraper' &&
    company.jobsUrl?.startsWith(GREENHOUSE_BOARD_URL_PREFIX)
  ) {
    return 'greenhouse';
  }
  return company.ats;
}

export const ATS_DISPLAY_NAMES: Record<ATSGroupKey, string> = {
  lever: 'lever',
  ashby: 'ashby',
  workday: 'workday',
  gem: 'gem',
  eightfold: 'eightfold',
  'backend-scraper': 'Custom Web Scrapers',
  greenhouse: 'Greenhouse',
};

export const NON_CAPITALIZED_GROUPS: ReadonlySet<ATSGroupKey> = new Set([
  'backend-scraper',
  'greenhouse',
]);
