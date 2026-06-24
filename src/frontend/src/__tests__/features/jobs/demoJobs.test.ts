import { describe, it, expect } from 'vitest';
import { DEMO_JOBS, DEMO_JOB_COUNT } from '../../../features/jobs/demoJobs';
import { getCompanyById } from '../../../config/companies';
import { filterJobsByHours } from '../../../lib/date';

describe('demoJobs (DEMO_JOBS fixture)', () => {
  it(`generates exactly ${DEMO_JOB_COUNT} listings`, () => {
    expect(DEMO_JOBS).toHaveLength(DEMO_JOB_COUNT);
  });

  it('has unique job ids (the dedupe Map keys on id)', () => {
    const ids = DEMO_JOBS.map((j) => j.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('every job is a valid Job with required fields populated', () => {
    for (const job of DEMO_JOBS) {
      expect(job.id).toBeTruthy();
      expect(job.source).toBe('backend-scraper');
      expect(job.company).toBeTruthy();
      expect(job.title).toBeTruthy();
      expect(job.url).toBeTruthy();
      expect(job.raw).toBeDefined();
      expect(Number.isNaN(Date.parse(job.createdAt))).toBe(false);
    }
  });

  it('every company id resolves via getCompanyById (names/logos/links will resolve)', () => {
    const unresolved = DEMO_JOBS.map((j) => j.company).filter((id) => !getCompanyById(id));
    expect(unresolved).toEqual([]);
  });

  it('every job carries a structured primary location tag', () => {
    for (const job of DEMO_JOBS) {
      const locations = job.locations ?? [];
      expect(locations.length).toBeGreaterThan(0);
      const tag = locations[0];
      expect(tag.canonicalName).toBeTruthy();
      expect(tag.kind).toBeTruthy();
    }
  });

  it('every title survives the Software Engineering keyword filter', () => {
    // matchesSearchTags lowercases the title; "engineer"/"developer" are SE tag substrings.
    for (const job of DEMO_JOBS) {
      expect(job.title.toLowerCase()).toMatch(/engineer|developer/);
    }
  });

  it('is weighted toward very recent timestamps (3h and 24h windows non-empty)', () => {
    const last3h = filterJobsByHours(DEMO_JOBS, 3).length;
    const last24h = filterJobsByHours(DEMO_JOBS, 24).length;
    expect(last3h).toBeGreaterThan(0);
    expect(last24h).toBeGreaterThan(last3h);
  });
});
