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

  describe('anonymous-request gate', () => {
    /**
     * SECURITY BOUNDARY. This function is a public internet endpoint
     * (vercel.json maps `/api/jobs-qa/:path(.*)` here) and it attaches
     * `X-Internal-Key` unconditionally, so it always satisfies the backend's
     * `require_internal_key` middleware. Before this gate existed, the only
     * thing stopping anonymous access was that every jobs-qa route happened
     * to carry `Depends(require_admin)` — so adding one route without it
     * (`GET /scraper-health`, which the scheduled GitHub Action needs to
     * reach with a static header) silently published the internal company
     * roster, per-company open-job counts, and scraper staleness to anyone
     * with curl.
     *
     * These tests must fail loudly if that gate is ever removed or narrowed
     * to specific paths.
     */
    it('rejects an anonymous request with 401 and never calls upstream', async () => {
      mockReq.query = { path: 'scraper-health', thresholdHours: '720' };
      mockReq.headers = {};

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(401);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Unauthorized' });
      // The upstream call must not happen at all — the proxy holds the
      // internal key, so forwarding first and relying on the backend to
      // refuse is exactly the hole being closed.
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('rejects anonymous requests to every jobs-qa path, not just scraper-health', async () => {
      // The gate is path-agnostic on purpose: it must protect future routes
      // that forget `require_admin`, not just the one that exposed the bug.
      for (const path of ['scraper-health', 'scrape-runs', 'stats', 'trigger-scrape']) {
        vi.clearAllMocks();
        mockReq.query = { path };
        mockReq.headers = {};

        await handler(mockReq as VercelRequest, mockRes as VercelResponse);

        expect(mockRes.status).toHaveBeenCalledWith(401);
        expect(fetchMock).not.toHaveBeenCalled();
      }
    });

    it('lets an authenticated request through to the backend', async () => {
      mockReq.query = { path: 'scraper-health' };
      mockReq.headers = { authorization: 'Bearer admin-token' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, { staleCount: 0 }));

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
