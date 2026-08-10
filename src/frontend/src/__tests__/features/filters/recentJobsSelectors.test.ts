import { describe, it, expect } from 'vitest';
import type { RootState } from '../../../app/store';
import type { RecentJobsFilters } from '../../../types';
import { COMPANIES } from '../../../config/companies';
import { DEMO_JOBS } from '../../../features/jobs/demoJobs';
import {
  selectRecentCompanyOptions,
  selectRecentJobsFilters,
} from '../../../features/filters/selectors/recentJobsSelectors';

/**
 * What is left of the Recent page's selectors after filtering moved to the
 * server: the filter slice accessor and the company dropdown's option list.
 *
 * The dropdown options are the interesting half. They come from the STATIC
 * company config, never from the jobs on screen — the cache now holds only rows
 * that already match every active filter, so deriving options from it would make
 * the dropdown shrink as the reader narrowed the search, and would hide the very
 * company they were about to pick.
 */

const BASE_FILTERS: RecentJobsFilters = {
  timeWindow: '90d',
  searchTags: undefined,
  location: undefined,
  employmentType: undefined,
  softwareOnly: false,
  company: undefined,
  category: undefined,
  level: undefined,
};

function makeState(
  enabledCompanyIds: string[] | null = null,
  demoModeEnabled = false,
  filters: RecentJobsFilters = BASE_FILTERS
): RootState {
  return {
    recentJobsFilters: { filters },
    enabledCompanies: { ids: enabledCompanyIds },
    ui: { demoModeEnabled },
  } as unknown as RootState;
}

/** Company ids the curated demo fixture actually contains. */
const DEMO_COMPANY_IDS = new Set(DEMO_JOBS.map((job) => job.company));

describe('selectRecentCompanyOptions', () => {
  // `null` (never saved a preference) and `[]` (saved an empty set) both mean
  // "all companies" everywhere else in the preferences code. The dropdown has to
  // agree, or a reader who unchecked everything would be offered nothing to pick.
  it.each([
    ['the reader has never saved a preference (null)', null],
    ['the reader saved an empty set (the [] opt-out)', [] as string[]],
  ])('offers every configured company when %s', (_label, enabledIds) => {
    const options = selectRecentCompanyOptions(makeState(enabledIds));

    expect(options).toHaveLength(COMPANIES.length);
    expect(options.map((o) => o.id).sort()).toEqual(COMPANIES.map((c) => c.id).sort());
  });

  it('orders options by display name', () => {
    const options = selectRecentCompanyOptions(makeState(null));
    const names = options.map((o) => o.name);

    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)));
    // The config is grouped by ATS, not alphabetized, so this proves the sort
    // ran rather than that the source happened to already be in order.
    expect(names).not.toEqual(COMPANIES.map((c) => c.name));
  });

  it('carries the config display name, not the id', () => {
    const options = selectRecentCompanyOptions(makeState(['spacex']));

    expect(options).toEqual([{ id: 'spacex', name: 'SpaceX' }]);
  });

  it('narrows to the reader’s enabled set', () => {
    const options = selectRecentCompanyOptions(makeState(['spotify', 'airbnb']));

    expect(options.map((o) => o.id)).toEqual(['airbnb', 'spotify']);
  });

  it('drops enabled ids that no longer exist in the config', () => {
    // A saved preference outlives a company being removed from the config. The
    // stale id must not become a dropdown entry the server could never match.
    const options = selectRecentCompanyOptions(makeState(['spacex', 'company-that-was-removed']));

    expect(options.map((o) => o.id)).toEqual(['spacex']);
  });

  describe('demo mode', () => {
    it('narrows to the companies present in DEMO_JOBS', () => {
      const options = selectRecentCompanyOptions(makeState(null, true));

      expect(options.length).toBe(DEMO_COMPANY_IDS.size);
      expect(options.every((o) => DEMO_COMPANY_IDS.has(o.id))).toBe(true);
      // Demo mode is a strict subset — the whole point is not offering options
      // that provably match nothing in the curated fixture.
      expect(options.length).toBeLessThan(COMPANIES.length);
    });

    it('ignores the enabled set, because the fixture is fixed', () => {
      // `spacex` is tracked but absent from DEMO_JOBS. Intersecting the two would
      // leave the demo dropdown empty; demo mode must serve the fixture's set.
      expect(DEMO_COMPANY_IDS.has('spacex')).toBe(false);

      const options = selectRecentCompanyOptions(makeState(['spacex'], true));

      expect(options.length).toBe(DEMO_COMPANY_IDS.size);
      expect(options.some((o) => o.id === 'spacex')).toBe(false);
    });
  });
});

describe('selectRecentJobsFilters', () => {
  it('returns the filters held by the slice', () => {
    const filters: RecentJobsFilters = { ...BASE_FILTERS, timeWindow: '24h', softwareOnly: true };

    expect(selectRecentJobsFilters(makeState(null, false, filters))).toEqual(filters);
  });

  it('returns the slice’s own object reference', () => {
    // Identity matters: the filter signature and the search hook both memoize on
    // this value, so returning a fresh object per call would re-mint the query
    // args — and therefore the RTK Query cache key — on every unrelated render.
    const filters: RecentJobsFilters = { ...BASE_FILTERS };
    const state = makeState(null, false, filters);

    expect(selectRecentJobsFilters(state)).toBe(filters);
  });
});
