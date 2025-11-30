import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../api/ashby';

describe('/api/ashby serverless function', () => {
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
      mockReq.query = { path: 'posting-api' };
      mockReq.url = '/api/ashby/posting-api';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ results: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.ashbyhq.com/posting-api',
        expect.objectContaining({
          method: 'GET',
          headers: {
            Accept: 'application/json',
            'User-Agent': 'Job-Visualizer-Notifier/1.0',
          },
        })
      );
    });

    it('should handle multiple path segments (job board)', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'anthropic'] };
      mockReq.url = '/api/ashby/posting-api/job-board/anthropic';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ results: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.ashbyhq.com/posting-api/job-board/anthropic',
        expect.any(Object)
      );
    });

    it('should handle path as array', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'openai'] };
      mockReq.url = '/api/ashby/posting-api/job-board/openai';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ results: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.ashbyhq.com/posting-api/job-board/openai',
        expect.any(Object)
      );
    });

    it('should handle path as string', async () => {
      mockReq.query = { path: 'posting-api/job-board/mistral' };
      mockReq.url = '/api/ashby/posting-api/job-board/mistral';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ results: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.ashbyhq.com/posting-api/job-board/mistral',
        expect.any(Object)
      );
    });

    it('should handle path array with empty strings (double slashes)', async () => {
      mockReq.query = { path: ['posting-api', '', 'job-board', '', 'cohere', ''] };
      mockReq.url = '/api/ashby/posting-api//job-board//cohere/';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ results: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      // Note: Current implementation doesn't filter empty strings from path arrays
      // This results in double slashes but still works (APIs typically normalize these)
      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.ashbyhq.com/posting-api//job-board//cohere/',
        expect.any(Object)
      );
    });

    it('should preserve query parameters from original URL', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'runway'] };
      mockReq.url = '/api/ashby/posting-api/job-board/runway?includeCompensation=true&page=0';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ results: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.ashbyhq.com/posting-api/job-board/runway?includeCompensation=true&page=0',
        expect.any(Object)
      );
    });

    it('should handle URL without query parameters', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'scale'] };
      mockReq.url = '/api/ashby/posting-api/job-board/scale';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ results: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.ashbyhq.com/posting-api/job-board/scale',
        expect.any(Object)
      );
    });
  });

  describe('Request Forwarding', () => {
    it('should forward GET requests with correct headers', async () => {
      mockReq.method = 'GET';
      mockReq.query = { path: ['posting-api', 'job-board', 'perplexity'] };
      mockReq.url = '/api/ashby/posting-api/job-board/perplexity';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ results: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.ashbyhq.com/posting-api/job-board/perplexity',
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
      mockReq.query = { path: ['posting-api', 'job-board', 'adept'] };
      mockReq.url = '/api/ashby/posting-api/job-board/adept';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ results: [] }),
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
      mockReq.query = { path: ['posting-api', 'job-board', 'inflection'] };
      mockReq.url = '/api/ashby/posting-api/job-board/inflection';

      const mockJobData = {
        results: [
          {
            id: 'job-1',
            title: 'Machine Learning Engineer',
            departmentName: 'Engineering',
          },
          {
            id: 'job-2',
            title: 'Research Scientist',
            departmentName: 'Research',
          },
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
      mockReq.query = { path: ['posting-api', 'job-board', 'character'] };
      mockReq.url = '/api/ashby/posting-api/job-board/character';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ results: [] }),
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

    it('should forward 404 status from Ashby API', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'nonexistent'] };
      mockReq.url = '/api/ashby/posting-api/job-board/nonexistent';

      fetchMock.mockResolvedValue({
        status: 404,
        json: async () => ({ error: 'Job board not found' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Job board not found' });
    });

    it('should forward 500 status from Ashby API', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'error'] };
      mockReq.url = '/api/ashby/posting-api/job-board/error';

      fetchMock.mockResolvedValue({
        status: 500,
        json: async () => ({ error: 'Internal server error' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Internal server error' });
    });

    it('should forward 401 status from Ashby API', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'private'] };
      mockReq.url = '/api/ashby/posting-api/job-board/private';

      fetchMock.mockResolvedValue({
        status: 401,
        json: async () => ({ error: 'Unauthorized' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(401);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Unauthorized' });
    });

    it('should handle empty response data', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'empty'] };
      mockReq.url = '/api/ashby/posting-api/job-board/empty';

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => ({ results: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith({ results: [] });
    });
  });

  describe('Error Handling', () => {
    it('should return 500 with error message on network error', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'network-error'] };
      mockReq.url = '/api/ashby/posting-api/job-board/network-error';

      fetchMock.mockRejectedValue(new Error('Network error'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Network error',
      });
    });

    it('should set CORS headers even on error', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'cors-error'] };
      mockReq.url = '/api/ashby/posting-api/job-board/cors-error';

      fetchMock.mockRejectedValue(new Error('CORS error'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Origin', '*');
    });

    it('should handle JSON parse errors', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'json-error'] };
      mockReq.url = '/api/ashby/posting-api/job-board/json-error';

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
      mockReq.query = { path: ['posting-api', 'job-board', 'unknown-error'] };
      mockReq.url = '/api/ashby/posting-api/job-board/unknown-error';

      fetchMock.mockRejectedValue('String error');

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Unknown error',
      });
    });

    it('should handle timeout errors', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'timeout'] };
      mockReq.url = '/api/ashby/posting-api/job-board/timeout';

      fetchMock.mockRejectedValue(new Error('Request timeout'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Request timeout',
      });
    });

    it('should handle DNS resolution errors', async () => {
      mockReq.query = { path: ['posting-api', 'job-board', 'dns-error'] };
      mockReq.url = '/api/ashby/posting-api/job-board/dns-error';

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
      // Simulate real Ashby API request
      mockReq.method = 'GET';
      mockReq.query = { path: ['posting-api', 'job-board', 'anthropic'] };
      mockReq.url = '/api/ashby/posting-api/job-board/anthropic?includeCompensation=true';
      mockReq.headers = {
        'user-agent': 'Mozilla/5.0',
        accept: '*/*',
      };

      const mockAshbyResponse = {
        results: [
          {
            id: 'job-abc-123',
            title: 'Research Engineer',
            departmentName: 'Research',
            locationName: 'San Francisco, CA',
            publishedDate: '2025-11-15T08:00:00.000Z',
            jobUrl: 'https://jobs.ashbyhq.com/anthropic/job-abc-123',
          },
          {
            id: 'job-def-456',
            title: 'Product Manager, Safety',
            departmentName: 'Product',
            locationName: 'Remote',
            publishedDate: '2025-11-18T12:30:00.000Z',
            jobUrl: 'https://jobs.ashbyhq.com/anthropic/job-def-456',
          },
        ],
        hasNext: false,
      };

      fetchMock.mockResolvedValue({
        status: 200,
        json: async () => mockAshbyResponse,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      // Verify fetch was called with correct URL and headers
      expect(fetchMock).toHaveBeenCalledWith(
        'https://api.ashbyhq.com/posting-api/job-board/anthropic?includeCompensation=true',
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
      expect(mockRes.json).toHaveBeenCalledWith(mockAshbyResponse);

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
