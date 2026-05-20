import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';

// Override COMPANIES with a tiny mixed fixture BEFORE the jobsApi module
// loads — otherwise we'd be exercising the production 100+ company list
// and the test would hit dozens of unrelated fetch mocks.
vi.mock('../../../config/companies', () => {
  // After the Eightfold (#124) and Workday (#123) backend migrations,
  // every supported ATS is `backend-scraper`. The old "partitioning"
  // case (backend-scraper batched call + per-company fallback for other
  // ATSes) still exists in jobsApi.ts but has no live consumers; the
  // tests below cover the surviving behavior — single batched call and
  // a cache entry per company even when the response omits some rows.
  const COMPANIES = [
    {
      id: 'stripe',
      name: 'Stripe',
      ats: 'backend-scraper' as const,
      config: { type: 'backend-scraper', companyId: 'stripe' },
    },
    {
      id: 'airbnb',
      name: 'Airbnb',
      ats: 'backend-scraper' as const,
      config: { type: 'backend-scraper', companyId: 'airbnb' },
    },
    {
      id: 'discord',
      name: 'Discord',
      ats: 'backend-scraper' as const,
      config: { type: 'backend-scraper', companyId: 'discord' },
    },
  ];
  return {
    COMPANIES,
    getCompanyById: (id: string) => COMPANIES.find((c) => c.id === id),
  };
});

import { jobsApi } from '../../../features/jobs/jobsApi';

function makeBackendRow(company: string, id: string) {
  return {
    id,
    title: `${company} role`,
    company,
    location: 'Remote',
    url: `https://example.com/${id}`,
    sourceId: 'greenhouse',
    details: JSON.stringify({ experience_level: 'L4', is_remote_eligible: true }),
    createdAt: '2026-05-01T00:00:00Z',
    postedOn: '2026-05-01T00:00:00Z',
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt: '2026-05-01T00:00:00Z',
    lastSeenAt: '2026-05-17T00:00:00Z',
    consecutiveMisses: 0,
    detailsScraped: true,
  };
}

function makeStore() {
  return configureStore({
    reducer: { [jobsApi.reducerPath]: jobsApi.reducer },
    middleware: (gdm) => gdm().concat(jobsApi.middleware),
  });
}

describe('jobsApi getAllJobs partitioning', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn((url: string) => {
      if (url.startsWith('/api/jobs')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => [
            makeBackendRow('stripe', 'stripe-1'),
            makeBackendRow('airbnb', 'airbnb-1'),
            // discord intentionally absent — still gets a cache entry
          ],
        });
      }
      // No non-backend-scraper ATSes exist post-migration; any other
      // URL is a regression — fail loudly so it shows up in the test
      // output instead of silently shaping a stub response.
      throw new Error(`unexpected fetch URL in jobsApi.batched test: ${url}`);
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('issues exactly one /api/jobs call for all backend-scraper companies', async () => {
    const store = makeStore();
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;

    // onCacheEntryAdded is async and runs after the initial return — give
    // the microtask queue several ticks to flush.
    for (let i = 0; i < 10; i++) {
      await Promise.resolve();
    }
    // And one more macrotask, since the cache-entry lifecycle yields.
    await new Promise((resolve) => setTimeout(resolve, 20));

    const jobsCalls = fetchMock.mock.calls.filter(([url]) =>
      typeof url === 'string' && url.startsWith('/api/jobs')
    );
    expect(jobsCalls.length).toBe(1);
    const [batchedUrl] = jobsCalls[0];
    expect(batchedUrl).toContain('companies=stripe%2Cairbnb%2Cdiscord');
    // Must NOT use the singular `company=` form for the batched fetch.
    expect(batchedUrl).not.toMatch(/[?&]company=/);

    promise.unsubscribe();
  });

  it('populates per-company cache for every backend-scraper company (including ones with zero rows in the batched response)', async () => {
    const store = makeStore();
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    for (let i = 0; i < 10; i++) {
      await Promise.resolve();
    }
    await new Promise((resolve) => setTimeout(resolve, 20));

    const state = store.getState();
    const queries = state[jobsApi.reducerPath].queries;
    const getAllEntry = Object.values(queries).find((q: any) =>
      q?.endpointName === 'getAllJobs'
    ) as any;
    expect(getAllEntry).toBeDefined();
    const data = getAllEntry?.data;
    expect(data).toBeDefined();
    expect(Object.keys(data.byCompanyId).sort()).toEqual(
      ['airbnb', 'discord', 'stripe'].sort()
    );
    expect(data.byCompanyId.stripe.length).toBe(1);
    expect(data.byCompanyId.airbnb.length).toBe(1);
    expect(data.byCompanyId.discord).toEqual([]);

    promise.unsubscribe();
  });
});
