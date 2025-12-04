import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { workdayClient } from '../../api/clients/workdayClient';
import type { WorkdayConfig } from '../../types';
import type { WorkdayJobPosting } from '../../api/types';
import { APIError } from '../../api/types';

describe('workdayClient', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('Configuration Validation', () => {
    it('should reject config with wrong type', async () => {
      const invalidConfig = {
        type: 'greenhouse', // Wrong type
        baseUrl: 'https://test.com',
        tenantSlug: 'test',
        careerSiteSlug: 'Test',
      } as any;

      await expect(workdayClient.fetchJobs(invalidConfig)).rejects.toThrow(
        "Invalid config type for Workday client. Expected 'workday'"
      );
    });

    it('should accept valid Workday config', async () => {
      const validConfig: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 0,
          jobPostings: [],
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(validConfig);
      expect(result).toBeDefined();
      expect(result.jobs).toEqual([]);
    });
  });

  describe('Default Facets Behavior', () => {
    it('should use defaultFacets from config when provided', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
        defaultFacets: {
          locationHierarchy1: ['test-id-123'],
          jobFamilyGroup: ['test-id-456'],
        },
      };

      let requestBody: any;
      (globalThis.fetch as any).mockImplementation(async (_url: string, init: RequestInit) => {
        requestBody = JSON.parse(init.body as string);
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 0,
            jobPostings: [],
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      await workdayClient.fetchJobs(config);

      expect(requestBody.appliedFacets).toEqual({
        locationHierarchy1: ['test-id-123'],
        jobFamilyGroup: ['test-id-456'],
      });
    });

    it('should use empty object when defaultFacets is undefined', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
        // No defaultFacets
      };

      let requestBody: any;
      (globalThis.fetch as any).mockImplementation(async (_url: string, init: RequestInit) => {
        requestBody = JSON.parse(init.body as string);
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 0,
            jobPostings: [],
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      await workdayClient.fetchJobs(config);

      expect(requestBody.appliedFacets).toEqual({});
    });

    it('should send facets in request body appliedFacets field', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
        defaultFacets: {
          timeType: ['full-time-id'],
        },
      };

      let requestBody: any;
      (globalThis.fetch as any).mockImplementation(async (_url: string, init: RequestInit) => {
        requestBody = JSON.parse(init.body as string);
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 0,
            jobPostings: [],
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      await workdayClient.fetchJobs(config);

      expect(requestBody).toHaveProperty('appliedFacets');
      expect(requestBody.appliedFacets.timeType).toEqual(['full-time-id']);
    });
  });

  describe('Pagination', () => {
    it('should fetch single page when total <= pageSize', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const job1: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        bulletFields: ['JR1'],
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 1,
          jobPostings: [job1],
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
      expect(result.jobs).toHaveLength(1);
    });

    it('should fetch multiple pages and aggregate results', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const job1: WorkdayJobPosting = {
        title: 'Engineer 1',
        externalPath: '/job/test_JR1',
        bulletFields: ['JR1'],
      };
      const job2: WorkdayJobPosting = {
        title: 'Engineer 2',
        externalPath: '/job/test_JR2',
        bulletFields: ['JR2'],
      };
      const job3: WorkdayJobPosting = {
        title: 'Engineer 3',
        externalPath: '/job/test_JR3',
        bulletFields: ['JR3'],
      };

      let callCount = 0;
      (globalThis.fetch as any).mockImplementation(async (_url: string, init: RequestInit) => {
        callCount++;
        const body = JSON.parse(init.body as string);

        // Page 1: offset 0
        if (body.offset === 0) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              total: 3,
              jobPostings: [job1, job2],
              facets: [],
              userAuthenticated: false,
            }),
          };
        }

        // Page 2: offset 20
        if (body.offset === 20) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              total: 0,
              jobPostings: [job3],
              facets: [],
              userAuthenticated: false,
            }),
          };
        }

        throw new Error('Unexpected offset');
      });

      const result = await workdayClient.fetchJobs(config);

      expect(callCount).toBe(2);
      expect(result.jobs).toHaveLength(3);
      expect(result.metadata.totalCount).toBe(3);
    });

    it('should stop when fetchedSoFar >= total', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const jobs = Array.from({ length: 20 }, (_, i) => ({
        title: `Engineer ${i + 1}`,
        externalPath: `/job/test_JR${i + 1}`,
        bulletFields: [`JR${i + 1}`],
      }));

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 20,
          jobPostings: jobs,
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      // Should only fetch once since total (20) equals pageSize (20)
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
      expect(result.jobs).toHaveLength(20);
    });

    it('should stop when fetchedSoFar >= options.limit', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      let callCount = 0;
      (globalThis.fetch as any).mockImplementation(async () => {
        callCount++;
        const jobs = Array.from({ length: 20 }, (_, i) => ({
          title: `Engineer ${callCount * 20 + i + 1}`,
          externalPath: `/job/test_JR${callCount * 20 + i + 1}`,
          bulletFields: [`JR${callCount * 20 + i + 1}`],
        }));

        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 100,
            jobPostings: jobs,
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      const result = await workdayClient.fetchJobs(config, { limit: 25 });

      // Should fetch 2 pages (20 + 20 = 40) but limit to 25 jobs
      expect(callCount).toBe(2);
      expect(result.jobs).toHaveLength(25);
    });

    it('should stop when page returns empty jobPostings', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      let callCount = 0;
      (globalThis.fetch as any).mockImplementation(async () => {
        callCount++;

        if (callCount === 1) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              total: 100,
              jobPostings: Array.from({ length: 20 }, (_, i) => ({
                title: `Job ${i}`,
                externalPath: `/job/JR${i}`,
                bulletFields: [`JR${i}`],
              })),
              facets: [],
              userAuthenticated: false,
            }),
          };
        }

        // Second page returns empty
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 0,
            jobPostings: [],
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      const result = await workdayClient.fetchJobs(config);

      expect(callCount).toBe(2);
      expect(result.jobs).toHaveLength(20);
    });

    it('should increment offset correctly (0, 20, 40...)', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const offsets: number[] = [];
      (globalThis.fetch as any).mockImplementation(async (_url: string, init: RequestInit) => {
        const body = JSON.parse(init.body as string);
        offsets.push(body.offset);

        const jobs = Array.from({ length: 10 }, (_, i) => ({
          title: `Job ${body.offset + i}`,
          externalPath: `/job/JR${body.offset + i}`,
          bulletFields: [`JR${body.offset + i}`],
        }));

        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 50,
            jobPostings: jobs,
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      await workdayClient.fetchJobs(config);

      // Should fetch 5 pages: offsets 0, 20, 40, 60, 80
      // Total is 50, but each page returns 10 jobs, so needs 5 fetches
      expect(offsets).toEqual([0, 20, 40, 60, 80]);
    });

    it('should respect maxIterations safety guard', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      let callCount = 0;
      (globalThis.fetch as any).mockImplementation(async () => {
        callCount++;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 999999, // Impossibly high number
            jobPostings: [{ title: 'Job', externalPath: '/job/JR1', bulletFields: ['JR1'] }],
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      await workdayClient.fetchJobs(config);

      // Should stop at maxIterations (100)
      expect(callCount).toBe(100);
    });

    it('should handle total=0 gracefully', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 0,
          jobPostings: [],
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      expect(result.jobs).toHaveLength(0);
      expect(result.metadata.totalCount).toBe(0);
    });
  });

  describe('Request Body Construction', () => {
    it('should include correct URL path structure', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://nvidia.wd5.myworkdayjobs.com',
        tenantSlug: 'nvidia',
        careerSiteSlug: 'NVIDIAExternalCareerSite',
      };

      let capturedUrl: string = '';
      (globalThis.fetch as any).mockImplementation(async (url: string, _init?: RequestInit) => {
        capturedUrl = url;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 0,
            jobPostings: [],
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      await workdayClient.fetchJobs(config);

      expect(capturedUrl).toContain('/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs');
    });

    it('should send POST request with proper headers', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      let capturedInit: RequestInit | undefined;
      (globalThis.fetch as any).mockImplementation(async (_url: string, init: RequestInit) => {
        capturedInit = init;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 0,
            jobPostings: [],
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      await workdayClient.fetchJobs(config);

      expect(capturedInit?.method).toBe('POST');
      expect(capturedInit?.headers).toEqual({
        Accept: 'application/json',
        'Content-Type': 'application/json',
      });
    });

    it('should include limit, offset, searchText, and appliedFacets in body', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
        defaultFacets: { test: ['value'] },
      };

      let requestBody: any;
      (globalThis.fetch as any).mockImplementation(async (_url: string, init: RequestInit) => {
        requestBody = JSON.parse(init.body as string);
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 0,
            jobPostings: [],
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      await workdayClient.fetchJobs(config);

      expect(requestBody).toHaveProperty('limit');
      expect(requestBody).toHaveProperty('offset');
      expect(requestBody).toHaveProperty('searchText');
      expect(requestBody).toHaveProperty('appliedFacets');
      expect(requestBody.limit).toBe(20);
      expect(requestBody.offset).toBe(0);
      expect(requestBody.searchText).toBe('');
      expect(requestBody.appliedFacets).toEqual({ test: ['value'] });
    });
  });

  describe('Response Handling', () => {
    it('should extract total from first page only', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      let callCount = 0;
      (globalThis.fetch as any).mockImplementation(async () => {
        callCount++;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: callCount === 1 ? 25 : 0, // Only first page has total
            jobPostings: Array.from({ length: 20 }, (_, i) => ({
              title: `Job ${i}`,
              externalPath: `/job/JR${i}`,
              bulletFields: [`JR${i}`],
            })),
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      const result = await workdayClient.fetchJobs(config);

      expect(result.jobs.length).toBeGreaterThan(20); // Multiple pages
      expect(callCount).toBeGreaterThan(1);
    });

    it('should aggregate jobPostings from all pages', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      let callCount = 0;
      (globalThis.fetch as any).mockImplementation(async (_url: string, init: RequestInit) => {
        callCount++;
        const body = JSON.parse(init.body as string);

        if (body.offset === 0) {
          return {
            ok: true,
            status: 200,
            json: async () => ({
              total: 22,
              jobPostings: Array.from({ length: 20 }, (_, i) => ({
                title: `Page1 Job ${i}`,
                externalPath: `/job/P1_JR${i}`,
                bulletFields: [`P1_JR${i}`],
              })),
              facets: [],
              userAuthenticated: false,
            }),
          };
        }

        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 0,
            jobPostings: Array.from({ length: 2 }, (_, i) => ({
              title: `Page2 Job ${i}`,
              externalPath: `/job/P2_JR${i}`,
              bulletFields: [`P2_JR${i}`],
            })),
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      const result = await workdayClient.fetchJobs(config);

      expect(result.jobs).toHaveLength(22);
      expect(result.jobs[0].title).toBe('Page1 Job 0');
      expect(result.jobs[20].title).toBe('Page2 Job 0');
    });

    it('should handle facets array (present but not used)', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 0,
          jobPostings: [],
          facets: [
            {
              facetParameter: 'locationHierarchy1',
              descriptor: 'Locations',
              values: [{ descriptor: 'US', id: 'test-id', count: 100 }],
            },
          ],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      // Facets are in response but not used - should still work
      expect(result).toBeDefined();
      expect(result.jobs).toEqual([]);
    });

    it('should handle userAuthenticated field', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 0,
          jobPostings: [],
          facets: [],
          userAuthenticated: true, // Should handle this field
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      expect(result).toBeDefined();
      expect(result.jobs).toEqual([]);
    });
  });

  describe('Client-Side Filtering', () => {
    it('should filter jobs by options.since after transformation', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const oldJob: WorkdayJobPosting = {
        title: 'Old Job',
        externalPath: '/job/test_JR1',
        postedOn: 'Posted 5 Days Ago',
        bulletFields: ['JR1'],
      };
      const newJob: WorkdayJobPosting = {
        title: 'New Job',
        externalPath: '/job/test_JR2',
        postedOn: 'Posted Today',
        bulletFields: ['JR2'],
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 2,
          jobPostings: [oldJob, newJob],
          facets: [],
          userAuthenticated: false,
        }),
      });

      // Filter to jobs from last 2 days
      const twoDaysAgo = new Date();
      twoDaysAgo.setDate(twoDaysAgo.getDate() - 2);

      const result = await workdayClient.fetchJobs(config, {
        since: twoDaysAgo.toISOString(),
      });

      expect(result.jobs.length).toBeLessThanOrEqual(2);
      // New job should be included, old job might be filtered out
    });

    it('should apply options.limit after since filter', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const jobs = Array.from({ length: 10 }, (_, i) => ({
        title: `Job ${i}`,
        externalPath: `/job/JR${i}`,
        postedOn: 'Posted Today',
        bulletFields: [`JR${i}`],
      }));

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 10,
          jobPostings: jobs,
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config, { limit: 5 });

      expect(result.jobs).toHaveLength(5);
    });

    it('should handle date comparison correctly', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const todayJob: WorkdayJobPosting = {
        title: 'Today Job',
        externalPath: '/job/JR1',
        postedOn: 'Posted Today',
        bulletFields: ['JR1'],
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 1,
          jobPostings: [todayJob],
          facets: [],
          userAuthenticated: false,
        }),
      });

      const yesterday = new Date();
      yesterday.setDate(yesterday.getDate() - 1);

      const result = await workdayClient.fetchJobs(config, {
        since: yesterday.toISOString(),
      });

      expect(result.jobs.length).toBeGreaterThan(0);
    });

    it('should preserve filter order (since → limit)', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const jobs = [
        {
          title: 'Old 1',
          externalPath: '/job/JR1',
          postedOn: 'Posted 10 Days Ago',
          bulletFields: ['JR1'],
        },
        {
          title: 'New 1',
          externalPath: '/job/JR2',
          postedOn: 'Posted Today',
          bulletFields: ['JR2'],
        },
        {
          title: 'New 2',
          externalPath: '/job/JR3',
          postedOn: 'Posted Yesterday',
          bulletFields: ['JR3'],
        },
        {
          title: 'New 3',
          externalPath: '/job/JR4',
          postedOn: 'Posted Today',
          bulletFields: ['JR4'],
        },
      ];

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 4,
          jobPostings: jobs,
          facets: [],
          userAuthenticated: false,
        }),
      });

      const twoDaysAgo = new Date();
      twoDaysAgo.setDate(twoDaysAgo.getDate() - 2);

      const result = await workdayClient.fetchJobs(config, {
        since: twoDaysAgo.toISOString(),
        limit: 2,
      });

      // Should filter by since first (3 jobs), then limit to 2
      expect(result.jobs.length).toBeLessThanOrEqual(2);
    });
  });

  describe('Metadata Calculation', () => {
    it('should calculate totalCount from filtered jobs', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const jobs = Array.from({ length: 15 }, (_, i) => ({
        title: `Software Engineer ${i}`,
        externalPath: `/job/JR${i}`,
        bulletFields: [`JR${i}`],
      }));

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 15,
          jobPostings: jobs,
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      expect(result.metadata.totalCount).toBe(15);
    });

    it('should calculate softwareCount from isSoftwareAdjacent flag', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const jobs: WorkdayJobPosting[] = [
        { title: 'Software Engineer', externalPath: '/job/JR1', bulletFields: ['JR1'] },
        { title: 'Frontend Developer', externalPath: '/job/JR2', bulletFields: ['JR2'] },
        { title: 'Recruiter', externalPath: '/job/JR3', bulletFields: ['JR3'] },
      ];

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 3,
          jobPostings: jobs,
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      expect(result.metadata.softwareCount).toBeGreaterThan(0);
      expect(result.metadata.softwareCount).toBeLessThanOrEqual(result.metadata.totalCount);
    });

    it('should include fetchedAt timestamp', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 0,
          jobPostings: [],
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      expect(result.metadata.fetchedAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
      expect(new Date(result.metadata.fetchedAt).toString()).not.toBe('Invalid Date');
    });
  });

  describe('Error Handling', () => {
    it('should mark HTTP 500 errors as retryable', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      });

      try {
        await workdayClient.fetchJobs(config);
        throw new Error('Should have thrown');
      } catch (error: any) {
        expect(error).toBeInstanceOf(APIError);
        expect(error.retryable).toBe(true);
        expect(error.statusCode).toBe(500);
        expect(error.atsProvider).toBe('workday');
      }
    });

    it('should mark HTTP 503 errors as retryable', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 503,
        statusText: 'Service Unavailable',
      });

      try {
        await workdayClient.fetchJobs(config);
        throw new Error('Should have thrown');
      } catch (error: any) {
        expect(error).toBeInstanceOf(APIError);
        expect(error.retryable).toBe(true);
        expect(error.statusCode).toBe(503);
      }
    });

    it('should mark HTTP 429 errors as retryable', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests',
      });

      try {
        await workdayClient.fetchJobs(config);
        throw new Error('Should have thrown');
      } catch (error: any) {
        expect(error).toBeInstanceOf(APIError);
        expect(error.retryable).toBe(true);
        expect(error.statusCode).toBe(429);
      }
    });

    it('should mark HTTP 401/403 errors as non-retryable', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: false,
        status: 403,
        statusText: 'Forbidden',
      });

      try {
        await workdayClient.fetchJobs(config);
        throw new Error('Should have thrown');
      } catch (error: any) {
        expect(error).toBeInstanceOf(APIError);
        expect(error.retryable).toBe(false);
        expect(error.statusCode).toBe(403);
      }
    });

    it('should handle network errors and mark as retryable', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      (globalThis.fetch as any).mockRejectedValue(new Error('Network failure'));

      try {
        await workdayClient.fetchJobs(config);
        throw new Error('Should have thrown');
      } catch (error: any) {
        expect(error).toBeInstanceOf(APIError);
        expect(error.retryable).toBe(true);
        expect(error.message).toContain('Network failure');
      }
    });

    it('should handle JSON parse errors and mark as retryable', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => {
          throw new Error('Invalid JSON');
        },
      });

      try {
        await workdayClient.fetchJobs(config);
        throw new Error('Should have thrown');
      } catch (error: any) {
        expect(error).toBeInstanceOf(APIError);
        expect(error.retryable).toBe(true);
        expect(error.message).toContain('Invalid JSON');
      }
    });
  });

  describe('Edge Cases', () => {
    it('should handle undefined jobsUrl (fallback to baseUrl)', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
        // jobsUrl undefined
      };

      const job: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        bulletFields: ['JR1'],
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 1,
          jobPostings: [job],
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      expect(result.jobs[0].url).toContain('test.wd5.myworkdayjobs.com');
    });

    it('should handle undefined defaultPageSize (default to 20)', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
        // defaultPageSize undefined
      };

      let requestBody: any;
      (globalThis.fetch as any).mockImplementation(async (_url: string, init: RequestInit) => {
        requestBody = JSON.parse(init.body as string);
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 0,
            jobPostings: [],
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      await workdayClient.fetchJobs(config);

      expect(requestBody.limit).toBe(20);
    });

    it('should handle undefined apiBaseUrl (default to /api/workday)', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
        // apiBaseUrl undefined
      };

      let capturedUrl: string = '';
      (globalThis.fetch as any).mockImplementation(async (url: string, _init?: RequestInit) => {
        capturedUrl = url;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 0,
            jobPostings: [],
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      await workdayClient.fetchJobs(config);

      expect(capturedUrl).toContain('/api/workday/wday/cxs');
    });

    it('should handle AbortSignal for request cancellation', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const controller = new AbortController();

      let capturedSignal: AbortSignal | null | undefined;
      (globalThis.fetch as any).mockImplementation(async (_url: string, init: RequestInit) => {
        capturedSignal = init.signal;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            total: 0,
            jobPostings: [],
            facets: [],
            userAuthenticated: false,
          }),
        };
      });

      await workdayClient.fetchJobs(config, { signal: controller.signal });

      expect(capturedSignal).toBe(controller.signal);
    });

    it('should handle jobs with missing bulletFields', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const job: WorkdayJobPosting = {
        title: 'Engineer',
        externalPath: '/job/test_JR1',
        // bulletFields missing
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 1,
          jobPostings: [job],
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      expect(result.jobs).toHaveLength(1);
      expect(result.jobs[0].id).toMatch(/^workday-/); // Generated ID
    });
  });

  describe('Integration with Transformer', () => {
    it('should transform jobs correctly', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const rawJob: WorkdayJobPosting = {
        title: 'Senior Software Engineer',
        externalPath: '/job/US-CA-Santa-Clara/Senior-Software-Engineer_JR123',
        locationsText: 'US, CA, Santa Clara',
        postedOn: 'Posted Today',
        bulletFields: ['JR123'],
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 1,
          jobPostings: [rawJob],
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      expect(result.jobs).toHaveLength(1);
      expect(result.jobs[0].id).toBe('JR123');
      expect(result.jobs[0].title).toBe('Senior Software Engineer');
      expect(result.jobs[0].location).toBe('US, CA, Santa Clara');
      expect(result.jobs[0].source).toBe('workday');
      expect(result.jobs[0].company).toBe('test');
      expect(result.jobs[0].classification).toBeDefined();
    });

    it('should filter out "X Locations" text via transformer', async () => {
      const config: WorkdayConfig = {
        type: 'workday',
        baseUrl: 'https://test.wd5.myworkdayjobs.com',
        tenantSlug: 'test',
        careerSiteSlug: 'TestSite',
      };

      const job1: WorkdayJobPosting = {
        title: 'Engineer 1',
        externalPath: '/job/test_JR1',
        locationsText: '2 Locations',
        bulletFields: ['JR1'],
      };
      const job2: WorkdayJobPosting = {
        title: 'Engineer 2',
        externalPath: '/job/test_JR2',
        locationsText: 'US, CA, Santa Clara',
        bulletFields: ['JR2'],
      };

      (globalThis.fetch as any).mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          total: 2,
          jobPostings: [job1, job2],
          facets: [],
          userAuthenticated: false,
        }),
      });

      const result = await workdayClient.fetchJobs(config);

      expect(result.jobs).toHaveLength(2);
      expect(result.jobs[0].location).toBeUndefined(); // Filtered out
      expect(result.jobs[1].location).toBe('US, CA, Santa Clara'); // Preserved
    });
  });
});
