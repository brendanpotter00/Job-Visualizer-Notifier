import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import {
  userCompaniesApi,
  type ResolveUrlResponse,
  type ResolveUrlFailure,
} from '../../../features/userCompanies/userCompaniesApi';

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

const SAMPLE_SUCCESS: ResolveUrlResponse = {
  candidate: {
    ats: 'workday',
    boardToken: 'intel',
    providerConfig: {
      baseUrl: 'https://intel.wd1.myworkdayjobs.com',
      tenantSlug: 'intel',
    },
    sourceUrl: 'https://intel.wd1.myworkdayjobs.com/External',
  },
  probe: { ok: true, jobCount: 663, error: null },
  via: 'direct',
  hops: [],
  finalUrl: 'https://intel.wd1.myworkdayjobs.com/External',
};

describe('userCompaniesApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('resolveCareersUrl', () => {
    it('POSTs to /api/companies/resolve with a { url } body', async () => {
      fetchMock.mockResolvedValue(jsonResponse(SAMPLE_SUCCESS));
      const store = makeStore(async () => 'tok');

      await store
        .dispatch(
          userCompaniesApi.endpoints.resolveCareersUrl.initiate({
            url: 'https://intel.com/careers',
          })
        )
        .unwrap();

      const [input, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
      // baseUrl is '/api' (not '/api/companies') so future users/companies
      // endpoints can share the slice — the endpoint supplies the rest.
      expect(urlFromInput(input)).toMatch(/\/api\/companies\/resolve$/);
      expect(getMethod(input, init)).toBe('POST');
      expect(JSON.parse((await getBody(input, init)) ?? '{}')).toEqual({
        url: 'https://intel.com/careers',
      });
    });

    it('returns the parsed 200 body, including probe details', async () => {
      fetchMock.mockResolvedValue(jsonResponse(SAMPLE_SUCCESS));
      const store = makeStore(async () => 'tok');

      const result = await store
        .dispatch(
          userCompaniesApi.endpoints.resolveCareersUrl.initiate({ url: 'https://intel.com' })
        )
        .unwrap();

      expect(result).toEqual(SAMPLE_SUCCESS);
      expect(result.probe.jobCount).toBe(663);
      expect(result.candidate.ats).toBe('workday');
    });

    it('sets Authorization: Bearer <token> when a token exists', async () => {
      fetchMock.mockResolvedValue(jsonResponse(SAMPLE_SUCCESS));
      const store = makeStore(async () => 'tok-abc');

      await store
        .dispatch(
          userCompaniesApi.endpoints.resolveCareersUrl.initiate({ url: 'https://intel.com' })
        )
        .unwrap();

      const [input, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
      expect(getHeader(input, init, 'Authorization')).toBe('Bearer tok-abc');
    });

    it('omits the Authorization header when the token getter returns null', async () => {
      fetchMock.mockResolvedValue(jsonResponse(SAMPLE_SUCCESS));
      const store = makeStore(async () => null);

      await store
        .dispatch(
          userCompaniesApi.endpoints.resolveCareersUrl.initiate({ url: 'https://intel.com' })
        )
        .unwrap();

      const [input, init] = fetchMock.mock.calls[0] as [RequestInfo | URL, RequestInit | undefined];
      expect(getHeader(input, init, 'Authorization')).toBeNull();
    });

    it('surfaces the FLAT 422 resolver body to the caller', async () => {
      const failure: ResolveUrlFailure = {
        reason: 'no_ats_detected',
        finalUrl: 'https://example.com/careers',
        hops: ['https://example.com', 'https://example.com/careers'],
      };
      fetchMock.mockResolvedValue(jsonResponse(failure, 422));
      const store = makeStore(async () => 'tok');

      const result = await store.dispatch(
        userCompaniesApi.endpoints.resolveCareersUrl.initiate({ url: 'https://example.com' })
      );

      expect('error' in result).toBe(true);
      const error = (result as { error: { status: number; data: ResolveUrlFailure } }).error;
      expect(error.status).toBe(422);
      // The `reason` must arrive at the top level of `data`, NOT under `detail` —
      // that distinction is what resolveErrors.ts keys off.
      expect(error.data.reason).toBe('no_ats_detected');
      expect(error.data.hops).toHaveLength(2);
      expect(error.data).not.toHaveProperty('detail');
    });

    it('surfaces a 503 (server feature flag off) to the caller', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({ detail: 'Custom company sources are not enabled' }, 503)
      );
      const store = makeStore(async () => 'tok');

      const result = await store.dispatch(
        userCompaniesApi.endpoints.resolveCareersUrl.initiate({ url: 'https://example.com' })
      );

      const error = (result as { error: { status: number; data: { detail: string } } }).error;
      expect(error.status).toBe(503);
      expect(error.data.detail).toBe('Custom company sources are not enabled');
    });

    it('issues a fresh request per submit (mutations are not cached)', async () => {
      // A new Response per call: a single instance would have its body
      // consumed by the first read and throw on the second.
      fetchMock.mockImplementation(async () => jsonResponse(SAMPLE_SUCCESS));
      const store = makeStore(async () => 'tok');

      const args = { url: 'https://intel.com' };
      await store.dispatch(userCompaniesApi.endpoints.resolveCareersUrl.initiate(args)).unwrap();
      await store.dispatch(userCompaniesApi.endpoints.resolveCareersUrl.initiate(args)).unwrap();

      // Re-checking the same URL must actually re-probe the board rather than
      // replay a cached answer — the board's job count changes over time.
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
  });
});
