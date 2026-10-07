import { describe, it, expect, beforeEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';
import { makeCardsResponse, makeRaindropCard } from '../../pages/AdminLaunchRadarPage/fixtures';

// Node's built-in `Request` requires absolute URLs; RTK Query passes relative
// ones. Same shim as adminApi.test.ts.
const OriginalRequest = globalThis.Request;
class TestRequest extends OriginalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (typeof input === 'string' && input.startsWith('/')) {
      super(`http://localhost${input}`, init);
    } else {
      super(input, init);
    }
  }
}
globalThis.Request = TestRequest as unknown as typeof Request;

function makeStore(getTokenOrNull: () => Promise<string | null> = () => Promise.resolve('tok')) {
  return configureStore({
    reducer: { [adminApi.reducerPath]: adminApi.reducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({ thunk: { extraArgument: { getTokenOrNull } } }).concat(
        adminApi.middleware
      ),
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function requestAt(fetchMock: ReturnType<typeof vi.fn>, i: number): Request {
  return fetchMock.mock.calls[i][0] as Request;
}

describe('adminApi — Launch Radar endpoints', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  describe('getLaunchRadarCards', () => {
    it('GETs one page of one tab with limit/offset and the Bearer token', async () => {
      fetchMock.mockResolvedValue(jsonResponse(makeCardsResponse()));
      const store = makeStore();

      const result = await store.dispatch(
        adminApi.endpoints.getLaunchRadarCards.initiate({
          status: 'archived',
          page: 2,
          rowsPerPage: 25,
        })
      );

      expect(result.data?.cards).toHaveLength(2);
      const req = requestAt(fetchMock, 0);
      const url = new URL(req.url);
      expect(req.method).toBe('GET');
      expect(url.pathname).toBe('/api/admin/launch-radar/cards');
      expect(url.searchParams.get('status')).toBe('archived');
      expect(url.searchParams.get('limit')).toBe('25');
      expect(url.searchParams.get('offset')).toBe('50');
      expect(req.headers.get('Authorization')).toBe('Bearer tok');
    });

    it('sends no Authorization header when there is no token (local dev bypass)', async () => {
      fetchMock.mockResolvedValue(jsonResponse(makeCardsResponse()));
      const store = makeStore(() => Promise.resolve(null));
      await store.dispatch(
        adminApi.endpoints.getLaunchRadarCards.initiate({ status: 'new', page: 0, rowsPerPage: 25 })
      );
      expect(requestAt(fetchMock, 0).headers.has('Authorization')).toBe(false);
    });

    it.each([
      ['a non-object body', 'oops'],
      ['missing cards[]', { ...makeCardsResponse(), cards: undefined }],
      ['a non-numeric total', { ...makeCardsResponse(), total: '2' }],
      ['missing counts.archived', { ...makeCardsResponse(), counts: { new: 2 } }],
      ['missing stats.capUsd', { ...makeCardsResponse(), stats: { spendUsd: 0 } }],
      [
        'a card without a numeric id',
        { ...makeCardsResponse(), cards: [{ ...makeRaindropCard(), id: '1' }] },
      ],
      [
        'a card without a domain',
        { ...makeCardsResponse(), cards: [{ ...makeRaindropCard(), domain: null }] },
      ],
    ])('rejects %s', async (_label, body) => {
      vi.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockResolvedValue(jsonResponse(body));
      const store = makeStore();
      const result = await store.dispatch(
        adminApi.endpoints.getLaunchRadarCards.initiate({ status: 'new', page: 0, rowsPerPage: 25 })
      );
      expect(result.data).toBeUndefined();
      expect(result.error).toBeDefined();
    });
  });

  it('setLaunchRadarCardStatus PATCHes the status', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeRaindropCard({ status: 'archived' })));
    const store = makeStore();
    const result = await store.dispatch(
      adminApi.endpoints.setLaunchRadarCardStatus.initiate({ id: 7, status: 'archived' })
    );
    expect(result.data?.status).toBe('archived');
    const req = requestAt(fetchMock, 0);
    expect(req.method).toBe('PATCH');
    expect(new URL(req.url).pathname).toBe('/api/admin/launch-radar/cards/7');
    expect(await req.json()).toEqual({ status: 'archived' });
  });

  it('deleteLaunchRadarCard DELETEs and accepts a 204 with no body', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const store = makeStore();
    const result = await store.dispatch(
      adminApi.endpoints.deleteLaunchRadarCard.initiate({ id: 7 })
    );
    expect('error' in result).toBe(false);
    const req = requestAt(fetchMock, 0);
    expect(req.method).toBe('DELETE');
    expect(new URL(req.url).pathname).toBe('/api/admin/launch-radar/cards/7');
  });

  it.each([
    ['archive', 'setLaunchRadarCardStatus'],
    ['delete', 'deleteLaunchRadarCard'],
  ] as const)('a successful %s invalidates the cached card lists', async (_label, endpoint) => {
    fetchMock.mockImplementation(async (input: unknown) => {
      const req = input as Request;
      if (req.method === 'PATCH') return jsonResponse(makeRaindropCard({ status: 'archived' }));
      if (req.method === 'DELETE') return new Response(null, { status: 204 });
      return jsonResponse(makeCardsResponse());
    });
    const store = makeStore();
    const sub = store.dispatch(
      adminApi.endpoints.getLaunchRadarCards.initiate({ status: 'new', page: 0, rowsPerPage: 25 })
    );
    await sub;
    const getsBefore = fetchMock.mock.calls.filter(
      (c) => (c[0] as Request).method === 'GET'
    ).length;

    if (endpoint === 'setLaunchRadarCardStatus') {
      await store.dispatch(
        adminApi.endpoints.setLaunchRadarCardStatus.initiate({ id: 1, status: 'archived' })
      );
    } else {
      await store.dispatch(adminApi.endpoints.deleteLaunchRadarCard.initiate({ id: 1 }));
    }

    await vi.waitFor(() => {
      const gets = fetchMock.mock.calls.filter((c) => (c[0] as Request).method === 'GET').length;
      expect(gets).toBe(getsBefore + 1);
    });
    sub.unsubscribe();
  });
});
