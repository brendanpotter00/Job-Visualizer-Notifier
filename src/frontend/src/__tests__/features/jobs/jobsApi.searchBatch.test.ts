import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';

import { jobsApi } from '../../../features/jobs/jobsApi';
import { TRIPTYCH_REQUESTS } from '../../../pages/LandingPage/sections/triptychJobs';
import { ERROR_MESSAGES } from '../../../constants/messages';
import { logger } from '../../../lib/logger';
import {
  buildRichLandingJobs,
  LANDING_NOW,
  SEARCH_META,
  simulateSearchParams,
  toBackendRow,
} from '../../pages/LandingPage/landingJobFixtures';

const HOUR = 3_600_000;
const CORPUS = buildRichLandingJobs(LANDING_NOW);

function makeStore(getTokenOrNull?: () => Promise<string | null>) {
  return configureStore({
    reducer: { [jobsApi.reducerPath]: jobsApi.reducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware(
        getTokenOrNull ? { thunk: { extraArgument: { getTokenOrNull } } } : undefined
      ).concat(jobsApi.middleware),
  });
}

interface MockReply {
  status?: number;
  body?: unknown;
  reject?: unknown;
}

type Responder = (params: URLSearchParams, call: number) => MockReply;

function makeFetchMock(respond: Responder) {
  let call = 0;
  return vi.fn((input: unknown, _init?: RequestInit) => {
    const url = String(input);
    if (!url.startsWith('/api/jobs/search?')) {
      throw new Error(`unexpected fetch URL in jobsApi.searchBatch test: ${url}`);
    }
    call += 1;
    const params = new URLSearchParams(url.slice(url.indexOf('?') + 1));
    const reply = respond(params, call);
    if (reply.reject !== undefined) return Promise.reject(reply.reject);
    const status = reply.status ?? 200;
    const body = reply.body ?? {
      jobs: simulateSearchParams(CORPUS, params).map(toBackendRow),
      nextCursor: null,
      meta: SEARCH_META,
    };
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      statusText: 'OK',
      headers: new Headers(),
      json: async () => body,
      text: async () => JSON.stringify(body),
    });
  });
}

let fetchMock: ReturnType<typeof makeFetchMock>;
let respond: Responder;
const originalFetch = globalThis.fetch;

beforeEach(() => {
  vi.spyOn(Date, 'now').mockReturnValue(LANDING_NOW);
  respond = () => ({});
  fetchMock = makeFetchMock((params, call) => respond(params, call));
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

async function runBatch(store = makeStore()) {
  const query = store.dispatch(jobsApi.endpoints.searchJobsBatch.initiate(TRIPTYCH_REQUESTS));
  const result = await query;
  return { store, query, result };
}

function sinceFor(hours: number): string {
  return new Date(LANDING_NOW - hours * HOUR).toISOString();
}

describe('searchJobsBatch', () => {
  it('issues exactly three page-1 searches with the exact query strings', async () => {
    const { query } = await runBatch();
    query.unsubscribe();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    const bigTech = [...TRIPTYCH_REQUESTS[2].companies!].map((id) => `company=${id}`).join('&');
    expect(urls).toEqual([
      `/api/jobs/search?since=${encodeURIComponent(sinceFor(1440))}&limit=5` +
        '&category=software_engineering&level=intern&level=new_grad',
      `/api/jobs/search?since=${encodeURIComponent(sinceFor(720))}&limit=10` +
        '&category=software_engineering',
      `/api/jobs/search?since=${encodeURIComponent(sinceFor(1440))}&limit=15&${bigTech}` +
        '&category=software_engineering',
    ]);
    for (const url of urls) {
      expect(new URLSearchParams(url.split('?')[1]).has('cursor')).toBe(false);
    }
  });

  it('never sends an Authorization header, even for a signed-in reader', async () => {
    const getTokenOrNull = vi.fn(async () => 'reader-token');
    const { query } = await runBatch(makeStore(getTokenOrNull));
    query.unsubscribe();

    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const [, init] of fetchMock.mock.calls) {
      expect(init?.headers).toBeUndefined();
      expect(JSON.stringify(init ?? {})).not.toContain('reader-token');
    }
    expect(getTokenOrNull).not.toHaveBeenCalled();
  });

  it('merges the three answers, dedupes by id, transforms rows and returns asOf', async () => {
    const shared = toBackendRow(CORPUS[0]);
    respond = (params) => {
      const rows = simulateSearchParams(CORPUS, params).map(toBackendRow);
      return { body: { jobs: [shared, ...rows], nextCursor: null, meta: SEARCH_META } };
    };
    const { result, query } = await runBatch();
    query.unsubscribe();

    expect(result.isSuccess).toBe(true);
    const { jobs, asOf } = result.data!;
    expect(asOf).toBe(LANDING_NOW);
    const ids = jobs.map((job) => job.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toContain(CORPUS[0].id);

    const stripeNewGrad = jobs.find((job) => job.id === CORPUS[0].id)!;
    expect(stripeNewGrad.company).toBe('stripe');
    expect(stripeNewGrad.firstSeenAt).toBe(CORPUS[0].firstSeenAt);
    expect(stripeNewGrad.url).toBe(CORPUS[0].url);
    expect(stripeNewGrad.level).toBe('new_grad');
    expect(stripeNewGrad.source).toBe('backend-scraper');
  });

  it.each([
    ['a 500 on one request', (call: number): MockReply => (call === 2 ? { status: 500 } : {})],
    [
      'a rejected fetch',
      (call: number): MockReply => (call === 3 ? { reject: new TypeError('network down') } : {}),
    ],
    ['a malformed body', (call: number): MockReply => (call === 1 ? { body: {} } : {})],
  ])('fails the whole batch on %s and logs it', async (_name, reply) => {
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    respond = (_params, call) => reply(call);
    const { result, query } = await runBatch();
    query.unsubscribe();

    expect(result.isError).toBe(true);
    expect(result.data).toBeUndefined();
    expect((result.error as { data: string }).data).toBe(ERROR_MESSAGES.LOAD_JOBS_FAILED);
    expect(logged).toHaveBeenCalled();
  });

  it('keeps the HTTP status of a failed request', async () => {
    vi.spyOn(logger, 'error').mockImplementation(() => {});
    respond = (_params, call) => (call === 2 ? { status: 503 } : {});
    const { result, query } = await runBatch();
    query.unsubscribe();

    expect(result.error).toEqual({ status: 503, data: ERROR_MESSAGES.LOAD_JOBS_FAILED });
  });

  it('does not log a genuine abort', async () => {
    const logged = vi.spyOn(logger, 'error').mockImplementation(() => {});
    let settled = 0;
    fetchMock.mockImplementation((_input: unknown, init?: RequestInit) => {
      return new Promise<never>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          settled += 1;
          reject(new DOMException('aborted', 'AbortError'));
        });
      });
    });

    const store = makeStore();
    const query = store.dispatch(jobsApi.endpoints.searchJobsBatch.initiate(TRIPTYCH_REQUESTS));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    query.abort();
    const result = await query;
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
    query.unsubscribe();

    expect(settled).toBe(3);
    expect(result.isError).toBe(true);
    expect(logged).not.toHaveBeenCalled();
  });

  it('a second subscriber with the same requests reuses the cached answer', async () => {
    const store = makeStore();
    const first = await runBatch(store);
    const second = await runBatch(store);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(second.result.data).toBe(first.result.data);
    first.query.unsubscribe();
    second.query.unsubscribe();
  });
});
