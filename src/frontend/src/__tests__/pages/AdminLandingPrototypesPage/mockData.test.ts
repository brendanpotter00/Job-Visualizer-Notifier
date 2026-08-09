import { describe, it, expect } from 'vitest';
import { buildMockJobs, buildSparseMockJobs, MOCK_STATS } from '../../../pages/AdminLandingPrototypesPage/mockData';
import { COMPANIES } from '../../../config/companies';
import { FALLBACK_CATEGORIES, FALLBACK_LEVELS } from '../../../constants/enrichment';

const NOW = new Date('2026-08-09T18:00:00Z').getTime();
const HOUR = 3_600_000;
const DAY = 24 * HOUR;

const COMPANY_IDS = new Set(COMPANIES.map((c) => c.id));
const CATEGORY_SLUGS = new Set(FALLBACK_CATEGORIES.map((c) => c.slug));
const LEVEL_SLUGS = new Set(FALLBACK_LEVELS.map((l) => l.slug));

describe('landing prototype mock data', () => {
  const rich = buildMockJobs(NOW);
  const sparse = buildSparseMockJobs(NOW);

  it.each([
    ['rich', rich],
    ['sparse', sparse],
  ])('%s fixture uses only real company ids and valid enrichment slugs', (_name, jobs) => {
    for (const job of jobs) {
      expect(COMPANY_IDS, `unknown company id: ${job.company}`).toContain(job.company);
      expect(CATEGORY_SLUGS, `bad category on ${job.id}`).toContain(job.category);
      expect(LEVEL_SLUGS, `bad level on ${job.id}`).toContain(job.level);
      expect(job.source).toBe('backend-scraper');
      expect(job.createdAt).toBe(job.firstSeenAt);
      expect(job.enrichmentStatus).toBe('done');
    }
  });

  it.each([
    ['rich', rich],
    ['sparse', sparse],
  ])('%s fixture ids are unique and timestamps sit inside the last 7 days', (_name, jobs) => {
    expect(new Set(jobs.map((j) => j.id)).size).toBe(jobs.length);
    for (const job of jobs) {
      const seen = new Date(job.firstSeenAt).getTime();
      expect(seen).toBeLessThanOrEqual(NOW);
      expect(seen).toBeGreaterThanOrEqual(NOW - 7 * DAY);
    }
  });

  it('rich fixture populates every freshness bucket the sections exercise', () => {
    const ageOf = (firstSeenAt: string) => NOW - new Date(firstSeenAt).getTime();
    const ages = rich.map((j) => ageOf(j.firstSeenAt));
    expect(ages.some((age) => age < 3 * HOUR)).toBe(true);
    expect(ages.some((age) => age >= 3 * HOUR && age < 24 * HOUR)).toBe(true);
    expect(ages.some((age) => age >= 24 * HOUR && age < 48 * HOUR)).toBe(true);
    expect(ages.some((age) => age >= 2 * DAY)).toBe(true);
  });

  it('sparse fixture models the weekend reality (few jobs, ≤2 inside 24h)', () => {
    expect(sparse.length).toBeLessThan(20);
    const within24h = sparse.filter(
      (j) => NOW - new Date(j.firstSeenAt).getTime() < 24 * HOUR
    );
    expect(within24h.length).toBeLessThanOrEqual(2);
  });

  it('companiesTracked derives from the registry', () => {
    expect(MOCK_STATS.companiesTracked).toBe(COMPANIES.length);
  });
});
