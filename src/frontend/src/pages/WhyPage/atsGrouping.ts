import type { Company } from '../../types';

/**
 * Greenhouse, Ashby, and Gem boards now flow through the backend
 * `/api/jobs` endpoint, so they share the `backend-scraper` ATS type
 * with the true custom scrapers (Google, Apple, Microsoft). The
 * `Company.sourceAts` field tags migrated providers so the Why page
 * can show them in their own column instead of lumping them in with
 * the custom scrapers.
 */
export type ATSGroupKey = Company['ats'] | 'greenhouse' | 'ashby' | 'gem';

export function getATSGroupKey(company: Company): ATSGroupKey {
  if (company.ats === 'backend-scraper' && company.sourceAts) {
    return company.sourceAts;
  }
  return company.ats;
}

export const ATS_DISPLAY_NAMES: Record<ATSGroupKey, string> = {
  lever: 'lever',
  workday: 'workday',
  eightfold: 'eightfold',
  'backend-scraper': 'Custom Web Scrapers',
  greenhouse: 'Greenhouse',
  ashby: 'Ashby',
  gem: 'Gem',
};

export const NON_CAPITALIZED_GROUPS: ReadonlySet<ATSGroupKey> = new Set([
  'backend-scraper',
  'greenhouse',
  'ashby',
  'gem',
]);
