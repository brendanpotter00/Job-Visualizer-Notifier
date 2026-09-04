import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { backendScraperClient } from '../../api/clients/backendScraperClient';
import type { BackendJobListing } from '../../api/types';
import { APIError } from '../../api/types';
import type { BackendScraperConfig } from '../../types';

function makeBackendJob(overrides: Partial<BackendJobListing> = {}): BackendJobListing {
  return {
    id: 'job-1',
    title: 'Software Engineer',
    company: 'stripe',
    location: 'San Francisco, CA',
    locations: [],
    url: 'https://example.com/job/1',
    sourceId: 'greenhouse',
    details: JSON.stringify({ experience_level: 'L4', is_remote_eligible: true }),
    createdAt: '2026-05-01T00:00:00Z',
    postedOn: '2026-05-01T00:00:00Z',
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt: '2026-05-01T00:00:00Z',
    lastSeenAt: '2026-05-17T00:00:00Z',
    consecutiveMisses: 0,
    detailsScraped: true,
    ...overrides,
  };
}

function makeConfig(overrides: Partial<BackendScraperConfig> = {}): BackendScraperConfig {
  return {
    type: 'backend-scraper',
    companyId: 'stripe',
    apiBaseUrl: '/api/jobs',
    ...overrides,
  };
}

/**
 * `backendScraperClient.fetchJobs` is the single-company read used by the
 * Companies / hiring-trend page (via the `getJobsForCompany` RTK Query
 * endpoint). It is unrelated to the Recent page, which now filters server-side
 * through `GET /api/jobs/search`.
 */
describe('backendScraperClient.fetchJobs', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  function okResponse(rows: BackendJobListing[]) {
    return {
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => rows,
    };
  }

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('rejects a config belonging to a different ATS', async () => {
    // The client is selected by ATS type upstream; a mismatch here means the
    // selection table is wrong, so fail loudly rather than build a bogus URL.
    const wrongConfig = { type: 'greenhouse', companyId: 'stripe' } as unknown as BackendScraperConfig;

    await expect(backendScraperClient.fetchJobs(wrongConfig)).rejects.toThrow(
      /Invalid config type for Backend Scraper client/
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('requests only OPEN jobs for the configured company', async () => {
    fetchMock.mockResolvedValueOnce(okResponse([]));

    await backendScraperClient.fetchJobs(makeConfig({ companyId: 'airbnb' }));

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain('/api/jobs?');
    expect(url).toContain('company=airbnb');
    expect(url).toContain('status=OPEN');
    // Default cap keeps a single company's full board in one response.
    expect(url).toContain('limit=5000');
  });

  it('honors an explicit limit override', async () => {
    fetchMock.mockResolvedValueOnce(okResponse([]));

    await backendScraperClient.fetchJobs(makeConfig(), { limit: 25 });

    expect(String(fetchMock.mock.calls[0][0])).toContain('limit=25');
  });

  it('falls back to the default /api/jobs base when apiBaseUrl is absent', async () => {
    fetchMock.mockResolvedValueOnce(okResponse([]));

    await backendScraperClient.fetchJobs({ type: 'backend-scraper', companyId: 'stripe' });

    expect(String(fetchMock.mock.calls[0][0]).startsWith('/api/jobs?')).toBe(true);
  });

  it('forwards the caller AbortSignal so RTK Query can cancel the fetch', async () => {
    fetchMock.mockResolvedValueOnce(okResponse([]));
    const controller = new AbortController();

    await backendScraperClient.fetchJobs(makeConfig(), { signal: controller.signal });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.signal).toBe(controller.signal);
  });

  it('transforms rows to the internal Job model and stamps the requested company id', async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse([
        makeBackendJob({ id: 'a1', company: 'stripe' }),
        makeBackendJob({ id: 'a2', company: 'stripe', title: 'SRE' }),
      ])
    );

    const result = await backendScraperClient.fetchJobs(makeConfig({ companyId: 'stripe' }));

    expect(result.jobs.map((j) => j.id)).toEqual(['a1', 'a2']);
    expect(result.jobs[0].source).toBe('backend-scraper');
    expect(result.jobs[0].company).toBe('stripe');
    expect(result.metadata.totalCount).toBe(2);
    expect(result.metadata.fetchedAt).toBeTruthy();
  });

  it('returns an empty result set rather than throwing when the board has no jobs', async () => {
    fetchMock.mockResolvedValueOnce(okResponse([]));

    const result = await backendScraperClient.fetchJobs(makeConfig());

    expect(result.jobs).toEqual([]);
    expect(result.metadata.totalCount).toBe(0);
  });

  it('drops jobs older than `since` and counts only what survives', async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse([
        makeBackendJob({ id: 'old', postedOn: '2026-01-01T00:00:00Z' }),
        makeBackendJob({ id: 'new', postedOn: '2026-06-01T00:00:00Z' }),
      ])
    );

    const result = await backendScraperClient.fetchJobs(makeConfig(), {
      since: '2026-03-01T00:00:00Z',
    });

    expect(result.jobs.map((j) => j.id)).toEqual(['new']);
    // totalCount reflects the filtered list, not the wire payload — the graph's
    // job counts are read straight off this number.
    expect(result.metadata.totalCount).toBe(1);
  });

  it('keeps a job posted exactly at the `since` boundary (inclusive)', async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse([makeBackendJob({ id: 'edge', postedOn: '2026-03-01T00:00:00Z' })])
    );

    const result = await backendScraperClient.fetchJobs(makeConfig(), {
      since: '2026-03-01T00:00:00Z',
    });

    expect(result.jobs.map((j) => j.id)).toEqual(['edge']);
  });

  it('throws a non-retryable APIError on a 4xx response', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: async () => ({}),
    });

    try {
      await backendScraperClient.fetchJobs(makeConfig());
      throw new Error('expected APIError');
    } catch (err) {
      expect(err).toBeInstanceOf(APIError);
      expect((err as APIError).statusCode).toBe(404);
      // A missing company will never succeed on retry — don't burn attempts.
      expect((err as APIError).retryable).toBe(false);
    }
  });

  it('marks 5xx and 429 responses as retryable', async () => {
    for (const status of [500, 503, 429]) {
      fetchMock.mockResolvedValueOnce({
        ok: false,
        status,
        statusText: 'Boom',
        json: async () => ({}),
      });

      try {
        await backendScraperClient.fetchJobs(makeConfig());
        throw new Error(`expected APIError for ${status}`);
      } catch (err) {
        expect(err).toBeInstanceOf(APIError);
        expect((err as APIError).statusCode).toBe(status);
        expect((err as APIError).retryable).toBe(true);
      }
    }
  });

  it('wraps network errors in a retryable APIError', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));

    try {
      await backendScraperClient.fetchJobs(makeConfig());
      throw new Error('expected APIError');
    } catch (err) {
      expect(err).toBeInstanceOf(APIError);
      expect((err as APIError).retryable).toBe(true);
      expect((err as APIError).atsProvider).toBe('backend-scraper');
    }
  });

  it('does not re-wrap an APIError it already threw (status survives the catch)', async () => {
    // The try/catch around the whole body would otherwise swallow the HTTP
    // status and report every failure as an untyped network error.
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      statusText: 'Bad Gateway',
      json: async () => ({}),
    });

    await expect(backendScraperClient.fetchJobs(makeConfig())).rejects.toMatchObject({
      statusCode: 502,
    });
  });
});
