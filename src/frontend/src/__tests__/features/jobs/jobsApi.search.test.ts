import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';

import { jobsApi } from '../../../features/jobs/jobsApi';
import { buildSearchJobsArgs, RECENT_SEARCH_PAGE_SIZE } from '../../../features/jobs/searchJobsArgs';
import type { SearchJobsArgs, SearchJobsPage } from '../../../features/jobs/searchJobsTypes';
import type { RecentJobsFilters } from '../../../types';
import { ERROR_MESSAGES } from '../../../constants/messages';
import { logger } from '../../../lib/logger';

/**
 * `searchJobs` is a native RTK `infiniteQuery` whose `queryFn` calls raw
 * `fetch('/api/jobs/search?…')` — no `fetchBaseQuery`, no MSW. So the seam under
 * test is the global fetch, and the assertions are (a) the exact query string
 * that goes out and (b) what comes back out of the cache entry.
 */

/** Frozen recency bound. Real callers freeze one per walk; a literal keeps the URL assertable. */
const SINCE = '2026-08-09T00:00:00.000Z';

/**
 * Realistic opaque cursors: standard base64, whose alphabet includes `+` and `/`
 * and which pads with `=` — every character the query serializer has to escape.
 * `buildSearchJobsQuery` rewrites `+` to `%20` after serializing, so a cursor
 * carrying a literal `+` is precisely the value that rewrite could corrupt. A
 * mangled cursor is a 422 from the server, not a visible frontend bug.
 */
const CURSOR_1 = 'ZnM9MjAyNi0wOC0wOVQxMjowMFomaWQ9YWJj+/8=';
const CURSOR_2 = 'ZnM9MjAyNi0wOC0wOFQwMzowMFomaWQ9ZGVm+/8=';

function makeStore() {
  return configureStore({
    reducer: { [jobsApi.reducerPath]: jobsApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(jobsApi.middleware),
  });
}

type Store = ReturnType<typeof makeStore>;

/** Let RTK's post-fulfillment bookkeeping settle before reading the store. */
async function flush() {
  for (let i = 0; i < 10; i++) await Promise.resolve();
}

interface MockResponse {
  status?: number;
  body?: unknown;
  /**
   * Raw body text, for the cases where the payload is NOT valid JSON — a proxy's
   * HTML 502 page, a WAF's plain-text 400. `queryFn` reads an error body with
   * `response.text()` (once, for both the reader's message and the log), so a
   * non-JSON error body is expressible here and nowhere else.
   */
  text?: string;
  /**
   * Make `text()` REJECT instead of resolving.
   *
   * A real `Response` resolves its headers and status as soon as they arrive and
   * streams the body afterwards, so `response.text()` can reject on its own — the
   * connection drops, the proxy resets, the body is truncated — long after
   * `fetch()` itself has settled. That is not the same failure as `fetch()`
   * rejecting (`fetchMock.mockRejectedValue`), and it is the failure mode a 500
   * under DB-pool pressure produces: a status worth reporting with no body behind
   * it. The mock resolved a string unconditionally before this, so the case could
   * not be expressed at all.
   */
  textError?: unknown;
}

type Responder = (params: URLSearchParams, url: string) => MockResponse;

/**
 * URL-param-aware fetch mock that THROWS on any URL that is not the search
 * endpoint. Fail loud: a test that silently answers a request it did not mean to
 * answer proves nothing.
 */
function makeFetchMock(respond: Responder) {
  return vi.fn((input: unknown) => {
    const url = String(input);
    if (!url.startsWith('/api/jobs/search?')) {
      throw new Error(`unexpected fetch URL in jobsApi.search test: ${url}`);
    }
    const params = new URLSearchParams(url.slice(url.indexOf('?') + 1));
    const {
      status = 200,
      body = { jobs: [], nextCursor: null },
      text,
      textError,
    } = respond(params, url);
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      statusText: 'OK',
      headers: new Headers(),
      json: async () => body,
      // A real `Response` serves both, off ONE stream. Modelling `text()` matters
      // because the error path reads the body that way — including the case where
      // reading it FAILS after the status has already arrived.
      text: async () => {
        if (textError !== undefined) throw textError;
        return text ?? JSON.stringify(body);
      },
    });
  });
}

