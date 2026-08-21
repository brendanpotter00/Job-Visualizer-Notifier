import { describe, it, expect, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';

// Two public backend-scraper companies -> one chunk, so the assertions below
// are about the PUBLIC-vs-PRIVATE split rather than about chunking (which
// `jobsApi.keyset.test.ts` already covers).
vi.mock('../../../config/companies', () => {
  const COMPANIES = ['pub1', 'pub2'].map((id) => ({
    id,
    name: id.toUpperCase(),
    ats: 'backend-scraper' as const,
    config: { type: 'backend-scraper', companyId: id },
  }));
  return {
    COMPANIES,
    getCompanyById: (id: string) => COMPANIES.find((c) => c.id === id),
  };
});

// The whole feature is behind `VITE_CUSTOM_COMPANIES_ENABLED`, and the flag is
// read once at module load — a getter keeps it flippable per test.
const { flagState } = vi.hoisted(() => ({ flagState: { isEnabled: true } }));
vi.mock('../../../config/customCompanies', () => ({
  CUSTOM_COMPANIES_CONFIG: {
    get isEnabled() {
      return flagState.isEnabled;
    },
    isDiscoveryProgressEnabled: false,
  },
}));

import { jobsApi } from '../../../features/jobs/jobsApi';
import { selectCompleteHorizon, selectHasMoreJobs } from '../../../features/jobs/jobsSelectors';
import { CUSTOM_JOBS_CHUNK_KEY } from '../../../features/jobs/keysetWalk';
import { selectAllJobsFromQuery } from '../../../features/filters/selectors/recentJobsSelectors';
import recentJobsFiltersReducer from '../../../features/filters/slices/recentJobsFiltersSlice';
import appReducer from '../../../features/app/appSlice';
import graphFiltersReducer from '../../../features/filters/slices/graphFiltersSlice';
import uiReducer from '../../../features/ui/uiSlice';
import enabledCompaniesReducer from '../../../features/preferences/enabledCompaniesSlice';
import type { RootState } from '../../../app/store';

const PUBLIC_CHUNK_KEY = 'pub1,pub2';
const CUSTOM_JOBS_PATH = '/api/users/companies/jobs';

function makeRow(
  company: string,
  id: string,
  firstSeenAt: string,
  sourceId = 'greenhouse'
): Record<string, unknown> {
  return {
    id,
    title: `${company} role`,
    company,
    location: 'Remote',
    locations: [],
    url: `https://example.com/${id}`,
    sourceId,
    details: '{}',
    createdAt: firstSeenAt,
    postedOn: firstSeenAt,
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt,
    lastSeenAt: firstSeenAt,
    consecutiveMisses: 0,
    detailsScraped: true,
  };
}

const customRow = (companyId: string, id: string, firstSeenAt: string) =>
  makeRow(companyId, id, firstSeenAt, `custom:${companyId}`);

interface Reply {
  rows: unknown[];
  nextCursor?: string;
  status?: number;
  /** Hold the response back, so a test can observe the cache between halves. */
  delayMs?: number;
}

/**
 * One fetch mock covering BOTH halves of the feed, routed on path so a test can
 * assert that the private request happened (or, for the signed-out case, that
 * it did not).
 */
function makeFetchMock(respond: (path: string, params: URLSearchParams) => Reply) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const [path, query = ''] = String(url).split('?');
    const reply = respond(path, new URLSearchParams(query));
    if (reply.delayMs) await new Promise((resolve) => setTimeout(resolve, reply.delayMs));
    const status = reply.status ?? 200;
    return {
      ok: status < 400,
      status,
      statusText: status < 400 ? 'OK' : 'Server Error',
      headers: new Headers(reply.nextCursor ? { 'X-Next-Cursor': reply.nextCursor } : {}),
      json: async () => reply.rows,
      // Echoed back so a test can assert on the Authorization header.
      _init: init,
    };
  });
}

