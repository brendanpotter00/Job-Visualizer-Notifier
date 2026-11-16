import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/billing';
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

describe('/api/billing serverless function', () => {
  let mockRes: Partial<VercelResponse>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockRes = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn().mockReturnThis(),
      end: vi.fn().mockReturnThis(),
      setHeader: vi.fn().mockReturnThis(),
    };
    fetchMock = vi.fn().mockResolvedValue(mockJsonResponse(200, { url: 'https://stripe.test' }));
    global.fetch = fetchMock as unknown as typeof fetch;
    delete process.env.BACKEND_API_URL;
  });

  afterEach(() => {
    delete process.env.INTERNAL_API_KEY;
    vi.clearAllMocks();
  });

  const req = (overrides: Partial<VercelRequest>): VercelRequest =>
    ({ method: 'GET', query: {}, headers: {}, body: undefined, ...overrides }) as VercelRequest;

  it('forwards the Authorization header and the internal key', async () => {
    process.env.INTERNAL_API_KEY = 'k';
    await handler(
      req({
        method: 'POST',
        query: { path: 'checkout-session' },
        headers: { authorization: 'Bearer t' },
      }),
      mockRes as VercelResponse
    );
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://localhost:8000/api/billing/checkout-session');
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer t');
    expect(headers['X-Internal-Key']).toBe('k');
    expect(init.method).toBe('POST');
    expect(init.redirect).toBe('manual');
  });

  it('never proxies the Stripe webhook (signature needs the raw body)', async () => {
    await handler(req({ method: 'POST', query: { path: 'webhook' } }), mockRes as VercelResponse);
    expect(mockRes.status).toHaveBeenCalledWith(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('502s when the backend is unreachable', async () => {
    fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
    await handler(req({ query: { path: 'subscription' } }), mockRes as VercelResponse);
    expect(mockRes.status).toHaveBeenCalledWith(502);
  });
});

runProxyAllowlistGuard({
  name: 'billing',
  prefix: '/api/billing',
  handler,
  legitimate: [
    ['subscription', '/api/billing/subscription'],
    ['checkout-session', '/api/billing/checkout-session'],
    ['portal-session', '/api/billing/portal-session'],
  ],
  normalizes: ['/subscription/', '/api/billing/subscription'],
  methods: ['GET', 'POST'],
});
