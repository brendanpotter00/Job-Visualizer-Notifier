import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import type { VercelRequest, VercelResponse } from '@vercel/node';
import handler from '../../../../../../api/eightfold';

describe('/api/eightfold serverless function', () => {
  let mockReq: Partial<VercelRequest>;
  let mockRes: Partial<VercelResponse>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockReq = {
      method: 'GET',
      query: {},
      body: {},
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

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('Method Validation', () => {
    it('allows GET requests', async () => {
      mockReq.method = 'GET';
      mockReq.query = { path: ['api', 'apply', 'v2', 'jobs'], domain: 'netflix.com' };
      mockReq.headers = { 'x-eightfold-tenant-host': 'explore.jobs.netflix.net' };
      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ positions: [], count: 0 }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
    });

    it('allows OPTIONS preflight', async () => {
      mockReq.method = 'OPTIONS';

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).toHaveBeenCalledWith(
        'Access-Control-Allow-Origin',
        '*'
      );
      expect(mockRes.setHeader).toHaveBeenCalledWith(
        'Access-Control-Allow-Methods',
        'GET, OPTIONS'
      );
      expect(mockRes.setHeader).toHaveBeenCalledWith(
        'Access-Control-Allow-Headers',
        'Content-Type, X-Eightfold-Tenant-Host'
      );
      expect(mockRes.end).toHaveBeenCalled();
    });

    it('rejects POST with 405', async () => {
      mockReq.method = 'POST';
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(405);
    });

    it('rejects PUT with 405', async () => {
      mockReq.method = 'PUT';
      await handler(mockReq as VercelRequest, mockRes as VercelResponse);
      expect(mockRes.status).toHaveBeenCalledWith(405);
    });
  });

  describe('Tenant Host Validation', () => {
    beforeEach(() => {
      mockReq.method = 'GET';
      mockReq.query = { path: ['api', 'apply', 'v2', 'jobs'] };
    });

    it('returns 400 when the tenant host header is missing', async () => {
      mockReq.headers = {};

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(400);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Missing X-Eightfold-Tenant-Host header',
      });
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('returns 400 when the tenant host header is empty', async () => {
      mockReq.headers = { 'x-eightfold-tenant-host': '  ' };

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(400);
    });

    it('returns 400 when the tenant host fails the SSRF allowlist', async () => {
      mockReq.headers = { 'x-eightfold-tenant-host': 'evil.example.org' };

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(400);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Invalid X-Eightfold-Tenant-Host value',
      });
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it.each([
      'evil.com',
      'attacker.net',
      'burpcollaborator.net',
      'attacker.eightfold.ai.evil.com',
      'localhost',
      '127.0.0.1',
      'eightfold.ai.evil.com',
    ])('rejects SSRF-style host %s', async (host) => {
      mockReq.headers = { 'x-eightfold-tenant-host': host };

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(400);
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('trims whitespace before allowlist check and target URL build', async () => {
      mockReq.headers = {
        'x-eightfold-tenant-host': '  explore.jobs.netflix.net  ',
      };
      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ positions: [], count: 0 }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(
          /^https:\/\/explore\.jobs\.netflix\.net\//
        ),
        expect.any(Object)
      );
    });

    it('accepts .eightfold.ai hosts', async () => {
      mockReq.headers = { 'x-eightfold-tenant-host': 'some-tenant.eightfold.ai' };
      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ positions: [], count: 0 }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('https://some-tenant.eightfold.ai/'),
        expect.any(Object)
      );
    });

    it('accepts explore.jobs.netflix.net', async () => {
      mockReq.headers = { 'x-eightfold-tenant-host': 'explore.jobs.netflix.net' };
      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ positions: [], count: 0 }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('https://explore.jobs.netflix.net/'),
        expect.any(Object)
      );
    });
  });

  describe('Path Validation', () => {
    beforeEach(() => {
      mockReq.method = 'GET';
      mockReq.headers = { 'x-eightfold-tenant-host': 'explore.jobs.netflix.net' };
    });

    it('returns 400 when path is missing', async () => {
      mockReq.query = {};

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(400);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Invalid Eightfold path. Expected prefix: api/apply/',
      });
    });

    it('returns 400 when path does not start with api/apply/', async () => {
      mockReq.query = { path: ['foo', 'bar'] };

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(400);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Invalid Eightfold path. Expected prefix: api/apply/',
      });
    });

    it('accepts path starting with api/apply/', async () => {
      mockReq.query = { path: ['api', 'apply', 'v2', 'jobs'] };
      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ positions: [], count: 0 }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/apply/v2/jobs'),
        expect.any(Object)
      );
    });
  });

  describe('Request Forwarding', () => {
    beforeEach(() => {
      mockReq.method = 'GET';
      mockReq.headers = { 'x-eightfold-tenant-host': 'explore.jobs.netflix.net' };
    });

    it('preserves query params (domain, num, start)', async () => {
      mockReq.query = {
        path: ['api', 'apply', 'v2', 'jobs'],
        domain: 'netflix.com',
        num: '10',
        start: '20',
      };
      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ positions: [], count: 0 }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      const calledUrl = fetchMock.mock.calls[0][0] as string;
      expect(calledUrl).toContain('https://explore.jobs.netflix.net/api/apply/v2/jobs');
      expect(calledUrl).toContain('domain=netflix.com');
      expect(calledUrl).toContain('num=10');
      expect(calledUrl).toContain('start=20');
    });

    it('sends the correct fetch headers to Eightfold', async () => {
      mockReq.query = { path: ['api', 'apply', 'v2', 'jobs'] };
      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ positions: [], count: 0 }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(fetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          method: 'GET',
          headers: {
            Accept: 'application/json',
            'User-Agent': 'Job-Visualizer-Notifier/1.0',
          },
        })
      );
    });
  });

  describe('Response Forwarding', () => {
    beforeEach(() => {
      mockReq.method = 'GET';
      mockReq.query = { path: ['api', 'apply', 'v2', 'jobs'] };
      mockReq.headers = { 'x-eightfold-tenant-host': 'explore.jobs.netflix.net' };
    });

    it('forwards status and body from the upstream', async () => {
      const data = { positions: [{ id: 1, name: 'x' }], count: 1 };
      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => data,
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(200);
      expect(mockRes.json).toHaveBeenCalledWith(data);
    });

    it('forwards non-200 statuses', async () => {
      fetchMock.mockResolvedValueOnce({
        status: 502,
        json: async () => ({ error: 'bad gateway' }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(502);
      expect(mockRes.json).toHaveBeenCalledWith({ error: 'bad gateway' });
    });

    it('sets CORS headers on successful responses', async () => {
      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => ({ positions: [], count: 0 }),
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.setHeader).toHaveBeenCalledWith(
        'Access-Control-Allow-Origin',
        '*'
      );
      expect(mockRes.setHeader).toHaveBeenCalledWith(
        'Access-Control-Allow-Methods',
        'GET, OPTIONS'
      );
    });

    it('returns 500 with CORS headers when fetch throws', async () => {
      fetchMock.mockRejectedValueOnce(new Error('network down'));

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'network down',
      });
      expect(mockRes.setHeader).toHaveBeenCalledWith(
        'Access-Control-Allow-Origin',
        '*'
      );
    });

    it('returns 500 on JSON parse failure', async () => {
      fetchMock.mockResolvedValueOnce({
        status: 200,
        json: async () => {
          throw new Error('invalid json');
        },
      });

      await handler(mockReq as VercelRequest, mockRes as VercelResponse);

      expect(mockRes.status).toHaveBeenCalledWith(500);
      expect(mockRes.json).toHaveBeenCalledWith({
        error: 'Proxy error',
        message: 'invalid json',
      });
    });
  });
});
