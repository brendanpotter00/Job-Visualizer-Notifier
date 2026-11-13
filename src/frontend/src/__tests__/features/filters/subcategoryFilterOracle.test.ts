import { describe, it, expect } from 'vitest';
import {
  matchesSubcategory,
  filterJobsByFilters,
} from '../../../features/filters/utils/jobFilteringUtils';
import { SUBCATEGORY_FILTER_EXPANSION } from '../../../constants/enrichment';
import { loadSubcategoryOracle } from '../../subcategoryOracle';
import type { GraphFilters, Job } from '../../../types';

/**
 * THE VITEST HALF of the cross-language oracle.
 *
 * The pytest half
 * (`src/backend/api/tests/test_jobs_search_filters.py::test_server_matches_the_committed_subcategory_oracle`)
 * seeds the same rows into Postgres and asserts `/api/jobs/search?subcategory=…`
 * returns the same ids. Neither side invents rows: both read
 * `src/backend/api/tests/fixtures/subcategory_filter_oracle.json`, which is the
 * only mechanical way to assert two languages agree — two hand-maintained lists
 * are exactly the thing that drifts.
 *
 * A divergence here is not a cosmetic bug. The Recent page filters server-side
 * and the Companies page filters in the browser, so the two implementations sit
 * behind the same checkbox: a reader ticking Backend on one page and on the
 * other must not get answers built from different rules.
 */

const ORACLE = loadSubcategoryOracle();

function toJob(row: (typeof ORACLE)['jobs'][number]): Job {
  const createdAt = '2026-06-01T09:00:00.000Z';
  return {
    id: row.job_id,
    source: 'backend-scraper',
    company: 'google',
    title: 'Software Engineer',
    createdAt,
    firstSeenAt: createdAt,
    url: 'https://example.com',
    raw: {},
    category: row.enrichment_category,
    subcategories: row.enrichment_subcategories,
  };
}

const JOBS: Job[] = ORACLE.jobs.map(toJob);

const BASE_FILTERS: GraphFilters = {
  timeWindow: 'all',
  searchTags: undefined,
  location: undefined,
  employmentType: undefined,
  softwareOnly: false,
};

describe('subcategory filter oracle (client half)', () => {
  it('reads a fixture that actually covers the tri-state and the widening', () => {
    // Guards the whole file against a fixture that silently lost its
    // interesting rows: every assertion below would still pass on an
    // all-labelled corpus while proving much less.
    const arrays = ORACLE.jobs.map((j) => j.enrichment_subcategories);
    expect(arrays).toContainEqual(null);
    expect(arrays).toContainEqual([]);
    expect(arrays.some((a) => a?.length === 2)).toBe(true);
    expect(arrays.some((a) => a?.includes('full_stack'))).toBe(true);
    expect(ORACLE.selections.length).toBeGreaterThanOrEqual(6);
  });

  it('declares the same expansion map the client implements', () => {
    expect(SUBCATEGORY_FILTER_EXPANSION).toEqual(ORACLE.expansion);
  });

  it.each(ORACLE.selections.map((c) => [c.name, c] as const))(
    'matchesSubcategory agrees with the oracle: %s',
    (_name, testCase) => {
      const selection = testCase.subcategory.length ? testCase.subcategory : undefined;
      const actual = JOBS.filter((job) => matchesSubcategory(job, selection)).map((j) => j.id);

      expect([...actual].sort()).toEqual([...testCase.expected].sort());
    }
  );

  it.each(ORACLE.category_composition.map((c) => [c.name, c] as const))(
    'filterJobsByFilters agrees with the oracle: %s',
    (_name, testCase) => {
      const actual = filterJobsByFilters(JOBS, {
        ...BASE_FILTERS,
        category: testCase.category.length ? testCase.category : undefined,
        subcategory: testCase.subcategory.length ? testCase.subcategory : undefined,
      }).map((j) => j.id);

      expect([...actual].sort()).toEqual([...testCase.expected].sort());
    }
  );

  it('is not vacuous: most selections pick a non-empty PROPER subset', () => {
    const total = JOBS.length;
    const strictSubsets = ORACLE.selections.filter(
      (c) => c.expected.length > 0 && c.expected.length < total
    ).length;

    expect(strictSubsets).toBeGreaterThanOrEqual(ORACLE.selections.length - 3);
  });
});
