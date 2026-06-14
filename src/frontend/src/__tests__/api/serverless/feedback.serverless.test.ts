import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/feedback';

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
});
