import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { createAPIClient } from '../../api/clients/baseClient';
import type { Job, GreenhouseConfig } from '../../types';
import { APIError } from '../../api/types';

describe('createAPIClient', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('should create a client with fetchJobs method', () => {
    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (job: any, identifier: string) =>
        ({
          id: job.id,
          source: 'greenhouse',
          company: identifier,
          title: job.title,
          createdAt: job.createdAt,
          url: job.url,
          raw: job,
        }) as Job,
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    expect(client).toHaveProperty('fetchJobs');
    expect(typeof client.fetchJobs).toBe('function');
  });

  it('should throw error for invalid config type', async () => {
    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (_job: any) => ({}) as Job,
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const invalidConfig = { type: 'lever' as const, companyId: 'test', jobsUrl: 'http://test.com' };

    await expect(client.fetchJobs(invalidConfig)).rejects.toThrow(
      'Invalid config type for Test client'
    );
  });

  it('should successfully fetch and transform jobs', async () => {
    const mockJobs = [
      { id: '1', title: 'Engineer', createdAt: '2025-01-01T00:00:00Z', url: 'http://test.com/1' },
      { id: '2', title: 'Designer', createdAt: '2025-01-02T00:00:00Z', url: 'http://test.com/2' },
    ];

    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ jobs: mockJobs }),
    });

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (job: any, identifier: string) =>
        ({
          id: job.id,
          source: 'greenhouse' as const,
          company: identifier,
          title: job.title,
          createdAt: job.createdAt,
          url: job.url,
          raw: job,
        }) as Job,
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
    const result = await client.fetchJobs(config);

    expect(result.jobs).toHaveLength(2);
    expect(result.jobs[0].id).toBe('1');
    expect(result.jobs[0].title).toBe('Engineer');
    expect(result.metadata.totalCount).toBe(2);
  });

  it('should apply since filter correctly', async () => {
    const mockJobs = [
      { id: '1', createdAt: '2025-01-01T00:00:00Z' },
      { id: '2', createdAt: '2025-01-05T00:00:00Z' },
      { id: '3', createdAt: '2025-01-10T00:00:00Z' },
    ];

    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ jobs: mockJobs }),
    });

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (job: any, identifier: string) =>
        ({
          id: job.id,
          source: 'greenhouse' as const,
          company: identifier,
          title: 'Test',
          createdAt: job.createdAt,
          url: 'http://test.com',
          raw: job,
        }) as Job,
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
    const result = await client.fetchJobs(config, { since: '2025-01-05T00:00:00Z' });

    expect(result.jobs).toHaveLength(2); // Only jobs from Jan 5 onwards
    expect(result.jobs[0].id).toBe('2');
    expect(result.jobs[1].id).toBe('3');
  });

  it('should apply limit correctly', async () => {
    const mockJobs = Array.from({ length: 10 }, (_, i) => ({
      id: String(i + 1),
      createdAt: '2025-01-01T00:00:00Z',
    }));

    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ jobs: mockJobs }),
    });

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (job: any, identifier: string) =>
        ({
          id: job.id,
          source: 'greenhouse' as const,
          company: identifier,
          title: 'Test',
          createdAt: job.createdAt,
          url: 'http://test.com',
          raw: job,
        }) as Job,
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
    const result = await client.fetchJobs(config, { limit: 3 });

    expect(result.jobs).toHaveLength(3);
    expect(result.jobs[0].id).toBe('1');
    expect(result.jobs[2].id).toBe('3');
  });

  it('should throw APIError for non-ok response', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
    });

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (_job: any) => ({}) as Job,
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };

    await expect(client.fetchJobs(config)).rejects.toThrow(APIError);
    await expect(client.fetchJobs(config)).rejects.toThrow('Test API error: Not Found');
  });

  it('should wrap non-APIError exceptions in APIError', async () => {
    (globalThis.fetch as any).mockRejectedValue(new Error('Network failure'));

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (_job: any) => ({}) as Job,
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };

    await expect(client.fetchJobs(config)).rejects.toThrow(APIError);
    await expect(client.fetchJobs(config)).rejects.toThrow(
      'Failed to fetch Test jobs: Network failure'
    );
  });

  it('should pass signal to fetch for cancellation support', async () => {
    (globalThis.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ jobs: [] }),
    });

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (_job: any) => ({}) as Job,
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
    const controller = new AbortController();

    await client.fetchJobs(config, { signal: controller.signal });

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        signal: controller.signal,
      })
    );
  });

  describe('Combined Filters', () => {
    it('should apply both since and limit filters together', async () => {
      const mockJobs = Array.from({ length: 10 }, (_, i) => ({
        id: String(i + 1),
        createdAt: new Date(2025, 0, i + 1).toISOString(), // Jan 1-10
      }));

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ jobs: mockJobs }),
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (job: any, identifier: string) =>
          ({
            id: job.id,
            source: 'greenhouse' as const,
            company: identifier,
            title: 'Test',
            createdAt: job.createdAt,
            url: 'http://test.com',
            raw: job,
          }) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
      // Filter: since Jan 5, limit 3
      const result = await client.fetchJobs(config, {
        since: new Date(2025, 0, 5).toISOString(),
        limit: 3,
      });

      // Should get jobs 5, 6, 7 (first 3 after Jan 5)
      expect(result.jobs).toHaveLength(3);
      expect(result.jobs[0].id).toBe('5');
      expect(result.jobs[1].id).toBe('6');
      expect(result.jobs[2].id).toBe('7');
    });

    it('should handle limit when fewer jobs match since filter', async () => {
      const mockJobs = [
        { id: '1', createdAt: '2025-01-01T00:00:00Z' },
        { id: '2', createdAt: '2025-01-10T00:00:00Z' },
      ];

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ jobs: mockJobs }),
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (job: any, identifier: string) =>
          ({
            id: job.id,
            source: 'greenhouse' as const,
            company: identifier,
            title: 'Test',
            createdAt: job.createdAt,
            url: 'http://test.com',
            raw: job,
          }) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
      // Filter: since Jan 10, limit 5 (but only 1 job matches)
      const result = await client.fetchJobs(config, {
        since: '2025-01-10T00:00:00Z',
        limit: 5,
      });

      // Should only get 1 job even though limit is 5
      expect(result.jobs).toHaveLength(1);
      expect(result.jobs[0].id).toBe('2');
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty jobs array response', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ jobs: [] }),
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (_job: any) => ({}) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
      const result = await client.fetchJobs(config);

      expect(result.jobs).toHaveLength(0);
      expect(result.metadata.totalCount).toBe(0);
    });

    it('should calculate metadata correctly with mixed job types', async () => {
      const mockJobs = [
        {
          id: '1',
          title: 'Software Engineer',
          createdAt: '2025-01-01T00:00:00Z',
          isSoftware: true,
        },
        { id: '2', title: 'Designer', createdAt: '2025-01-02T00:00:00Z', isSoftware: false },
        { id: '3', title: 'Backend Engineer', createdAt: '2025-01-03T00:00:00Z', isSoftware: true },
        { id: '4', title: 'HR Manager', createdAt: '2025-01-04T00:00:00Z', isSoftware: false },
      ];

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ jobs: mockJobs }),
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (job: any, identifier: string) =>
          ({
            id: job.id,
            source: 'greenhouse' as const,
            company: identifier,
            title: job.title,
            createdAt: job.createdAt,
            url: 'http://test.com',
            raw: job,
          }) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
      const result = await client.fetchJobs(config);

      expect(result.jobs).toHaveLength(4);
      expect(result.metadata.totalCount).toBe(4);
    });

    it('should handle large datasets (1000+ jobs)', async () => {
      const mockJobs = Array.from({ length: 1500 }, (_, i) => ({
        id: String(i + 1),
        createdAt: new Date(2025, 0, 1 + Math.floor(i / 100)).toISOString(),
        isSoftware: i % 3 === 0, // Every 3rd job is software
      }));

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ jobs: mockJobs }),
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (job: any, identifier: string) =>
          ({
            id: job.id,
            source: 'greenhouse' as const,
            company: identifier,
            title: 'Test',
            createdAt: job.createdAt,
            url: 'http://test.com',
            raw: job,
          }) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
      const result = await client.fetchJobs(config);

      expect(result.jobs).toHaveLength(1500);
      expect(result.metadata.totalCount).toBe(1500);
    });

    it('should filter jobs with identical timestamps correctly', async () => {
      const sameTime = '2025-01-05T10:00:00Z';
      const mockJobs = [
        { id: '1', createdAt: '2025-01-01T00:00:00Z' },
        { id: '2', createdAt: sameTime },
        { id: '3', createdAt: sameTime },
        { id: '4', createdAt: sameTime },
        { id: '5', createdAt: '2025-01-10T00:00:00Z' },
      ];

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ jobs: mockJobs }),
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (job: any, identifier: string) =>
          ({
            id: job.id,
            source: 'greenhouse' as const,
            company: identifier,
            title: 'Test',
            createdAt: job.createdAt,
            url: 'http://test.com',
            raw: job,
          }) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
      const result = await client.fetchJobs(config, { since: sameTime });

      // Should include all jobs with exactly the same timestamp (inclusive)
      expect(result.jobs).toHaveLength(4); // Jobs 2, 3, 4, 5
      expect(result.jobs.map((j) => j.id)).toEqual(['2', '3', '4', '5']);
    });

    it('should handle response with non-array jobs field gracefully', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ jobs: null }), // Non-array value
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs || [], // Handle null/undefined
        transformer: (_job: any) => ({}) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
      const result = await client.fetchJobs(config);

      expect(result.jobs).toHaveLength(0);
      expect(result.metadata.totalCount).toBe(0);
    });
  });

  describe('Error Handling - Retryable Errors', () => {
    it('should mark 500 errors as retryable', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (_job: any) => ({}) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };

      try {
        await client.fetchJobs(config);
        throw new Error('Should have thrown APIError');
      } catch (error) {
        expect(error).toBeInstanceOf(APIError);
        expect((error as APIError).statusCode).toBe(500);
        expect((error as APIError).retryable).toBe(true);
      }
    });

    it('should mark 429 rate limit errors as retryable', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests',
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (_job: any) => ({}) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };

      try {
        await client.fetchJobs(config);
        throw new Error('Should have thrown APIError');
      } catch (error) {
        expect(error).toBeInstanceOf(APIError);
        expect((error as APIError).statusCode).toBe(429);
        expect((error as APIError).retryable).toBe(true);
      }
    });

    it('should include retryable flag in APIError', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 503,
        statusText: 'Service Unavailable',
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (_job: any) => ({}) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };

      await expect(client.fetchJobs(config)).rejects.toThrow(APIError);

      try {
        await client.fetchJobs(config);
      } catch (error) {
        expect((error as APIError).retryable).toBe(true);
      }
    });
  });

  describe('Error Handling - Non-Retryable Errors', () => {
    it('should mark 403 errors as non-retryable', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 403,
        statusText: 'Forbidden',
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (_job: any) => ({}) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };

      try {
        await client.fetchJobs(config);
        throw new Error('Should have thrown APIError');
      } catch (error) {
        expect(error).toBeInstanceOf(APIError);
        expect((error as APIError).statusCode).toBe(403);
        expect((error as APIError).retryable).toBe(false);
      }
    });

    it('should mark 401 errors as non-retryable', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (_job: any) => ({}) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };

      try {
        await client.fetchJobs(config);
        throw new Error('Should have thrown APIError');
      } catch (error) {
        expect(error).toBeInstanceOf(APIError);
        expect((error as APIError).statusCode).toBe(401);
        expect((error as APIError).retryable).toBe(false);
      }
    });
  });

  describe('Malformed Responses', () => {
    it('should handle JSON parse errors gracefully', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => {
          throw new Error('Invalid JSON');
        },
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs,
        transformer: (_job: any) => ({}) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };

      await expect(client.fetchJobs(config)).rejects.toThrow(APIError);
      await expect(client.fetchJobs(config)).rejects.toThrow(
        'Failed to fetch Test jobs: Invalid JSON'
      );
    });

    it('should handle empty response body', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({}), // Empty object, no jobs field
      });

      const client = createAPIClient({
        name: 'Test',
        buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
        extractJobs: (response: any) => response.jobs || [], // Handle missing jobs field
        transformer: (_job: any) => ({}) as Job,
        getIdentifier: (config: GreenhouseConfig) => config.boardToken,
        validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
      });

      const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
      const result = await client.fetchJobs(config);

      expect(result.jobs).toHaveLength(0);
      expect(result.metadata.totalCount).toBe(0);
    });
  });
});
