import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import jobsHandler from '../../../../../../api/jobs';
import locationsHandler from '../../../../../../api/locations';
import { runProxyAllowlistGuard } from './proxyAllowlistGuard';

function mockJsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  const serialized = JSON.stringify(body);
  const lower = Object.fromEntries(
    Object.entries({ 'content-type': 'application/json', ...headers }).map(([k, v]) => [
      k.toLowerCase(),
      v,
    ])
  );
  return {
    status,
    headers: { get: (key: string) => lower[key.toLowerCase()] ?? null },
    text: async () => serialized,
    json: async () => body,
  };
}

/**
 * `api/jobs.ts` and `api/locations.ts` were already allowlisted — a single
 * literal comparison, which cannot be traversed. They moved onto the shared
 * `resolveProxyPath` for two reasons, both recorded here:
 *
 *   1. One implementation of the control instead of eight. Divergence is how
 *      the same `?path=` hole ended up live on five sibling proxies while
 *      these two were fine.
 *   2. Their inline check did NOT normalize, so `?path=facets/` and the array
 *      form `?path=facets&path=` 404'd a legitimate caller. Failing closed, so
 *      never a vulnerability — just wrong.
 *
 * The behaviour that must NOT change is the rest of each handler: `api/jobs.ts`
 * explicitly re-emits `X-Next-Cursor` (keyset pagination dies silently without
 * it) and allow-lists its query params, and `api/locations.ts` forwards
 * `q`/`limit`/`openOnly`.
 */
describe('/api/jobs serverless function — behaviour that must not regress', () => {
  let mockRes: Partial<VercelResponse>;
  let fetchMock: ReturnType<typeof vi.fn>;

  const makeReq = (query: Record<string, unknown>): VercelRequest =>
    ({ method: 'GET', query, headers: {}, body: undefined }) as VercelRequest;

  beforeEach(() => {
    mockRes = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn().mockReturnThis(),
      end: vi.fn().mockReturnThis(),
      setHeader: vi.fn().mockReturnThis(),
    };
    fetchMock = vi.fn().mockResolvedValue(mockJsonResponse(200, []));
    global.fetch = fetchMock as unknown as typeof fetch;
    process.env.BACKEND_API_URL = 'https://backend.test';
  });

  afterEach(() => {
    delete process.env.BACKEND_API_URL;
    vi.clearAllMocks();
  });

  it('re-emits X-Next-Cursor when the upstream sets it', async () => {
    // `forwardResponse` copies status + body only. Without this the SPA sees no
    // next-page token and the keyset walk stops after page 1, looking exactly
    // like a legitimate end of results.
    fetchMock.mockResolvedValue(mockJsonResponse(200, [], { 'x-next-cursor': 'opaque-token' }));

    await jobsHandler(makeReq({ since: '2026-01-01', cursor: '' }), mockRes as VercelResponse);

    expect(mockRes.setHeader).toHaveBeenCalledWith('X-Next-Cursor', 'opaque-token');
  });

  it('omits X-Next-Cursor when the upstream does not set it (end of results)', async () => {
    await jobsHandler(makeReq({ since: '2026-01-01' }), mockRes as VercelResponse);

    expect(mockRes.setHeader).not.toHaveBeenCalled();
  });

  it('forwards `cursor` on presence, not truthiness', async () => {
    // `?cursor=` empty is a client bug the backend answers with a 422. Dropping
    // it here would hand back page 1 with a 200 instead — a silent restart of
    // the caller's paging loop.
    await jobsHandler(makeReq({ cursor: '' }), mockRes as VercelResponse);

    expect(new URL(fetchMock.mock.calls[0][0] as string).searchParams.has('cursor')).toBe(true);
  });

  it('still allow-lists query params — an unlisted one is dropped', async () => {
    await jobsHandler(
      makeReq({ company: 'openai', limit: '5', enrichment_status: 'claimed' }),
      mockRes as VercelResponse
    );

    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.searchParams.get('company')).toBe('openai');
    expect(url.searchParams.get('limit')).toBe('5');
    expect(url.searchParams.has('enrichment_status')).toBe(false);
  });

  it('normalizes a trailing slash on facets instead of 404ing it', async () => {
    // Regression: the old inline check compared the raw capture, so `facets/`
    // was refused even though it is the same route.
    await jobsHandler(makeReq({ path: 'facets/' }), mockRes as VercelResponse);

    expect(fetchMock.mock.calls[0][0]).toBe('https://backend.test/api/jobs/facets');
  });
});

describe('/api/locations serverless function — behaviour that must not regress', () => {
  let mockRes: Partial<VercelResponse>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockRes = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn().mockReturnThis(),
      end: vi.fn().mockReturnThis(),
    };
    fetchMock = vi.fn().mockResolvedValue(mockJsonResponse(200, []));
    global.fetch = fetchMock as unknown as typeof fetch;
    process.env.BACKEND_API_URL = 'https://backend.test';
  });

  afterEach(() => {
    delete process.env.BACKEND_API_URL;
    vi.clearAllMocks();
  });

  it('forwards q / limit / openOnly', async () => {
    await locationsHandler(
      {
        method: 'GET',
        query: { path: 'search', q: 'sea', limit: '10', openOnly: 'true' },
        headers: {},
      } as unknown as VercelRequest,
      mockRes as VercelResponse
    );

    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.pathname).toBe('/api/locations/search');
    expect(url.searchParams.get('q')).toBe('sea');
    expect(url.searchParams.get('limit')).toBe('10');
    expect(url.searchParams.get('openOnly')).toBe('true');
  });

  it('404s the bare prefix — the backend has no route there', async () => {
    await locationsHandler(
      { method: 'GET', query: {}, headers: {} } as unknown as VercelRequest,
      mockRes as VercelResponse
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(mockRes.status).toHaveBeenCalledWith(404);
  });
});

runProxyAllowlistGuard({
  name: 'jobs',
  prefix: '/api/jobs',
  handler: jobsHandler,
  legitimate: [
    ['', '/api/jobs'],
    ['facets', '/api/jobs/facets'],
  ],
  normalizes: [['facets', ''], '/api/jobs/facets'],
  // GET only: `api/jobs.ts` never forwards a body or a method, so every other
  // verb reaches the backend as a GET. The guard still proves a POST body on a
  // traversal path is refused.
  methods: ['GET'],
});

runProxyAllowlistGuard({
  name: 'locations',
  prefix: '/api/locations',
  handler: locationsHandler,
  legitimate: [['search', '/api/locations/search']],
  normalizes: ['/search/', '/api/locations/search'],
  methods: ['GET'],
});
