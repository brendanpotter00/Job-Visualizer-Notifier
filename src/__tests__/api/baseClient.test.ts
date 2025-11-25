import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { createAPIClient } from '../../api/baseClient';
import type { Job, GreenhouseConfig } from '../../types';
import { APIError } from '../../api/types';

describe('createAPIClient', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('should create a client with fetchJobs method', () => {
    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (job: any, identifier: string) => ({
        id: job.id,
        source: 'greenhouse',
        company: identifier,
        title: job.title,
        createdAt: job.createdAt,
        url: job.url,
        classification: {
          isSoftwareAdjacent: false,
          category: 'nonTech',
          confidence: 0,
          matchedKeywords: [],
        },
        raw: job,
      } as Job),
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
      transformer: (job: any) => ({} as Job),
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const invalidConfig = { type: 'lever' as const, companyId: 'test', jobsUrl: 'http://test.com' };

    await expect(client.fetchJobs(invalidConfig)).rejects.toThrow('Invalid config type for Test client');
  });

  it('should successfully fetch and transform jobs', async () => {
    const mockJobs = [
      { id: '1', title: 'Engineer', createdAt: '2025-01-01T00:00:00Z', url: 'http://test.com/1' },
      { id: '2', title: 'Designer', createdAt: '2025-01-02T00:00:00Z', url: 'http://test.com/2' },
    ];

    (global.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ jobs: mockJobs }),
    });

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (job: any, identifier: string) => ({
        id: job.id,
        source: 'greenhouse' as const,
        company: identifier,
        title: job.title,
        createdAt: job.createdAt,
        url: job.url,
        classification: {
          isSoftwareAdjacent: job.title.includes('Engineer'),
          category: 'backend' as const,
          confidence: 0.9,
          matchedKeywords: [],
        },
        raw: job,
      } as Job),
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
    const result = await client.fetchJobs(config);

    expect(result.jobs).toHaveLength(2);
    expect(result.jobs[0].id).toBe('1');
    expect(result.jobs[0].title).toBe('Engineer');
    expect(result.metadata.totalCount).toBe(2);
    expect(result.metadata.softwareCount).toBe(1); // Only Engineer counts as software
  });

  it('should apply since filter correctly', async () => {
    const mockJobs = [
      { id: '1', createdAt: '2025-01-01T00:00:00Z' },
      { id: '2', createdAt: '2025-01-05T00:00:00Z' },
      { id: '3', createdAt: '2025-01-10T00:00:00Z' },
    ];

    (global.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ jobs: mockJobs }),
    });

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (job: any, identifier: string) => ({
        id: job.id,
        source: 'greenhouse' as const,
        company: identifier,
        title: 'Test',
        createdAt: job.createdAt,
        url: 'http://test.com',
        classification: { isSoftwareAdjacent: false, category: 'nonTech' as const, confidence: 0, matchedKeywords: [] },
        raw: job,
      } as Job),
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

    (global.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ jobs: mockJobs }),
    });

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (job: any, identifier: string) => ({
        id: job.id,
        source: 'greenhouse' as const,
        company: identifier,
        title: 'Test',
        createdAt: job.createdAt,
        url: 'http://test.com',
        classification: { isSoftwareAdjacent: false, category: 'nonTech' as const, confidence: 0, matchedKeywords: [] },
        raw: job,
      } as Job),
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
    (global.fetch as any).mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
    });

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (job: any) => ({} as Job),
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };

    await expect(client.fetchJobs(config)).rejects.toThrow(APIError);
    await expect(client.fetchJobs(config)).rejects.toThrow('Test API error: Not Found');
  });

  it('should wrap non-APIError exceptions in APIError', async () => {
    (global.fetch as any).mockRejectedValue(new Error('Network failure'));

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (job: any) => ({} as Job),
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };

    await expect(client.fetchJobs(config)).rejects.toThrow(APIError);
    await expect(client.fetchJobs(config)).rejects.toThrow('Failed to fetch Test jobs: Network failure');
  });

  it('should pass signal to fetch for cancellation support', async () => {
    (global.fetch as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ jobs: [] }),
    });

    const client = createAPIClient({
      name: 'Test',
      buildUrl: (config: GreenhouseConfig) => `https://api.test.com/${config.boardToken}`,
      extractJobs: (response: any) => response.jobs,
      transformer: (job: any) => ({} as Job),
      getIdentifier: (config: GreenhouseConfig) => config.boardToken,
      validateConfig: (config): config is GreenhouseConfig => config.type === 'greenhouse',
    });

    const config: GreenhouseConfig = { type: 'greenhouse', boardToken: 'test-token' };
    const controller = new AbortController();

    await client.fetchJobs(config, { signal: controller.signal });

    expect(global.fetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        signal: controller.signal,
      })
    );
  });
});
