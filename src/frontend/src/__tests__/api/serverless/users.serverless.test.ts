import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/users';

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
    };

    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    delete process.env.BACKEND_API_URL;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('Path Parsing', () => {
    it('should proxy to /api/users/ with no path segments', async () => {
      mockReq.query = {};

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ id: '1', email: 'test@example.com' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/users/',
        expect.any(Object)
      );
    });

    it('should handle single path segment', async () => {
      mockReq.query = { path: 'profile' };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/users/profile',
        expect.any(Object)
      );
    });

    it('should handle multiple path segments as array', async () => {
      mockReq.query = { path: ['settings', 'notifications'] };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/users/settings/notifications',
        expect.any(Object)
      );
    });

    it('should forward query parameters', async () => {
      mockReq.query = { path: 'search', q: 'test', limit: '10' };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

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

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

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

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ id: '1' }),
      });

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

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      const headers = calledOptions.headers as Record<string, string>;
      expect(headers).not.toHaveProperty('Authorization');
    });

    it('should always include Accept and Content-Type headers', async () => {
      mockReq.query = {};

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

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

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ displayName: 'New Name' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.method).toBe('PUT');
      expect(calledOptions.body).toBe('{"displayName":"New Name"}');
    });

    it('should forward string body for POST requests', async () => {
      mockReq.method = 'POST';
      mockReq.query = {};
      mockReq.body = '{"email":"test@example.com"}';

      fetchMock.mockResolvedValue({
        status: 201,
        json: async () => ({ id: '1' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.method).toBe('POST');
      expect(calledOptions.body).toBe('{"email":"test@example.com"}');
    });

    it('should not include body for GET requests', async () => {
      mockReq.method = 'GET';
      mockReq.query = {};

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const calledOptions = fetchMock.mock.calls[0][1] as RequestInit;
      expect(calledOptions.body).toBeUndefined();
    });

    it('should not include body for PUT with null body', async () => {
      mockReq.method = 'PUT';
      mockReq.query = {};
      mockReq.body = null;

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

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

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => userData,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(userData);
    });

    it('should forward 401 when not authenticated', async () => {
      mockReq.query = {};

      fetchMock.mockResolvedValue({
        status: 401,
        json: async () => ({ detail: 'Not authenticated' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(401);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Not authenticated' });
    });

    it('should forward 404 when user not found', async () => {
      mockReq.query = {};
      mockReq.headers = { authorization: 'Bearer token' };

      fetchMock.mockResolvedValue({
        status: 404,
        json: async () => ({ detail: 'User not found' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'User not found' });
    });

    it('should forward 500 from backend', async () => {
      mockReq.query = {};

      fetchMock.mockResolvedValue({
        status: 500,
        json: async () => ({ detail: 'Internal server error' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({ detail: 'Internal server error' });
    });
  });

  describe('Error Handling', () => {
    it('should return 500 with error details on network error', async () => {
      mockReq.query = {};

      fetchMock.mockRejectedValue(new Error('ECONNREFUSED'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Failed to fetch from backend',
        details: 'ECONNREFUSED',
      });
    });

    it('should handle JSON parse errors', async () => {
      mockReq.query = {};

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

    it('should handle non-Error exceptions', async () => {
      mockReq.query = {};

      fetchMock.mockRejectedValue('string error');

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Failed to fetch from backend',
        details: 'string error',
      });
    });
  });

  describe('Backend URL Configuration', () => {
    it('should use BACKEND_API_URL env var when set', async () => {
      process.env.BACKEND_API_URL = 'https://api.production.railway.app';
      mockReq.query = {};

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('https://api.production.railway.app/api/users/'),
        expect.any(Object)
      );
    });

    it('should fall back to localhost:8000 when env var not set', async () => {
      delete process.env.BACKEND_API_URL;
      mockReq.query = {};

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('http://localhost:8000/api/users/'),
        expect.any(Object)
      );
    });
  });

  describe('Integration Scenarios', () => {
    it('should handle authenticated GET /api/users (get-or-create user)', async () => {
      mockReq.method = 'GET';
      mockReq.query = {};
      mockReq.headers = { authorization: 'Bearer eyJhbGciOiJSUzI1NiJ9.valid-token' };

      const userResponse = {
        id: 'abc-123',
        auth0Id: 'google-oauth2|12345',
        email: 'user@gmail.com',
        displayName: null,
        givenName: 'Test',
        familyName: 'User',
        pictureUrl: 'https://lh3.googleusercontent.com/photo.jpg',
        createdAt: '2026-04-12T00:00:00Z',
        updatedAt: '2026-04-12T00:00:00Z',
      };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => userResponse,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/users/',
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

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => updatedUser,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/users/',
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
