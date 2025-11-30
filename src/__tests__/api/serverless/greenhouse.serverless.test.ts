import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../api/greenhouse';

describe('/api/greenhouse serverless function', () => {
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
    global.fetch = fetchMock;
  });

  describe('Path Parsing', () => {
    it('should handle single path segment', async () => {
      mockReq.query = { path: 'v1' };
      mockReq.url = '/api/greenhouse/v1';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ jobs: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://boards-api.greenhouse.io/v1',
        expect.objectContaining({
          method: 'GET',
          headers: {
            Accept: 'application/json',
            'User-Agent': 'Job-Visualizer-Notifier/1.0',
          },
        })
      );
    });

    it('should handle multiple path segments (board token + embed)', async () => {
      mockReq.query = { path: ['v1', 'boards', 'airbnb', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/airbnb/jobs';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ jobs: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://boards-api.greenhouse.io/v1/boards/airbnb/jobs',
        expect.any(Object)
      );
    });

    it('should handle path as array', async () => {
      mockReq.query = { path: ['v1', 'boards', 'meta', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/meta/jobs';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ jobs: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://boards-api.greenhouse.io/v1/boards/meta/jobs',
        expect.any(Object)
      );
    });

    it('should handle path as string', async () => {
      mockReq.query = { path: 'v1/boards/google/jobs' };
      mockReq.url = '/api/greenhouse/v1/boards/google/jobs';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ jobs: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://boards-api.greenhouse.io/v1/boards/google/jobs',
        expect.any(Object)
      );
    });

    it('should handle path array with empty strings (double slashes)', async () => {
      mockReq.query = { path: ['v1', '', 'boards', '', 'stripe', '', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1//boards//stripe//jobs';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ jobs: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      // Note: Current implementation doesn't filter empty strings from path arrays
      // This results in double slashes but still works (APIs typically normalize these)
      expect(fetchMock).toHaveBeenCalledWith(
        'https://boards-api.greenhouse.io/v1//boards//stripe//jobs',
        expect.any(Object)
      );
    });

    it('should preserve query parameters from original URL', async () => {
      mockReq.query = { path: ['v1', 'boards', 'netflix', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/netflix/jobs?content=true&page=1';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ jobs: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://boards-api.greenhouse.io/v1/boards/netflix/jobs?content=true&page=1',
        expect.any(Object)
      );
    });

    it('should handle URL without query parameters', async () => {
      mockReq.query = { path: ['v1', 'boards', 'tesla', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/tesla/jobs';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ jobs: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://boards-api.greenhouse.io/v1/boards/tesla/jobs',
        expect.any(Object)
      );
    });
  });

  describe('Request Forwarding', () => {
    it('should forward GET requests with correct headers', async () => {
      mockReq.method = 'GET';
      mockReq.query = { path: ['v1', 'boards', 'uber', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/uber/jobs';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ jobs: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://boards-api.greenhouse.io/v1/boards/uber/jobs',
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
      mockReq.query = { path: ['v1', 'boards', 'lyft', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/lyft/jobs';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ jobs: [] }),
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
      mockReq.query = { path: ['v1', 'boards', 'spotify', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/spotify/jobs';

      const mockJobData = {
        jobs: [
          { id: 1, title: 'Software Engineer' },
          { id: 2, title: 'Product Manager' },
        ],
      };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => mockJobData,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(mockJobData);
    });

    it('should set CORS headers on successful response', async () => {
      mockReq.query = { path: ['v1', 'boards', 'slack', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/slack/jobs';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ jobs: [] }),
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

    it('should forward 404 status from Greenhouse API', async () => {
      mockReq.query = { path: ['v1', 'boards', 'nonexistent', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/nonexistent/jobs';

      fetchMock.mockResolvedValue({
        status: 404,
        json: async () => ({ error: 'Board not found' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Board not found' });
    });

    it('should forward 500 status from Greenhouse API', async () => {
      mockReq.query = { path: ['v1', 'boards', 'error', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/error/jobs';

      fetchMock.mockResolvedValue({
        status: 500,
        json: async () => ({ error: 'Internal server error' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Internal server error' });
    });

    it('should forward 401 status from Greenhouse API', async () => {
      mockReq.query = { path: ['v1', 'boards', 'private', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/private/jobs';

      fetchMock.mockResolvedValue({
        status: 401,
        json: async () => ({ error: 'Unauthorized' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(401);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Unauthorized' });
    });

    it('should handle empty response data', async () => {
      mockReq.query = { path: ['v1', 'boards', 'empty', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/empty/jobs';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith({});
    });
  });

  describe('Error Handling', () => {
    it('should return 500 with error message on network error', async () => {
      mockReq.query = { path: ['v1', 'boards', 'network-error', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/network-error/jobs';

      fetchMock.mockRejectedValue(new Error('Network error'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Network error',
      });
    });

    it('should set CORS headers even on error', async () => {
      mockReq.query = { path: ['v1', 'boards', 'cors-error', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/cors-error/jobs';

      fetchMock.mockRejectedValue(new Error('CORS error'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Origin', '*');
    });

    it('should handle JSON parse errors', async () => {
      mockReq.query = { path: ['v1', 'boards', 'json-error', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/json-error/jobs';

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
      mockReq.query = { path: ['v1', 'boards', 'unknown-error', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/unknown-error/jobs';

      fetchMock.mockRejectedValue('String error');

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Unknown error',
      });
    });

    it('should handle timeout errors', async () => {
      mockReq.query = { path: ['v1', 'boards', 'timeout', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/timeout/jobs';

      fetchMock.mockRejectedValue(new Error('Request timeout'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Request timeout',
      });
    });

    it('should handle DNS resolution errors', async () => {
      mockReq.query = { path: ['v1', 'boards', 'dns-error', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/dns-error/jobs';

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
      // Simulate real Greenhouse API request
      mockReq.method = 'GET';
      mockReq.query = { path: ['v1', 'boards', 'stripe', 'jobs'] };
      mockReq.url = '/api/greenhouse/v1/boards/stripe/jobs?content=true';
      mockReq.headers = {
        'user-agent': 'Mozilla/5.0',
        accept: '*/*',
      };

      const mockGreenhouseResponse = {
        jobs: [
          {
            id: 123456,
            title: 'Senior Software Engineer',
            location: { name: 'San Francisco, CA' },
            updated_at: '2025-11-20T10:30:00Z',
            absolute_url: 'https://boards.greenhouse.io/stripe/jobs/123456',
          },
          {
            id: 789012,
            title: 'Product Designer',
            location: { name: 'Remote' },
            updated_at: '2025-11-21T14:20:00Z',
            absolute_url: 'https://boards.greenhouse.io/stripe/jobs/789012',
          },
        ],
      };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => mockGreenhouseResponse,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      // Verify fetch was called with correct URL and headers
      expect(fetchMock).toHaveBeenCalledWith(
        'https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true',
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
      expect(mockRes.json).toHaveBeenCalledWith(mockGreenhouseResponse);

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
