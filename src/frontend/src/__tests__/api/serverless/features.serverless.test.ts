import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/features';
import { getBackendUrl } from '../../../../../../api/utils/backendUrl';

function mockJsonResponse(status: number, body: unknown) {
  const serialized = JSON.stringify(body);
  return {
    status,
    headers: { get: (key: string) => (key === 'content-type' ? 'application/json' : null) },
    text: async () => serialized,
    json: async () => body,
  };
}

function mockTextResponse(status: number, text: string, statusText = 'OK') {
  return {
    status,
    statusText,
    headers: { get: () => 'text/html' },
    text: async () => text,
  };
}

function mockJsonResponseWithBody(status: number, body: string, statusText = 'No Content') {
  return {
    status,
    statusText,
    headers: { get: (key: string) => (key === 'content-type' ? 'application/json' : null) },
    text: async () => body,
    json: async () => {
      if (!body) throw new SyntaxError('Unexpected end of JSON input');
      return JSON.parse(body);
    },
  };
}

describe('/api/features serverless function', () => {
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

  describe('Path Parsing', () => {
    it('should proxy to /api/features with no path segments', async () => {
      mockReq.query = {};
      fetchMock.mockResolvedValue(mockJsonResponse(200, { features: [] }));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/features',
        expect.any(Object)
      );
    });

    it('should handle single path segment', async () => {
      mockReq.query = { path: 'resume-match-ai' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/features/resume-match-ai',
        expect.any(Object)
      );
    });

    it('should handle multiple path segments as array', async () => {
      mockReq.query = { path: ['resume-match-ai', 'upvote'] };
      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/features/resume-match-ai/upvote',
        expect.any(Object)
      );
    });

    it('should forward query parameters', async () => {
      mockReq.query = { path: 'resume-match-ai', foo: 'bar' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      const calledUrl = fetchMock.mock.calls[0][0] as string;
      const url = new URL(calledUrl);
      expect(url.searchParams.get('foo')).toBe('bar');
    });

    it('should not append query string when no extra params exist', async () => {
      mockReq.query = { path: 'resume-match-ai' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/features/resume-match-ai',
        expect.any(Object)
      );
    });
  });

  describe('Authorization Header Forwarding', () => {
    it('should forward Authorization header when present', async () => {
      mockReq.query = {};
      mockReq.headers = { authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.test' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, { features: [] }));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(fetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.test',
          }),
        })
      );
    });

    it('should not include Authorization header when absent (anonymous GET allowed)', async () => {
      mockReq.query = {};
      mockReq.headers = {};
      fetchMock.mockResolvedValue(mockJsonResponse(200, { features: [] }));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      const headers = calledOptions.headers as Record<string, string>;
      expect(headers).not.toHaveProperty('Authorization');
    });

    it('should always include Accept and Content-Type headers', async () => {
      mockReq.query = {};
      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(fetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            Accept: 'application/json',
            'Content-Type': 'application/json',
          }),
        })
      );
    });
  });

  describe('Request Body Forwarding', () => {
    it('should forward JSON body for POST requests', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['resume-match-ai', 'upvote'] };
      mockReq.body = { note: 'test' };
      mockReq.headers = { authorization: 'Bearer token123' };
      fetchMock.mockResolvedValue(
        mockJsonResponse(200, { featureId: 'resume-match-ai', upvoteCount: 1, hasUpvoted: true })
      );
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.method).toBe('POST');
      expect(calledOptions.body).toBe('{"note":"test"}');
    });

    it('should forward string body for POST requests', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['resume-match-ai', 'upvote'] };
      mockReq.body = '{"note":"x"}';
      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.method).toBe('POST');
      expect(calledOptions.body).toBe('{"note":"x"}');
    });

    it('should not include body for GET requests', async () => {
      mockReq.method = 'GET';
      mockReq.query = {};
      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.body).toBeUndefined();
    });

    it('should not include body for DELETE requests (upvote removal has no body)', async () => {
      mockReq.method = 'DELETE';
      mockReq.query = { path: ['resume-match-ai', 'upvote'] };
      mockReq.headers = { authorization: 'Bearer token' };
      fetchMock.mockResolvedValue(
        mockJsonResponse(200, { featureId: 'resume-match-ai', upvoteCount: 0, hasUpvoted: false })
      );
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.method).toBe('DELETE');
      expect(calledOptions.body).toBeUndefined();
    });

    it('should not include body for POST with null body', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['resume-match-ai', 'upvote'] };
      mockReq.body = null;
      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.body).toBeUndefined();
    });
  });

  describe('Response Handling', () => {
    it('should forward 200 with features list', async () => {
      mockReq.query = {};
      const body = {
        features: [
          {
            id: 'resume-match-ai',
            title: 'AI resume matching notifications',
            description: 'Upload your resume…',
            createdAt: '2026-04-12T00:00:00Z',
            upvoteCount: 0,
            hasUpvoted: false,
          },
        ],
      };
      fetchMock.mockResolvedValue(mockJsonResponse(200, body));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(body);
    });

    it('should forward 401 when mutation is unauthenticated', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['resume-match-ai', 'upvote'] };
      fetchMock.mockResolvedValue(mockJsonResponse(401, { detail: 'Not authenticated' }));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(401);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Not authenticated' });
    });

    it('should forward 404 when feature_id is unknown (pass-through contract)', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['does-not-exist', 'upvote'] };
      mockReq.headers = { authorization: 'Bearer token' };
      fetchMock.mockResolvedValue(mockJsonResponse(404, { detail: 'Feature not found' }));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Feature not found' });
    });

    it('should forward 500 from backend', async () => {
      mockReq.query = {};
      fetchMock.mockResolvedValue(mockJsonResponse(500, { detail: 'Internal server error' }));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Internal server error' });
    });

    it('should handle non-JSON responses by forwarding as error', async () => {
      mockReq.query = {};
      fetchMock.mockResolvedValue(mockTextResponse(502, '<html>Bad Gateway</html>', 'Bad Gateway'));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(502);
      expect(mockRes.json).toHaveBeenCalledWith({ error: '<html>Bad Gateway</html>' });
    });

    it('should use statusText when non-JSON response body is empty', async () => {
      mockReq.query = {};
      fetchMock.mockResolvedValue(mockTextResponse(204, '', 'No Content'));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(204);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'No Content' });
    });
  });

  describe('Error Handling', () => {
    it('should return 502 with error details on network error', async () => {
      mockReq.query = {};
      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(502);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Upstream backend unavailable',
        details: 'ECONNREFUSED',
      });
      expect(errorSpy).toHaveBeenCalledWith(
        '[api/features] Upstream fetch failed:',
        expect.any(Error)
      );
      errorSpy.mockRestore();
    });

    it('should handle non-Error exceptions', async () => {
      mockReq.query = {};
      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
      fetchMock.mockRejectedValue('string error');
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(502);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Upstream backend unavailable',
        details: 'string error',
      });
      errorSpy.mockRestore();
    });

    it('should forward upstream status with no body when JSON response body is empty (e.g. 204)', async () => {
      mockReq.query = {};
      fetchMock.mockResolvedValue(mockJsonResponseWithBody(204, ''));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(204);
      expect(mockRes.end).toHaveBeenCalled();
      expect(mockRes.json).not.toHaveBeenCalled();
    });
  });

  describe('Backend URL Configuration', () => {
    it('should use BACKEND_API_URL env var when set (production host)', async () => {
      process.env.BACKEND_API_URL = 'https://api.production.railway.app';
      mockReq.query = {};
      mockReq.headers = { host: 'job-viz.vercel.app' };
      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.production.railway.app/api/features',
        expect.any(Object)
      );
    });

    it('should fall back to localhost:8000 when env var not set', async () => {
      delete process.env.BACKEND_API_URL;
      mockReq.query = {};
      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('http://localhost:8000/api/features'),
        expect.any(Object)
      );
    });
  });

  describe('getBackendUrl Host header detection', () => {
    it('should use localhost:8000 when host is localhost, even with BACKEND_API_URL set', () => {
      process.env.BACKEND_API_URL = 'https://api.production.railway.app';
      const req = { headers: { host: 'localhost:3000' } } as unknown as VercelRequest;
      expect(getBackendUrl(req)).toBe('http://localhost:8000');
    });

    it('should use BACKEND_API_URL when host is a production domain', () => {
      process.env.BACKEND_API_URL = 'https://api.production.railway.app';
      const req = { headers: { host: 'job-viz.vercel.app' } } as unknown as VercelRequest;
      expect(getBackendUrl(req)).toBe('https://api.production.railway.app');
    });
  });

  describe('Integration Scenarios', () => {
    it('should handle anonymous GET /api/features (no Authorization header)', async () => {
      mockReq.method = 'GET';
      mockReq.query = {};
      mockReq.headers = {};
      const body = {
        features: [
          {
            id: 'resume-match-ai',
            title: 'AI resume matching notifications',
            description: '...',
            createdAt: '2026-04-12T00:00:00Z',
            upvoteCount: 0,
            hasUpvoted: false,
          },
        ],
      };
      fetchMock.mockResolvedValue(mockJsonResponse(200, body));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/features',
        expect.objectContaining({
          method: 'GET',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
        })
      );
      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(body);
    });

    it('should handle authenticated POST /api/features/:id/upvote (forwards Authorization)', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['resume-match-ai', 'upvote'] };
      mockReq.headers = { authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.valid-token' };
      mockReq.body = undefined;
      const upvoteResponse = {
        featureId: 'resume-match-ai',
        upvoteCount: 1,
        hasUpvoted: true,
      };
      fetchMock.mockResolvedValue(mockJsonResponse(200, upvoteResponse));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/features/resume-match-ai/upvote',
        expect.objectContaining({
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            Authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.valid-token',
          },
        })
      );
      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(upvoteResponse);
    });

    it('should handle authenticated DELETE /api/features/:id/upvote (forwards Authorization, no body)', async () => {
      mockReq.method = 'DELETE';
      mockReq.query = { path: ['resume-match-ai', 'upvote'] };
      mockReq.headers = { authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.valid-token' };
      const removeResponse = {
        featureId: 'resume-match-ai',
        upvoteCount: 0,
        hasUpvoted: false,
      };
      fetchMock.mockResolvedValue(mockJsonResponse(200, removeResponse));
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/features/resume-match-ai/upvote',
        expect.objectContaining({
          method: 'DELETE',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            Authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.valid-token',
          },
        })
      );
      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.body).toBeUndefined();
      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(removeResponse);
    });
  });
});
