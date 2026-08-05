import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';

// 55 backend-scraper companies -> chunkCompanyIds splits them 50 + 5, so the
// batched load spans TWO independent requests and therefore two independent
// cursors. That multi-chunk shape is the whole point of the design under test.
// (vi.mock factories are hoisted above every top-level binding, so the roster
// is generated independently inside the factory rather than shared.)
vi.mock('../../../config/companies', () => {
  const COMPANIES = Array.from({ length: 55 }, (_, i) => `co${i}`).map((id) => ({
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

import { jobsApi, RECENT_JOBS_PAGE_SIZE } from '../../../features/jobs/jobsApi';
import { selectHasMoreJobs } from '../../../features/jobs/jobsSelectors';
import { sinceForWindow } from '../../../features/jobs/keysetWalk';
import type { RootState } from '../../../app/store';

const COMPANY_IDS = Array.from({ length: 55 }, (_, i) => `co${i}`);
const CHUNK_A = COMPANY_IDS.slice(0, 50);
const CHUNK_B = COMPANY_IDS.slice(50);
const CHUNK_A_KEY = CHUNK_A.join(',');
const CHUNK_B_KEY = CHUNK_B.join(',');

const DAY_MS = 24 * 60 * 60 * 1000;

function makeBackendRow(company: string, id: string, firstSeenAt = '2026-05-01T00:00:00.000Z') {
  return {
    id,
    title: `${company} role`,
    company,
    location: 'Remote',
    locations: [],
    url: `https://example.com/${id}`,
    sourceId: 'greenhouse',
    details: JSON.stringify({ experience_level: 'L4', is_remote_eligible: true }),
    createdAt: firstSeenAt,
    postedOn: firstSeenAt,
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt,
    lastSeenAt: '2026-05-17T00:00:00.000Z',
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

/** onCacheEntryAdded is async; give the microtask queue and one macrotask time. */
async function flush() {
  for (let i = 0; i < 10; i++) await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 20));
}

interface AllJobsEntry {
  byCompanyId: Record<string, { id: string; firstSeenAt: string }[]>;
  metadata: Record<string, { totalCount: number }>;
  progress: { companies: { companyId: string; status: string; jobCount?: number }[] };
  cursors: Record<string, string>;
  chunkFloors: Record<string, string>;
  windowKey: string;
  since: string;
}

function getAllJobsData(store: ReturnType<typeof makeStore>): AllJobsEntry | undefined {
  const queries = store.getState()[jobsApi.reducerPath].queries;
  const entry = Object.values(queries).find((q) => q?.endpointName === 'getAllJobs');
  return (entry as { data?: AllJobsEntry } | undefined)?.data;
}

function perCompanyEntries(store: ReturnType<typeof makeStore>) {
  const queries = store.getState()[jobsApi.reducerPath].queries;
  return Object.values(queries).filter((q) => q?.endpointName === 'getJobsForCompany');
}

/** Build a fetch mock keyed on the `companies=` param of each request URL. */
function makeFetchMock(
  respond: (params: URLSearchParams) => { rows: unknown[]; nextCursor?: string }
) {
  return vi.fn((url: string) => {
    if (!url.startsWith('/api/jobs')) {
      throw new Error(`unexpected fetch URL in jobsApi.keyset test: ${url}`);
    }
    const params = new URLSearchParams(url.slice(url.indexOf('?') + 1));
    const { rows, nextCursor } = respond(params);
    return Promise.resolve({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers(nextCursor ? { 'X-Next-Cursor': nextCursor } : {}),
      json: async () => rows,
    });
  });
}

const paramsOf = (url: unknown) => new URLSearchParams(String(url).split('?')[1]);

describe('getAllJobs default load is bounded by a 90-day window', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = makeFetchMock(() => ({ rows: [] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('sends `since` ~90 days ago on every chunk and never sends limit=50000', async () => {
    const before = Date.now();
    const store = makeStore();
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    const urls = fetchMock.mock.calls.map(([u]) => String(u));
    // 55 companies -> 2 chunks -> 2 requests.
    expect(urls).toHaveLength(2);

    for (const url of urls) {
      const params = paramsOf(url);

      const since = params.get('since');
      expect(since).toBeTruthy();
      // ISO-8601 with a UTC offset — a naive value is a backend 422.
      expect(since).toMatch(/Z$/);
      const expected = before - 90 * DAY_MS;
      expect(Math.abs(new Date(since as string).getTime() - expected)).toBeLessThan(60_000);

      // The 50k row cap is gone; the page size is the bound now.
      expect(params.get('limit')).toBe(String(RECENT_JOBS_PAGE_SIZE));
      expect(params.get('limit')).not.toBe('50000');
      // offset is a 422 in keyset mode.
      expect(params.get('offset')).toBeNull();
      expect(params.get('status')).toBe('OPEN');
      // Page 1 carries no cursor.
      expect(params.get('cursor')).toBeNull();
    }

    const data = getAllJobsData(store);
    expect(data?.windowKey).toBe('90d');
    expect(data?.since).toBe(paramsOf(urls[0]).get('since'));

    promise.unsubscribe();
  });

  it('does NOT seed per-company caches from a bounded page', async () => {
    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      return { rows: cos.slice(0, 2).map((id) => makeBackendRow(id, `${id}-1`)) };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore();
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    // A page-1 slice is NOT a company's full result set. Parking it in
    // getJobsForCompany (fresh for keepUnusedDataFor = 10 min) would serve the
    // /companies click-through truncated data. It refetches instead.
    expect(perCompanyEntries(store)).toHaveLength(0);

    // The aggregate entry still covers every company, including zero-row ones.
    const data = getAllJobsData(store);
    expect(Object.keys(data?.byCompanyId ?? {})).toHaveLength(COMPANY_IDS.length);

    promise.unsubscribe();
  });

  it('flips every backend-scraper company together and reports loaded-so-far counts', async () => {
    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      return { rows: [makeBackendRow(cos[0], `${cos[0]}-1`)] };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore();
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    const companies = getAllJobsData(store)?.progress.companies ?? [];
    expect(companies).toHaveLength(COMPANY_IDS.length);
    expect(companies.every((c) => c.status === 'success')).toBe(true);
    // jobCount is "rows loaded so far", sourced from the aggregate cache — not
    // a completeness claim, and not from a per-company seed.
    expect(companies.find((c) => c.companyId === CHUNK_A[0])?.jobCount).toBe(1);
    expect(companies.find((c) => c.companyId === CHUNK_A[1])?.jobCount).toBe(0);

    promise.unsubscribe();
  });

  it('records a per-chunk floor from the oldest row of each page', async () => {
    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      const isChunkA = cos.length === 50;
      const floor = isChunkA ? '2026-07-30T00:00:00.000Z' : '2026-07-21T00:00:00.000Z';
      return {
        rows: [
          makeBackendRow(cos[0], `${cos[0]}-new`, '2026-08-02T00:00:00.000Z'),
          makeBackendRow(cos[0], `${cos[0]}-old`, floor),
        ],
        nextCursor: 'CUR',
      };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore();
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    const data = getAllJobsData(store);
    expect(data?.chunkFloors[CHUNK_A_KEY]).toBe('2026-07-30T00:00:00.000Z');
    expect(data?.chunkFloors[CHUNK_B_KEY]).toBe('2026-07-21T00:00:00.000Z');

    promise.unsubscribe();
  });
});

describe('fetchNextJobsPage', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  afterEach(() => {
    vi.resetAllMocks();
  });

  /**
   * First load: chunk A comes back full (cursor CUR-A1), chunk B comes back
   * short (no cursor, i.e. already exhausted).
   */
  async function seedFirstPage() {
    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      const isChunkA = cos.length === 50;
      return {
        rows: [makeBackendRow(cos[0], `${cos[0]}-p1`, '2026-08-02T00:00:00.000Z')],
        nextCursor: isChunkA ? 'CUR-A1' : undefined,
      };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore();
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();
    return { store, promise };
  }

  it('records one cursor per FULL chunk and reports hasMore while any is outstanding', async () => {
    const { store, promise } = await seedFirstPage();

    const data = getAllJobsData(store);
    expect(Object.keys(data?.cursors ?? {})).toEqual([CHUNK_A_KEY]);
    expect(data?.cursors[CHUNK_A_KEY]).toBe('CUR-A1');
    expect(data?.cursors[CHUNK_B_KEY]).toBeUndefined();
    expect(selectHasMoreJobs(store.getState() as unknown as RootState)).toBe(true);

    promise.unsubscribe();
  });

  it('APPENDS the next page: new ids added, existing ids retained', async () => {
    const { store, promise } = await seedFirstPage();
    expect(getAllJobsData(store)?.byCompanyId[CHUNK_A[0]].map((j) => j.id)).toEqual([
      `${CHUNK_A[0]}-p1`,
    ]);

    // Page 2 for chunk A only: a brand-new row plus a repeat of page 1's row
    // (a concurrent re-scrape can re-serve a row) — the repeat must not duplicate.
    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      return {
        rows: [
          makeBackendRow(cos[0], `${cos[0]}-p1`, '2026-08-02T00:00:00.000Z'),
          makeBackendRow(cos[0], `${cos[0]}-p2`, '2026-07-25T00:00:00.000Z'),
        ],
        nextCursor: 'CUR-A2',
      };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const result = await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate());
    await flush();

    // Only the chunk still holding a cursor was advanced.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const params = paramsOf(fetchMock.mock.calls[0][0]);
    expect(params.get('cursor')).toBe('CUR-A1');
    expect(params.get('companies')).toBe(CHUNK_A_KEY);

    const data = getAllJobsData(store);
    expect(data?.byCompanyId[CHUNK_A[0]].map((j) => j.id)).toEqual([
      `${CHUNK_A[0]}-p1`,
      `${CHUNK_A[0]}-p2`,
    ]);
    expect(data?.metadata[CHUNK_A[0]].totalCount).toBe(2);
    // Chunk B's rows are untouched — never replaced.
    expect(data?.byCompanyId[CHUNK_B[0]].map((j) => j.id)).toEqual([`${CHUNK_B[0]}-p1`]);
    // Cursor advanced and the floor deepened.
    expect(data?.cursors[CHUNK_A_KEY]).toBe('CUR-A2');
    expect(data?.chunkFloors[CHUNK_A_KEY]).toBe('2026-07-25T00:00:00.000Z');
    expect('data' in result ? result.data : undefined).toEqual({ added: 1, hasMore: true });

    promise.unsubscribe();
  });

  it('clears an exhausted cursor and reports hasMore=false once all are done', async () => {
    const { store, promise } = await seedFirstPage();

    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      return { rows: [makeBackendRow(cos[0], `${cos[0]}-p2`, '2026-07-25T00:00:00.000Z')] };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const result = await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate());
    await flush();

    expect(getAllJobsData(store)?.cursors).toEqual({});
    expect(selectHasMoreJobs(store.getState() as unknown as RootState)).toBe(false);
    expect('data' in result ? result.data : undefined).toEqual({ added: 1, hasMore: false });

    promise.unsubscribe();
  });

  it('is a no-op that issues no request when the walk is already exhausted', async () => {
    const { store, promise } = await seedFirstPage();

    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      return { rows: [makeBackendRow(cos[0], `${cos[0]}-p2`)] };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate());
    await flush();

    fetchMock.mockClear();
    const result = await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate());
    await flush();

    expect(fetchMock).not.toHaveBeenCalled();
    expect('data' in result ? result.data : undefined).toEqual({ added: 0, hasMore: false });

    promise.unsubscribe();
  });

  it('still does not seed per-company caches when appending a page', async () => {
    const { store, promise } = await seedFirstPage();

    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      return { rows: [makeBackendRow(cos[0], `${cos[0]}-p2`)] };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate());
    await flush();

    expect(perCompanyEntries(store)).toHaveLength(0);

    promise.unsubscribe();
  });

  it('hands PLAIN arrays across the mutation boundary (no revoked Immer proxies)', async () => {
    const { store, promise } = await seedFirstPage();

    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      return { rows: [makeBackendRow(cos[0], `${cos[0]}-p2`, '2026-07-25T00:00:00.000Z')] };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate());
    await flush();

    // The merge builds `[...existing, ...appended]` from DRAFT elements inside
    // an Immer recipe. If any of those escaped un-finalized, every read below
    // would throw "Cannot perform 'get' on a proxy that has been revoked".
    const data = getAllJobsData(store);
    const merged = data?.byCompanyId[CHUNK_A[0]];
    expect(Array.isArray(merged)).toBe(true);
    expect(() => JSON.stringify(merged)).not.toThrow();
    expect(merged?.map((j) => j.id)).toEqual([`${CHUNK_A[0]}-p1`, `${CHUNK_A[0]}-p2`]);
    // Deep read of every field on every row of the whole entry.
    expect(() => JSON.stringify(data)).not.toThrow();

    promise.unsubscribe();
  });
});

