import type { Company } from '../../types';

/**
 * Greenhouse, Ashby, Lever, Gem, Eightfold, and Workday boards now flow
 * through the backend `/api/jobs` endpoint, so they share the
 * `backend-scraper` ATS type with the true custom scrapers (Google,
 * Apple, Microsoft). The `Company.sourceAts` field tags migrated
 * providers so the Why page can show them in their own column instead
 * of lumping them in with the custom scrapers.
 *
 * Note: `'eightfold'` and `'workday'` are no longer in `Company['ats']`
 * after their respective backend migrations, but stay in this union so
 * the Why page can render dedicated columns for `sourceAts === 'eightfold'`
 * and `sourceAts === 'workday'` companies.
 */
export type ATSGroupKey =
  | Company['ats']
  | 'greenhouse'
  | 'ashby'
  | 'lever'
  | 'gem'
  | 'eightfold'
  | 'workday';

export function getATSGroupKey(company: Company): ATSGroupKey {
  if (company.ats === 'backend-scraper' && company.sourceAts) {
    return company.sourceAts;
  }
  return company.ats;
}

export const ATS_DISPLAY_NAMES: Record<ATSGroupKey, string> = {
  'backend-scraper': 'Custom Web Scrapers',
  greenhouse: 'Greenhouse',
  ashby: 'Ashby',
  lever: 'Lever',
  gem: 'Gem',
  eightfold: 'Eightfold',
  workday: 'Workday',
};

export const NON_CAPITALIZED_GROUPS: ReadonlySet<ATSGroupKey> = new Set([
  'backend-scraper',
  'greenhouse',
  'ashby',
  'lever',
  'gem',
  'eightfold',
  'workday',
]);