const paramsOf = (url: unknown) => new URLSearchParams(String(url).split('?')[1]);

let fetchMock: ReturnType<typeof makeFetchMock>;
let respond: Responder;
const originalFetch = globalThis.fetch;

beforeEach(() => {
  // Default: one terminal empty page. Tests that care about the body override it.
  respond = () => ({ body: { jobs: [], nextCursor: null, meta: META } });
  fetchMock = makeFetchMock((params, url) => respond(params, url));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.resetAllMocks();
});

function makeArgs(overrides: Partial<SearchJobsArgs> = {}): SearchJobsArgs {
  return { since: SINCE, limit: RECENT_SEARCH_PAGE_SIZE, ...overrides };
}

/** A complete backend row; `overrides` lets a test corrupt exactly one field. */
function makeRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'job-1',
    title: 'Software Engineer',
    company: 'stripe',
    location: 'New York, NY, US',
    locations: [],
    url: 'https://example.com/job-1',
    sourceId: 'greenhouse',
    details: JSON.stringify({ experience_level: 'L4', is_remote_eligible: true }),
    createdAt: '2026-08-09T12:00:00.000Z',
    postedOn: '2026-08-01T12:00:00.000Z',
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt: '2026-08-09T12:00:00.000Z',
    lastSeenAt: '2026-08-10T00:00:00.000Z',
    consecutiveMisses: 0,
    detailsScraped: true,
    category: 'software_engineering',
    level: 'entry',
    tags: ['python'],
    enrichmentStatus: 'enriched',
    ...overrides,
  };
}

function withoutField(field: string, overrides: Record<string, unknown> = {}) {
  const row = makeRow(overrides);
  delete row[field];
  return row;
}

const META = { filteredTotal: 137, countLast24h: 42, countLast3h: 7 };

/** Fetch page 1 and hand back the (still subscribed) dispatch result. */
function startWalk(store: Store, args: SearchJobsArgs) {
  return store.dispatch(jobsApi.endpoints.searchJobs.initiate(args));
}

/** Fetch the request URL a given set of args produces, then tear the walk down. */
async function requestUrlFor(args: SearchJobsArgs): Promise<string> {
  const store = makeStore();
  const walk = startWalk(store, args);
  await walk;
  walk.unsubscribe();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  return String(fetchMock.mock.calls[0][0]);
}

const MULTI_FILTERS: RecentJobsFilters = {
  timeWindow: '24h',
  softwareOnly: false,
  // Every list is deliberately out of order — sorting is what keeps two
  // equivalent filter states on ONE cache entry instead of two.
  company: ['stripe', 'airbnb'],
  category: ['software_engineering', 'data_science'],
  level: ['senior', 'entry'],
  location: ['Austin, TX, US', 'Amsterdam, NL'],
  searchTags: [
    { text: 'rust', mode: 'include' },
    { text: 'golang', mode: 'include' },
    { text: 'staffing', mode: 'exclude' },
    { text: 'clearance', mode: 'exclude' },
  ],
};

function argsFromFilters(filters: RecentJobsFilters): SearchJobsArgs {
  const args = buildSearchJobsArgs({
    filters,
    enabledCompanyIds: null,
    since: SINCE,
    isSignedOut: false,
  });
  if (args === null) throw new Error('test setup: expected buildSearchJobsArgs to produce args');
  return args;
}

