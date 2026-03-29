import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/auth';

describe('/api/auth serverless function', () => {
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
  });

  describe('CORS Preflight', () => {
    it('should return 200 for OPTIONS requests without proxying', async () => {
      mockReq.method = 'OPTIONS';

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.end).toHaveBeenCalled();
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  describe('Path Parsing', () => {
    it('should handle single path segment (google)', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: 'google' };
      mockReq.body = { credential: 'test-token' };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ token: 'jwt', user: {} }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/auth/google',
        expect.objectContaining({ method: 'POST' })
      );
    });

    it('should handle path as array', async () => {
      mockReq.query = { path: ['me'] };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ id: 1 }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/auth/me',
        expect.any(Object)
      );
    });

    it('should handle empty path', async () => {
      mockReq.query = {};

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/auth/',
        expect.any(Object)
      );
    });

    it('should forward extra query parameters', async () => {
      mockReq.query = { path: 'me', foo: 'bar' };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/auth/me?foo=bar',
        expect.any(Object)
      );
    });
  });

  describe('Authorization Header Forwarding', () => {
    it('should forward Authorization header when present', async () => {
      mockReq.query = { path: 'me' };
      mockReq.headers = { authorization: 'Bearer test-jwt-token' };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ id: 1, name: 'Test User' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: 'Bearer test-jwt-token',
          }),
        })
      );
    });

    it('should not include Authorization header when absent', async () => {
      mockReq.query = { path: 'me' };
      mockReq.headers = {};

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const callHeaders = fetchMock.mock.calls[0][1].headers;
      expect(callHeaders).not.toHaveProperty('Authorization');
    });
  });

  describe('POST Body Forwarding', () => {
    it('should forward JSON body for POST requests', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: 'google' };
      mockReq.body = { credential: 'google-id-token-abc123' };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ token: 'jwt', user: {} }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ credential: 'google-id-token-abc123' }),
        })
      );
    });

    it('should not include body for GET requests', async () => {
      mockReq.method = 'GET';
      mockReq.query = { path: 'me' };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const fetchOptions = fetchMock.mock.calls[0][1];
      expect(fetchOptions.body).toBeUndefined();
    });

    it('should not include body for POST with no body', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: 'google' };
      mockReq.body = undefined;

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const fetchOptions = fetchMock.mock.calls[0][1];
      expect(fetchOptions.body).toBeUndefined();
    });
  });

  describe('Response Forwarding', () => {
    it('should forward 200 with user data', async () => {
      mockReq.query = { path: 'me' };
      mockReq.headers = { authorization: 'Bearer valid-token' };

      const userData = { id: 1, name: 'Test User', email: 'test@example.com' };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => userData,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(userData);
    });

    it('should forward 401 for unauthenticated requests', async () => {
      mockReq.query = { path: 'me' };

      fetchMock.mockResolvedValue({
        status: 401,
        json: async () => ({ detail: 'Not authenticated' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(401);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Not authenticated' });
    });

    it('should forward 422 for invalid request body', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: 'google' };
      mockReq.body = {};

      fetchMock.mockResolvedValue({
        status: 422,
        json: async () => ({ detail: 'Validation error' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(422);
    });

    it('should forward 500 from backend', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: 'google' };
      mockReq.body = { credential: 'token' };

      fetchMock.mockResolvedValue({
        status: 500,
        json: async () => ({ detail: 'Google OAuth not configured' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Google OAuth not configured' });
    });
  });

  describe('Error Handling', () => {
    it('should return 500 on network error', async () => {
      mockReq.query = { path: 'me' };

      fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Failed to fetch from backend',
        details: 'ECONNREFUSED',
      });
    });

    it('should handle non-Error exceptions', async () => {
      mockReq.query = { path: 'me' };

      fetchMock.mockRejectedValue('unexpected string error');

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Failed to fetch from backend',
        details: 'unexpected string error',
      });
    });

    it('should handle JSON parse errors from backend', async () => {
      mockReq.query = { path: 'me' };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => {
          throw new Error('Unexpected token');
        },
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Failed to fetch from backend',
        details: 'Unexpected token',
      });
    });
  });

  describe('Integration Scenarios', () => {
    it('should handle full Google login flow', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: 'google' };
      mockReq.body = { credential: 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test' };

      const authResponse = {
        token: 'jwt-token-abc',
        user: {
          id: 1,
          email: 'user@gmail.com',
          name: 'Test User',
          picture: 'https://lh3.googleusercontent.com/photo',
          isAdmin: false,
        },
      };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => authResponse,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/auth/google',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
          }),
          body: JSON.stringify({
            credential: 'eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test',
          }),
        })
      );
      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(authResponse);
    });

    it('should handle full GET /me flow with valid JWT', async () => {
      mockReq.method = 'GET';
      mockReq.query = { path: 'me' };
      mockReq.headers = { authorization: 'Bearer valid-jwt-token' };

      const userResponse = {
        id: 1,
        email: 'user@gmail.com',
        name: 'Test User',
        picture: 'https://lh3.googleusercontent.com/photo',
        isAdmin: false,
      };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => userResponse,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/auth/me',
        expect.objectContaining({
          method: 'GET',
          headers: expect.objectContaining({
            Authorization: 'Bearer valid-jwt-token',
          }),
        })
      );
      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(userResponse);
    });
  });
});
