import { describe, it, expect } from 'vitest';
import { filterJobsByFilters } from '../../../features/filters/utils/jobFilteringUtils';
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

describe('filterJobsByFilters with a company type', () => {
  const jobs = [makeJob('google'), makeJob('stripe'), makeJob('spacex')];

  const companiesFor = (companyCategory: string[] | undefined) =>
    filterJobsByFilters(jobs, { ...recent, companyCategory }).map((j) => j.company);

  it('passes every job when nothing is selected', () => {
    expect(companiesFor(undefined)).toEqual(['google', 'stripe', 'spacex']);
    expect(companiesFor([])).toEqual(['google', 'stripe', 'spacex']);
  });

  it('keeps members and drops non-members', () => {
    expect(companiesFor(['big_tech'])).toEqual(['google']);
  });

  it('ORs across categories', () => {
    expect(companiesFor(['big_tech', 'fintech'])).toEqual(['google', 'stripe']);
  });

  it('matches nothing for an unknown slug', () => {
    expect(companiesFor(['not_a_type'])).toEqual([]);
  });

  it('is a no-op when the field is absent (the graph shape has none)', () => {
    const graph: GraphFilters = { timeWindow: 'all', softwareOnly: false };
    expect(filterJobsByFilters(jobs, graph)).toHaveLength(3);
    expect(filterJobsByFilters(jobs, recent)).toHaveLength(3);
  });
});
