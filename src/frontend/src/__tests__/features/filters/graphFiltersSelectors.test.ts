import { describe, it, expect } from 'vitest';
import { createTestStore } from '../../../test/testUtils';
import { jobsApi } from '../../../features/jobs/jobsApi';
import { ATSConstants } from '../../../api/types';
import type { Job } from '../../../types';
import {
  selectGraphFilteredJobs,
  selectGraphFilteredJobsSorted,
} from '../../../features/filters/selectors/graphFiltersSelectors';

// Jobs seeded deliberately OUT of createdAt order so a sort actually has work to
// do (Feb, then Jan, then Mar). Mirrors ListSection.test.tsx's Job shape.
const jobs: Job[] = [
  {
    id: 'j-feb',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Frontend Engineer',
    createdAt: '2026-02-01T00:00:00Z',
    firstSeenAt: '2026-02-01T00:00:00Z',
    url: 'https://example.com/j-feb',
    location: 'Hawthorne, CA',
    department: 'Engineering',
    raw: {},
  },
  {
    id: 'j-jan',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Backend Engineer',
    createdAt: '2026-01-01T00:00:00Z',
    firstSeenAt: '2026-01-01T00:00:00Z',
    url: 'https://example.com/j-jan',
    location: 'Hawthorne, CA',
    department: 'Engineering',
    raw: {},
  },
  {
    id: 'j-mar',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Recruiter',
    createdAt: '2026-03-01T00:00:00Z',
    firstSeenAt: '2026-03-01T00:00:00Z',
    url: 'https://example.com/j-mar',
    location: 'Remote',
    department: 'People',
    raw: {},
  },
];

// Realistic graphFilters so every seeded job passes the filter (timeWindow 'all'
// disables the time cutoff; softwareOnly off keeps the non-engineering row).
async function seedStore(graphFilters: Record<string, unknown> = { timeWindow: 'all', softwareOnly: false }) {
  const store = createTestStore({
    app: {
      selectedCompanyId: 'spacex',
      selectedATS: ATSConstants.BackendScraper as const,
      isInitialized: true,
    },
    graphFilters: { filters: graphFilters },
  });
  await store.dispatch(
    jobsApi.util.upsertQueryData(
      'getJobsForCompany',
      { companyId: 'spacex' },
      { jobs, metadata: { totalCount: jobs.length, fetchedAt: '2026-04-01T00:00:00Z' } }
    )
  );
  return store;
}

describe('selectGraphFilteredJobsSorted', () => {
  it('returns the filtered jobs sorted most-recent-first (descending createdAt)', async () => {
    const store = await seedStore();

    const sorted = selectGraphFilteredJobsSorted(store.getState());

    expect(sorted.map((j) => j.id)).toEqual(['j-mar', 'j-feb', 'j-jan']);

    // Spot-check the ordering invariant directly on the timestamps.
    const times = sorted.map((j) => new Date(j.createdAt).getTime());
    for (let i = 1; i < times.length; i++) {
      expect(times[i - 1]).toBeGreaterThanOrEqual(times[i]);
    }
  });

  it('does NOT mutate or reorder the array returned by selectGraphFilteredJobs (the array selectGraphBucketData also consumes)', async () => {
    const store = await seedStore();
    const state = store.getState();

    // Capture the base selector's array + its order BEFORE the sorted selector runs.
    const baseBefore = selectGraphFilteredJobs(state);
    const baseOrderBefore = baseBefore.map((j) => j.id);
    // memoized selectors return a stable reference; snapshot it to detect in-place sorting.
    expect(baseOrderBefore).toEqual(['j-feb', 'j-jan', 'j-mar']);

    // Running the sorted selector must NOT touch the base array. If a future
    // change replaced `[...jobs].sort(...)` with `jobs.sort(...)`, the base
    // array would be reordered in place and this assertion would fail.
    const sorted = selectGraphFilteredJobsSorted(state);
    expect(sorted.map((j) => j.id)).toEqual(['j-mar', 'j-feb', 'j-jan']);

    const baseAfter = selectGraphFilteredJobs(state);
    // Same reference (selector memoization) AND same original order — unmutated.
    expect(baseAfter).toBe(baseBefore);
    expect(baseAfter.map((j) => j.id)).toEqual(baseOrderBefore);

    // And the sorted output is a distinct array, not an alias of the base array.
    expect(sorted).not.toBe(baseBefore);
  });

  it('orders by firstSeenAt desc even when createdAt order disagrees', async () => {
    // The list ranks by when WE first saw a job, not its (display-only) posted
    // date. `j-newest-seen` has the OLDEST createdAt but the NEWEST firstSeenAt,
    // so it must sort first — proving the sort keys off firstSeenAt.
    const mixedJobs: Job[] = [
      {
        id: 'j-mid',
        source: 'backend-scraper',
        company: 'spacex',
        title: 'Backend Engineer',
        createdAt: '2026-02-01T00:00:00Z',
        firstSeenAt: '2026-02-01T00:00:00Z',
        url: 'https://example.com/j-mid',
        location: 'Hawthorne, CA',
        department: 'Engineering',
        raw: {},
      },
      {
        id: 'j-newest-seen',
        source: 'backend-scraper',
        company: 'spacex',
        title: 'Staff Engineer',
        createdAt: '2020-01-01T00:00:00Z', // stale posted date (display only)
        firstSeenAt: '2026-03-15T00:00:00Z', // newest discovery — sorts first
        url: 'https://example.com/j-newest-seen',
        location: 'Remote',
        department: 'Engineering',
        raw: {},
      },
      {
        id: 'j-earliest-seen',
        source: 'backend-scraper',
        company: 'spacex',
        title: 'Frontend Engineer',
        createdAt: '2026-01-01T00:00:00Z',
        firstSeenAt: '2026-01-01T00:00:00Z',
        url: 'https://example.com/j-earliest-seen',
        location: 'Hawthorne, CA',
        department: 'Engineering',
        raw: {},
      },
    ];

    const store = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: ATSConstants.BackendScraper as const,
        isInitialized: true,
      },
      graphFilters: { filters: { timeWindow: 'all', softwareOnly: false } },
    });
    await store.dispatch(
      jobsApi.util.upsertQueryData(
        'getJobsForCompany',
        { companyId: 'spacex' },
        { jobs: mixedJobs, metadata: { totalCount: mixedJobs.length, fetchedAt: '2026-04-01T00:00:00Z' } }
      )
    );

    const sorted = selectGraphFilteredJobsSorted(store.getState());

    // firstSeenAt order: j-newest-seen (Mar) > j-mid (Feb) > j-earliest-seen (Jan)
    expect(sorted.map((j) => j.id)).toEqual(['j-newest-seen', 'j-mid', 'j-earliest-seen']);
  });
});
