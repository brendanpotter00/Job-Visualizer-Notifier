import type { Company } from '../types';

/**
 * Greenhouse, Ashby, Lever, Gem, Eightfold, and Workday boards now flow
 * through the backend `/api/jobs` endpoint, so they share the
 * `backend-scraper` ATS type with the true custom scrapers (Google,
 * Apple, Microsoft). The `Company.sourceAts` field tags migrated
 * providers so the UI can show their original provider instead of
 * lumping them in with the custom scrapers.
 *
 * Note: `'eightfold'` and `'workday'` are no longer in `Company['ats']`
 * after their respective backend migrations, but stay in this union so
 * consumers can render dedicated labels for `sourceAts === 'eightfold'`
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

/**
 * Human-readable label for a single company's *true* data source, used by the
 * Company Hiring Trends header. The `backend-scraper` ATS type is only the
 * fetch mechanism — every company's jobs originate from its original provider,
 * so we resolve that via `sourceAts` (Greenhouse/Ashby/Lever/Gem/Eightfold/
 * Workday). The true custom scrapers (Google/Apple/Microsoft) carry no
 * `sourceAts` and are labeled "Custom Web Scraper" (singular, unlike the Why
 * page's plural column header which groups all three).
 */
export function getCompanySourceLabel(company: Company): string {
  const key = getATSGroupKey(company);
  return key === 'backend-scraper' ? 'Custom Web Scraper' : ATS_DISPLAY_NAMES[key];
}
