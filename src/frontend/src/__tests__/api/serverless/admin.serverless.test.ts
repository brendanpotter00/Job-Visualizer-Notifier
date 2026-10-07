import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/admin';
import { expectNoKeyedUpstreamCall, runProxyAllowlistGuard } from './proxyAllowlistGuard';
import { WILDCARD_TAIL_ESCAPES } from './proxyAttackVectors';

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

  it('forwards every Launch Radar list query param (status, limit, offset, sort)', async () => {
    // The page's whole view is in these four: the tab, the page and the order.
    // A proxy that dropped one would answer 200 with the wrong cards (the
    // default sort, page 1) and no error anywhere.
    mockReq.query = {
      path: ['launch-radar', 'cards'],
      status: 'saved',
      limit: '25',
      offset: '50',
      sort: 'talent',
    };
    fetchMock.mockResolvedValue(mockJsonResponse(200, { cards: [] }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const target = new URL(fetchMock.mock.calls[0][0] as string);
    expect(target.pathname).toBe('/api/admin/launch-radar/cards');
    expect(Object.fromEntries(target.searchParams)).toEqual({
      status: 'saved',
      limit: '25',
      offset: '50',
      sort: 'talent',
    });
  });

  it.each(['announced', 'talent', 'vc', 'added'])(
    'forwards sort=%s to the Launch Radar list unchanged',
    async (sort) => {
      mockReq.query = { path: 'launch-radar/cards', status: 'new', sort };
      fetchMock.mockResolvedValue(mockJsonResponse(200, { cards: [] }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const target = new URL(fetchMock.mock.calls[0][0] as string);
      expect(target.searchParams.get('sort')).toBe(sort);
      expect(target.searchParams.get('status')).toBe('new');
    }
  );

  it('forwards a Launch Radar status PATCH with its { status, from } body', async () => {
    // `from` is the backend's compare-and-swap guard; dropping it would let a
    // stale Unsave restore an archived card instead of answering 409.
    mockReq.method = 'PATCH';
    mockReq.query = { path: ['launch-radar', 'cards', '4'] };
    mockReq.body = { status: 'new', from: 'saved' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, { id: 4, status: 'new' }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    const [url, fetchOptions] = fetchMock.mock.calls[0];
    expect(new URL(url as string).pathname).toBe('/api/admin/launch-radar/cards/4');
    expect(fetchOptions.method).toBe('PATCH');
    expect(fetchOptions.body).toBe(JSON.stringify({ status: 'new', from: 'saved' }));
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
    ['enrichment/jobs/custom:u-x/q-1/confirm', '/api/admin/enrichment/jobs/custom:u-x/q-1/confirm'],
    [
      'enrichment/jobs/custom:u-x/q-1/reenrich',
      '/api/admin/enrichment/jobs/custom:u-x/q-1/reenrich',
    ],
    // Custom Companies (E7). Missing allowlist entries here produce a clean 404
    // in Vercel dev and production while everything still works against
    // localhost:8000 — a failure that looks like a routing bug and isn't.
    ['custom-companies', '/api/admin/custom-companies'],
    ['custom-companies/attempts', '/api/admin/custom-companies/attempts'],
    // Launch Radar: the list, and one card (PATCH status / DELETE).
    ['launch-radar/cards', '/api/admin/launch-radar/cards'],
    ['launch-radar/cards/12', '/api/admin/launch-radar/cards/12'],
  ],
  normalizes: ['/users//stats/', '/api/admin/users/stats'],
  encodes: [
    ['users/u 1/visits', 'https://backend.test/api/admin/users/u%201/visits'],
    ['launch-radar/cards/card 12', 'https://backend.test/api/admin/launch-radar/cards/card%2012'],
    [
      'locations/aliases/emea / remote',
      'https://backend.test/api/admin/locations/aliases/emea%20/%20remote',
    ],
  ],
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

  describe.each(WILDCARD_TAIL_ESCAPES)('encoded climb: %s', (_label, tail) => {
    const pathValue = `locations/aliases/${tail}`;

    it.each([
      ['anonymous GET', 'GET', {}],
      ['admin GET', 'GET', { authorization: 'Bearer admin-token' }],
      ['admin PUT with a body', 'PUT', { authorization: 'Bearer admin-token' }],
    ] as const)(
      '%s is refused before the internal key is attached',
      async (_who, method, headers) => {
        const req = {
          method,
          query: { path: pathValue },
          headers,
          body: method === 'PUT' ? { locations: [] } : undefined,
        } as unknown as VercelRequest;

        await handler(req, mockRes as VercelResponse);

        expectNoKeyedUpstreamCall(fetchMock);
        expect(mockRes.status).toHaveBeenCalledWith(404);
        expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Not Found' });
      }
    );
  });

  it('the exact production reproduction never reaches /api/internal/launch-radar/monitors', async () => {
    // Verbatim from the verifier: the client sent `%25252e%25252e`, Vercel
    // decoded it once, and this is what `req.query.path` held. Before the fix
    // it canonicalized to `%2e%2e` (not `..`, so it passed), matched the
    // wildcard, and `fetch` collapsed it to GET /api/internal/launch-radar/monitors
    // with X-Internal-Key set.
    const req = {
      method: 'GET',
      query: {
        path: 'locations/aliases/%252e%252e/%252e%252e/%252e%252e/internal/launch-radar/monitors',
      },
      headers: {},
      body: undefined,
    } as unknown as VercelRequest;

    await handler(req, mockRes as VercelResponse);

    expectNoKeyedUpstreamCall(fetchMock);
    expect(mockRes.status).toHaveBeenCalledWith(404);
  });

  it.each([
    // [label, req.query.path as Vercel delivers it, exact upstream URL]
    [
      'an alias key with a space and a comma',
      'locations/aliases/Austin, TX',
      'https://backend.test/api/admin/locations/aliases/Austin,%20TX',
    ],
    [
      'a unicode alias key',
      'locations/aliases/São Paulo',
      'https://backend.test/api/admin/locations/aliases/S%C3%A3o%20Paulo',
    ],
    [
      'a multi-segment unicode alias key',
      'locations/aliases/Zürich / Remote',
      'https://backend.test/api/admin/locations/aliases/Z%C3%BCrich%20/%20Remote',
    ],
    [
      'an array-form alias key',
      ['locations', 'aliases', 'München'],
      'https://backend.test/api/admin/locations/aliases/M%C3%BCnchen',
    ],
  ])('forwards %s with each segment percent-encoded by the proxy', async (_label, path, url) => {
    // The proxy encodes each validated segment itself rather than handing a raw
    // string to `fetch`'s URL parser, so the backend receives exactly the
    // segment that was validated. Compared as the EXACT string passed to
    // `fetch`, not the parsed pathname, so it proves the proxy did the encoding.
    const req = {
      method: 'PUT',
      query: { path },
      headers: { authorization: 'Bearer admin-token' },
      body: { locations: [] },
    } as unknown as VercelRequest;

    await handler(req, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(url);
    const resolved = new URL(fetchMock.mock.calls[0][0] as string);
    expect(resolved.pathname.startsWith('/api/admin/locations/aliases/')).toBe(true);
    // Round-trips to the key the admin typed — what the backend's
    // `{raw_text:path}` converter will hand the handler after Uvicorn decodes.
    const tail = decodeURIComponent(
      resolved.pathname.slice('/api/admin/locations/aliases/'.length)
    );
    expect(tail).toBe(
      (Array.isArray(path) ? path.join('/') : path).replace('locations/aliases/', '')
    );
  });

  it('forwards an alias whose raw text is "Internal" — data, not the internal router', async () => {
    // Only the router segment right after `/api` is refused as `internal`. An
    // alias key is data inside `/api/admin/locations/aliases/`, and 404ing it
    // would make a real location string impossible to normalize.
    const req = {
      method: 'PUT',
      query: { path: 'locations/aliases/Internal' },
      headers: { authorization: 'Bearer admin-token' },
      body: { locations: [] },
    } as unknown as VercelRequest;

    await handler(req, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(
      'https://backend.test/api/admin/locations/aliases/Internal'
    );
  });

  it.each([
    'locations/aliases/../../../internal/launch-radar/monitors',
    'locations/aliases/../../Internal/enrichment/pending',
    'locations/aliases/\u2025/\u2025/\u2025/internal/enrichment/pending',
    'locations/aliases/..;/..;/..;/internal/enrichment/pending',
    'locations/aliases/\uFF0E\uFF0E\uFF0F\uFF0E\uFF0E\uFF0F\uFF0E\uFF0E\uFF0Finternal',
  ])('still refuses a climb to the internal router: %s', async (pathValue) => {
    const req = {
      method: 'GET',
      query: { path: pathValue },
      headers: {},
      body: undefined,
    } as unknown as VercelRequest;

    await handler(req, mockRes as VercelResponse);

    expectNoKeyedUpstreamCall(fetchMock);
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
