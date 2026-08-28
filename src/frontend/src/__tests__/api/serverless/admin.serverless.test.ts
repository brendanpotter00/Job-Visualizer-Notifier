import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/admin';
import { runProxyAllowlistGuard } from './proxyAllowlistGuard';

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

/**
 * The allowlist that closed the production `?path=` traversal.
 *
 * `legitimate` below is the full `/api/admin` route table from
 * `app.openapi()["paths"]`, cross-checked against `features/admin/adminApi.ts`
 * (the only caller). Every one is `Depends(require_admin)` on the backend, so
 * the allowlist is defence in depth here — but it is what stops `/api/admin`
 * being a doorway into `/api/internal/*`, which has no JWT gate at all.
 *
 * `locations/aliases/*` is the one wildcard, matching the backend's
 * `{raw_text:path}` converter: real alias keys ("EMEA / Remote") carry literal
 * slashes, so the key genuinely spans segments. The prefix is still fixed and
 * dot segments are already rejected, so it cannot escape the alias subtree —
 * the traversal vectors above are run against this proxy like every other.
 */
runProxyAllowlistGuard({
  name: 'admin',
  prefix: '/api/admin',
  handler,
  legitimate: [
    ['users', '/api/admin/users'],
    ['users/stats', '/api/admin/users/stats'],
    ['users/u-1/visits', '/api/admin/users/u-1/visits'],
    [['users', 'u-1', 'admin'], '/api/admin/users/u-1/admin'],
    ['feedback', '/api/admin/feedback'],
    ['jobs/job-1/normalize', '/api/admin/jobs/job-1/normalize'],
    ['locations/aliases', '/api/admin/locations/aliases'],
    ['locations/aliases/sunnyvale', '/api/admin/locations/aliases/sunnyvale'],
    // {raw_text:path}: a real alias key spanning two segments.
    // The space is percent-encoded by `fetch`'s URL parser; the slash stays a
    // separator, which is exactly what the backend's {raw_text:path} expects.
    ['locations/aliases/emea / remote', '/api/admin/locations/aliases/emea%20/%20remote'],
    ['locations/alias-originals', '/api/admin/locations/alias-originals'],
    ['locations/health', '/api/admin/locations/health'],
    ['locations/integrity', '/api/admin/locations/integrity'],
    ['locations/problem-jobs', '/api/admin/locations/problem-jobs'],
    ['locations/re-normalize-all', '/api/admin/locations/re-normalize-all'],
    ['locations/reverse', '/api/admin/locations/reverse'],
    ['enrichment/health', '/api/admin/enrichment/health'],
    ['enrichment/needs-human', '/api/admin/enrichment/needs-human'],
    ['enrichment/recent', '/api/admin/enrichment/recent'],
    ['enrichment/ticks', '/api/admin/enrichment/ticks'],
    [
      'enrichment/jobs/greenhouse:openai/q-1/correct',
      '/api/admin/enrichment/jobs/greenhouse:openai/q-1/correct',
    ],
    [
      'enrichment/jobs/custom:u-x/q-1/confirm',
      '/api/admin/enrichment/jobs/custom:u-x/q-1/confirm',
    ],
    [
      'enrichment/jobs/custom:u-x/q-1/reenrich',
      '/api/admin/enrichment/jobs/custom:u-x/q-1/reenrich',
    ],
  ],
  normalizes: ['/users//stats/', '/api/admin/users/stats'],
  methods: ['GET', 'POST', 'PUT', 'DELETE'],
});

/**
 * The wildcard subtree, attacked directly.
 *
 * `locations/aliases/*` is the only multi-segment entry in any of the seven
 * allowlists, and it is the only place where a traversal can be *inside* an
 * allowlisted route rather than instead of one. Mutation testing found this:
 * deleting the `..` rejection or the structural-hazard gate from the shared
 * canonicalizer left every other test green, because a mangled path missed the
 * narrow allowlists anyway — but the wildcard eats whatever follows it, so a
 * dot segment there resolves straight out of `/api/admin` and into
 * `/api/internal/enrichment/*` with the internal key attached.
 *
 * The canonicalizer is what stops it. These cases are what notice if it stops.
 */
describe('api/admin — the locations/aliases wildcard cannot be climbed', () => {
  let mockRes: Partial<VercelResponse>;
  let fetchMock: ReturnType<typeof vi.fn>;

  const WILDCARD_ESCAPES = [
    'locations/aliases/../../../internal/enrichment/pending',
    'locations/aliases/../../internal/enrichment/results',
    'locations/aliases/%2e%2e/%2e%2e/%2e%2e/internal/enrichment/pending',
    'locations/aliases/..%2F..%2F..%2Finternal%2Fenrichment%2Fpending',
    'locations/aliases/..\\..\\..\\internal\\enrichment\\pending',
    'locations/aliases/./../../../internal/enrichment/pending',
    'locations/aliases/x?limit=99999',
    'locations/aliases/x#/../../internal/enrichment/pending',
    'locations/aliases/%00/../../internal/enrichment/pending',
  ];

  beforeEach(() => {
    mockRes = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn().mockReturnThis(),
      end: vi.fn().mockReturnThis(),
    };
    fetchMock = vi.fn().mockResolvedValue(mockJsonResponse(200, {}));
    global.fetch = fetchMock as unknown as typeof fetch;
    process.env.INTERNAL_API_KEY = 'test-internal-key';
    process.env.BACKEND_API_URL = 'https://backend.test';
  });

  afterEach(() => {
    delete process.env.INTERNAL_API_KEY;
    delete process.env.BACKEND_API_URL;
    vi.clearAllMocks();
  });

  it.each(WILDCARD_ESCAPES)('refuses %s', async (pathValue) => {
    const req = {
      method: 'PUT',
      query: { path: pathValue },
      headers: { authorization: 'Bearer admin-token' },
      body: { locations: [] },
    } as unknown as VercelRequest;

    await handler(req, mockRes as VercelResponse);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(mockRes.status).toHaveBeenCalledWith(404);
  });

  it('a legitimate multi-segment alias key still forwards, and stays inside the subtree', async () => {
    // The wildcard is not decoration: real alias keys carry literal slashes
    // ("EMEA / Remote"), which is why the backend declares {raw_text:path}.
    const req = {
      method: 'PUT',
      query: { path: 'locations/aliases/emea / remote' },
      headers: { authorization: 'Bearer admin-token' },
      body: { locations: [] },
    } as unknown as VercelRequest;

    await handler(req, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const resolved = new URL(fetchMock.mock.calls[0][0] as string);
    expect(resolved.pathname.startsWith('/api/admin/locations/aliases/')).toBe(true);
  });
});
