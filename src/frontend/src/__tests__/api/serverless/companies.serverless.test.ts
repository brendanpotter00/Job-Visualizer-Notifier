import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/companies';
import { runProxyAllowlistGuard } from './proxyAllowlistGuard';

function mockJsonResponse(status: number, body: unknown) {
  const serialized = JSON.stringify(body);
  return {
    status,
    headers: { get: (key: string) => (key === 'content-type' ? 'application/json' : null) },
    text: async () => serialized,
    json: async () => body,
  };
}

describe('/api/companies serverless function', () => {
  let mockReq: Partial<VercelRequest>;
  let mockRes: Partial<VercelResponse>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockReq = { method: 'GET', query: {}, headers: {}, body: undefined };
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

  it('proxies the bare curated-companies directory', async () => {
    fetchMock.mockResolvedValue(mockJsonResponse(200, { companies: [] }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/companies',
      expect.any(Object)
    );
    expect(mockRes.status).toHaveBeenCalledWith(200);
  });

  it('proxies POST /resolve with its body', async () => {
    mockReq.method = 'POST';
    mockReq.query = { path: 'resolve' };
    mockReq.body = { url: 'https://example.com/careers' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, { finalUrl: 'https://example.com/careers' }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/companies/resolve');
    const opts = fetchMock.mock.calls[0][1] as RequestInit;
    expect(opts.method).toBe('POST');
    expect(opts.body).toBe(JSON.stringify({ url: 'https://example.com/careers' }));
  });

  it('forwards extra query params', async () => {
    mockReq.query = { limit: '25' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, { companies: [] }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    const url = new URL(fetchMock.mock.calls[0][0] as string);
    expect(url.searchParams.get('limit')).toBe('25');
  });

  it('forwards the Authorization header when present, and omits it otherwise', async () => {
    // The backend route takes no auth; the passthrough exists so a signed-in
    // caller is not treated differently, and must stay optional.
    mockReq.headers = { authorization: 'Bearer token123' };
    fetchMock.mockResolvedValue(mockJsonResponse(200, { companies: [] }));
    await handler(mockReq as VercelRequest, mockRes as VercelResponse);
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers).toMatchObject({
      Authorization: 'Bearer token123',
    });

    vi.clearAllMocks();
    mockReq.headers = {};
    fetchMock.mockResolvedValue(mockJsonResponse(200, { companies: [] }));
    await handler(mockReq as VercelRequest, mockRes as VercelResponse);
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers).not.toHaveProperty('Authorization');
  });

  it('returns 502 when the upstream fetch throws', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(mockRes.status).toHaveBeenCalledWith(502);
  });

  it('forwards the backend status and body unchanged', async () => {
    fetchMock.mockResolvedValue(mockJsonResponse(503, { detail: 'Feature disabled' }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(mockRes.status).toHaveBeenCalledWith(503);
    expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Feature disabled' });
  });
});

/**
 * The allowlist that closed the production `?path=` traversal.
 *
 * The backend `companies` router declares exactly two routes and the frontend
 * uses both: `features/companies/companiesApi.ts` reads the bare directory, and
 * `features/userCompanies/userCompaniesApi.ts` posts to `resolve` (it bases
 * itself at `/api` and spells the url `companies/resolve`).
 */
runProxyAllowlistGuard({
  name: 'companies',
  prefix: '/api/companies',
  handler,
  legitimate: [
    ['', '/api/companies'],
    ['resolve', '/api/companies/resolve'],
  ],
  normalizes: ['/resolve/', '/api/companies/resolve'],
  methods: ['GET', 'POST'],
});