describe('searchJobs request shape', () => {
  it('issues exactly one GET to /api/jobs/search carrying since and limit', async () => {
    const url = await requestUrlFor(makeArgs());

    expect(url.split('?')[0]).toBe('/api/jobs/search');
    const params = paramsOf(url);
    expect(params.get('since')).toBe(SINCE);
    expect(params.get('limit')).toBe(String(RECENT_SEARCH_PAGE_SIZE));
    // Both are unconditional: `since` participates in the server's cursor
    // fingerprint and `limit` is what makes `nextCursor` meaningful.
    expect(params.getAll('since')).toHaveLength(1);
    expect(params.getAll('limit')).toHaveLength(1);
  });

  it('sends every multi-value filter as repeated params in sorted order', async () => {
    const url = await requestUrlFor(argsFromFilters(MULTI_FILTERS));
    const params = paramsOf(url);

    // Repeated, never comma-joined: locations and keywords contain commas, so a
    // joined scalar could not be split back apart on the server.
    expect(params.getAll('company')).toEqual(['airbnb', 'stripe']);
    expect(params.getAll('category')).toEqual(['data_science', 'software_engineering']);
    expect(params.getAll('level')).toEqual(['entry', 'senior']);
    expect(params.getAll('location')).toEqual(['Amsterdam, NL', 'Austin, TX, US']);
    expect(params.getAll('include')).toEqual(['golang', 'rust']);
    expect(params.getAll('exclude')).toEqual(['clearance', 'staffing']);
  });

  it('sends level slugs unexpanded so the server owns the new_grad hierarchy', async () => {
    const url = await requestUrlFor(
      argsFromFilters({ timeWindow: '24h', softwareOnly: false, level: ['entry'] })
    );

    // Expanding 'entry' -> ['entry','new_grad'] here would mean two copies of the
    // taxonomy that can drift apart. The wire value stays exactly what the user picked.
    expect(paramsOf(url).getAll('level')).toEqual(['entry']);
    expect(url).not.toContain('new_grad');
  });

  it('encodes spaces as %20 rather than +', async () => {
    const url = await requestUrlFor(
      argsFromFilters({
        timeWindow: '24h',
        softwareOnly: false,
        location: ['New York, NY, US'],
      })
    );

    // `URLSearchParams` emits `+` for a space, which is form-encoding — ambiguous
    // in a query string, and this request crosses a Vercel proxy that re-parses it.
    expect(url).toContain('location=New%20York%2C%20NY%2C%20US');
    expect(url).not.toContain('+');
  });

  it('keeps a comma-bearing canonical location as ONE param value', async () => {
    const url = await requestUrlFor(
      argsFromFilters({
        timeWindow: '24h',
        softwareOnly: false,
        location: ['New York, NY, US'],
      })
    );

    const locations = paramsOf(url).getAll('location');
    expect(locations).toHaveLength(1);
    expect(locations[0]).toBe('New York, NY, US');
  });

  it('omits empty filter lists entirely instead of sending blank params', async () => {
    const url = await requestUrlFor(
      argsFromFilters({ timeWindow: '24h', softwareOnly: false })
    );
    const params = paramsOf(url);

    // An empty `category=` is a 422 on the server, and `company=` with no value
    // would read as "no companies" rather than "all companies".
    expect([...params.keys()]).toEqual(['since', 'limit']);
    for (const name of ['company', 'category', 'level', 'location', 'include', 'exclude']) {
      expect(params.has(name)).toBe(false);
    }
  });
});

