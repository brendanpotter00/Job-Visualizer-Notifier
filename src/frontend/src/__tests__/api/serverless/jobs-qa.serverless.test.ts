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

  it('proxies GET /api/jobs-qa/scrape-runs with query params preserved', async () => {
    mockReq.query = { path: 'scrape-runs', limit: '100', company: 'google' };
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
    fetchMock.mockResolvedValue(mockJsonResponse(403, { detail: 'Admin access required' }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(mockRes.status).toHaveBeenCalledWith(403);
    expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Admin access required' });
  });
});
