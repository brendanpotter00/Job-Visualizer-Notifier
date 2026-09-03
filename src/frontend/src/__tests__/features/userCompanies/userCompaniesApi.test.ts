import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import {
  addsRemaining,
  isDiscoveryPending,
  isMonthlyLimitError,
  userCompaniesApi,
  type UserCompany,
} from '../../../features/userCompanies/userCompaniesApi';
import type { BackendJobListing } from '../../../api/types';

// Node's built-in `Request` (undici) requires absolute URLs, but
// `fetchBaseQuery` builds relative ones from `baseUrl: '/api'`. Resolve them
// against a test origin so the constructor succeeds. Mirrors featuresApi.test.ts.
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

type TestExtra = { getTokenOrNull: () => Promise<string | null> };

function makeStore(getTokenOrNull: () => Promise<string | null>) {
  return configureStore({
    reducer: { [userCompaniesApi.reducerPath]: userCompaniesApi.reducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: { extraArgument: { getTokenOrNull } as TestExtra },
      }).concat(userCompaniesApi.middleware),
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

/** 204 must be constructed with a null body — a string body throws. */
function noContentResponse(): Response {
  return new Response(null, { status: 204 });
}

function urlFromInput(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  if (input instanceof Request) return input.url;
  return String(input);
}

function getHeader(
  input: RequestInfo | URL,
  init: RequestInit | undefined,
  name: string
): string | null {
  if (input instanceof Request) return input.headers.get(name);
  if (!init?.headers) return null;
  const headers = init.headers;
  if (headers instanceof Headers) return headers.get(name);
  if (Array.isArray(headers)) {
    const hit = headers.find(([k]) => k.toLowerCase() === name.toLowerCase());
    return hit ? hit[1] : null;
  }
  const rec = headers as Record<string, string>;
  const key = Object.keys(rec).find((k) => k.toLowerCase() === name.toLowerCase());
  return key ? rec[key] : null;
}

function getMethod(input: RequestInfo | URL, init: RequestInit | undefined): string | undefined {
  if (input instanceof Request) return input.method;
  return init?.method;
}

async function getBody(
  input: RequestInfo | URL,
  init: RequestInit | undefined
): Promise<string | null> {
  if (input instanceof Request) return input.text();
  if (typeof init?.body === 'string') return init.body;
  return null;
}

describe('userCompaniesApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const SAMPLE_COMPANY: UserCompany = {
    id: 'u-abc1234567',
    displayName: 'duolingo',
    ats: 'greenhouse',
    boardToken: 'duolingo',
    sourceId: 'custom:u-abc1234567',
    healthState: 'unverified',
    openJobCount: 0,
    lastSuccessAt: null,
    trackingStartedAt: null,
  };

  describe('getUserCompanies', () => {
    it('GETs /api/users/companies and keeps the whole envelope', async () => {
      const quota = { used: 3, limit: 20, resetsAt: '2026-09-01T00:00:00Z' };
      fetchMock.mockResolvedValue(jsonResponse({ companies: [SAMPLE_COMPANY], quota }));
      const store = makeStore(async () => 'tok');

      const result = await store
        .dispatch(userCompaniesApi.endpoints.getUserCompanies.initiate())
        .unwrap();

      const [input, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
      expect(urlFromInput(input)).toMatch(/\/api\/users\/companies$/);
      expect(getMethod(input, init) ?? 'GET').toBe('GET');
      // NOT unwrapped to a bare array any more: `quota` lives beside `companies` on
      // the wire, and unwrapping would silently drop the whole counter.
      expect(result).toEqual({ companies: [SAMPLE_COMPANY], quota });
    });

    it('sends the bearer token', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ companies: [] }));
      const store = makeStore(async () => 'tok-xyz');

      await store.dispatch(userCompaniesApi.endpoints.getUserCompanies.initiate()).unwrap();

      const [input, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
      expect(getHeader(input, init, 'Authorization')).toBe('Bearer tok-xyz');
    });
  });

  describe('addUserCompany', () => {
    it('POSTs the final URL to /api/users/companies and returns the company', async () => {
      fetchMock.mockResolvedValue(jsonResponse(SAMPLE_COMPANY, 201));
      const store = makeStore(async () => 'tok');

      const result = await store
        .dispatch(
          userCompaniesApi.endpoints.addUserCompany.initiate({
            url: 'https://boards.greenhouse.io/duolingo',
          })
        )
        .unwrap();

      const [input, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
      expect(urlFromInput(input)).toMatch(/\/api\/users\/companies$/);
      expect(getMethod(input, init)).toBe('POST');
      expect(JSON.parse((await getBody(input, init)) ?? '{}')).toEqual({
        url: 'https://boards.greenhouse.io/duolingo',
      });
      expect(result).toEqual(SAMPLE_COMPANY);
    });

    it('sets Authorization: Bearer <token> when a token exists', async () => {
      fetchMock.mockResolvedValue(jsonResponse(SAMPLE_COMPANY, 201));
      const store = makeStore(async () => 'tok-abc');

      await store
        .dispatch(userCompaniesApi.endpoints.addUserCompany.initiate({ url: 'https://x' }))
        .unwrap();

      const [input, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
      expect(getHeader(input, init, 'Authorization')).toBe('Bearer tok-abc');
    });

    it('omits the Authorization header when the token getter returns null', async () => {
      fetchMock.mockResolvedValue(jsonResponse(SAMPLE_COMPANY, 201));
      const store = makeStore(async () => null);

      await store
        .dispatch(userCompaniesApi.endpoints.addUserCompany.initiate({ url: 'https://x' }))
        .unwrap();

      const [input, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
      expect(getHeader(input, init, 'Authorization')).toBeNull();
    });

    it('issues a fresh request per submit (mutations are not cached)', async () => {
      // A new Response per call: a single instance would have its body consumed by
      // the first read and throw on the second. Re-submitting the same URL must
      // actually re-run the add rather than replay a cached answer — this is the
      // ONLY call the page makes now, so a cached second press would silently do
      // nothing where it used to re-probe the board.
      fetchMock.mockImplementation(async () => jsonResponse(SAMPLE_COMPANY, 201));
      const store = makeStore(async () => 'tok');

      const args = { url: 'https://boards.greenhouse.io/duolingo' };
      await store.dispatch(userCompaniesApi.endpoints.addUserCompany.initiate(args)).unwrap();
      await store.dispatch(userCompaniesApi.endpoints.addUserCompany.initiate(args)).unwrap();

      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it('surfaces a 503 (server feature flag off) to the caller', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({ detail: 'Custom company sources are not enabled' }, 503)
      );
      const store = makeStore(async () => 'tok');

      const result = await store.dispatch(
        userCompaniesApi.endpoints.addUserCompany.initiate({ url: 'https://example.com' })
      );

      const error = (result as { error: { status: number; data: { detail: string } } }).error;
      expect(error.status).toBe(503);
      expect(error.data.detail).toBe('Custom company sources are not enabled');
    });

    it('surfaces the 422 { reason, detail, finalUrl } body to the caller', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse(
          { reason: 'empty', detail: 'That board has no open jobs.', finalUrl: 'https://x/careers' },
          422
        )
      );
      const store = makeStore(async () => 'tok');

      const result = await store.dispatch(
        userCompaniesApi.endpoints.addUserCompany.initiate({ url: 'https://x/careers' })
      );

      const error = (result as { error: { status: number; data: { reason: string } } }).error;
      expect(error.status).toBe(422);
      expect(error.data.reason).toBe('empty');
    });

    it('still discriminates the 202 discovery body now that it carries an id', async () => {
      // The 202 gained `id` / `sourceId` so the UI can point at the row it just
      // created — and `UserCompany` also has an `id`. `isDiscoveryPending` narrows on
      // `status`, which only the 202 has, so the two bodies stay tellable apart.
      fetchMock.mockResolvedValue(
        jsonResponse(
          {
            status: 'discovery_pending',
            detail: 'One-time setup — …',
            finalUrl: 'https://careers.acme.example/jobs',
            id: 'u-discover01',
            sourceId: 'custom:u-discover01',
          },
          202
        )
      );
      const store = makeStore(async () => 'tok');

      const result = await store
        .dispatch(
          userCompaniesApi.endpoints.addUserCompany.initiate({
            url: 'https://careers.acme.example/jobs',
          })
        )
        .unwrap();

      expect(isDiscoveryPending(result)).toBe(true);
      expect(isDiscoveryPending(SAMPLE_COMPANY)).toBe(false);
      if (isDiscoveryPending(result)) {
        expect(result.id).toBe('u-discover01');
      }
    });
  });

  describe('removeUserCompany', () => {
    it('DELETEs /api/users/companies/{id}', async () => {
      fetchMock.mockResolvedValue(noContentResponse());
      const store = makeStore(async () => 'tok');

      await store
        .dispatch(userCompaniesApi.endpoints.removeUserCompany.initiate('u-abc1234567'))
        .unwrap();

      const [input, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
      expect(urlFromInput(input)).toMatch(/\/api\/users\/companies\/u-abc1234567$/);
      expect(getMethod(input, init)).toBe('DELETE');
    });
  });

  describe('getUserCompanyJobs', () => {
    const RAW_JOB: BackendJobListing = {
      id: 'job-1',
      title: 'Staff Engineer',
      company: 'irrelevant-server-value',
      location: 'Remote - US',
      locations: [],
      url: 'https://boards.greenhouse.io/duolingo/jobs/1',
      sourceId: 'custom:u-abc1234567',
      details: '{}',
      createdAt: '2026-08-01T00:00:00Z',
      postedOn: null,
      closedOn: null,
      status: 'OPEN',
      hasMatched: false,
      aiMetadata: '{}',
      firstSeenAt: '2026-08-05T12:00:00Z',
      lastSeenAt: '2026-08-09T00:00:00Z',
      consecutiveMisses: 0,
      detailsScraped: false,
    };

    it('GETs the owner-scoped jobs path and transforms the SAME /api/jobs shape into Job[]', async () => {
      // A BARE ARRAY (not an envelope) — identical to what /api/jobs returns.
      fetchMock.mockResolvedValue(jsonResponse([RAW_JOB]));
      const store = makeStore(async () => 'tok');

      const jobs = await store
        .dispatch(userCompaniesApi.endpoints.getUserCompanyJobs.initiate({ id: 'u-abc1234567' }))
        .unwrap();

      const [input, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
      expect(urlFromInput(input)).toMatch(/\/api\/users\/companies\/u-abc1234567\/jobs$/);
      expect(getMethod(input, init) ?? 'GET').toBe('GET');

      // Reuses transformBackendJob: company is stamped from the id arg, and the
      // canonical recency field firstSeenAt survives verbatim.
      expect(jobs).toHaveLength(1);
      expect(jobs[0].id).toBe('job-1');
      expect(jobs[0].company).toBe('u-abc1234567');
      expect(jobs[0].firstSeenAt).toBe('2026-08-05T12:00:00Z');
      // postedOn was null → createdAt falls back to firstSeenAt (display-only).
      expect(jobs[0].createdAt).toBe('2026-08-05T12:00:00Z');
    });
  });

  describe('tag invalidation', () => {
    function routedFetch() {
      return vi.fn(async (input: RequestInfo | URL) => {
        const req = input as Request;
        if (req.method === 'POST') return jsonResponse(SAMPLE_COMPANY, 201);
        if (req.method === 'DELETE') return noContentResponse();
        return jsonResponse({ companies: [SAMPLE_COMPANY] }); // GET list
      });
    }

    function listCallCount(mock: ReturnType<typeof vi.fn>): number {
      return mock.mock.calls.filter(([input]) => (input as Request).method === 'GET').length;
    }

    it('addUserCompany invalidates MyCompanies, refetching the list', async () => {
      const mock = routedFetch();
      globalThis.fetch = mock as unknown as typeof fetch;
      const store = makeStore(async () => 'tok');

      // Keep an active subscription so invalidation triggers a refetch.
      store.dispatch(userCompaniesApi.endpoints.getUserCompanies.initiate());
      await vi.waitFor(() => expect(listCallCount(mock)).toBe(1));

      await store
        .dispatch(userCompaniesApi.endpoints.addUserCompany.initiate({ url: 'https://x' }))
        .unwrap();

      await vi.waitFor(() => expect(listCallCount(mock)).toBe(2));
    });

    it('removeUserCompany invalidates MyCompanies, refetching the list', async () => {
      const mock = routedFetch();
      globalThis.fetch = mock as unknown as typeof fetch;
      const store = makeStore(async () => 'tok');

      store.dispatch(userCompaniesApi.endpoints.getUserCompanies.initiate());
      await vi.waitFor(() => expect(listCallCount(mock)).toBe(1));

      await store
        .dispatch(userCompaniesApi.endpoints.removeUserCompany.initiate('u-abc1234567'))
        .unwrap();

      await vi.waitFor(() => expect(listCallCount(mock)).toBe(2));
    });
  });

  describe('addsRemaining', () => {
    const RESETS = '2026-09-01T00:00:00Z';

    it('counts down from the limit', () => {
      expect(addsRemaining({ used: 3, limit: 20, resetsAt: RESETS })).toBe(17);
      expect(addsRemaining({ used: 0, limit: 20, resetsAt: RESETS })).toBe(20);
      expect(addsRemaining({ used: 20, limit: 20, resetsAt: RESETS })).toBe(0);
    });

    it('floors at zero rather than going negative', () => {
      // Reachable: the cap can be lowered while a user is already over it, and a
      // counter reading "-3 adds left" would be a bug the reader sees.
      expect(addsRemaining({ used: 25, limit: 20, resetsAt: RESETS })).toBe(0);
    });

    it('returns null ONLY when the payload carries no quota at all', () => {
      // A server older than this feature. "We don't know" must not be read as "you
      // have none left" — hence `null` rather than `0`, a value the caller reads as
      // exhausted and uses to disable the submit.
      expect(addsRemaining(undefined)).toBeNull();
      expect(addsRemaining(null)).toBeNull();
    });

    it('returns 0 — not null — when the limit is 0', () => {
      // THIS IS THE CASE THAT SWAPPED MEANING. `limit: 0` used to be the unlimited
      // sentinel and returned `null`. It is now a cap that is in force and allows
      // nothing, so it must count down to `0` like any other spent month: the counter
      // renders and the submit disables. Collapsing it back into `null` would turn
      // the kill switch into "unlimited" in the UI while the server refuses.
      expect(addsRemaining({ used: 0, limit: 0, resetsAt: RESETS })).toBe(0);
      expect(addsRemaining({ used: 400, limit: 0, resetsAt: RESETS })).toBe(0);
    });
  });

  describe('isMonthlyLimitError', () => {
    it('recognises the cap refusal', () => {
      expect(
        isMonthlyLimitError({
          status: 422,
          data: { reason: 'monthly_limit_reached', detail: 'x', finalUrl: '' },
        })
      ).toBe(true);
    });

    it('is false for every other add failure and for non-HTTP rejections', () => {
      expect(isMonthlyLimitError({ status: 422, data: { reason: 'empty' } })).toBe(false);
      // 429 is the BURST limiter — a different refusal with different advice.
      expect(
        isMonthlyLimitError({ status: 429, data: { detail: 'too quickly' } })
      ).toBe(false);
      expect(isMonthlyLimitError({ status: 'FETCH_ERROR', error: 'x' })).toBe(false);
      expect(isMonthlyLimitError(undefined)).toBe(false);
      expect(isMonthlyLimitError(null)).toBe(false);
    });
  });
});