describe('searchJobs paging', () => {
  it('sends no cursor on page 1 and replays the previous nextCursor verbatim', async () => {
    respond = (params) => {
      if (params.get('cursor') === null) {
        return { body: { jobs: [makeRow({ id: 'p1' })], nextCursor: CURSOR_1, meta: META } };
      }
      return { body: { jobs: [makeRow({ id: 'p2' })], nextCursor: null } };
    };

    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    await walk;
    expect(paramsOf(fetchMock.mock.calls[0][0]).get('cursor')).toBeNull();

    await store.dispatch(jobsApi.endpoints.searchJobs.initiate(makeArgs(), { direction: 'forward' }));
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const page2Url = String(fetchMock.mock.calls[1][0]);
    const page2 = paramsOf(page2Url);
    // Byte-for-byte: the cursor is opaque, and a re-encoded one is a 422.
    expect(page2.get('cursor')).toBe(CURSOR_1);
    // The `+` in the cursor must reach the wire as %2B. The serializer's blanket
    // `+` -> `%20` sweep runs on the ALREADY-escaped string, so it can only ever
    // hit spaces — but that is exactly the kind of invariant a refactor breaks.
    expect(page2Url).toContain('cursor=ZnM9MjAyNi0wOC0wOVQxMjowMFomaWQ9YWJj%2B%2F8%3D');
    // The rest of the filter set is unchanged — a cursor is only valid under the
    // exact args that minted it.
    expect(page2.get('since')).toBe(SINCE);
    expect(page2.get('limit')).toBe(String(RECENT_SEARCH_PAGE_SIZE));

    walk.unsubscribe();
  });

  it('accumulates pages in order and drops hasNextPage once nextCursor is null', async () => {
    respond = (params) => {
      const cursor = params.get('cursor');
      if (cursor === null) {
        return {
          body: { jobs: [makeRow({ id: 'a' }), makeRow({ id: 'b' })], nextCursor: CURSOR_1, meta: META },
        };
      }
      if (cursor === CURSOR_1) {
        return { body: { jobs: [makeRow({ id: 'c' })], nextCursor: CURSOR_2 } };
      }
      return { body: { jobs: [makeRow({ id: 'd' })], nextCursor: null } };
    };

    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    const first = await walk;
    expect(first.hasNextPage).toBe(true);

    await store.dispatch(jobsApi.endpoints.searchJobs.initiate(makeArgs(), { direction: 'forward' }));
    const last = await store.dispatch(
      jobsApi.endpoints.searchJobs.initiate(makeArgs(), { direction: 'forward' })
    );
    await flush();

    const pages = last.data?.pages ?? [];
    expect(pages).toHaveLength(3);
    // Flattened, the walk reads newest-first in the order the server served it.
    expect(pages.flatMap((page: SearchJobsPage) => page.jobs.map((job) => job.id))).toEqual([
      'a',
      'b',
      'c',
      'd',
    ]);
    // `nextCursor: null` is the ONLY termination signal, and it is terminal.
    expect(last.hasNextPage).toBe(false);

    walk.unsubscribe();
  });

  it('ends the walk cleanly on a trailing empty page', async () => {
    // `nextCursor` is present iff the page came back full, so a final exactly-full
    // page costs one extra request that legitimately returns zero rows. That is
    // the end of the list, not an error and not an empty result set.
    respond = (params) =>
      params.get('cursor') === null
        ? { body: { jobs: [makeRow({ id: 'only' })], nextCursor: CURSOR_1, meta: META } }
        : { body: { jobs: [], nextCursor: null } };

    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    await walk;
    const result = await store.dispatch(
      jobsApi.endpoints.searchJobs.initiate(makeArgs(), { direction: 'forward' })
    );
    await flush();

    expect(result.error).toBeUndefined();
    expect(result.data?.pages).toHaveLength(2);
    expect(result.data?.pages[1].jobs).toEqual([]);
    expect(result.hasNextPage).toBe(false);
    // The rows already walked survive the empty tail.
    expect(result.data?.pages[0].jobs.map((job) => job.id)).toEqual(['only']);

    walk.unsubscribe();
  });
});

describe('searchJobs cache isolation', () => {
  it('gives two different filter sets separate entries and leaves the first intact', async () => {
    respond = (params) => ({
      body: {
        jobs: [makeRow({ id: `${params.getAll('category')[0] ?? 'none'}-row` })],
        nextCursor: null,
        meta: META,
      },
    });

    const store = makeStore();
    const argsA = argsFromFilters({
      timeWindow: '24h',
      softwareOnly: false,
      category: ['data_science'],
    });
    const argsB = argsFromFilters({
      timeWindow: '24h',
      softwareOnly: false,
      category: ['software_engineering'],
    });

    const walkA = startWalk(store, argsA);
    await walkA;
    const walkB = startWalk(store, argsB);
    await walkB;
    await flush();

    const queries = store.getState()[jobsApi.reducerPath].queries as unknown as Record<
      string,
      { endpointName?: string; status?: string; data?: { pages: SearchJobsPage[] } } | undefined
    >;
    const entries = Object.values(queries).filter((q) => q?.endpointName === 'searchJobs');
    expect(entries).toHaveLength(2);
    expect(entries.every((entry) => entry?.status === 'fulfilled')).toBe(true);

    // Changing a filter must not evict or overwrite the previous filter set:
    // flipping the filter back has to be instant, and no row from one entry may
    // ever leak into the other.
    const selectA = jobsApi.endpoints.searchJobs.select(argsA);
    const selectB = jobsApi.endpoints.searchJobs.select(argsB);
    const stateA = selectA(store.getState() as never);
    const stateB = selectB(store.getState() as never);
    expect(stateA.status).toBe('fulfilled');
    expect(stateA.data?.pages[0].jobs.map((job) => job.id)).toEqual(['data_science-row']);
    expect(stateB.data?.pages[0].jobs.map((job) => job.id)).toEqual(['software_engineering-row']);

    walkA.unsubscribe();
    walkB.unsubscribe();
  });
});

