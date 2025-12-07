import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/lever';

describe('/api/lever serverless function', () => {
  let mockReq: Partial<VercelRequest>;
  let mockRes: Partial<VercelResponse>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Reset mocks before each test
    mockReq = {
      method: 'GET',
      query: {},
      headers: {},
      url: '',
    };

    mockRes = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn().mockReturnThis(),
      setHeader: vi.fn().mockReturnThis(),
      end: vi.fn().mockReturnThis(),
    };

    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  describe('Path Parsing', () => {
    it('should handle single path segment', async () => {
      mockReq.query = { path: 'v0' };
      mockReq.url = '/api/lever/v0';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => [],
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.lever.co/v0',
        expect.objectContaining({
          method: 'GET',
          headers: {
            Accept: 'application/json',
            'User-Agent': 'Job-Visualizer-Notifier/1.0',
          },
        })
      );
    });

    it('should handle multiple path segments (company postings)', async () => {
      mockReq.query = { path: ['v0', 'postings', 'netflix'] };
      mockReq.url = '/api/lever/v0/postings/netflix';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => [],
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.lever.co/v0/postings/netflix',
        expect.any(Object)
      );
    });

    it('should handle path as array', async () => {
      mockReq.query = { path: ['v0', 'postings', 'uber'] };
      mockReq.url = '/api/lever/v0/postings/uber';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => [],
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.lever.co/v0/postings/uber',
        expect.any(Object)
      );
    });

    it('should handle path as string', async () => {
      mockReq.query = { path: 'v0/postings/lyft' };
      mockReq.url = '/api/lever/v0/postings/lyft';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => [],
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.lever.co/v0/postings/lyft',
        expect.any(Object)
      );
    });

    it('should handle path array with empty strings (double slashes)', async () => {
      mockReq.query = { path: ['v0', '', 'postings', '', 'reddit', ''] };
      mockReq.url = '/api/lever/v0//postings//reddit/';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => [],
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      // Note: Current implementation doesn't filter empty strings from path arrays
      // This results in double slashes but still works (APIs typically normalize these)
      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.lever.co/v0//postings//reddit/',
        expect.any(Object)
      );
    });

    it('should preserve query parameters from original URL', async () => {
      mockReq.query = { path: ['v0', 'postings', 'airbnb'] };
      mockReq.url = '/api/lever/v0/postings/airbnb?mode=json&skip=0&limit=100';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => [],
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.lever.co/v0/postings/airbnb?mode=json&skip=0&limit=100',
        expect.any(Object)
      );
    });

    it('should handle URL without query parameters', async () => {
      mockReq.query = { path: ['v0', 'postings', 'shopify'] };
      mockReq.url = '/api/lever/v0/postings/shopify';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => [],
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.lever.co/v0/postings/shopify',
        expect.any(Object)
      );
    });
  });

  describe('Request Forwarding', () => {
    it('should forward GET requests with correct headers', async () => {
      mockReq.method = 'GET';
      mockReq.query = { path: ['v0', 'postings', 'spotify'] };
      mockReq.url = '/api/lever/v0/postings/spotify';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => [],
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.lever.co/v0/postings/spotify',
        expect.objectContaining({
          method: 'GET',
          headers: {
            Accept: 'application/json',
            'User-Agent': 'Job-Visualizer-Notifier/1.0',
          },
        })
      );
    });

    it('should use the request method from req.method', async () => {
      mockReq.method = 'OPTIONS';
      mockReq.query = { path: ['v0', 'postings', 'slack'] };
      mockReq.url = '/api/lever/v0/postings/slack';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => [],
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          method: 'OPTIONS',
        })
      );
    });
  });

  describe('Response Handling', () => {
    it('should return 200 with job data on success', async () => {
      mockReq.query = { path: ['v0', 'postings', 'pinterest'] };
      mockReq.url = '/api/lever/v0/postings/pinterest';

      const mockJobData = [
        {
          id: 'abc-123',
          text: 'Software Engineer',
          categories: { team: 'Engineering' },
        },
        {
          id: 'def-456',
          text: 'Product Manager',
          categories: { team: 'Product' },
        },
      ];

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => mockJobData,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(mockJobData);
    });

    it('should set CORS headers on successful response', async () => {
      mockReq.query = { path: ['v0', 'postings', 'twitch'] };
      mockReq.url = '/api/lever/v0/postings/twitch';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => [],
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Origin', '*');
      expect(mockRes.setHeader).toHaveBeenCalledWith(
        'Access-Control-Allow-Methods',
        'GET, OPTIONS'
      );
      expect(mockRes.setHeader).toHaveBeenCalledWith(
        'Access-Control-Allow-Headers',
        'Content-Type'
      );
    });

    it('should forward 404 status from Lever API', async () => {
      mockReq.query = { path: ['v0', 'postings', 'nonexistent'] };
      mockReq.url = '/api/lever/v0/postings/nonexistent';

      fetchMock.mockResolvedValue({
        status: 404,
        json: async () => ({ error: 'Company not found' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Company not found' });
    });

    it('should forward 500 status from Lever API', async () => {
      mockReq.query = { path: ['v0', 'postings', 'error'] };
      mockReq.url = '/api/lever/v0/postings/error';

      fetchMock.mockResolvedValue({
        status: 500,
        json: async () => ({ error: 'Internal server error' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Internal server error' });
    });

    it('should forward 401 status from Lever API', async () => {
      mockReq.query = { path: ['v0', 'postings', 'private'] };
      mockReq.url = '/api/lever/v0/postings/private';

      fetchMock.mockResolvedValue({
        status: 401,
        json: async () => ({ error: 'Unauthorized' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(401);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Unauthorized' });
    });

    it('should handle empty response data', async () => {
      mockReq.query = { path: ['v0', 'postings', 'empty'] };
      mockReq.url = '/api/lever/v0/postings/empty';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => [],
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith([]);
    });
  });

  describe('Error Handling', () => {
    it('should return 500 with error message on network error', async () => {
      mockReq.query = { path: ['v0', 'postings', 'network-error'] };
      mockReq.url = '/api/lever/v0/postings/network-error';

      fetchMock.mockRejectedValue(new Error('Network error'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Network error',
      });
    });

    it('should set CORS headers even on error', async () => {
      mockReq.query = { path: ['v0', 'postings', 'cors-error'] };
      mockReq.url = '/api/lever/v0/postings/cors-error';

      fetchMock.mockRejectedValue(new Error('CORS error'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Origin', '*');
    });

    it('should handle JSON parse errors', async () => {
      mockReq.query = { path: ['v0', 'postings', 'json-error'] };
      mockReq.url = '/api/lever/v0/postings/json-error';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => {
          throw new Error('Invalid JSON');
        },
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Invalid JSON',
      });
    });

    it('should handle non-Error exceptions', async () => {
      mockReq.query = { path: ['v0', 'postings', 'unknown-error'] };
      mockReq.url = '/api/lever/v0/postings/unknown-error';

      fetchMock.mockRejectedValue('String error');

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Unknown error',
      });
    });

    it('should handle timeout errors', async () => {
      mockReq.query = { path: ['v0', 'postings', 'timeout'] };
      mockReq.url = '/api/lever/v0/postings/timeout';

      fetchMock.mockRejectedValue(new Error('Request timeout'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Request timeout',
      });
    });

    it('should handle DNS resolution errors', async () => {
      mockReq.query = { path: ['v0', 'postings', 'dns-error'] };
      mockReq.url = '/api/lever/v0/postings/dns-error';

      fetchMock.mockRejectedValue(new Error('getaddrinfo ENOTFOUND'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'getaddrinfo ENOTFOUND',
      });
    });
  });

  describe('Integration Scenarios', () => {
    it('should handle complete realistic request flow', async () => {
      // Simulate real Lever API request
      mockReq.method = 'GET';
      mockReq.query = { path: ['v0', 'postings', 'netflix'] };
      mockReq.url = '/api/lever/v0/postings/netflix?mode=json&skip=0&limit=50';
      mockReq.headers = {
        'user-agent': 'Mozilla/5.0',
        accept: '*/*',
      };

      const mockLeverResponse = [
        {
          id: 'abc-123-def',
          text: 'Senior Backend Engineer',
          categories: {
            team: 'Engineering',
            location: 'Los Gatos, CA',
          },
          hostedUrl: 'https://jobs.lever.co/netflix/abc-123-def',
          createdAt: 1700000000000,
        },
        {
          id: 'xyz-456-uvw',
          text: 'Staff Product Designer',
          categories: {
            team: 'Design',
            location: 'Remote',
          },
          hostedUrl: 'https://jobs.lever.co/netflix/xyz-456-uvw',
          createdAt: 1700100000000,
        },
      ];

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => mockLeverResponse,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      // Verify fetch was called with correct URL and headers
      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.lever.co/v0/postings/netflix?mode=json&skip=0&limit=50',
        {
          method: 'GET',
          headers: {
            Accept: 'application/json',
            'User-Agent': 'Job-Visualizer-Notifier/1.0',
          },
        }
      );

      // Verify response was forwarded correctly
      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(mockLeverResponse);

      // Verify CORS headers were set
      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Origin', '*');
      expect(mockRes.setHeader).toHaveBeenCalledWith(
        'Access-Control-Allow-Methods',
        'GET, OPTIONS'
      );
      expect(mockRes.setHeader).toHaveBeenCalledWith(
        'Access-Control-Allow-Headers',
        'Content-Type'
      );
    });
  });
});
