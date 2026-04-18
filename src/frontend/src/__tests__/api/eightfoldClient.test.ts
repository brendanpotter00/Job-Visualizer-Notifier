import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { eightfoldClient } from '../../api/clients/eightfoldClient';
import type { EightfoldConfig } from '../../types';
import type { EightfoldJobPosition } from '../../api/types';
import { APIError } from '../../api/types';

function makeConfig(overrides: Partial<EightfoldConfig> = {}): EightfoldConfig {
  return {
    type: 'eightfold',
    companyId: 'netflix',
    tenantHost: 'explore.jobs.netflix.net',
    domain: 'netflix.com',
    ...overrides,
  };
}

function makePosition(
  id: number,
  overrides: Partial<EightfoldJobPosition> = {}
): EightfoldJobPosition {
  return {
    id,
    name: `Job ${id}`,
    location: 'Los Angeles,California,United States of America',
    department: 'Engineering',
    t_create: 1700000000,
    t_update: 1700000000,
    ats_job_id: `JR${id}`,
    display_job_id: `JR${id}`,
    type: 'ATS',
    work_location_option: 'onsite',
    canonicalPositionUrl: `https://explore.jobs.netflix.net/careers/job/${id}`,
    isPrivate: false,
    ...overrides,
  };
}

describe('eightfoldClient', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('Configuration Validation', () => {
    it('rejects configs with the wrong type', async () => {
      const invalidConfig = {
        type: 'greenhouse',
        tenantHost: 'explore.jobs.netflix.net',
        domain: 'netflix.com',
      } as unknown as EightfoldConfig;

      await expect(eightfoldClient.fetchJobs(invalidConfig)).rejects.toThrow(
        "Invalid config type for Eightfold client. Expected 'eightfold'"
      );
    });

    it('accepts a valid Eightfold config', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ positions: [], count: 0 }),
      });

      const result = await eightfoldClient.fetchJobs(makeConfig());
      expect(result).toBeDefined();
      expect(result.jobs).toEqual([]);
    });
  });

  describe('Single Page Results', () => {
    it('returns a single page when count fits within pageSize', async () => {
      const positions = Array.from({ length: 5 }, (_, i) => makePosition(i + 1));
      (globalThis.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ positions, count: 5 }),
      });

      const result = await eightfoldClient.fetchJobs(makeConfig());

      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
      expect(result.jobs).toHaveLength(5);
      expect(result.jobs[0].source).toBe('eightfold');
      expect(result.jobs[0].company).toBe('netflix');
    });
  });

  describe('Pagination', () => {
    it('fetches multiple pages with correct start offsets (0, 10, 20)', async () => {
      const seenStarts: number[] = [];
      (globalThis.fetch as any).mockImplementation(async (url: string) => {
        const u = new URL(url, 'http://localhost');
        const start = Number(u.searchParams.get('start'));
        seenStarts.push(start);
        const page = Array.from({ length: 10 }, (_, i) => makePosition(start + i + 1));
        return {
          ok: true,
          status: 200,
          json: async () => ({ positions: page, count: 25 }),
        };
      });

      const result = await eightfoldClient.fetchJobs(makeConfig());

      // count=25 → 10 + 10 + 5. Third page has 5 (<pageSize) → stop after third page.
      // But our mock returns 10 every time. The client stops when fetchedSoFar >= total.
      // So we expect 3 pages: starts 0, 10, 20. fetchedSoFar after page 3 = 30 >= 25.
      expect(seenStarts).toEqual([0, 10, 20]);
      expect(result.jobs).toHaveLength(30);
    });

    it('stops when a partial final page is returned (Eightfold under-reports count)', async () => {
      // Simulate a tenant where count=100 is reported but only 23 positions exist.
      const seenStarts: number[] = [];
      (globalThis.fetch as any).mockImplementation(async (url: string) => {
        const u = new URL(url, 'http://localhost');
        const start = Number(u.searchParams.get('start'));
        seenStarts.push(start);
        // Page 1 (start=0): 10, Page 2 (start=10): 10, Page 3 (start=20): 3 (partial)
        let count: number;
        if (start === 0) count = 10;
        else if (start === 10) count = 10;
        else if (start === 20) count = 3;
        else count = 0;
        const page = Array.from({ length: count }, (_, i) =>
          makePosition(start + i + 1)
        );
        return {
          ok: true,
          status: 200,
          json: async () => ({ positions: page, count: 100 }),
        };
      });

      const result = await eightfoldClient.fetchJobs(makeConfig());

      // Should stop after the partial page at start=20, even though count=100 was reported.
      expect(seenStarts).toEqual([0, 10, 20]);
      expect(result.jobs).toHaveLength(23);
    });

    it('handles an empty page defensively', async () => {
      let call = 0;
      (globalThis.fetch as any).mockImplementation(async () => {
        call++;
        if (call === 1) {
          const page = Array.from({ length: 10 }, (_, i) => makePosition(i + 1));
          return {
            ok: true,
            status: 200,
            json: async () => ({ positions: page, count: 50 }),
          };
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({ positions: [], count: 50 }),
        };
      });

      const result = await eightfoldClient.fetchJobs(makeConfig());
      expect(call).toBe(2);
      expect(result.jobs).toHaveLength(10);
    });

    it('stops when options.limit is satisfied', async () => {
      (globalThis.fetch as any).mockImplementation(async () => {
        const page = Array.from({ length: 10 }, (_, i) => makePosition(i + 1));
        return {
          ok: true,
          status: 200,
          json: async () => ({ positions: page, count: 100 }),
        };
      });

      const result = await eightfoldClient.fetchJobs(makeConfig(), { limit: 15 });
      // Two pages fetched (20 positions), but response is sliced to 15.
      expect(globalThis.fetch).toHaveBeenCalledTimes(2);
      expect(result.jobs).toHaveLength(15);
    });

    it('throws a non-retryable APIError when MAX_ITERATIONS is reached', async () => {
      // Configure the mock to always return a full page with high count and no partial.
      (globalThis.fetch as any).mockImplementation(async () => {
        const page = Array.from({ length: 10 }, (_, i) => makePosition(i + 1));
        return {
          ok: true,
          status: 200,
          json: async () => ({ positions: page, count: 99999999 }),
        };
      });

      await expect(eightfoldClient.fetchJobs(makeConfig())).rejects.toMatchObject({
        name: 'APIError',
        atsProvider: 'eightfold',
        retryable: false,
      });
      // MAX_ITERATIONS=200 → 200 fetches were issued before the throw
      expect(globalThis.fetch).toHaveBeenCalledTimes(200);
    });
  });

  describe('Filtering', () => {
    it('filters out private positions', async () => {
      const positions: EightfoldJobPosition[] = [
        makePosition(1),
        makePosition(2, { isPrivate: true }),
        makePosition(3),
      ];
      (globalThis.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ positions, count: 3 }),
      });

      const result = await eightfoldClient.fetchJobs(makeConfig());
      expect(result.jobs).toHaveLength(2);
      expect(result.jobs.map((j) => j.id)).toEqual(['1', '3']);
    });

    it('drops positions missing canonicalPositionUrl', async () => {
      const positions: EightfoldJobPosition[] = [
        makePosition(1),
        makePosition(2, { canonicalPositionUrl: undefined }),
      ];
      (globalThis.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ positions, count: 2 }),
      });

      const result = await eightfoldClient.fetchJobs(makeConfig());
      expect(result.jobs).toHaveLength(1);
      expect(result.jobs[0].id).toBe('1');
    });

    it("applies the 'since' filter on createdAt", async () => {
      // t_create of 1700000000 → 2023-11-14T22:13:20Z
      const oldJob = makePosition(1, { t_create: 1600000000 }); // 2020-09-13
      const newJob = makePosition(2, { t_create: 1700000000 }); // 2023-11-14
      (globalThis.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ positions: [oldJob, newJob], count: 2 }),
      });

      const result = await eightfoldClient.fetchJobs(makeConfig(), {
        since: '2023-01-01T00:00:00.000Z',
      });
      expect(result.jobs).toHaveLength(1);
      expect(result.jobs[0].id).toBe('2');
    });
  });

  describe('Request Construction', () => {
    it('sends X-Eightfold-Tenant-Host header on every page', async () => {
      const seenHeaders: Array<Record<string, string>> = [];
      let call = 0;
      (globalThis.fetch as any).mockImplementation(
        async (_url: string, init: RequestInit) => {
          call++;
          seenHeaders.push(init.headers as Record<string, string>);
          const page = Array.from({ length: 10 }, (_, i) => makePosition(i + 1));
          if (call === 2) {
            // partial page → stop after this
            return {
              ok: true,
              status: 200,
              json: async () => ({
                positions: page.slice(0, 3),
                count: 13,
              }),
            };
          }
          return {
            ok: true,
            status: 200,
            json: async () => ({ positions: page, count: 13 }),
          };
        }
      );

      await eightfoldClient.fetchJobs(makeConfig());
      expect(seenHeaders).toHaveLength(2);
      for (const headers of seenHeaders) {
        expect(headers['X-Eightfold-Tenant-Host']).toBe('explore.jobs.netflix.net');
        expect(headers['Accept']).toBe('application/json');
      }
    });

    it('builds the URL with correct query params', async () => {
      let capturedUrl = '';
      (globalThis.fetch as any).mockImplementation(async (url: string) => {
        capturedUrl = url;
        return {
          ok: true,
          status: 200,
          json: async () => ({ positions: [], count: 0 }),
        };
      });

      await eightfoldClient.fetchJobs(makeConfig());
      expect(capturedUrl).toContain('/api/eightfold/api/apply/v2/jobs');
      expect(capturedUrl).toContain('domain=netflix.com');
      expect(capturedUrl).toContain('num=10');
      expect(capturedUrl).toContain('start=0');
    });

    it('URL-encodes the domain param', async () => {
      let capturedUrl = '';
      (globalThis.fetch as any).mockImplementation(async (url: string) => {
        capturedUrl = url;
        return {
          ok: true,
          status: 200,
          json: async () => ({ positions: [], count: 0 }),
        };
      });

      await eightfoldClient.fetchJobs(makeConfig({ domain: 'foo bar.com' }));
      expect(capturedUrl).toContain('domain=foo%20bar.com');
    });

    it('clamps defaultPageSize to 10 (server cap)', async () => {
      let capturedUrl = '';
      (globalThis.fetch as any).mockImplementation(async (url: string) => {
        capturedUrl = url;
        return {
          ok: true,
          status: 200,
          json: async () => ({ positions: [], count: 0 }),
        };
      });

      await eightfoldClient.fetchJobs(makeConfig({ defaultPageSize: 50 }));
      expect(capturedUrl).toContain('num=10');
    });
  });

  describe('Error Handling', () => {
    it('marks 500 as retryable', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      });

      await expect(eightfoldClient.fetchJobs(makeConfig())).rejects.toMatchObject({
        name: 'APIError',
        statusCode: 500,
        retryable: true,
        atsProvider: 'eightfold',
      });
    });

    it('marks 429 as retryable', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests',
      });

      await expect(eightfoldClient.fetchJobs(makeConfig())).rejects.toMatchObject({
        statusCode: 429,
        retryable: true,
      });
    });

    it('marks 404 as non-retryable', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
      });

      await expect(eightfoldClient.fetchJobs(makeConfig())).rejects.toMatchObject({
        statusCode: 404,
        retryable: false,
      });
    });

    it('marks 401 as non-retryable', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
      });

      await expect(eightfoldClient.fetchJobs(makeConfig())).rejects.toMatchObject({
        statusCode: 401,
        retryable: false,
      });
    });

    it('wraps network errors as retryable APIError', async () => {
      (globalThis.fetch as any).mockRejectedValue(new Error('Network down'));

      try {
        await eightfoldClient.fetchJobs(makeConfig());
        throw new Error('Should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(APIError);
        expect((err as APIError).retryable).toBe(true);
        expect((err as APIError).atsProvider).toBe('eightfold');
      }
    });

    it('wraps JSON parse errors as retryable APIError', async () => {
      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => {
          throw new Error('bad json');
        },
      });

      try {
        await eightfoldClient.fetchJobs(makeConfig());
        throw new Error('Should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(APIError);
        expect((err as APIError).retryable).toBe(true);
      }
    });
  });

  describe('Abort Signal', () => {
    it('passes the signal into fetch', async () => {
      const controller = new AbortController();
      let capturedSignal: AbortSignal | undefined;
      (globalThis.fetch as any).mockImplementation(
        async (_url: string, init: RequestInit) => {
          capturedSignal = init.signal as AbortSignal;
          return {
            ok: true,
            status: 200,
            json: async () => ({ positions: [], count: 0 }),
          };
        }
      );

      await eightfoldClient.fetchJobs(makeConfig(), { signal: controller.signal });
      expect(capturedSignal).toBe(controller.signal);
    });

    it('throws AbortError instead of returning partial results when aborted between pages', async () => {
      const controller = new AbortController();
      let call = 0;
      (globalThis.fetch as any).mockImplementation(async () => {
        call++;
        if (call === 1) {
          controller.abort();
          const page = Array.from({ length: 10 }, (_, i) => makePosition(i + 1));
          return {
            ok: true,
            status: 200,
            json: async () => ({ positions: page, count: 100 }),
          };
        }
        throw new Error('Should not fetch a second page after abort');
      });

      await expect(
        eightfoldClient.fetchJobs(makeConfig(), { signal: controller.signal })
      ).rejects.toMatchObject({ name: 'AbortError' });
      expect(call).toBe(1);
    });
  });

  describe('Company Id', () => {
    it('uses the explicit companyId from config, not the domain slug', async () => {
      const positions = [makePosition(1)];
      (globalThis.fetch as any).mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ positions, count: 1 }),
      });

      const result = await eightfoldClient.fetchJobs(
        // companyId "foo-inc" intentionally diverges from domain "foocorp.com"
        // to prove the client uses the explicit field, not a domain guess.
        makeConfig({ companyId: 'foo-inc', domain: 'foocorp.com' })
      );
      expect(result.jobs[0].company).toBe('foo-inc');
    });
  });
});