/**
 * A store shaped like the real one: the Recent selectors need the filter slices,
 * and `extraArgument.getTokenOrNull` is what decides whether the private half of
 * the feed is fetched at all. `getToken` returning `null` IS the signed-out
 * case — that is exactly how `getTokenOrNull` behaves for an anonymous visitor.
 */
function makeStore(getTokenOrNull: () => Promise<string | null>) {
  return configureStore({
    reducer: {
      app: appReducer,
      graphFilters: graphFiltersReducer,
      recentJobsFilters: recentJobsFiltersReducer,
      ui: uiReducer,
      enabledCompanies: enabledCompaniesReducer,
      [jobsApi.reducerPath]: jobsApi.reducer,
    },
    middleware: (gdm) =>
      gdm({ thunk: { extraArgument: { getTokenOrNull } } }).concat(jobsApi.middleware),
  });
}

/** onCacheEntryAdded is async; give the microtask queue and one macrotask time. */
async function flush() {
  for (let i = 0; i < 10; i++) await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 20));
}

interface AllJobsEntry {
  byCompanyId: Record<string, { id: string; company: string; firstSeenAt: string }[]>;
  metadata: Record<string, { totalCount: number }>;
  progress: { total: number; companies: { companyId: string }[] };
  cursors: Record<string, string>;
  chunkFloors: Record<string, string>;
  since: string;
  isStreaming: boolean;
}

function getAllJobsData(store: {
  getState: () => Record<string, unknown>;
}): AllJobsEntry | undefined {
  const queries = (store.getState()[jobsApi.reducerPath] as { queries: Record<string, unknown> })
    .queries;
  const entry = Object.values(queries).find(
    (q) => (q as { endpointName?: string })?.endpointName === 'getAllJobs'
  );
  return (entry as { data?: AllJobsEntry } | undefined)?.data;
}

function getAllJobsError(store: { getState: () => Record<string, unknown> }): unknown {
  const queries = (store.getState()[jobsApi.reducerPath] as { queries: Record<string, unknown> })
    .queries;
  const entry = Object.values(queries).find(
    (q) => (q as { endpointName?: string })?.endpointName === 'getAllJobs'
  );
  return (entry as { error?: unknown } | undefined)?.error;
}

const pathsHit = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.map(([u]) => String(u).split('?')[0]);

afterEach(() => {
  vi.resetAllMocks();
  flagState.isEnabled = true;
});

