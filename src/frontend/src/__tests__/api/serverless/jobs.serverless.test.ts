import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { Mock } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/jobs';

/**
 * Build a stand-in for the upstream `fetch` Response.
 *
 * `headers.get` is case-insensitive on purpose: the handler looks the cursor up
 * as lowercase `x-next-cursor` while the backend emits `X-Next-Cursor`, and a
 * case-sensitive mock would let a real casing bug pass here.
 */
function mockJsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  const serialized = JSON.stringify(body);
  const lookup = new Map(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]));
  if (!lookup.has('content-type')) lookup.set('content-type', 'application/json');
  return {
    status,
    headers: { get: (key: string) => lookup.get(key.toLowerCase()) ?? null },
    text: async () => serialized,
    json: async () => body,
  };
}

/**
 * The six multi-select filters on `GET /api/jobs/search`.
 *
 * Restated here rather than imported from `api/jobs.ts` so the test asserts the
 * wire contract independently — importing the constant would make a deletion
 * from it invisible.
 */
const REPEATABLE_PARAMS = [
  'category',
  'level',
  'company',
  'location',
  'include',
  'exclude',
] as const;

/** A realistic search response body: page 1 carries `meta`, later pages don't. */
const SEARCH_PAGE = {
  jobs: [{ id: 'job-1', title: 'Backend Engineer' }],
  nextCursor: 'eyJmc2EiOiIyMDI2LTA4LTEwIn0',
  meta: { filteredTotal: 42, countLast24h: 7, countLast3h: 2 },
};

