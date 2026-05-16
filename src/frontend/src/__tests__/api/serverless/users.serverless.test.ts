import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/users';
import { getBackendUrl } from '../../../../../../api/utils/backendUrl';

function mockJsonResponse(status: number, body: unknown) {
  const serialized = JSON.stringify(body);
  return {
    status,
    headers: { get: (key: string) => (key === 'content-type' ? 'application/json' : null) },
    // forwardResponse reads text first and JSON.parses, so provide both.
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

// Models a Response whose body-reading methods behave like a real empty body:
// `.json()` would throw on empty body (the bug before forwardResponse read
// text first), so we stub both and let forwardResponse pick the safe path.
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

describe('/api/users serverless function', () => {
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

  describe('Path Parsing', () => {
    it('should proxy to /api/users with no path segments', async () => {
      mockReq.query = {};

      fetchMock.mockResolvedValue(mockJsonResponse(200, { id: '1', email: 'test@example.com' }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/users',
        expect.any(Object)
      );
    });

    it('should handle single path segment', async () => {
      mockReq.query = { path: 'profile' };

      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/users/profile',
        expect.any(Object)
      );
    });

    it('should handle multiple path segments as array', async () => {
      mockReq.query = { path: ['settings', 'notifications'] };

      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/users/settings/notifications',
        expect.any(Object)
      );
    });

    it('should forward query parameters', async () => {
      mockReq.query = { path: 'search', q: 'test', limit: '10' };

      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('http://localhost:8000/api/users/search?'),
        expect.any(Object)
      );
      const calledUrl = fetchMock.mock.calls[0][0] as string;
      const url = new URL(calledUrl);
      expect(url.searchParams.get('q')).toBe('test');
      expect(url.searchParams.get('limit')).toBe('10');
    });

    it('should not append query string when no extra params exist', async () => {
      mockReq.query = { path: 'me' };

      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/users/me',
        expect.any(Object)
      );
    });
  });

  describe('Authorization Header Forwarding', () => {
    it('should forward Authorization header when present', async () => {
      mockReq.query = {};
      mockReq.headers = { authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.test' };

      fetchMock.mockResolvedValue(mockJsonResponse(200, { id: '1' }));

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

    it('should not include Authorization header when absent', async () => {
      mockReq.query = {};
      mockReq.headers = {};

      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));

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
    it('should forward JSON body for PUT requests', async () => {
      mockReq.method = 'PUT';
      mockReq.query = {};
      mockReq.body = { displayName: 'New Name' };
      mockReq.headers = { authorization: 'Bearer token123' };

      fetchMock.mockResolvedValue(mockJsonResponse(200, { displayName: 'New Name' }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.method).toBe('PUT');
      expect(calledOptions.body).toBe('{"displayName":"New Name"}');
    });

    it('should forward string body for POST requests', async () => {
      mockReq.method = 'POST';
      mockReq.query = {};
      mockReq.body = '{"email":"test@example.com"}';

      fetchMock.mockResolvedValue(mockJsonResponse(201, { id: '1' }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.method).toBe('POST');
      expect(calledOptions.body).toBe('{"email":"test@example.com"}');
    });

    it('should not include body for GET requests', async () => {
      mockReq.method = 'GET';
      mockReq.query = {};

      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.body).toBeUndefined();
    });

    it('should not include body for PUT with null body', async () => {
      mockReq.method = 'PUT';
      mockReq.query = {};
      mockReq.body = null;

      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.body).toBeUndefined();
    });
  });

  describe('Response Handling', () => {
    it('should forward 200 with user data', async () => {
      mockReq.query = {};
      mockReq.headers = { authorization: 'Bearer token' };

      const userData = {
        id: 'abc123',
        email: 'user@example.com',
        displayName: 'Test User',
        givenName: 'Test',
        familyName: 'User',
      };

      fetchMock.mockResolvedValue(mockJsonResponse(200, userData));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(userData);
    });

    it('should forward 401 when not authenticated', async () => {
      mockReq.query = {};

      fetchMock.mockResolvedValue(mockJsonResponse(401, { detail: 'Not authenticated' }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(401);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Not authenticated' });
    });

    it('should forward 404 when user not found', async () => {
      mockReq.query = {};
      mockReq.headers = { authorization: 'Bearer token' };

      fetchMock.mockResolvedValue(mockJsonResponse(404, { detail: 'User not found' }));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'User not found' });
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
        '[api/users] Upstream fetch failed:',
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
        'https://api.production.railway.app/api/users',
        expect.any(Object)
      );
    });

    it('should fall back to localhost:8000 when env var not set', async () => {
      delete process.env.BACKEND_API_URL;
      mockReq.query = {};

      fetchMock.mockResolvedValue(mockJsonResponse(200, {}));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('http://localhost:8000/api/users'),
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

    it('should use localhost:8000 when host is 127.0.0.1', () => {
      process.env.BACKEND_API_URL = 'https://api.production.railway.app';
      const req = { headers: { host: '127.0.0.1:3000' } } as unknown as VercelRequest;

      expect(getBackendUrl(req)).toBe('http://localhost:8000');
    });

    it('should use localhost:8000 when host is IPv6 loopback [::1]', () => {
      process.env.BACKEND_API_URL = 'https://api.production.railway.app';
      const req = { headers: { host: '[::1]:3000' } } as unknown as VercelRequest;

      expect(getBackendUrl(req)).toBe('http://localhost:8000');
    });

    it('should use BACKEND_API_URL when host is a production domain', () => {
      process.env.BACKEND_API_URL = 'https://api.production.railway.app';
      const req = { headers: { host: 'job-viz.vercel.app' } } as unknown as VercelRequest;

      expect(getBackendUrl(req)).toBe('https://api.production.railway.app');
    });

    it('should fall back to localhost:8000 when host is missing and no env var', () => {
      delete process.env.BACKEND_API_URL;
      const req = { headers: {} } as unknown as VercelRequest;

      expect(getBackendUrl(req)).toBe('http://localhost:8000');
    });

    it('should NOT treat localhost.evil.com as localhost', () => {
      // Regression: previously used host.startsWith('localhost') which matched
      // localhost.evil.com. Now requires exact hostname match.
      process.env.BACKEND_API_URL = 'https://api.production.railway.app';
      const req = {
        headers: { host: 'localhost.evil.com:443' },
      } as unknown as VercelRequest;

      expect(getBackendUrl(req)).toBe('https://api.production.railway.app');
    });
  });

  describe('Integration Scenarios', () => {
    it('should handle authenticated GET /api/users (get-or-create user)', async () => {
      mockReq.method = 'GET';
      mockReq.query = {};
      mockReq.headers = { authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.valid-token' };

      const userResponse = {
        id: 'abc-123',
        providerSubject: 'google-oauth2|12345',
        email: 'user@gmail.com',
        displayName: null,
        givenName: 'Test',
        familyName: 'User',
        pictureUrl: 'https://lh3.googleusercontent.com/photo.jpg',
        createdAt: '2026-04-12T00:00:00Z',
        updatedAt: '2026-04-12T00:00:00Z',
        isAdmin: false,
      };

      fetchMock.mockResolvedValue(mockJsonResponse(200, userResponse));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/users',
        expect.objectContaining({
          method: 'GET',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            Authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.valid-token',
          },
        })
      );
      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(userResponse);
    });

    it('should handle authenticated PUT /api/users (update display name)', async () => {
      mockReq.method = 'PUT';
      mockReq.query = {};
      mockReq.headers = { authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.valid-token' };
      mockReq.body = { displayName: 'New Display Name' };

      const updatedUser = {
        id: 'abc-123',
        displayName: 'New Display Name',
        email: 'user@gmail.com',
      };

      fetchMock.mockResolvedValue(mockJsonResponse(200, updatedUser));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/users',
        expect.objectContaining({
          method: 'PUT',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            Authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.valid-token',
          },
          body: '{"displayName":"New Display Name"}',
        })
      );
      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(updatedUser);
    });
  });
});
