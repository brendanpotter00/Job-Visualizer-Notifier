import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/admin';

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

describe('/api/admin serverless function', () => {
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

  it('proxies GET /api/admin/users to the backend', async () => {
    mockReq.query = { path: 'users' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, { users: [] }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/admin/users',
      expect.any(Object)
    );
  });

  it('proxies GET /api/admin/users/stats to the backend', async () => {
    mockReq.query = { path: ['users', 'stats'] };
    fetchMock.mockResolvedValue(mockJsonResponse(200, { totalUsers: 0 }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/admin/users/stats',
      expect.any(Object)
    );
  });

  it('forwards the Authorization header to the backend', async () => {
    // The whole /api/admin/* surface is admin-gated by require_admin. Losing
    // the Bearer token at the proxy returns 401 for every authenticated
    // call, so this assertion is load-bearing.
    mockReq.query = { path: 'users' };
    mockReq.headers = { authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.test-token' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, { users: [] }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/admin/users',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          Authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.test-token',
        }),
      })
    );
  });

  it('omits Authorization when no header is provided (anonymous → backend returns 401)', async () => {
    mockReq.query = { path: 'users' };
    mockReq.headers = {};
    fetchMock.mockResolvedValue(mockJsonResponse(401, { detail: 'Authentication required' }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    const callArgs = fetchMock.mock.calls[0][1];
    expect(callArgs.headers).not.toHaveProperty('Authorization');
  });

  it('returns 502 when the upstream fetch throws', async () => {
    mockReq.query = { path: 'users' };
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(mockRes.status).toHaveBeenCalledWith(502);
    expect(mockRes.json).toHaveBeenCalledWith(
      expect.objectContaining({
        error: 'Upstream backend unavailable',
      })
    );
  });

  it('forwards the response status code and body from the backend', async () => {
    mockReq.query = { path: 'users' };
    fetchMock.mockResolvedValue(mockJsonResponse(403, { detail: 'Admin access required' }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(mockRes.status).toHaveBeenCalledWith(403);
    expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Admin access required' });
  });

  it('forwards POST /api/admin/users/{id}/admin (grant) and passes 204 through with no body', async () => {
    // Grant returns 204 with no body — forwardResponse must short-circuit
    // and not attach a JSON envelope. Without that, RFC 9110 §15.3.5 is
    // violated and strict HTTP clients (or anything that asserts
    // body-length === 0 on 204) trip.
    mockReq.method = 'POST';
    mockReq.query = { path: ['users', 'target-1', 'admin'] };
    fetchMock.mockResolvedValue({
      status: 204,
      headers: {
        get: () => null, // no content-type on a 204 — typical
      },
      text: async () => '',
      json: async () => ({}),
    });

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/admin/users/target-1/admin',
      expect.objectContaining({ method: 'POST' })
    );
    expect(mockRes.status).toHaveBeenCalledWith(204);
    expect(mockRes.end).toHaveBeenCalled();
    // ``json`` must NOT have been called for a 204 — that would attach a body.
    expect(mockRes.json).not.toHaveBeenCalled();
  });

  it('forwards DELETE /api/admin/users/{id}/admin (revoke) and passes 204 through with no body', async () => {
    mockReq.method = 'DELETE';
    mockReq.query = { path: ['users', 'target-2', 'admin'] };
    fetchMock.mockResolvedValue({
      status: 204,
      headers: { get: () => null },
      text: async () => '',
      json: async () => ({}),
    });

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/admin/users/target-2/admin',
      expect.objectContaining({ method: 'DELETE' })
    );
    expect(mockRes.status).toHaveBeenCalledWith(204);
    expect(mockRes.end).toHaveBeenCalled();
    expect(mockRes.json).not.toHaveBeenCalled();
  });

  it('forwards request body for non-PUT/POST methods (PATCH with body)', async () => {
    // Today's admin endpoints have no body. The next admin endpoint with a
    // PATCH (or DELETE) body would silently drop it under the previous
    // PUT/POST-only restriction. This test pins the contract: any method
    // with ``req.body != null`` must forward the body upstream.
    mockReq.method = 'PATCH';
    mockReq.query = { path: ['users', 'target-3', 'admin'] };
    mockReq.body = { role: 'super-admin' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, { ok: true }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    const [, fetchOptions] = fetchMock.mock.calls[0];
    expect(fetchOptions.method).toBe('PATCH');
    // Body should be JSON-stringified (req.body is a plain object).
    expect(fetchOptions.body).toBe(JSON.stringify({ role: 'super-admin' }));
  });
});