describe('searchJobs response validation', () => {
  /**
   * Every malformed body must land as a query ERROR, never as renderable data —
   * and the diagnostic must land in the LOG, not on the page.
   *
   * `messageFragment` is asserted against what was logged, because none of these
   * strings is written for a reader: "bad job row shape" names a wire contract
   * they cannot act on and reads as self-inflicted. `extractErrorMessage` renders
   * `error.data` verbatim in `ErrorState`, so anything put there IS the page.
   */
  async function expectValidationError(body: unknown, messageFragment: string) {
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    respond = () => ({ body });
    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    const result = await walk;

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
    expect((result.error as { status?: unknown }).status).toBe('CUSTOM_ERROR');
    expect((result.error as { data?: unknown }).data).toBe(ERROR_MESSAGES.LOAD_JOBS_FAILED);
    expect(logged).toHaveBeenCalledTimes(1);
    expect(String(logged.mock.calls[0][1])).toContain(messageFragment);

    logged.mockRestore();
    walk.unsubscribe();
  }

  it('errors when the body is not an object', async () => {
    // The old /api/jobs returned a bare array, and a proxy or CDN error page can
    // return anything at all with a 200. Reaching the transformer with this
    // used to surface as a scatter of undefineds in the UI instead of an error.
    await expectValidationError([makeRow()], 'body is not an object');
  });

  it('errors when jobs is not an array', async () => {
    await expectValidationError({ jobs: { '0': makeRow() }, nextCursor: null }, 'jobs is not an array');
  });

  it('errors when a row is missing firstSeenAt', async () => {
    // firstSeenAt is the canonical recency field — sort order, time windows, and
    // bucketing all key off it, so a row without one is not renderable.
    await expectValidationError(
      { jobs: [withoutField('firstSeenAt')], nextCursor: null },
      'bad job row shape'
    );
  });

  it('errors when a row is missing id', async () => {
    await expectValidationError({ jobs: [withoutField('id')], nextCursor: null }, 'bad job row shape');
  });

  it('errors when meta has the wrong shape', async () => {
    // A meta that parses to NaN counts would render as "NaN jobs" in the header
    // tiles rather than failing.
    await expectValidationError(
      { jobs: [makeRow()], nextCursor: null, meta: { filteredTotal: '137' } },
      'bad meta shape'
    );
  });

  it('does not put a transport failure on the page, but does log it', async () => {
    // A dropped connection throws a browser-specific TypeError ("Failed to fetch"
    // in Chrome, "NetworkError when attempting to fetch resource." in Firefox).
    // Returning it as `data` made the page's error text vary by browser and named
    // nothing the reader could do; the reason belongs in the log instead.
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    const result = await walk;

    expect((result.error as { status?: unknown }).status).toBe('CUSTOM_ERROR');
    expect((result.error as { data?: unknown }).data).toBe(ERROR_MESSAGES.LOAD_JOBS_FAILED);
    expect(logged).toHaveBeenCalledTimes(1);
    expect(String(logged.mock.calls[0][1])).toContain('Failed to fetch');

    logged.mockRestore();
    walk.unsubscribe();
  });

  it('stays silent when the request was REALLY aborted', async () => {
    // A cancelled request is not a failure, so it must not reach the log. The
    // abort is driven through RTK's own `abort()` rather than by throwing an
    // AbortError-shaped object, because `signal.aborted` — not the error's name
    // — is what the silence keys on.
    //
    // `abort()` is how the branch is reached AT ALL. In RTK Query 2.11.0 this
    // signal is aborted only by the `keepUnusedDataFor` removal timer (10
    // minutes after the last subscriber leaves) and by `resetApiState`, neither
    // of which the Recent page reaches — a filter change merely unsubscribes.
    // So this case pins the contract, not a production frequency; the branch
    // below it ("LOGS an AbortError that no abort actually caused") is the one
    // that can actually fire.
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    fetchMock.mockImplementation(
      (_input: unknown, init?: { signal?: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => {
            const abort = new Error('The operation was aborted.');
            abort.name = 'AbortError';
            reject(abort);
          });
        }) as Promise<never>
    );
    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    await flush();
    // Precondition: the request genuinely went out and is genuinely in flight,
    // so the silence below is about an abort and not about a no-op.
    expect(fetchMock).toHaveBeenCalledTimes(1);

    walk.abort();
    await walk;

    expect(logged).not.toHaveBeenCalled();

    logged.mockRestore();
    walk.unsubscribe();
  });

  it('LOGS an AbortError that no abort actually caused', async () => {
    // `error.name === 'AbortError'` is a CLAIM: any browser extension, polyfill
    // or fetch interceptor can raise one, and RTK's signal is untouched when they
    // do. That is a real failure — the reader is looking at the generic error
    // line — so silencing it on the name alone left the one class of failure with
    // no reader-facing reason AND no log. The silence keys on `signal.aborted`,
    // the fact, which is false here.
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    const impostor = new Error('The operation was aborted.');
    impostor.name = 'AbortError';
    fetchMock.mockRejectedValue(impostor);
    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    const result = await walk;

    expect((result.error as { data?: unknown }).data).toBe(ERROR_MESSAGES.LOAD_JOBS_FAILED);
    expect(logged).toHaveBeenCalledTimes(1);
    expect(String(logged.mock.calls[0][1])).toContain('The operation was aborted.');

    logged.mockRestore();
    walk.unsubscribe();
  });

  it('preserves a 404 status so the deploy-grace layer can key off it', async () => {
    // Frontend and backend deploy independently; for a few minutes the new bundle
    // calls an endpoint the old backend does not serve. useRecentJobsSearch keeps
    // retrying on exactly this status, so collapsing it to CUSTOM_ERROR would turn
    // a self-healing gap into a hard error page.
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    respond = () => ({ status: 404, body: { detail: 'Not Found' } });
    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    const result = await walk;

    expect(result.data).toBeUndefined();
    expect((result.error as { status?: unknown }).status).toBe(404);

    logged.mockRestore();
    walk.unsubscribe();
  });
});

