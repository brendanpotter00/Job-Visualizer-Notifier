import { describe, it, expect } from 'vitest';
import {
  filterJobsByFilters,
  matchesSubcategory,
} from '../../../features/filters/utils/jobFilteringUtils';
import type { GraphFilters, Job } from '../../../types';

/**
 * A specialty narrows SOFTWARE jobs only (the onboarding "scope" decision):
 * Product Manager + Backend shows every PM job plus the Backend SWE jobs. The
 * server applies the same rule in `services/job_search.py`; the committed
 * oracle (`subcategoryFilterOracle.test.ts`) pins the two together, and this
 * file pins the client rule with a PM row, the onboarding case itself.
 */

function job(id: string, category: string | null, subcategories: string[] | null): Job {
  const at = '2026-11-01T09:00:00.000Z';
  return {
    id,
    source: 'backend-scraper',
    company: 'google',
    title: 'Role',
    createdAt: at,
    firstSeenAt: at,
    url: 'https://example.com',
    raw: {},
    category,
    subcategories,
  };
}

const JOBS: Job[] = [
  job('swe-backend', 'software_engineering', ['backend']),
  job('swe-full-stack', 'software_engineering', ['full_stack']),
  job('swe-frontend', 'software_engineering', ['frontend']),
  job('swe-null', 'software_engineering', null),
  job('pm-a', 'product_manager', null),
  job('pm-b', 'product_manager', []),
  job('ds', 'data_scientist', null),
  job('unenriched', null, null),
];

const BASE: GraphFilters = {
  timeWindow: 'all',
  searchTags: undefined,
  location: undefined,
  employmentType: undefined,
  softwareOnly: false,
};

const ids = (filters: Partial<GraphFilters>) =>
  filterJobsByFilters(JOBS, { ...BASE, ...filters })
    .map((j) => j.id)
    .sort();

describe('subcategory scope: a specialty narrows only software jobs', () => {
  it('PM + Backend keeps every PM job and narrows the SWE jobs', () => {
    expect(
      ids({ category: ['product_manager', 'software_engineering'], subcategory: ['backend'] })
    ).toEqual(['pm-a', 'pm-b', 'swe-backend', 'swe-full-stack']);
  });

  it('Software Engineering alone still narrows to the specialty', () => {
    expect(ids({ category: ['software_engineering'], subcategory: ['backend'] })).toEqual([
      'swe-backend',
      'swe-full-stack',
    ]);
  });

  it('a non-SWE role alone ignores the specialty', () => {
    expect(ids({ category: ['product_manager'], subcategory: ['backend'] })).toEqual([
      'pm-a',
      'pm-b',
    ]);
  });

  it('with no category the specialty filters on its own, as before', () => {
    expect(ids({ subcategory: ['backend'] })).toEqual(['swe-backend', 'swe-full-stack']);
  });

  it('matchesSubcategory without categories keeps the plain overlap', () => {
    const pm = JOBS.find((j) => j.id === 'pm-a')!;
    expect(matchesSubcategory(pm, ['backend'])).toBe(false);
    expect(matchesSubcategory(pm, ['backend'], ['product_manager'])).toBe(true);
    // An unenriched job is never let through by the scope rule.
    const unenriched = JOBS.find((j) => j.id === 'unenriched')!;
    expect(matchesSubcategory(unenriched, ['backend'], ['product_manager'])).toBe(false);
  });
});
