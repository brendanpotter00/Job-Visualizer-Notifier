import { describe, it, expect } from 'vitest';
import { createTestStore } from '../../../test/testUtils';
import { jobsApi } from '../../../features/jobs/jobsApi';
import { ATSConstants } from '../../../api/types';
import type { Job, JobLocation } from '../../../types';
import { selectAvailableLocations } from '../../../features/filters/selectors/commonFiltersSelectors';

// Builds a companies-page store (selectAvailableLocations reads the
// `getJobsForCompany` RTK Query cache for state.app.selectedCompanyId).
// Mirrors the ListFilters.test.tsx seeding pattern.
async function seedStore(jobs: Job[], companyId = 'spacex') {
  const store = createTestStore({
    app: {
      selectedCompanyId: companyId,
      selectedATS: ATSConstants.BackendScraper as const,
      isInitialized: true,
    },
  });
  await store.dispatch(
    jobsApi.util.upsertQueryData(
      'getJobsForCompany',
      { companyId },
      {
        jobs,
        metadata: { totalCount: jobs.length, fetchedAt: '2026-06-14T00:00:00Z' },
      }
    )
  );
  return store;
}

// Helper: derives a single city tag from the raw `location` string (canonicalName
// === the string, country null so no implicit "United States" option) unless the
// caller passes `locations` explicitly — same convention as recentJobsSelectors.test.ts.
const makeJob = (overrides: Partial<Job> = {}): Job => {
  const job: Job = {
    id: '1',
    source: 'backend-scraper',
    company: 'spacex',
    title: 'Software Engineer',
    location: 'San Francisco, CA',
    createdAt: '2026-06-14T00:00:00Z',
    url: 'https://example.com/job/1',
    raw: {},
    ...overrides,
  };
  if (job.locations === undefined && job.location) {
    job.locations = [{ canonicalName: job.location, kind: 'city', country: null, isPrimary: true }];
  }
  return job;
};

describe('commonFiltersSelectors', () => {
  describe('selectAvailableLocations', () => {
    it('builds options from canonical tags (not raw strings) and returns them sorted', async () => {
      const jobs: Job[] = [
        makeJob({ id: '1', location: 'San Francisco, CA' }),
        makeJob({ id: '2', location: 'Austin, TX' }),
        makeJob({ id: '3', location: 'San Francisco, CA' }), // duplicate raw string
      ];

      const store = await seedStore(jobs);
      const result = selectAvailableLocations(store.getState());

      // Sorted, unique canonical-tag options. No "United States" (country is null).
      expect(result).toEqual(['Austin, TX', 'San Francisco, CA']);
      expect(result).not.toContain('United States');
    });

    it('collapses raw location variants into a single canonical tag option', async () => {
      // Three different raw strings + a multi-location string, all normalizing to
      // the same Austin tag, must yield exactly ONE "Austin, TX, US" option.
      const austinTag: JobLocation = {
        canonicalName: 'Austin, TX, US',
        kind: 'city',
        city: 'Austin',
        region: 'TX',
        country: 'US',
        remoteScope: null,
        isPrimary: true,
      };
      const atlantaTag: JobLocation = {
        canonicalName: 'Atlanta, GA, US',
        kind: 'city',
        city: 'Atlanta',
        region: 'GA',
        country: 'US',
        remoteScope: null,
        isPrimary: false,
      };
      const jobs: Job[] = [
        makeJob({ id: '1', location: 'Austin - 5323', locations: [austinTag] }),
        makeJob({ id: '2', location: 'Austin, Texas, United States', locations: [austinTag] }),
        makeJob({
          id: '3',
          location: 'Austin, TX, USA; Atlanta, GA, USA',
          locations: [austinTag, atlantaTag],
        }),
      ];

      const store = await seedStore(jobs);
      const result = selectAvailableLocations(store.getState());

      // "United States" meta + synthesized state parents (Georgia, Texas) + the
      // two distinct canonical city tags. "Austin, TX, US" appears exactly once
      // despite 3 source rows / raw strings.
      expect(result).toEqual([
        'United States',
        'Georgia, US',
        'Texas, US',
        'Atlanta, GA, US',
        'Austin, TX, US',
      ]);
      expect(result.filter((l) => l === 'Austin, TX, US')).toHaveLength(1);
    });

    it('prepends "United States" only when a job carries a US-country tag', async () => {
      const londonTag: JobLocation = {
        canonicalName: 'London, GB',
        kind: 'city',
        city: 'London',
        region: null,
        country: 'GB',
        remoteScope: null,
        isPrimary: true,
      };
      const jobs: Job[] = [makeJob({ id: '1', location: 'London', locations: [londonTag] })];

      const store = await seedStore(jobs);
      const result = selectAvailableLocations(store.getState());

      expect(result).toEqual(['London, GB']);
      expect(result).not.toContain('United States');
    });

    it('does not duplicate "United States" when a canonical country tag already says so', async () => {
      // Raw "US" normalizes to a country-kind tag whose canonicalName IS
      // "United States"; it must not collide with the prepended meta-option.
      const usCountryTag: JobLocation = {
        canonicalName: 'United States',
        kind: 'country',
        city: null,
        region: null,
        country: 'US',
        remoteScope: null,
        isPrimary: true,
      };
      const austinTag: JobLocation = {
        canonicalName: 'Austin, TX, US',
        kind: 'city',
        city: 'Austin',
        region: 'TX',
        country: 'US',
        remoteScope: null,
        isPrimary: true,
      };
      const jobs: Job[] = [
        makeJob({ id: '1', location: 'US', locations: [usCountryTag] }),
        makeJob({ id: '2', location: 'Austin, TX, USA', locations: [austinTag] }),
      ];

      const store = await seedStore(jobs);
      const result = selectAvailableLocations(store.getState());

      expect(result.filter((l) => l === 'United States')).toHaveLength(1);
      // The country-only tag synthesizes no state; the Austin tag synthesizes "Texas, US".
      expect(result).toEqual(['United States', 'Texas, US', 'Austin, TX, US']);
    });

    it('returns an empty array when the selected company has no jobs', async () => {
      const store = await seedStore([]);
      const result = selectAvailableLocations(store.getState());
      expect(result).toEqual([]);
    });
  });
});
