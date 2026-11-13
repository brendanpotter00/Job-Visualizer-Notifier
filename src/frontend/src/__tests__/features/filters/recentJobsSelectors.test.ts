import { describe, it, expect } from 'vitest';
import type { RootState } from '../../../app/store';
import type { RecentJobsFilters } from '../../../types';
import { selectRecentJobsFilters } from '../../../features/filters/selectors/recentJobsSelectors';

/**
 * What is left of the Recent page's selectors after filtering moved to the
 * server and the company dropdown was removed (2026-11-12): the filter slice
 * accessor.
 */

const BASE_FILTERS: RecentJobsFilters = {
  timeWindow: '90d',
  searchTags: undefined,
  location: undefined,
  employmentType: undefined,
  softwareOnly: false,
  category: undefined,
  level: undefined,
};

function makeState(filters: RecentJobsFilters = BASE_FILTERS): RootState {
  return {
    recentJobsFilters: { filters },
  } as unknown as RootState;
}

describe('selectRecentJobsFilters', () => {
  it('returns the filters held by the slice', () => {
    const filters: RecentJobsFilters = { ...BASE_FILTERS, timeWindow: '24h', softwareOnly: true };

    expect(selectRecentJobsFilters(makeState(filters))).toEqual(filters);
  });

  it('returns the slice’s own object reference', () => {
    // Identity matters: the filter signature and the search hook both memoize on
    // this value, so returning a fresh object per call would re-mint the query
    // args — and therefore the RTK Query cache key — on every unrelated render.
    const filters: RecentJobsFilters = { ...BASE_FILTERS };
    const state = makeState(filters);

    expect(selectRecentJobsFilters(state)).toBe(filters);
  });
});
