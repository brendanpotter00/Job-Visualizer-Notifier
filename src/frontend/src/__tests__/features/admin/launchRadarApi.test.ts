import { describe, it, expect, beforeEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';
import {
  makeAthennianCard,
  makeCardsResponse,
  makeRaindropCard,
} from '../../pages/AdminLaunchRadarPage/fixtures';

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
          sort: 'announced',
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
      expect(url.searchParams.get('sort')).toBe('announced');
      expect(req.headers.get('Authorization')).toBe('Bearer tok');
    });

    it.each(['announced', 'talent', 'vc', 'added'] as const)(
      'sends sort=%s, and each sort is its own cache entry',
      async (sort) => {
        fetchMock.mockImplementation(async () => jsonResponse(makeCardsResponse()));
        const store = makeStore();
        const args = { status: 'new', page: 0, rowsPerPage: 25 } as const;
        await store.dispatch(
          adminApi.endpoints.getLaunchRadarCards.initiate({ ...args, sort: 'announced' })
        );
        await store.dispatch(adminApi.endpoints.getLaunchRadarCards.initiate({ ...args, sort }));
        const sorts = fetchMock.mock.calls.map((c) =>
          new URL((c[0] as Request).url).searchParams.get('sort')
        );
        // The same args are served from the cache; a different sort is a new request.
        expect(sorts).toEqual(sort === 'announced' ? ['announced'] : ['announced', sort]);
      }
    );

    it('sends no Authorization header when there is no token (local dev bypass)', async () => {
      fetchMock.mockResolvedValue(jsonResponse(makeCardsResponse()));
      const store = makeStore(() => Promise.resolve(null));
      await store.dispatch(
        adminApi.endpoints.getLaunchRadarCards.initiate({
          status: 'new',
          page: 0,
          rowsPerPage: 25,
          sort: 'announced',
        })
      );
      expect(requestAt(fetchMock, 0).headers.has('Authorization')).toBe(false);
    });

    it.each([
      ['a non-object body', 'oops'],
      ['missing cards[]', { ...makeCardsResponse(), cards: undefined }],
      ['a non-numeric total', { ...makeCardsResponse(), total: '2' }],
      ['missing counts.archived', { ...makeCardsResponse(), counts: { new: 2, saved: 0 } }],
      // Strict: the backend always sends every tab's count.
      ['missing counts.saved', { ...makeCardsResponse(), counts: { new: 2, archived: 1 } }],
      [
        'a non-numeric counts.saved',
        { ...makeCardsResponse(), counts: { new: 2, saved: '1', archived: 1 } },
      ],
      [
        'a null counts.saved',
        { ...makeCardsResponse(), counts: { new: 2, saved: null, archived: 1 } },
      ],
      [
        'a card without a numeric id',
        { ...makeCardsResponse(), cards: [{ ...makeRaindropCard(), id: '1' }] },
      ],
      [
        'a card without a domain',
        { ...makeCardsResponse(), cards: [{ ...makeRaindropCard(), domain: null }] },
      ],
      [
        'a card with a status this build does not know',
        { ...makeCardsResponse(), cards: [{ ...makeRaindropCard(), status: 'starred' }] },
      ],
      [
        'a deleted card (tombstones never reach the client)',
        { ...makeCardsResponse(), cards: [{ ...makeRaindropCard(), status: 'deleted' }] },
      ],
      [
        'a card without a status',
        { ...makeCardsResponse(), cards: [{ ...makeRaindropCard(), status: undefined }] },
      ],
      [
        'a card without scores',
        { ...makeCardsResponse(), cards: [{ ...makeRaindropCard(), scores: null }] },
      ],
      [
        'a card with a Talent basis this build does not know',
        {
          ...makeCardsResponse(),
          cards: [
            {
              ...makeRaindropCard(),
              scores: { ...makeRaindropCard().scores, talentBasis: 'founders' },
            },
          ],
        },
      ],
    ])('rejects %s', async (_label, body) => {
      vi.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockResolvedValue(jsonResponse(body));
      const store = makeStore();
      const result = await store.dispatch(
        adminApi.endpoints.getLaunchRadarCards.initiate({
          status: 'new',
          page: 0,
          rowsPerPage: 25,
          sort: 'announced',
        })
      );
      expect(result.data).toBeUndefined();
      expect(result.error).toBeDefined();
    });
  });

  it.each([
    ['legacy (null basis)', { talentLeaders: null, talentTeam: null, talentBasis: null }],
    ['a backend that predates the blend (no basis key)', {}],
  ])('accepts a card whose Talent has no breakdown: %s', async (_label, blend) => {
    const { talent, vc, talentReasons, vcReasons } = makeRaindropCard().scores;
    const card = {
      ...makeRaindropCard(),
      scores: { talent, vc, talentReasons, vcReasons, ...blend },
    };
    fetchMock.mockResolvedValue(jsonResponse({ ...makeCardsResponse(), cards: [card] }));
    const store = makeStore();
    const result = await store.dispatch(
      adminApi.endpoints.getLaunchRadarCards.initiate({
        status: 'new',
        page: 0,
        rowsPerPage: 25,
        sort: 'announced',
      })
    );
    expect(result.error).toBeUndefined();
    expect(result.data?.cards[0].scores.talent).toBe(49);
  });

  it('reads every tab count, saved included', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeCardsResponse()));
    const store = makeStore();
    const result = await store.dispatch(
      adminApi.endpoints.getLaunchRadarCards.initiate({
        status: 'saved',
        page: 0,
        rowsPerPage: 25,
        sort: 'announced',
      })
    );
    expect(result.data?.counts).toEqual({ new: 2, saved: 1, archived: 1 });
    expect(new URL(requestAt(fetchMock, 0).url).searchParams.get('status')).toBe('saved');
  });

  it.each([
    ['saved', 'new'],
    ['new', 'saved'],
    ['archived', 'new'],
    ['archived', 'saved'],
    ['new', 'archived'],
  ] as const)('setLaunchRadarCardStatus PATCHes status=%s from=%s', async (status, from) => {
    fetchMock.mockResolvedValue(jsonResponse(makeRaindropCard({ status })));
    const store = makeStore();
    const result = await store.dispatch(
      adminApi.endpoints.setLaunchRadarCardStatus.initiate({ id: 9, status, from })
    );
    expect(result.data?.status).toBe(status);
    const req = requestAt(fetchMock, 0);
    expect(req.method).toBe('PATCH');
    expect(new URL(req.url).pathname).toBe('/api/admin/launch-radar/cards/9');
    // `from` makes the move a compare-and-swap on the backend (409 if the card moved).
    expect(await req.json()).toEqual({ status, from });
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
    ['save', 'saved', 'new'],
    ['unsave', 'new', 'saved'],
    ['archive', 'archived', 'new'],
    ['restore', 'new', 'archived'],
    ['delete', null, null],
  ] as const)('a successful %s invalidates the cached card lists', async (_label, status, from) => {
    fetchMock.mockImplementation(async (input: unknown) => {
      const req = input as Request;
      if (req.method === 'PATCH')
        return jsonResponse(makeRaindropCard({ status: status ?? 'new' }));
      if (req.method === 'DELETE') return new Response(null, { status: 204 });
      return jsonResponse(makeCardsResponse());
    });
    const store = makeStore();
    const sub = store.dispatch(
      adminApi.endpoints.getLaunchRadarCards.initiate({
        status: 'new',
        page: 0,
        rowsPerPage: 25,
        sort: 'announced',
      })
    );
    await sub;
    const getsBefore = fetchMock.mock.calls.filter(
      (c) => (c[0] as Request).method === 'GET'
    ).length;

    if (status === null || from === null) {
      await store.dispatch(adminApi.endpoints.deleteLaunchRadarCard.initiate({ id: 1 }));
    } else {
      await store.dispatch(
        adminApi.endpoints.setLaunchRadarCardStatus.initiate({ id: 1, status, from })
      );
    }

    await vi.waitFor(() => {
      const gets = fetchMock.mock.calls.filter((c) => (c[0] as Request).method === 'GET').length;
      expect(gets).toBe(getsBefore + 1);
    });
    sub.unsubscribe();
  });

  describe('a successful move drops the card from the cached lists at once', () => {
    /**
     * The refetch the invalidation starts is held open, so what is asserted is
     * the cache between the PATCH/DELETE succeeding and the refetch landing:
     * the window in which the old tab's buttons used to stay clickable.
     */
    function holdRefetches(
      mutation: (req: Request) => Response,
      firstList: unknown = makeCardsResponse()
    ) {
      let gets = 0;
      fetchMock.mockImplementation(async (input: unknown) => {
        const req = input as Request;
        if (req.method !== 'GET') return mutation(req);
        gets += 1;
        return gets === 1 ? jsonResponse(firstList) : new Promise<Response>(() => {});
      });
    }

    const NEW_ARGS = { status: 'new', page: 0, rowsPerPage: 25, sort: 'announced' } as const;

    function cached(store: ReturnType<typeof makeStore>) {
      return adminApi.endpoints.getLaunchRadarCards.select(NEW_ARGS)(store.getState()).data;
    }

    it.each([
      ['saved', { new: 1, saved: 2, archived: 1 }],
      ['archived', { new: 1, saved: 1, archived: 2 }],
    ] as const)('PATCH status=%s', async (status, counts) => {
      holdRefetches(() => jsonResponse(makeRaindropCard({ status })));
      const store = makeStore();
      const sub = store.dispatch(adminApi.endpoints.getLaunchRadarCards.initiate(NEW_ARGS));
      await sub;
      expect(cached(store)?.cards.map((c) => c.id)).toEqual([2, 1]);

      await store.dispatch(
        adminApi.endpoints.setLaunchRadarCardStatus.initiate({ id: 1, status, from: 'new' })
      );

      await vi.waitFor(() => expect(cached(store)?.cards.map((c) => c.id)).toEqual([2]));
      expect(cached(store)?.total).toBe(1);
      expect(cached(store)?.counts).toEqual(counts);
      sub.unsubscribe();
    });

    it('DELETE: the card leaves and only its old tab count drops', async () => {
      holdRefetches(
        () => new Response(null, { status: 204 }),
        makeCardsResponse({ cards: [makeAthennianCard()], total: 1 })
      );
      const store = makeStore();
      const args = { ...NEW_ARGS, status: 'archived' } as const;
      const sub = store.dispatch(adminApi.endpoints.getLaunchRadarCards.initiate(args));
      await sub;

      await store.dispatch(adminApi.endpoints.deleteLaunchRadarCard.initiate({ id: 3 }));

      const read = () => adminApi.endpoints.getLaunchRadarCards.select(args)(store.getState()).data;
      await vi.waitFor(() => expect(read()?.cards).toEqual([]));
      expect(read()?.total).toBe(0);
      expect(read()?.counts).toEqual({ new: 2, saved: 1, archived: 0 });
      sub.unsubscribe();
    });

    it('a refused move leaves every cached list as it was', async () => {
      holdRefetches(() => jsonResponse({ detail: 'card is archived' }, 409));
      const store = makeStore();
      const sub = store.dispatch(adminApi.endpoints.getLaunchRadarCards.initiate(NEW_ARGS));
      await sub;
      const before = cached(store);

      const result = await store.dispatch(
        adminApi.endpoints.setLaunchRadarCardStatus.initiate({
          id: 1,
          status: 'saved',
          from: 'new',
        })
      );

      expect('error' in result).toBe(true);
      expect(cached(store)).toBe(before);
      sub.unsubscribe();
    });
  });
});