describe('/api/jobs serverless function', () => {
  let mockReq: Partial<VercelRequest>;
  let mockRes: Partial<VercelResponse>;
  let fetchMock: ReturnType<typeof vi.fn>;

  /** The URL the proxy actually requested upstream, parsed. */
  function forwardedUrl(): URL {
    expect(fetchMock).toHaveBeenCalledTimes(1);
    return new URL(fetchMock.mock.calls[0][0] as string);
  }

  function forwardedParams(): URLSearchParams {
    return forwardedUrl().searchParams;
  }

  function forwardedHeaders(): Record<string, string> {
    const options = fetchMock.mock.calls[0][1] as RequestInit;
    return (options.headers ?? {}) as Record<string, string>;
  }

  const originalFetch = global.fetch;

  beforeEach(() => {
    mockReq = { method: 'GET', query: {}, headers: {}, body: undefined };

    mockRes = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn().mockReturnThis(),
      end: vi.fn().mockReturnThis(),
      setHeader: vi.fn().mockReturnThis(),
    };

    fetchMock = vi.fn();
    // Restored in `afterEach` — a replaced global outlives the file otherwise
    // and leaks into whatever the runner schedules next in this worker.
    global.fetch = fetchMock as unknown as typeof fetch;

    delete process.env.BACKEND_API_URL;
    delete process.env.INTERNAL_API_KEY;
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.clearAllMocks();
    delete process.env.BACKEND_API_URL;
    delete process.env.INTERNAL_API_KEY;
  });

  describe('sub-path routing', () => {
    it('forwards ?path=search to the backend search endpoint', async () => {
      // vercel.json rewrites /api/jobs/search -> /api/jobs?path=search, so the
      // sub-path arrives as a query param and has to be re-attached to the URL.
      mockReq.query = { path: 'search', since: '2026-08-09T00:00:00.000Z', limit: '100' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, SEARCH_PAGE));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const url = forwardedUrl();
      expect(url.origin).toBe('http://localhost:8000');
      expect(url.pathname).toBe('/api/jobs/search');
    });

    it('forwards ?path=facets, the other allowlisted sub-path', async () => {
      mockReq.query = { path: 'facets' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, { job_categories: [], job_levels: [] }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      // No params at all means no trailing '?' — the backend route is exact.
      expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/jobs/facets');
      expect(mockRes.status).toHaveBeenCalledWith(200);
    });

    /**
     * The allowlist is a security boundary, not a typo guard: this proxy attaches
     * the internal key unconditionally, so anything it forwards clears the
     * backend's require_internal_key middleware. The enrichment routes live under
     * the same /api/jobs prefix and must stay unreachable from the internet.
     */
    it.each<[string, string | string[]]>([
      ['an internal enrichment route', 'enrich'],
      ['a nested internal route', 'enrichment/next'],
      ['a traversal out of the prefix', '../jobs-qa/scraper-health'],
      ['a different case spelling', 'Search'],
      ['a sub-path smuggled through the array form', ['search', 'enrich']],
    ])('404s %s and never calls upstream', async (_label, pathValue) => {
      mockReq.query = { path: pathValue };

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(404);
      // The SHARED rejection body (`PROXY_REJECTION` in api/utils/proxyPath.ts),
      // not this proxy's old hand-rolled `{ error: 'Not found' }`. Adopting
      // `resolveProxyPath` here put /api/jobs behind the same control as the
      // other seven proxies — which is the point, and it means the shape is
      // theirs: `proxyAllowlistGuard.ts` and jobs-qa already assert this one.
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Not Found' });
      // Forwarding and letting the backend decide is exactly the hole the
      // allowlist closes — the proxy holds the shared secret.
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('forwards the legacy list path when no sub-path is given', async () => {
      mockReq.query = {};
      fetchMock.mockResolvedValue(mockJsonResponse(200, []));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/jobs');
    });
  });

  describe('backend authentication', () => {
    it('attaches the internal key so the backend middleware admits the request', async () => {
      // Without this header every search returns 401 from require_internal_key
      // and the Recent page renders an error instead of jobs.
      process.env.INTERNAL_API_KEY = 'shared-secret-abc';
      mockReq.query = { path: 'search', since: '2026-08-09T00:00:00.000Z' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, SEARCH_PAGE));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(forwardedHeaders()).toEqual({ 'X-Internal-Key': 'shared-secret-abc' });
    });

    it('omits the internal key when none is configured, so local dev still works', async () => {
      mockReq.query = { path: 'search' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, SEARCH_PAGE));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(forwardedHeaders()).toEqual({});
    });

    it('targets the configured backend origin in deployed environments', async () => {
      process.env.BACKEND_API_URL = 'https://backend.example.com';
      mockReq.headers = { host: 'onesecondswe.dev' };
      mockReq.query = { path: 'search' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, SEARCH_PAGE));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(forwardedUrl().origin).toBe('https://backend.example.com');
    });
  });

  describe('search: multi-value filters stay repeated params', () => {
    /**
     * THE bug this file exists to prevent.
     *
     * Vercel hands a repeated query param back as `string[]`. The scalar
     * treatment used elsewhere in this handler — `String(value)` — silently
     * joins an array with commas, so two selected categories would arrive at the
     * backend as one bogus slug `backend,data` that matches nothing and the user
     * would see an empty list with no error anywhere.
     */
    it.each(REPEATABLE_PARAMS)('forwards two %s values as two params', async (name) => {
      mockReq.query = { path: 'search', [name]: ['alpha', 'beta'] };
      fetchMock.mockResolvedValue(mockJsonResponse(200, SEARCH_PAGE));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const url = forwardedUrl();
      expect(url.searchParams.getAll(name)).toEqual(['alpha', 'beta']);
      // Belt and braces: a comma-joined collapse would still produce ONE param
      // whose value happens to contain both, which getAll() alone wouldn't catch
      // if the array assertion above were ever relaxed.
      expect(url.search).not.toContain('alpha%2Cbeta');
      expect(url.search).not.toContain('alpha,beta');
    });

    it.each(REPEATABLE_PARAMS)('forwards a single %s value unchanged', async (name) => {
      // Vercel gives a string (not a one-element array) for a param sent once;
      // both shapes have to land on the same wire format.
      mockReq.query = { path: 'search', [name]: 'alpha' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, SEARCH_PAGE));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(forwardedParams().getAll(name)).toEqual(['alpha']);
    });

    it('preserves commas and spaces inside a single filter value', async () => {
      // Canonical location names and free-text keywords contain commas, which is
      // why these cannot be a comma-joined scalar in the first place: the backend
      // could not split "Austin, TX, US" back apart unambiguously.
      mockReq.query = {
        path: 'search',
        location: ['Austin, TX, US', 'New York, NY, US'],
        include: ['staff engineer'],
      };
      fetchMock.mockResolvedValue(mockJsonResponse(200, SEARCH_PAGE));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const params = forwardedParams();
      expect(params.getAll('location')).toEqual(['Austin, TX, US', 'New York, NY, US']);
      expect(params.getAll('include')).toEqual(['staff engineer']);
    });

    it('carries every filter of a fully-loaded search in one request', async () => {
      // The shape the Recent page actually sends once a user has picked from all
      // six dropdowns — no filter may be dropped or flattened on the way through.
      mockReq.query = {
        path: 'search',
        since: '2026-08-09T12:00:00.000Z',
        limit: '100',
        cursor: 'eyJwYWdlIjoyfQ',
        company: ['google', 'stripe'],
        category: ['backend', 'data'],
        level: ['entry', 'senior'],
        location: ['Austin, TX, US'],
        include: ['rust', 'distributed systems'],
        exclude: ['clearance required'],
      };
      fetchMock.mockResolvedValue(mockJsonResponse(200, SEARCH_PAGE));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const params = forwardedParams();
      expect(params.get('since')).toBe('2026-08-09T12:00:00.000Z');
      expect(params.get('limit')).toBe('100');
      expect(params.get('cursor')).toBe('eyJwYWdlIjoyfQ');
      expect(params.getAll('company')).toEqual(['google', 'stripe']);
      expect(params.getAll('category')).toEqual(['backend', 'data']);
      expect(params.getAll('level')).toEqual(['entry', 'senior']);
      expect(params.getAll('location')).toEqual(['Austin, TX, US']);
      expect(params.getAll('include')).toEqual(['rust', 'distributed systems']);
      expect(params.getAll('exclude')).toEqual(['clearance required']);
    });

    it('drops query params outside the allowlist', async () => {
      // Documented behavior: an unforwarded param is silently dropped rather than
      // rejected, so nothing a caller invents can reach the backend.
      mockReq.query = { path: 'search', q: 'sql injection', internal_only: '1' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, SEARCH_PAGE));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const params = forwardedParams();
      expect(params.has('q')).toBe(false);
      expect(params.has('internal_only')).toBe(false);
    });
  });

  describe('search: filters are forwarded on PRESENCE, not truthiness', () => {
    /**
     * An empty `?include=` is a caller bug the backend answers with a 422.
     * Dropping it here would instead hand back a 200 full of unfiltered jobs that
     * the caller believes were filtered — a loud error converted into a silent
     * wrong answer.
     */
    it.each(REPEATABLE_PARAMS)('forwards an empty %s instead of dropping it', async (name) => {
      mockReq.query = { path: 'search', [name]: '' };
      fetchMock.mockResolvedValue(mockJsonResponse(422, { detail: `Invalid '${name}' value` }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const params = forwardedParams();
      expect(params.has(name)).toBe(true);
      expect(params.get(name)).toBe('');
    });

    it('forwards an empty value sitting alongside a real one', async () => {
      // ?include=rust&include= — the array form of the same caller bug.
      mockReq.query = { path: 'search', include: ['rust', ''] };
      fetchMock.mockResolvedValue(mockJsonResponse(422, { detail: 'Invalid include value' }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(forwardedParams().getAll('include')).toEqual(['rust', '']);
    });

    it('lets the backend 422 for an empty filter reach the caller', async () => {
      // End-to-end statement of why presence-forwarding matters: the caller sees
      // the error, not a page of jobs.
      mockReq.query = { path: 'search', include: '' };
      fetchMock.mockResolvedValue(mockJsonResponse(422, { detail: 'Invalid include value' }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(forwardedUrl().search).toContain('include=');
      expect(mockRes.status).toHaveBeenCalledWith(422);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Invalid include value' });
    });

    it.each(['since', 'cursor'])('forwards an empty %s so paging fails loudly', async (name) => {
      // A dropped empty cursor would restart the walk at page 1 with a 200 —
      // an infinite loop that looks like success.
      mockReq.query = { path: 'search', [name]: '' };
      fetchMock.mockResolvedValue(mockJsonResponse(422, { detail: 'bad' }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(forwardedParams().has(name)).toBe(true);
    });

    it('omits a filter the caller never sent', async () => {
      // Presence-forwarding must not turn "absent" into "empty" — an absent
      // filter is the legitimate "no filter" case and would 422 if sent empty.
      mockReq.query = { path: 'search', since: '2026-08-09T00:00:00.000Z' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, SEARCH_PAGE));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const params = forwardedParams();
      for (const name of REPEATABLE_PARAMS) expect(params.has(name)).toBe(false);
      expect(params.has('cursor')).toBe(false);
    });
  });

  describe('legacy list path', () => {
    it('forwards the single-valued company/category/level filters', async () => {
      mockReq.query = {
        company: 'google',
        category: 'backend',
        level: 'senior',
        status: 'OPEN',
        limit: '5000',
        offset: '0',
        since: '2026-08-01T00:00:00.000Z',
      };
      fetchMock.mockResolvedValue(mockJsonResponse(200, []));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const url = forwardedUrl();
      expect(url.pathname).toBe('/api/jobs');
      expect(url.searchParams.get('company')).toBe('google');
      expect(url.searchParams.get('category')).toBe('backend');
      expect(url.searchParams.get('level')).toBe('senior');
      expect(url.searchParams.get('status')).toBe('OPEN');
      expect(url.searchParams.get('limit')).toBe('5000');
      expect(url.searchParams.get('offset')).toBe('0');
      expect(url.searchParams.get('since')).toBe('2026-08-01T00:00:00.000Z');
    });

    it('forwards the multi-company `companies` param', async () => {
      // Distinct from search's repeated `company`: the legacy endpoint takes one
      // comma-joined scalar, and company IDs are slugs so joining is safe there.
      mockReq.query = { companies: 'google,stripe,netflix' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, []));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(forwardedParams().get('companies')).toBe('google,stripe,netflix');
    });

    it('drops an empty category/level here, unlike on search', async () => {
      // Deliberate divergence, not an oversight: this endpoint has no repeated-
      // param contract to violate, so an empty facet filter genuinely means
      // "no filter" and forwarding it would 422 a legitimate request.
      mockReq.query = { category: '', level: '', company: '' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, []));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/jobs');
    });

    it('re-emits X-Next-Cursor so the keyset walk can continue', async () => {
      // forwardResponse copies status + body ONLY. Losing this header is silent
      // in exactly the wrong way: the array forwards fine, the SPA sees no token,
      // and the walk stops after page 1 looking like a legitimate end of results.
      mockReq.query = { since: '2026-08-01T00:00:00.000Z', limit: '500' };
      fetchMock.mockResolvedValue(
        mockJsonResponse(200, [], { 'X-Next-Cursor': 'eyJmc2EiOiIyMDI2LTA4LTAxIn0' })
      );

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).toHaveBeenCalledWith(
        'X-Next-Cursor',
        'eyJmc2EiOiIyMDI2LTA4LTAxIn0'
      );
    });

    it('sets the cursor header before the body is flushed', async () => {
      // forwardResponse ENDS the response; a setHeader after it would throw
      // ERR_HTTP_HEADERS_SENT in production while passing a naive equality test.
      mockReq.query = { since: '2026-08-01T00:00:00.000Z' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, [], { 'X-Next-Cursor': 'tok' }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const headerOrder = (mockRes.setHeader as unknown as Mock).mock.invocationCallOrder[0];
      const statusOrder = (mockRes.status as unknown as Mock).mock.invocationCallOrder[0];
      expect(headerOrder).toBeLessThan(statusOrder);
    });

    it('omits X-Next-Cursor on the last page, the end-of-results signal', async () => {
      mockReq.query = { since: '2026-08-01T00:00:00.000Z' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, []));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).not.toHaveBeenCalled();
    });

    it('forwards the opaque cursor verbatim on the next page request', async () => {
      const cursor = 'eyJmaXJzdF9zZWVuX2F0IjoiMjAyNi0wOC0wMVQwMDowMDowMFoifQ==';
      mockReq.query = { since: '2026-08-01T00:00:00.000Z', cursor };
      fetchMock.mockResolvedValue(mockJsonResponse(200, []));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(forwardedParams().get('cursor')).toBe(cursor);
    });
  });

  describe('response pass-through', () => {
    it('passes the search body through unchanged, cursor and meta included', async () => {
      // The search endpoint puts its cursor in the BODY precisely so it cannot be
      // lost the way a header can — which only holds if the body is untouched.
      mockReq.query = { path: 'search', since: '2026-08-09T00:00:00.000Z' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, SEARCH_PAGE));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(SEARCH_PAGE);
    });

    it('passes a terminal page through with a null cursor', async () => {
      const lastPage = { jobs: [], nextCursor: null, meta: null };
      mockReq.query = { path: 'search', cursor: 'tok' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, lastPage));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.json).toHaveBeenCalledWith(lastPage);
    });

    it.each([400, 401, 422, 500, 503])('passes backend status %i through', async (status) => {
      mockReq.query = { path: 'search' };
      fetchMock.mockResolvedValue(mockJsonResponse(status, { detail: 'upstream said so' }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(status);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'upstream said so' });
    });

    it('returns 500 when the upstream fetch throws', async () => {
      mockReq.query = { path: 'search' };
      fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Failed to fetch from backend' });
    });
  });
});
