import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/jobs-qa';

function mockJsonResponse(status: number, body: unknown) {
  const serialized = JSON.stringify(body);
  return {
    status,
    headers: {
      get: (key: string) => (key === 'content-type' ? 'application/json' : null),
    },
    text: async () => serialized,
    json: async () => body,
  };
}

describe('/api/jobs-qa serverless function', () => {
  let mockReq: Partial<VercelRequest>;
  let mockRes: Partial<VercelResponse>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockReq = {
      method: 'GET',
      query: {},
      headers: {},
      body: undefined,
    };

    mockRes = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn().mockReturnThis(),
      end: vi.fn().mockReturnThis(),
    };

    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    delete process.env.BACKEND_API_URL;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('only allowlisted paths are proxied', () => {
    /**
     * SECURITY BOUNDARY.
     *
     * This function is a public internet endpoint and attaches
     * `X-Internal-Key` unconditionally, so it always clears the backend's
     * `require_internal_key` middleware. The only real identity check on any
     * jobs-qa route is `Depends(require_admin)` on the backend, and
     * `GET /scraper-health` deliberately has none (the scheduled Action
     * cannot mint an admin JWT). For that route the proxy IS the perimeter,
     * and it cannot verify a token.
     *
     * Two earlier shapes were bypassed:
     *   1. requiring only that an `Authorization` header be PRESENT —
     *      `Authorization: garbage` sailed through;
     *   2. a denylist compared by exact string against the raw `?path=` —
     *      every non-byte-identical spelling below got proxied, and the
     *      trailing-slash one is a working exploit end to end (Starlette
     *      307s to the canonical path and Node's fetch follows it with
     *      headers intact).
     *
     * Every case here is a falsification attempt against those two
     * mistakes: each supplies a credential, each uses a spelling that
     * defeated the denylist, and each still demands a 404.
     */
    const BYPASS_SPELLINGS: Array<[string, string | string[]]> = [
      ['exact', 'scraper-health'],
      ['trailing slash', 'scraper-health/'],
      ['leading slash', '/scraper-health'],
      ['double trailing slash', 'scraper-health//'],
      ['dot-slash prefix', './scraper-health'],
      ['percent-encoded hyphen', 'scraper%2Dhealth'],
      ['surrounding slashes', '/scraper-health/'],
      ['repeated inner slashes', 'scraper-health///'],
      ['array form with empty tail', ['scraper-health', '']],
      ['array form with empty head', ['', 'scraper-health']],
    ];

    it.each(BYPASS_SPELLINGS)(
      'returns 404 for %s and never calls upstream',
      async (_label, pathValue) => {
        mockReq.query = { path: pathValue, thresholdHours: '720' };
        // Credentialed on purpose: presence of a header must not help.
        mockReq.headers = { authorization: 'Bearer admin-token' };

        await handler(mockReq as VercelRequest, mockRes as VercelResponse);

        expect(mockRes.status).toHaveBeenCalledWith(404);
        expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Not Found' });
        // The upstream call must not happen AT ALL — the proxy holds the
        // internal key, so forwarding and letting the backend decide is
        // precisely the hole being closed.
        expect(fetchMock).not.toHaveBeenCalled();
      }
    );

    const FABRICATED_CREDENTIALS = [
      'garbage',
      'Bearer x',
      '0',
      'Basic YWRtaW46YWRtaW4=',
      'Bearer eyJhbGciOiJub25lIn0.eyJzdWIiOiJhZG1pbiJ9.',
    ];

    it.each(FABRICATED_CREDENTIALS)(
      'returns 404 for scraper-health with Authorization: %s',
      async (authorization) => {
        mockReq.query = { path: 'scraper-health' };
        mockReq.headers = { authorization };

        await handler(mockReq as VercelRequest, mockRes as VercelResponse);

        expect(mockRes.status).toHaveBeenCalledWith(404);
        expect(fetchMock).not.toHaveBeenCalled();
      }
    );

    it('404s anonymously too, before the credential pre-filter', async () => {
      // Ordering matters: if the presence check ran first, an anonymous
      // request would get 401 and a credentialed one 404, and the
      // difference would advertise that the path exists.
      mockReq.query = { path: 'scraper-health' };
      mockReq.headers = {};

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(mockRes.status).not.toHaveBeenCalledWith(401);
    });

    it.each(['stats', 'trigger-greenhouse-fan-out', 'trigger-workday-fetch'])(
      'returns 404 for the un-allowlisted admin route %s',
      async (pathValue) => {
        // Fails CLOSED by default: these are admin-gated so they were never a
        // vulnerability, but they are not what the browser needs, and the
        // operator runbooks curl Railway directly. An allowlist means a new
        // backend route is unreachable here until someone deliberately adds it.
        mockReq.query = { path: pathValue };
        mockReq.headers = { authorization: 'Bearer admin-token' };

        await handler(mockReq as VercelRequest, mockRes as VercelResponse);

        expect(mockRes.status).toHaveBeenCalledWith(404);
        expect(fetchMock).not.toHaveBeenCalled();
      }
    );

    it('returns 404 for a malformed percent-escape rather than throwing', async () => {
      // decodeURIComponent('%') throws URIError; an unhandled throw here
      // would surface as a 500 and, worse, could be mistaken for a
      // reachable endpoint.
      mockReq.query = { path: '%' };
      mockReq.headers = { authorization: 'Bearer admin-token' };

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('returns 404 for a traversal attempt out of /api/jobs-qa', async () => {
      mockReq.query = { path: '../jobs' };
      mockReq.headers = { authorization: 'Bearer admin-token' };

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('never follows redirects, so a 307 cannot reach a refused path', async () => {
      // Node's fetch defaults to following redirects and preserves headers
      // across a same-origin 3xx — including the injected X-Internal-Key.
      mockReq.query = { path: 'scrape-runs' };
      mockReq.headers = { authorization: 'Bearer admin-token' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, []));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const [, fetchOptions] = fetchMock.mock.calls[0];
      expect(fetchOptions.redirect).toBe('manual');
    });
  });

  describe('allowlisted paths still work', () => {
    it.each(['scrape-runs', 'trigger-scrape'])(
      'forwards %s when credentialed',
      async (pathValue) => {
        mockReq.query = { path: pathValue };
        mockReq.headers = { authorization: 'Bearer admin-token' };
        fetchMock.mockResolvedValue(mockJsonResponse(200, []));

        await handler(mockReq as VercelRequest, mockRes as VercelResponse);

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(fetchMock.mock.calls[0][0]).toContain(`/api/jobs-qa/${pathValue}`);
        expect(mockRes.status).toHaveBeenCalledWith(200);
      }
    );

    it('normalizes a trailing slash on an allowlisted path instead of 404ing it', async () => {
      // The normalizer is not only a security control — without it the
      // allowlist would reject legitimate spellings, and the upstream URL
      // would carry the trailing slash into a pointless 307.
      mockReq.query = { path: 'scrape-runs/' };
      mockReq.headers = { authorization: 'Bearer admin-token' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, []));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(fetchMock.mock.calls[0][0]).toContain('/api/jobs-qa/scrape-runs');
      expect(fetchMock.mock.calls[0][0]).not.toContain('scrape-runs/?');
    });

    it('rejects a credential-less request to an allowlisted route', async () => {
      // Not a security boundary — the backend would 401 anyway. This just
      // avoids a pointless upstream round trip.
      mockReq.query = { path: 'scrape-runs' };
      mockReq.headers = {};

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(401);
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  it('proxies GET /api/jobs-qa/scrape-runs with query params preserved', async () => {
    mockReq.query = { path: 'scrape-runs', limit: '100', company: 'google' };
    mockReq.headers = { authorization: 'Bearer admin-token' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, []));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/api/jobs-qa/scrape-runs');
    expect(url).toContain('limit=100');
    expect(url).toContain('company=google');
  });

  it('forwards the Authorization header — jobs_qa is admin-gated on the backend', async () => {
    // Regression guard: before this fix the proxy stripped Authorization, so
    // every QAPage request returned 401 once require_admin was enforced.
    mockReq.query = { path: 'scrape-runs' };
    mockReq.headers = { authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.admin-token' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, { totalJobs: 0 }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/jobs-qa/scrape-runs'),
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.admin-token',
        }),
      })
    );
  });

  it('forwards a POST trigger-scrape with body', async () => {
    mockReq.method = 'POST';
    mockReq.query = { path: 'trigger-scrape', company: 'google' };
    mockReq.headers = { authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.admin-token' };
    mockReq.body = { force: true };
    fetchMock.mockResolvedValue(mockJsonResponse(202, { message: 'Scrape started' }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/jobs-qa/trigger-scrape'),
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ force: true }),
      })
    );
  });

  it('returns 502 when the upstream fetch throws', async () => {
    mockReq.query = { path: 'scrape-runs' };
    mockReq.headers = { authorization: 'Bearer admin-token' };
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(mockRes.status).toHaveBeenCalledWith(502);
    expect(mockRes.json).toHaveBeenCalledWith(
      expect.objectContaining({
        error: 'Upstream backend unavailable',
      })
    );
  });

  it('forwards the backend status code and body', async () => {
    mockReq.query = { path: 'scrape-runs' };
    mockReq.headers = { authorization: 'Bearer admin-token' };
    fetchMock.mockResolvedValue(mockJsonResponse(403, { detail: 'Admin access required' }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(mockRes.status).toHaveBeenCalledWith(403);
    expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Admin access required' });
  });

  it('forwards request body for non-PUT/POST methods (PATCH with body)', async () => {
    // Audit pass-3: parity with ``api/admin.ts`` — the body-forwarding
    // gate is lifted from ``PUT/POST`` to ``req.body != null`` so a
    // future PATCH or DELETE endpoint with a body doesn't silently
    // drop the body upstream.
    mockReq.method = 'PATCH';
    mockReq.query = { path: 'trigger-scrape' };
    mockReq.headers = { authorization: 'Bearer admin-token' };
    mockReq.body = { mode: 'detail' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, {}));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    const [, fetchOptions] = fetchMock.mock.calls[0];
    expect(fetchOptions.method).toBe('PATCH');
    expect(fetchOptions.body).toBe(JSON.stringify({ mode: 'detail' }));
  });
});
