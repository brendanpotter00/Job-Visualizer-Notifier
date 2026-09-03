import { describe, it, expect, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';

/**
 * T7 — adding or removing a board must move the Recent Jobs feed.
 *
 * The bug this pins: `addUserCompany` / `removeUserCompany` invalidate
 * `['MyCompanies']`, but the custom rows live in `jobsApi`'s `getAllJobs` cache,
 * which is a different API slice and carries a different tag. So removing a
 * board left its jobs in the feed for the rest of the session — jobs from a
 * company the user had just told us to stop tracking.
 */
vi.mock('../../../config/companies', () => {
  const COMPANIES = ['pub1', 'pub2'].map((id) => ({
    id,
    name: id.toUpperCase(),
    ats: 'backend-scraper' as const,
    config: { type: 'backend-scraper', companyId: id },
  }));
  return { COMPANIES, getCompanyById: (id: string) => COMPANIES.find((c) => c.id === id) };
});

vi.mock('../../../config/customCompanies', () => ({
  CUSTOM_COMPANIES_CONFIG: { isEnabled: true, isDiscoveryProgressEnabled: false },
}));

import { jobsApi } from '../../../features/jobs/jobsApi';
import { userCompaniesApi } from '../../../features/userCompanies/userCompaniesApi';

// Node's `Request` (undici) requires absolute URLs; `fetchBaseQuery` builds
// relative ones. Same shim the other API-slice tests use.
const OriginalRequest = globalThis.Request;
class TestRequest extends OriginalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(
      typeof input === 'string' && input.startsWith('/') ? `http://localhost${input}` : input,
      init
    );
  }
}
globalThis.Request = TestRequest as unknown as typeof Request;

const CUSTOM_ID = 'u-abc123';
const CUSTOM_JOBS_PATH = '/api/users/companies/jobs';

function row(company: string, id: string, sourceId: string): Record<string, unknown> {
  const seen = '2026-08-20T00:00:00.000Z';
  return {
    id,
    title: `${company} role`,
    company,
    location: 'Remote',
    locations: [],
    url: `https://example.com/${id}`,
    sourceId,
    details: '{}',
    createdAt: seen,
    postedOn: seen,
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt: seen,
    lastSeenAt: seen,
    consecutiveMisses: 0,
    detailsScraped: true,
  };
}

function makeStore() {
  return configureStore({
    reducer: {
      [jobsApi.reducerPath]: jobsApi.reducer,
      [userCompaniesApi.reducerPath]: userCompaniesApi.reducer,
    },
    middleware: (gdm) =>
      gdm({ thunk: { extraArgument: { getTokenOrNull: async () => 'tok' } } })
        .concat(jobsApi.middleware)
        .concat(userCompaniesApi.middleware),
  });
}

function getFeed(store: ReturnType<typeof makeStore>): Record<string, unknown[]> | undefined {
  const queries = store.getState()[jobsApi.reducerPath].queries;
  const entry = Object.values(queries).find((q) => q?.endpointName === 'getAllJobs');
  return (entry as { data?: { byCompanyId: Record<string, unknown[]> } } | undefined)?.data
    ?.byCompanyId;
}

async function flush() {
  for (let i = 0; i < 20; i++) await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 30));
}

/**
 * Wait until the feed's streaming walk has finished. An invalidation restarts
 * `getAllJobs` from its skeleton, so "the cache changed" is not the same thing
 * as "the refreshed feed has landed".
 */
async function settled(store: ReturnType<typeof makeStore>) {
  for (let i = 0; i < 100; i++) {
    await flush();
    const queries = store.getState()[jobsApi.reducerPath].queries;
    const entry = Object.values(queries).find((q) => q?.endpointName === 'getAllJobs');
    const data = (entry as { data?: { isStreaming: boolean } } | undefined)?.data;
    if (data && data.isStreaming === false) return;
  }
  throw new Error('getAllJobs never finished streaming');
}

afterEach(() => {
  vi.resetAllMocks();
});

/** The board's rows come back until `tracked` is flipped off — as they would server-side. */
function installFetch(tracked: { value: boolean }) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const href = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const path = href.replace('http://localhost', '').split('?')[0];
    if (path === CUSTOM_JOBS_PATH) {
      const rows = tracked.value ? [row(CUSTOM_ID, 'cus-1', `custom:${CUSTOM_ID}`)] : [];
      return new Response(JSON.stringify(rows), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    if (path === '/api/jobs') {
      return new Response(JSON.stringify([row('pub1', 'pub-1', 'greenhouse')]), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }
    // DELETE / POST on users/companies
    return new Response(null, { status: 204 });
  });
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

describe('T7 — the Recent feed follows add / remove', () => {
  it('drops a removed board’s jobs instead of keeping them for the session', async () => {
    const tracked = { value: true };
    installFetch(tracked);
    const store = makeStore();

    const feed = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await feed;
    await settled(store);
    expect(Object.keys(getFeed(store) ?? {})).toContain(CUSTOM_ID);

    // The server no longer owns the board for this user.
    tracked.value = false;
    await store.dispatch(userCompaniesApi.endpoints.removeUserCompany.initiate(CUSTOM_ID));
    await settled(store);

    expect(getFeed(store)?.[CUSTOM_ID] ?? []).toEqual([]);
    // The public half is still there — the refresh is a re-walk, not a wipe.
    expect(Object.keys(getFeed(store) ?? {})).toContain('pub1');

    feed.unsubscribe();
  });

  it('picks up a newly added board’s jobs without a reload', async () => {
    const tracked = { value: false };
    installFetch(tracked);
    const store = makeStore();

    const feed = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await feed;
    await settled(store);
    expect(Object.keys(getFeed(store) ?? {})).not.toContain(CUSTOM_ID);

    tracked.value = true;
    await store.dispatch(
      userCompaniesApi.endpoints.addUserCompany.initiate({ url: 'https://acme.example/careers' })
    );
    await settled(store);

    expect(getFeed(store)?.[CUSTOM_ID]).toHaveLength(1);

    feed.unsubscribe();
  });

  it('leaves the feed alone when the mutation FAILS', async () => {
    const tracked = { value: true };
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const href =
        typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const path = href.replace('http://localhost', '').split('?')[0];
      if (path === CUSTOM_JOBS_PATH) {
        return new Response(
          JSON.stringify(tracked.value ? [row(CUSTOM_ID, 'cus-1', `custom:${CUSTOM_ID}`)] : []),
          { status: 200, headers: { 'content-type': 'application/json' } }
        );
      }
      if (path === '/api/jobs') {
        return new Response(JSON.stringify([row('pub1', 'pub-1', 'greenhouse')]), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
      return new Response(JSON.stringify({ detail: 'nope' }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      });
    }) as unknown as typeof fetch;
    const store = makeStore();

    const feed = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await feed;
    await settled(store);
    const before = getFeed(store);

    // A 404 delete changed nothing server-side; throwing away a good feed for it
    // would be pure loss.
    tracked.value = false;
    await store.dispatch(userCompaniesApi.endpoints.removeUserCompany.initiate(CUSTOM_ID));
    await flush();
    await flush();

    expect(getFeed(store)).toBe(before);

    feed.unsubscribe();
  });
});