describe('fetchNextJobsPage window widening', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  afterEach(() => {
    vi.resetAllMocks();
  });

  async function seedFirstPage() {
    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      return {
        rows: [makeBackendRow(cos[0], `${cos[0]}-p1`, '2026-08-02T00:00:00.000Z')],
        nextCursor: cos.length === 50 ? 'CUR-A1' : undefined,
      };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore();
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();
    return { store, promise };
  }

  it('does NOT restart when handed the window it is already on', async () => {
    const { store, promise } = await seedFirstPage();
    const cursorBefore = getAllJobsData(store)?.cursors[CHUNK_A_KEY];

    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      return { rows: [makeBackendRow(cos[0], `${cos[0]}-p2`)], nextCursor: 'CUR-A2' };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    // This is the F5-loop guard: 1.4's scroll trigger passes the SAME logical
    // window every tick. Comparing raw ISO `since` would see a new timestamp
    // each call and restart the walk forever.
    await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate({ window: '90d' }));
    await flush();

    // Resumed (one cursored chunk), not restarted (which would hit both chunks).
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(paramsOf(fetchMock.mock.calls[0][0]).get('cursor')).toBe(cursorBefore);
    expect(getAllJobsData(store)?.windowKey).toBe('90d');

    promise.unsubscribe();
  });

  it('restarts every chunk from page 1 under a genuinely wider window', async () => {
    const { store, promise } = await seedFirstPage();
    const since90 = getAllJobsData(store)?.since;

    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      return { rows: [makeBackendRow(cos[0], `${cos[0]}-wide`, '2026-03-01T00:00:00.000Z')] };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate({ window: '180d' }));
    await flush();

    // A cursor is only meaningful under the window that minted it, so CUR-A1
    // must NOT be replayed.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [url] of fetchMock.mock.calls) {
      const params = paramsOf(url);
      expect(params.get('cursor')).toBeNull();
      expect(params.get('since')).not.toBe(since90);
    }

    const data = getAllJobsData(store);
    expect(data?.windowKey).toBe('180d');
    expect(new Date(data!.since).getTime()).toBeLessThan(new Date(since90!).getTime());
    // Widened rows APPEND on top of what was already walked.
    expect(data?.byCompanyId[CHUNK_A[0]].map((j) => j.id)).toEqual([
      `${CHUNK_A[0]}-p1`,
      `${CHUNK_A[0]}-wide`,
    ]);
    // Stale floors from the 90d walk were cleared, not carried over.
    expect(data?.chunkFloors[CHUNK_A_KEY]).toBe('2026-03-01T00:00:00.000Z');

    promise.unsubscribe();
  });

  it("maps 'all' to the epoch so the walk stays in keyset mode", async () => {
    const { store, promise } = await seedFirstPage();

    fetchMock = makeFetchMock((params) => {
      const cos = (params.get('companies') ?? '').split(',');
      return { rows: [makeBackendRow(cos[0], `${cos[0]}-all`)] };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await store.dispatch(jobsApi.endpoints.fetchNextJobsPage.initiate({ window: 'all' }));
    await flush();

    for (const [url] of fetchMock.mock.calls) {
      expect(paramsOf(url).get('since')).toBe(sinceForWindow('all'));
    }
    expect(getAllJobsData(store)?.windowKey).toBe('all');

    promise.unsubscribe();
  });

  it('converges when a widen lands WHILE the initial page-1 load is still in flight', async () => {
    // Page 1 hangs until we release it; the widen runs in the gap.
    let releasePageOne: (() => void) | undefined;
    const pageOneGate = new Promise<void>((resolve) => {
      releasePageOne = resolve;
    });
    let gateArmed = true;

    fetchMock = vi.fn(async (url: string) => {
      const params = paramsOf(url);
      const cos = (params.get('companies') ?? '').split(',');
      const isPageOne = gateArmed && params.get('cursor') === null;
      if (isPageOne) await pageOneGate;
      // Classify by depth, not by an exact ISO match: `since` is minted from
      // `Date.now()` inside the data layer, so it never equals a value the test
      // recomputes a few ms later.
      const widened = Date.parse(params.get('since') ?? '') < Date.now() - 120 * DAY_MS;
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: new Headers(
          isPageOne && !widened ? { 'X-Next-Cursor': 'STALE-90D-CURSOR' } : {}
        ),
        json: async () => [
          makeBackendRow(
            cos[0],
            widened ? `${cos[0]}-wide` : `${cos[0]}-p1`,
            widened ? '2026-03-01T00:00:00.000Z' : '2026-08-02T00:00:00.000Z'
          ),
        ],
      };
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const store = makeStore();
    const promise = store.dispatch(jobsApi.endpoints.getAllJobs.initiate());
    await promise;
    await flush();

    // Page 1 is airborne and blocked. Widen now.
    gateArmed = false;
    const widenPromise = store.dispatch(
      jobsApi.endpoints.fetchNextJobsPage.initiate({ window: '180d' })
    );
    await flush();
    releasePageOne?.();
    await widenPromise;
    await flush();

    const data = getAllJobsData(store);
    // The entry is consistently on 180d...
    expect(data?.windowKey).toBe('180d');
    expect(Math.abs(Date.parse(data!.since) - (Date.now() - 180 * DAY_MS))).toBeLessThan(60_000);
    // ...and the superseded 90d page-1 payload did NOT write its cursor, which
    // would have paged the wrong window from then on.
    expect(Object.values(data?.cursors ?? {})).not.toContain('STALE-90D-CURSOR');
    // ...nor a stale floor claiming a horizon the new window has not reached.
    expect(data?.chunkFloors[CHUNK_A_KEY]).not.toBe('2026-08-02T00:00:00.000Z');
    // The widened rows survived — nothing stomped them.
    expect(data?.byCompanyId[CHUNK_A[0]].map((j) => j.id)).toContain(`${CHUNK_A[0]}-wide`);
    // And the entry is still readable end to end (no revoked proxies).
    expect(() => JSON.stringify(data)).not.toThrow();

    promise.unsubscribe();
  });
});