describe('signed out', () => {
  it('never issues the custom-jobs request, and leaves the feed byte-identical', async () => {
    const getToken = vi.fn(async () => null);
    const fetchMock = makeFetchMock(() => ({
      rows: [makeRow('pub1', 'pub1-a', '2026-08-10T00:00:00.000Z')],
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore(getToken);
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    // The whole anonymous requirement in one assertion: the private endpoint is
    // never touched. Not "touched and 401'd" — never touched.
    expect(pathsHit(fetchMock)).not.toContain(CUSTOM_JOBS_PATH);
    expect(pathsHit(fetchMock)).toEqual(['/api/jobs']);

    const data = getAllJobsData(store);
    expect(Object.keys(data?.byCompanyId ?? {})).toEqual(['pub1', 'pub2']);
    expect(data?.cursors[CUSTOM_JOBS_CHUNK_KEY]).toBeUndefined();
    expect(data?.chunkFloors[CUSTOM_JOBS_CHUNK_KEY]).toBeUndefined();

    promise.unsubscribe();
  });

  it('leaves the cache entry and the Recent array untouched BY IDENTITY', async () => {
    // Any private request is held back past the capture below, so this test
    // catches a merge that happens at all — not just one that happens early.
    const fetchMock = makeFetchMock((path) =>
      path === CUSTOM_JOBS_PATH
        ? { rows: [makeRow('u-abc', 'cus-1', '2026-08-05T00:00:00.000Z')], delayMs: 60 }
        : { rows: [makeRow('pub1', 'pub1-a', '2026-08-10T00:00:00.000Z')] }
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore(async () => null);
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    const entry = getAllJobsData(store);
    const jobs = selectAllJobsFromQuery(store.getState() as unknown as RootState);

    // Long enough for a held-back private response to land, if one was ever
    // asked for.
    await new Promise((resolve) => setTimeout(resolve, 80));
    await flush();

    // Strict identity, not deep equality. `selectAllJobsFromQuery` is the single
    // upstream source for the whole Recent page, so a merge step that rebuilt
    // its array with nothing to add would re-render the entire page — for a
    // feature this visitor is not even using.
    expect(getAllJobsData(store)).toBe(entry);
    expect(selectAllJobsFromQuery(store.getState() as unknown as RootState)).toBe(jobs);
    expect(jobs.map((j) => j.id)).toEqual(['pub1-a']);

    promise.unsubscribe();
  });
});

describe('signed in', () => {
  it('makes no private request at all with the custom-companies flag off', async () => {
    flagState.isEnabled = false;
    const fetchMock = makeFetchMock(() => ({
      rows: [makeRow('pub1', 'pub-a', '2026-08-10T00:00:00.000Z')],
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore(async () => 'tok');
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    // Flag-off contract: the app is byte-for-byte what shipped before this
    // feature — no nav entry, no route, and no network calls. It also covers the
    // half-off deployment, where the backend flag is off and this endpoint 503s.
    expect(pathsHit(fetchMock)).toEqual(['/api/jobs']);
    expect(getAllJobsData(store)?.cursors[CUSTOM_JOBS_CHUNK_KEY]).toBeUndefined();

    promise.unsubscribe();
  });

  it('merges custom jobs into the same feed, interleaved by first_seen_at', async () => {
    const fetchMock = makeFetchMock((path) =>
      path === CUSTOM_JOBS_PATH
        ? { rows: [customRow('u-abc', 'cus-mid', '2026-08-05T00:00:00.000Z')] }
        : {
            rows: [
              makeRow('pub1', 'pub-new', '2026-08-10T00:00:00.000Z'),
              makeRow('pub2', 'pub-old', '2026-08-01T00:00:00.000Z'),
            ],
          }
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore(async () => 'tok');
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    const data = getAllJobsData(store);
    // The custom company gets its own `byCompanyId` entry, keyed by the runtime
    // `u-<id>` the rest of the custom-company UI uses.
    expect(data?.byCompanyId['u-abc']?.map((j) => j.id)).toEqual(['cus-mid']);
    expect(data?.byCompanyId['u-abc']?.[0].company).toBe('u-abc');

    // Ordering is the point: the custom row lands BETWEEN the two public rows
    // by date, not appended after them.
    const sorted = [...selectAllJobsFromQuery(store.getState() as unknown as RootState)].sort(
      (a, b) => new Date(b.firstSeenAt).getTime() - new Date(a.firstSeenAt).getTime()
    );
    expect(sorted.map((j) => j.id)).toEqual(['pub-new', 'cus-mid', 'pub-old']);

    promise.unsubscribe();
  });

  it('merges custom rows without disturbing the public arrays BY IDENTITY', async () => {
    // The private half lands strictly after the public one, so the public
    // arrays can be captured in between.
    const fetchMock = makeFetchMock((path) =>
      path === CUSTOM_JOBS_PATH
        ? { rows: [customRow('u-abc', 'cus-1', '2026-08-05T00:00:00.000Z')], delayMs: 60 }
        : { rows: [makeRow('pub1', 'pub-a', '2026-08-10T00:00:00.000Z')] }
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore(async () => 'tok');
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    const pub1Before = getAllJobsData(store)?.byCompanyId['pub1'];
    const pub2Before = getAllJobsData(store)?.byCompanyId['pub2'];
    expect(pub1Before?.map((j) => j.id)).toEqual(['pub-a']);

    await new Promise((resolve) => setTimeout(resolve, 80));
    await flush();

    // The custom rows arrived...
    expect(getAllJobsData(store)?.byCompanyId['u-abc']?.map((j) => j.id)).toEqual(['cus-1']);
    // ...and every public company's array kept its identity. Rebuilding them
    // (e.g. by looping the whole roster in the custom merge) would invalidate
    // every downstream memo and re-render the page for rows that did not move.
    expect(getAllJobsData(store)?.byCompanyId['pub1']).toBe(pub1Before);
    expect(getAllJobsData(store)?.byCompanyId['pub2']).toBe(pub2Before);

    promise.unsubscribe();
  });

  it('sends the bearer token and the walk contract on the private request', async () => {
    const fetchMock = makeFetchMock(() => ({ rows: [] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore(async () => 'tok-abc');
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    const call = fetchMock.mock.calls.find(([u]) => String(u).startsWith(CUSTOM_JOBS_PATH));
    expect(call).toBeDefined();
    const params = new URLSearchParams(String(call?.[0]).split('?')[1]);
    // Same `since` the public chunk was bounded by — one walk, one window.
    const entrySince = getAllJobsData(store)?.since;
    expect(entrySince).toMatch(/Z$/);
    expect(params.get('since')).toBe(entrySince);
    const publicCall = fetchMock.mock.calls.find(([u]) => String(u).startsWith('/api/jobs'));
    expect(new URLSearchParams(String(publicCall?.[0]).split('?')[1]).get('since')).toBe(
      entrySince
    );
    expect(params.get('status')).toBe('OPEN');
    expect((call?.[1] as RequestInit).headers).toMatchObject({
      Authorization: 'Bearer tok-abc',
    });

    promise.unsubscribe();
  });

  it('books the custom cursor and floor under the reserved key so the horizon accounts for it', async () => {
    const fetchMock = makeFetchMock((path) =>
      path === CUSTOM_JOBS_PATH
        ? {
            rows: [
              customRow('u-abc', 'cus-1', '2026-08-09T00:00:00.000Z'),
              customRow('u-abc', 'cus-2', '2026-08-08T00:00:00.000Z'),
            ],
            nextCursor: 'CUS-1',
          }
        : {
            rows: [makeRow('pub1', 'pub-a', '2026-08-02T00:00:00.000Z')],
            nextCursor: 'PUB-1',
          }
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore(async () => 'tok');
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    const data = getAllJobsData(store);
    expect(data?.cursors[CUSTOM_JOBS_CHUNK_KEY]).toBe('CUS-1');
    expect(data?.chunkFloors[CUSTOM_JOBS_CHUNK_KEY]).toBe('2026-08-08T00:00:00.000Z');

    // The horizon is the max over ACTIVE chunks' floors. The custom walk stopped
    // shallower (08-08) than the public one (08-02), so it is what bounds the
    // provably-complete prefix — without booking it the feed would render public
    // rows below 08-08 with no custom rows beside them and look complete.
    expect(selectCompleteHorizon(store.getState() as unknown as RootState)).toBe(
      '2026-08-08T00:00:00.000Z'
    );
    expect(selectHasMoreJobs(store.getState() as unknown as RootState)).toBe(true);

    promise.unsubscribe();
  });

  it('renders the public feed unchanged when the custom request fails', async () => {
    const fetchMock = makeFetchMock((path) =>
      path === CUSTOM_JOBS_PATH
        ? { rows: [], status: 500 }
        : { rows: [makeRow('pub1', 'pub-a', '2026-08-10T00:00:00.000Z')], nextCursor: 'PUB-1' }
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore(async () => 'tok');
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    // A private-companies failure must never blank the main feed, and must never
    // reach the page's error banner (which is driven by the query's own error).
    expect(getAllJobsError(store)).toBeUndefined();
    const data = getAllJobsData(store);
    // The load must still be able to FINISH. If the failure escaped the
    // per-half isolation it would abort `onCacheEntryAdded` before this flips,
    // stranding the progress bar and blocking the window-widening restart
    // (`selectJobsFirstPageSettled` gates it on exactly this flag).
    expect(data?.isStreaming).toBe(false);
    expect(data?.byCompanyId['pub1']?.map((j) => j.id)).toEqual(['pub-a']);
    expect(data?.cursors[PUBLIC_CHUNK_KEY]).toBe('PUB-1');
    // No half-applied walk state from the failed half.
    expect(data?.cursors[CUSTOM_JOBS_CHUNK_KEY]).toBeUndefined();
    expect(data?.chunkFloors[CUSTOM_JOBS_CHUNK_KEY]).toBeUndefined();
    expect(
      selectAllJobsFromQuery(store.getState() as unknown as RootState).map((j) => j.id)
    ).toEqual(['pub-a']);

    promise.unsubscribe();
  });
});

describe('fetchNextJobsPage', () => {
  /** Page 1 with both halves still holding a cursor. */
  async function seedFirstPage() {
    const fetchMock = makeFetchMock((path) =>
      path === CUSTOM_JOBS_PATH
        ? { rows: [customRow('u-abc', 'cus-p1', '2026-08-09T00:00:00.000Z')], nextCursor: 'CUS-1' }
        : { rows: [makeRow('pub1', 'pub-p1', '2026-08-10T00:00:00.000Z')], nextCursor: 'PUB-1' }
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore(async () => 'tok');
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();
    return { store, promise };
  }

  it('advances both halves, replaying each cursor on its own endpoint', async () => {
    const { store, promise } = await seedFirstPage();

    const fetchMock = makeFetchMock((path) =>
      path === CUSTOM_JOBS_PATH
        ? {
            rows: [
              // A repeat of page 1's row (a concurrent re-harvest can re-serve
              // one) plus a genuinely new one — the repeat must not duplicate.
              customRow('u-abc', 'cus-p1', '2026-08-09T00:00:00.000Z'),
              customRow('u-abc', 'cus-p2', '2026-08-03T00:00:00.000Z'),
            ],
          }
        : { rows: [makeRow('pub1', 'pub-p2', '2026-08-04T00:00:00.000Z')] }
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const result = await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate());
    await flush();

    const publicCall = fetchMock.mock.calls.find(([u]) => String(u).startsWith('/api/jobs'));
    const customCall = fetchMock.mock.calls.find(([u]) => String(u).startsWith(CUSTOM_JOBS_PATH));
    expect(new URLSearchParams(String(publicCall?.[0]).split('?')[1]).get('cursor')).toBe('PUB-1');
    expect(new URLSearchParams(String(customCall?.[0]).split('?')[1]).get('cursor')).toBe('CUS-1');

    const data = getAllJobsData(store);
    expect(data?.byCompanyId['u-abc']?.map((j) => j.id)).toEqual(['cus-p1', 'cus-p2']);
    // Both halves came back short -> both cursors dropped -> the walk is over.
    expect(data?.cursors[CUSTOM_JOBS_CHUNK_KEY]).toBeUndefined();
    expect(selectHasMoreJobs(store.getState() as unknown as RootState)).toBe(false);
    // `added` counts the private rows too: 1 public + 1 new custom.
    expect('data' in result ? result.data : undefined).toEqual({ added: 2, hasMore: false });

    promise.unsubscribe();
  });

  it('never asks /api/jobs for a company named after the reserved custom key', async () => {
    const { store, promise } = await seedFirstPage();

    const fetchMock = makeFetchMock(() => ({ rows: [] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate());
    await flush();

    // The reserved key is not a comma-joined list of company ids. Feeding it
    // back through `parseChunkKey` would request `companies=custom:jobs`.
    const publicCompanies = fetchMock.mock.calls
      .filter(([u]) => String(u).startsWith('/api/jobs'))
      .map(([u]) => new URLSearchParams(String(u).split('?')[1]).get('companies'));
    expect(publicCompanies).toEqual([PUBLIC_CHUNK_KEY]);

    promise.unsubscribe();
  });

  it('keeps paging the private half after the public walk is exhausted', async () => {
    // Public comes back short on page 1; only the custom walk holds a cursor.
    const seedMock = makeFetchMock((path) =>
      path === CUSTOM_JOBS_PATH
        ? { rows: [customRow('u-abc', 'cus-p1', '2026-08-09T00:00:00.000Z')], nextCursor: 'CUS-1' }
        : { rows: [makeRow('pub1', 'pub-p1', '2026-08-10T00:00:00.000Z')] }
    );
    globalThis.fetch = seedMock as unknown as typeof fetch;
    const store = makeStore(async () => 'tok');
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();
    expect(selectHasMoreJobs(store.getState() as unknown as RootState)).toBe(true);

    const fetchMock = makeFetchMock(() => ({
      rows: [customRow('u-abc', 'cus-p2', '2026-08-03T00:00:00.000Z')],
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate());
    await flush();

    // Only the private endpoint is called — no public chunk holds a cursor.
    expect(pathsHit(fetchMock)).toEqual([CUSTOM_JOBS_PATH]);
    expect(getAllJobsData(store)?.byCompanyId['u-abc']?.map((j) => j.id)).toEqual([
      'cus-p1',
      'cus-p2',
    ]);

    promise.unsubscribe();
  });

  it('does not fail the page when only the private half errors', async () => {
    const { store, promise } = await seedFirstPage();

    const fetchMock = makeFetchMock((path) =>
      path === CUSTOM_JOBS_PATH
        ? { rows: [], status: 500 }
        : { rows: [makeRow('pub1', 'pub-p2', '2026-08-04T00:00:00.000Z')], nextCursor: 'PUB-2' }
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const result = await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate());
    await flush();

    // A rejection here would latch `useRecentJobsPaging`'s error and stop the
    // PUBLIC walk — a private-companies outage must not do that.
    expect('error' in result ? result.error : undefined).toBeUndefined();
    expect('data' in result ? result.data : undefined).toEqual({ added: 1, hasMore: true });
    const data = getAllJobsData(store);
    expect(data?.byCompanyId['pub1']?.map((j) => j.id)).toEqual(['pub-p1', 'pub-p2']);
    // The cursor survives a failure so a transient one heals on the next page.
    expect(data?.cursors[CUSTOM_JOBS_CHUNK_KEY]).toBe('CUS-1');

    promise.unsubscribe();
  });

  it('restarts the private walk from page 1 when the window widens', async () => {
    const { store, promise } = await seedFirstPage();

    const fetchMock = makeFetchMock(() => ({ rows: [] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate({ window: 'all' }));
    await flush();

    const customCall = fetchMock.mock.calls.find(([u]) => String(u).startsWith(CUSTOM_JOBS_PATH));
    const params = new URLSearchParams(String(customCall?.[0]).split('?')[1]);
    // A cursor is only meaningful under the filter set that minted it, so the
    // widened walk starts clean under the new bound.
    expect(params.get('cursor')).toBeNull();
    expect(params.get('since')).toBe(new Date(0).toISOString());

    promise.unsubscribe();
  });

  it('does not touch the private endpoint when signed out', async () => {
    const seedMock = makeFetchMock(() => ({
      rows: [makeRow('pub1', 'pub-p1', '2026-08-10T00:00:00.000Z')],
      nextCursor: 'PUB-1',
    }));
    globalThis.fetch = seedMock as unknown as typeof fetch;
    const store = makeStore(async () => null);
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    const fetchMock = makeFetchMock(() => ({ rows: [] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate({ window: 'all' }));
    await flush();

    // Even a widen — which restarts every walk from page 1 — must not reach the
    // authed endpoint for an anonymous visitor.
    expect(pathsHit(fetchMock)).not.toContain(CUSTOM_JOBS_PATH);

    promise.unsubscribe();
  });
});
