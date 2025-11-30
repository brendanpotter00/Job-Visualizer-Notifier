import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../api/workday';

describe('/api/workday serverless function', () => {
  let mockReq: Partial<VercelRequest>;
  let mockRes: Partial<VercelResponse>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Mock request object
    mockReq = {
      method: 'POST',
      query: {},
      body: {},
      headers: {},
      url: '',
    };

    // Mock response object with chainable methods
    mockRes = {
      status: vi.fn().mockReturnThis(),
      json: vi.fn().mockReturnThis(),
      setHeader: vi.fn().mockReturnThis(),
      end: vi.fn().mockReturnThis(),
    };

    // Mock global fetch
    fetchMock = vi.fn();
    global.fetch = fetchMock;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('Method Validation', () => {
    it('should allow POST requests', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };
      mockReq.body = { appliedFacets: {}, limit: 20, offset: 0, searchText: '' };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ total: 0, jobPostings: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
    });

    it('should allow OPTIONS requests (CORS preflight)', async () => {
      mockReq.method = 'OPTIONS';

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Origin', '*');
      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Methods', 'POST, OPTIONS');
      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Headers', 'Content-Type');
      expect(mockRes.end).toHaveBeenCalled();
    });

    it('should reject GET requests with 405', async () => {
      mockReq.method = 'GET';

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(405);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Method not allowed' });
    });

    it('should reject PUT requests with 405', async () => {
      mockReq.method = 'PUT';

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(405);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Method not allowed' });
    });

    it('should reject DELETE requests with 405', async () => {
      mockReq.method = 'DELETE';

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(405);
    });
  });

  describe('Path Parsing', () => {
    it('should extract tenant from path correctly', async () => {
      mockReq.method = 'POST';
      mockReq.query = {
        path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'],
      };
      mockReq.body = { limit: 20 };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ total: 0, jobPostings: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      // Verify fetch was called with correct URL
      expect(fetchMock).toHaveBeenCalledWith(
        'https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ limit: 20 }),
        })
      );
    });

    it('should handle path as array', async () => {
      mockReq.method = 'POST';
      mockReq.query = {
        path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'],
      };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ total: 0, jobPostings: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('nvidia.wd5.myworkdayjobs.com'),
        expect.any(Object)
      );
    });

    it('should handle path as single string', async () => {
      mockReq.method = 'POST';
      mockReq.query = {
        path: 'wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs',
      };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ total: 0, jobPostings: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('nvidia.wd5.myworkdayjobs.com'),
        expect.any(Object)
      );
    });

    it('should return 400 for invalid path format', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['invalid', 'path'] };

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(400);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Invalid Workday path format. Expected: /wday/cxs/{tenant}/{careerSite}/jobs',
      });
    });

    it('should return 400 for missing path', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: [] };

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(400);
    });

    it('should return 400 for path without tenant', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday'] };

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(400);
    });
  });

  describe('Request Forwarding', () => {
    it('should forward request body correctly', async () => {
      const requestBody = {
        appliedFacets: { location: ['US'] },
        limit: 50,
        offset: 10,
        searchText: 'engineer',
      };

      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };
      mockReq.body = requestBody;

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ total: 0, jobPostings: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          body: JSON.stringify(requestBody),
        })
      );
    });

    it('should set correct headers in proxied request', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ total: 0, jobPostings: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'Job-Visualizer-Notifier/1.0',
          },
        })
      );
    });

    it('should forward empty request body', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };
      mockReq.body = {};

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ total: 0, jobPostings: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          body: JSON.stringify({}),
        })
      );
    });
  });

  describe('Response Handling', () => {
    it('should forward successful response', async () => {
      const mockData = {
        total: 2000,
        jobPostings: [
          {
            title: 'Software Engineer',
            externalPath: '/job/US-CA/Software-Engineer_JR123',
            locationsText: 'Santa Clara, CA',
            postedOn: 'Posted Today',
          },
        ],
      };

      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => mockData,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(mockData);
    });

    it('should set CORS headers on successful response', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ total: 0, jobPostings: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Origin', '*');
      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Methods', 'POST, OPTIONS');
      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Headers', 'Content-Type');
    });

    it('should forward error status codes', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockResolvedValueOnce({
        status: 404,
        json: async () => ({ error: 'Not found' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(404);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'Not found' });
    });

    it('should forward 500 error responses', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockResolvedValueOnce({
        status: 500,
        json: async () => ({ error: 'Internal server error' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
    });

    it('should handle empty response', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({}),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith({});
    });
  });

  describe('Error Handling', () => {
    it('should handle network errors', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockRejectedValueOnce(new Error('Network error'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Origin', '*');
      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Network error',
      });
    });

    it('should handle JSON parse errors', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockResolvedValueOnce({
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

    it('should handle unknown errors gracefully', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockRejectedValueOnce('Unknown error');

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Unknown error',
      });
    });

    it('should handle fetch timeout', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockRejectedValueOnce(new Error('Request timeout'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'Request timeout',
      });
    });

    it('should set CORS headers even on error', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockRejectedValueOnce(new Error('Test error'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Origin', '*');
    });
  });

  describe('Tenant-Specific Routing', () => {
    it('should route to nvidia.wd5.myworkdayjobs.com for nvidia tenant', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ total: 0, jobPostings: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs',
        expect.any(Object)
      );
    });

    it('should support different tenants dynamically', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'google', 'GoogleCareers', 'jobs'] };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ total: 0, jobPostings: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://google.wd5.myworkdayjobs.com/wday/cxs/google/GoogleCareers/jobs',
        expect.any(Object)
      );
    });

    it('should support different career sites', async () => {
      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'UniversityCareers', 'jobs'] };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ total: 0, jobPostings: [] }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        'https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/UniversityCareers/jobs',
        expect.any(Object)
      );
    });
  });

  describe('Integration Scenarios', () => {
    it('should handle complete realistic request', async () => {
      const mockData = {
        total: 1500,
        jobPostings: [
          {
            title: 'Senior Software Engineer - AI/ML',
            externalPath: '/job/US-CA-Santa-Clara/Senior-Software-Engineer-AI-ML_JR2008216',
            locationsText: 'Santa Clara, CA',
            postedOn: 'Posted Today',
            bulletFields: ['JR2008216', 'Full-time', 'Engineering'],
          },
        ],
      };

      mockReq.method = 'POST';
      mockReq.query = { path: ['wday', 'cxs', 'nvidia', 'NVIDIAExternalCareerSite', 'jobs'] };
      mockReq.body = {
        appliedFacets: {
          locationHierarchy1: ['2fcb99c455831013ea52fb338f2932d8'],
          jobFamilyGroup: ['0c40f6bd1d8f10ae43ffaefd46dc7e78'],
          timeType: ['5509c0b5959810ac0029943377d47364'],
        },
        limit: 20,
        offset: 0,
        searchText: '',
      };

      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => mockData,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      // Verify request was forwarded correctly
      expect(fetchMock).toHaveBeenCalledWith(
        'https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs',
        expect.objectContaining({
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'Job-Visualizer-Notifier/1.0',
          },
          body: JSON.stringify(mockReq.body),
        })
      );

      // Verify response
      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(mockData);

      // Verify CORS headers
      expect(mockRes.setHeader).toHaveBeenCalledWith('Access-Control-Allow-Origin', '*');
    });
  });
});
