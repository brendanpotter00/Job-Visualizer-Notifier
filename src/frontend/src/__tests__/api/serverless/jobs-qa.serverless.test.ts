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

  describe('scraper-health is not routable through the public proxy', () => {
    /**
     * SECURITY BOUNDARY.
     *
     * This function is a public internet endpoint and attaches
     * `X-Internal-Key` unconditionally, so it always clears the backend's
     * `require_internal_key` middleware. The only real identity check on any
     * jobs-qa route is `Depends(require_admin)` on the backend, and
     * `GET /scraper-health` deliberately has none (the scheduled Action
     * cannot mint an admin JWT). So for that route the proxy IS the
     * perimeter, and it cannot verify a token.
     *
     * A previous fix here checked only that an `Authorization` header was
     * present. Driving the real handler proved that useless:
     * `Authorization: garbage` and `Authorization: 0` both reached upstream
     * and returned the internal roster. The tests below are written as
     * falsification attempts against exactly that mistake — every one of
     * them supplies a credential and still demands a 404.
     */
    const FABRICATED_CREDENTIALS = [
      'garbage',
      'Bearer x',
      'Bearer admin-token',
      '0',
      'Basic YWRtaW46YWRtaW4=',
      'Bearer eyJhbGciOiJub25lIn0.eyJzdWIiOiJhZG1pbiJ9.',
    ];

    it.each(FABRICATED_CREDENTIALS)(
      'returns 404 and never calls upstream with Authorization: %s',
      async (authorization) => {
        mockReq.query = { path: 'scraper-health', thresholdHours: '720' };
        mockReq.headers = { authorization };

        await handler(mockReq as VercelRequest, mockRes as VercelResponse);

        expect(mockRes.status).toHaveBeenCalledWith(404);
        expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Not Found' });
        // The upstream call must not happen AT ALL — the proxy holds the
        // internal key, so forwarding and letting the backend decide is
        // precisely the hole being closed.
        expect(fetchMock).not.toHaveBeenCalled();
      }
    );

    it('returns 404 with no Authorization header at all', async () => {
      mockReq.query = { path: 'scraper-health' };
      mockReq.headers = {};

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('404s before the anonymous pre-filter, so the path is indistinguishable from unrouted', async () => {
      // Ordering matters: if the presence check ran first, an anonymous
      // request would get 401 and a credentialed one 404, and the
      // difference would advertise that the path exists.
      mockReq.query = { path: 'scraper-health' };
      mockReq.headers = {};
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(mockRes.status).not.toHaveBeenCalledWith(401);
    });
  });

  describe('anonymous pre-filter on proxied routes', () => {
    it('rejects a credential-less request without calling upstream', async () => {
      // Not a security boundary — these routes are admin-gated on the
      // backend and would 401 there anyway. This just avoids a pointless
      // upstream round trip.
      mockReq.query = { path: 'scrape-runs' };
      mockReq.headers = {};

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(401);
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('forwards a credentialed request to an admin-gated route', async () => {
      // The backend, not this proxy, decides whether the token is real.
      mockReq.query = { path: 'scrape-runs' };
      mockReq.headers = { authorization: 'Bearer admin-token' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, []));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(mockRes.status).toHaveBeenCalledWith(200);
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
    mockReq.query = { path: 'stats' };
    mockReq.headers = { authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.admin-token' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, { totalJobs: 0 }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/jobs-qa/stats'),
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
    mockReq.query = { path: 'stats' };
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
    mockReq.query = { path: 'stats' };
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
    mockReq.query = { path: 'some-endpoint' };
    mockReq.headers = { authorization: 'Bearer admin-token' };
    mockReq.body = { mode: 'detail' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, {}));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    const [, fetchOptions] = fetchMock.mock.calls[0];
    expect(fetchOptions.method).toBe('PATCH');
    expect(fetchOptions.body).toBe(JSON.stringify({ mode: 'detail' }));
  });
});