/**
 * The non-2xx branch. Two audiences, one body read:
 *
 * - the READER gets `error.data`, gated by `READER_FACING_ERROR_STATUSES` so only
 *   a 400/422 (the client-FIXABLE rejections) shows the endpoint's own words;
 * - the LOG gets the status and the verbatim body, ungated.
 *
 * The gate decides what is fit to put on screen, not whether the failure
 * happened. Before this, a 500 from a `DB_POOL_MAX` checkout timeout, a proxy
 * 502/504 and a post-grace-window 404 all produced the generic line on screen and
 * an EMPTY console — status and body discarded on both sides of the wire.
 */
describe('searchJobs non-2xx responses', () => {
  async function expectErrorResponse(
    mock: MockResponse,
    expected: { readerSees: string; loggedStatus: number; loggedBodyFragment: string }
  ) {
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    respond = () => mock;
    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    const result = await walk;

    expect(result.data).toBeUndefined();
    expect((result.error as { status?: unknown }).status).toBe(expected.loggedStatus);
    expect((result.error as { data?: unknown }).data).toBe(expected.readerSees);
    expect(logged).toHaveBeenCalledTimes(1);
    expect(String(logged.mock.calls[0][0])).toContain(String(expected.loggedStatus));
    expect(String(logged.mock.calls[0][1])).toContain(expected.loggedBodyFragment);

    logged.mockRestore();
    walk.unsubscribe();
  }

  it('logs a 500 the reader is deliberately not shown', async () => {
    // Prod runs DB_POOL_MAX=15 / DB_POOL_TIMEOUT=5s and has logged bursts of
    // `RuntimeError: Timed out waiting for a database connection`. Those surface
    // HERE, as 500s, and this endpoint is the Recent page's primary read path.
    await expectErrorResponse(
      { status: 500, body: { detail: 'Internal Server Error' } },
      {
        readerSees: ERROR_MESSAGES.LOAD_JOBS_FAILED,
        loggedStatus: 500,
        loggedBodyFragment: 'Internal Server Error',
      }
    );
  });

  it('logs a proxy 502 whose body is not JSON at all', async () => {
    // The Vercel proxy and the CDN in front of it answer with HTML, which never
    // parsed and therefore never reached anything. `text()` keeps it.
    await expectErrorResponse(
      { status: 502, text: '<html><body>502 Bad Gateway</body></html>' },
      {
        readerSees: ERROR_MESSAGES.LOAD_JOBS_FAILED,
        loggedStatus: 502,
        loggedBodyFragment: '502 Bad Gateway',
      }
    );
  });

  it('logs a 400 even though its reason DOES reach the reader', async () => {
    // Reader-facing and loggable are independent decisions. The reason on screen
    // is what the reader acts on; the log line is what says a rejection happened
    // at all, which is the only way to notice a filter combination that starts
    // 400-ing for everyone.
    await expectErrorResponse(
      { status: 400, body: { detail: "'include' accepts at most 20 values." } },
      {
        readerSees: "'include' accepts at most 20 values.",
        loggedStatus: 400,
        loggedBodyFragment: 'at most 20 values',
      }
    );
  });

  it('logs the raw body when a 400 is not JSON', async () => {
    // The one status class whose reason is client-fixable, arriving as something
    // FastAPI did not write — so a proxy, WAF or CDN answered instead. The reader
    // gets the fallback (there is nothing actionable to show), but swallowing the
    // body in a bare `catch {}` hid the fact that the request never reached the
    // endpoint's validation at all.
    await expectErrorResponse(
      { status: 400, text: 'Bad Request (blocked by edge rule 42)' },
      {
        readerSees: ERROR_MESSAGES.LOAD_JOBS_FAILED,
        loggedStatus: 400,
        loggedBodyFragment: 'edge rule 42',
      }
    );
  });

  it('still logs the status when the body cannot be read at all', async () => {
    // The status arrives, then the body stream dies — a connection reset, a proxy
    // hanging up mid-response, a truncated chunked body. `response.text()` rejects
    // AFTER `fetch()` has already resolved, so this is not the transport-failure
    // case above: the status is known and is the single most useful fact about the
    // failure. Without the marker the log would say only "responded 500:" with
    // nothing after it, and the reader would still be looking at the generic line.
    //
    // This is the exact shape a `DB_POOL_MAX` checkout timeout takes when the
    // container is under enough pressure to drop the connection as well.
    await expectErrorResponse(
      { status: 500, textError: new TypeError('network error') },
      {
        readerSees: ERROR_MESSAGES.LOAD_JOBS_FAILED,
        loggedStatus: 500,
        loggedBodyFragment: '<body unreadable: network error>',
      }
    );
  });

  it('marks an EMPTY body rather than logging a bare trailing colon', async () => {
    // A 502 with a zero-length body is a real and common proxy behaviour. Logged
    // as `''` it renders as "responded 502:" with nothing after it — which reads
    // as a broken log line, not as a fact about the response, and sends whoever is
    // debugging looking for a bug in the logging instead of in the proxy.
    await expectErrorResponse(
      { status: 502, text: '' },
      {
        readerSees: ERROR_MESSAGES.LOAD_JOBS_FAILED,
        loggedStatus: 502,
        loggedBodyFragment: '<empty body>',
      }
    );
  });

  it('truncates a multi-megabyte error page instead of logging it verbatim', async () => {
    // A CDN or WAF block page can be megabytes (inlined CSS, a base64 logo). The
    // whole thing went to `console.error` verbatim, which floods the console and
    // any error transport reading it — for a payload whose first few lines already
    // say which layer answered. The cap keeps enough to identify it and says how
    // much was dropped, so the number is never silently wrong.
    const huge = `<html><body>Blocked by edge rule 42.${'x'.repeat(2_000_000)}</body></html>`;
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    respond = () => ({ status: 502, text: huge });
    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    await walk;

    const diagnostic = String(logged.mock.calls[0][1]);
    expect(diagnostic.length).toBeLessThan(huge.length / 100);
    // The head survives, so the log still identifies who answered...
    expect(diagnostic).toContain('Blocked by edge rule 42');
    // ...and the marker carries the real size, so "short body" is never inferred
    // from a truncated one.
    expect(diagnostic).toContain(`<truncated: ${huge.length} chars total>`);

    logged.mockRestore();
    walk.unsubscribe();
  });
});

