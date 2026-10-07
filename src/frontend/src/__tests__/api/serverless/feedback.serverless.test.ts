import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/feedback';
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

describe('/api/feedback serverless function', () => {
  let mockReq: Partial<VercelRequest>;
  let mockRes: Partial<VercelResponse>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockReq = { method: 'POST', query: {}, headers: {}, body: { message: 'hi' } };
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

  it('proxies POST to the backend /api/feedback with the JSON body', async () => {
    fetchMock.mockResolvedValue(mockJsonResponse(201, { id: 'fb1' }));
    await handler(mockReq as VercelRequest, mockRes as VercelResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/feedback',
      expect.objectContaining({ method: 'POST', body: '{"message":"hi"}' })
    );
  });

  it('forwards the Authorization header when present', async () => {
    mockReq.headers = { authorization: 'Bearer tok-123' };
    fetchMock.mockResolvedValue(mockJsonResponse(201, { id: 'fb1' }));
    await handler(mockReq as VercelRequest, mockRes as VercelResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer tok-123' }),
      })
    );
  });

  it('forwards the client IP as X-Forwarded-For for backend rate limiting', async () => {
    mockReq.headers = { 'x-forwarded-for': '203.0.113.7' };
    fetchMock.mockResolvedValue(mockJsonResponse(201, { id: 'fb1' }));
    await handler(mockReq as VercelRequest, mockRes as VercelResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-Forwarded-For': '203.0.113.7' }),
      })
    );
  });

  it('falls back to x-real-ip when x-forwarded-for is absent', async () => {
    mockReq.headers = { 'x-real-ip': '198.51.100.4' };
    fetchMock.mockResolvedValue(mockJsonResponse(201, { id: 'fb1' }));
    await handler(mockReq as VercelRequest, mockRes as VercelResponse);
    const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = calledOptions.headers as Record<string, string>;
    expect(headers['X-Forwarded-For']).toBe('198.51.100.4');
  });

  it('omits X-Forwarded-For when no client IP header is present', async () => {
    mockReq.headers = {};
    fetchMock.mockResolvedValue(mockJsonResponse(201, { id: 'fb1' }));
    await handler(mockReq as VercelRequest, mockRes as VercelResponse);
    const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = calledOptions.headers as Record<string, string>;
    expect(headers).not.toHaveProperty('X-Forwarded-For');
  });

  it('omits Authorization when absent (anonymous feedback allowed)', async () => {
    mockReq.headers = {};
    fetchMock.mockResolvedValue(mockJsonResponse(201, { id: 'fb1' }));
    await handler(mockReq as VercelRequest, mockRes as VercelResponse);
    const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = calledOptions.headers as Record<string, string>;
    expect(headers).not.toHaveProperty('Authorization');
  });

  it('returns 502 when the upstream fetch throws', async () => {
    fetchMock.mockRejectedValue(new Error('connection refused'));
    await handler(mockReq as VercelRequest, mockRes as VercelResponse);
    expect(mockRes.status).toHaveBeenCalledWith(502);
  });

  it('never echoes the upstream error on a 502 — it carries the backend hostname', async () => {
    // A public, unauthenticated endpoint: anything in this body is handed to
    // whoever asks. Node's fetch errors name the internal host and port.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
    fetchMock.mockRejectedValue(
      new Error('getaddrinfo ENOTFOUND backend-prod.railway.internal:8080')
    );

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(mockRes.status).toHaveBeenCalledWith(502);
    expect(mockRes.json).toHaveBeenCalledWith({ error: 'Upstream backend unavailable' });
    expect(JSON.stringify((mockRes.json as ReturnType<typeof vi.fn>).mock.calls)).not.toContain(
      'railway.internal'
    );
    // Still logged server-side, so the failure stays debuggable.
    expect(consoleError).toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it('forwards a `#` inside a query value encoded, never as a fragment', async () => {
    // buildUpstreamUrl refuses a raw `#` in the query string; URLSearchParams
    // encodes one as %23, so a legitimate value must still forward.
    mockReq.query = { ref: 'issue#12' };
    fetchMock.mockResolvedValue(mockJsonResponse(201, { id: 'fb1' }));

    await handler(mockReq as VercelRequest, mockRes as VercelResponse);

    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/feedback?ref=issue%2312');
  });
});

/**
 * The allowlist that closed the production `?path=` traversal.
 *
 * This is the proxy the bypass was demonstrated against, and its legitimate
 * surface is a single bare POST — the backend `feedback` router declares
 * exactly one route and `features/feedback/feedbackApi.ts` spells its url as
 * the empty string. `/api/feedback/:path(.*)` existed in vercel.json as
 * boilerplate, never because a sub-path was needed.
 */
runProxyAllowlistGuard({
  name: 'feedback',
  prefix: '/api/feedback',
  handler,
  legitimate: [['', '/api/feedback']],
  normalizes: [['', ''], '/api/feedback'],
  methods: ['GET', 'POST'],
});
