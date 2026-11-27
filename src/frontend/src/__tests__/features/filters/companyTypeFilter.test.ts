import { describe, it, expect } from 'vitest';
import {
  filterJobsByFilters,
  matchesCompanyCategory,
} from '../../../features/filters/utils/jobFilteringUtils';
import type { GraphFilters, Job, RecentJobsFilters } from '../../../types';

/**
 * The client-side company type filter. Only demo mode uses it: the live
 * Recent page is server-filtered (`company_category` on `/api/jobs/search`).
 */
function makeJob(company: string): Job {
  const now = new Date().toISOString();
  return {
    id: `${company}-1`,
    source: 'backend-scraper',
    company,
    title: 'Software Engineer',
    createdAt: now,
    firstSeenAt: now,
    url: 'https://example.com',
    raw: {},
  };
}

const recent: RecentJobsFilters = { timeWindow: 'all', softwareOnly: false };

describe('matchesCompanyCategory', () => {
  it('passes every job when nothing is selected', () => {
    expect(matchesCompanyCategory(makeJob('stripe'), undefined)).toBe(true);
    expect(matchesCompanyCategory(makeJob('stripe'), [])).toBe(true);
  });

  it('keeps members and drops non-members', () => {
    expect(matchesCompanyCategory(makeJob('google'), ['big_tech'])).toBe(true);
    expect(matchesCompanyCategory(makeJob('stripe'), ['big_tech'])).toBe(false);
  });

  it('ORs across categories', () => {
    expect(matchesCompanyCategory(makeJob('stripe'), ['big_tech', 'fintech'])).toBe(true);
  });

  it('matches nothing for an unknown slug', () => {
    expect(matchesCompanyCategory(makeJob('google'), ['not_a_type'])).toBe(false);
  });
});

describe('filterJobsByFilters with a company type', () => {
  const jobs = [makeJob('google'), makeJob('stripe'), makeJob('spacex')];

  it('narrows a Recent filter set', () => {
    const out = filterJobsByFilters(jobs, { ...recent, companyCategory: ['big_tech'] });
    expect(out.map((j) => j.company)).toEqual(['google']);
  });

  it('is a no-op when the field is absent (the graph shape has none)', () => {
    const graph: GraphFilters = { timeWindow: 'all', softwareOnly: false };
    expect(filterJobsByFilters(jobs, graph)).toHaveLength(3);
    expect(filterJobsByFilters(jobs, recent)).toHaveLength(3);
  });
});