describe('searchJobs row mapping and counts', () => {
  it('maps rows through transformBackendJob', async () => {
    respond = () => ({
      body: {
        jobs: [
          makeRow({
            id: 'job-42',
            company: 'airbnb',
            firstSeenAt: '2026-08-09T09:30:00.000Z',
            category: 'data_science',
            level: 'senior',
          }),
        ],
        nextCursor: null,
        meta: META,
      },
    });

    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    const result = await walk;

    const job = result.data?.pages[0].jobs[0];
    expect(job?.id).toBe('job-42');
    expect(job?.source).toBe('backend-scraper');
    // The company comes off the ROW, not from any client-side company list — the
    // search endpoint spans every company at once.
    expect(job?.company).toBe('airbnb');
    expect(job?.firstSeenAt).toBe('2026-08-09T09:30:00.000Z');
    expect(job?.category).toBe('data_science');
    expect(job?.level).toBe('senior');
    // ATS-derived tags (from the details blob) stay distinct from enrichment tags.
    expect(job?.tags).toEqual(['L4', 'Remote Eligible']);
    expect(job?.enrichmentTags).toEqual(['python']);
    // Display-only "posted" date falls back through postedOn, unlike firstSeenAt.
    expect(job?.createdAt).toBe('2026-08-01T12:00:00.000Z');

    walk.unsubscribe();
  });

  it('parses meta into counts on page 1 and leaves later pages without counts', async () => {
    respond = (params) =>
      params.get('cursor') === null
        ? { body: { jobs: [makeRow({ id: 'p1' })], nextCursor: CURSOR_1, meta: META } }
        : // The server sends `meta: null` on cursor pages by design: the counts
          // describe the filter set, not the page, so they are computed once.
          { body: { jobs: [makeRow({ id: 'p2' })], nextCursor: null, meta: null } };

    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    await walk;
    const result = await store.dispatch(
      jobsApi.endpoints.searchJobs.initiate(makeArgs(), { direction: 'forward' })
    );
    await flush();

    expect(result.data?.pages[0].counts).toEqual({ total: 137, last24h: 42, last3h: 7 });
    expect(result.data?.pages[1].counts).toBeUndefined();

    walk.unsubscribe();
  });

  it('logs — but does not throw — when PAGE 1 arrives without meta', async () => {
    // The endpoint sends `meta` on page 1 unconditionally, so its absence is a
    // broken contract: a serializer regression, or a proxy that rewrote the
    // envelope. Before this it was accepted in total silence and the page
    // degraded PERMANENTLY to em-dash tiles and `aria-setsize="-1"` — correct
    // degradation, zero diagnostic, and nothing on screen a reader would report.
    // The rows are still good, so throwing would blank a working page; the fact
    // belongs in the log instead.
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    respond = () => ({ body: { jobs: [makeRow({ id: 'p1' })], nextCursor: null } });
    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    const result = await walk;

    // Degraded, not failed: the rows rendered and no error reached the page.
    expect(result.error).toBeUndefined();
    expect(result.data?.pages[0].jobs).toHaveLength(1);
    expect(result.data?.pages[0].counts).toBeUndefined();

    expect(logged).toHaveBeenCalledTimes(1);
    expect(String(logged.mock.calls[0][0])).toContain('page 1 came back without');

    logged.mockRestore();
    walk.unsubscribe();
  });

  it('stays silent when a CURSOR page arrives without meta', async () => {
    // The other half of the same contract, and the reason the validator has to be
    // TOLD which page it is looking at: `meta` is absent on every cursor page by
    // design (the counts describe the filter set, not the page, so the endpoint
    // computes them once). A check that could not tell the two apart would either
    // log on every page of every walk or never log at all.
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    respond = (params) =>
      params.get('cursor') === null
        ? { body: { jobs: [makeRow({ id: 'p1' })], nextCursor: CURSOR_1, meta: META } }
        : { body: { jobs: [makeRow({ id: 'p2' })], nextCursor: null } };

    const store = makeStore();
    const walk = startWalk(store, makeArgs());
    await walk;
    await store.dispatch(
      jobsApi.endpoints.searchJobs.initiate(makeArgs(), { direction: 'forward' })
    );
    await flush();

    // Precondition: page 2 really did go out, so the silence is about the page
    // and not about a request that never happened.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(logged).not.toHaveBeenCalled();

    logged.mockRestore();
    walk.unsubscribe();
  });
});
