import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { fetchJobsForCompanies } from '../../api/clients/backendScraperClient';
import type { BackendJobListing } from '../../api/types';
import { APIError } from '../../api/types';

function makeBackendJob(overrides: Partial<BackendJobListing> = {}): BackendJobListing {
  return {
    id: 'job-1',
    title: 'Software Engineer',
    company: 'stripe',
    location: 'San Francisco, CA',
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

describe('fetchJobsForCompanies (batched backend scraper)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it('returns empty map without calling fetch when no company IDs are passed', async () => {
    const result = await fetchJobsForCompanies([]);
    expect(result).toEqual({});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('issues exactly one /api/jobs call regardless of company count', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => [],
    });

    await fetchJobsForCompanies(['stripe', 'airbnb', 'discord']);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/jobs?');
    expect(url).toContain('companies=stripe%2Cairbnb%2Cdiscord');
    expect(url).toContain('status=OPEN');
    expect(url).toContain('limit=50000');
  });

  it('groups response rows by company id', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => [
        makeBackendJob({ id: 'stripe-1', company: 'stripe', title: 'Stripe SWE' }),
        makeBackendJob({ id: 'stripe-2', company: 'stripe', title: 'Stripe SRE' }),
        makeBackendJob({ id: 'airbnb-1', company: 'airbnb', title: 'Airbnb SWE' }),
      ],
    });

    const result = await fetchJobsForCompanies(['stripe', 'airbnb', 'discord']);

    expect(Object.keys(result).sort()).toEqual(['airbnb', 'discord', 'stripe']);
    expect(result.stripe.jobs.length).toBe(2);
    expect(result.stripe.jobs.map((j) => j.id)).toEqual(['stripe-1', 'stripe-2']);
    expect(result.airbnb.jobs.length).toBe(1);
    expect(result.airbnb.jobs[0].id).toBe('airbnb-1');
    // Companies with no rows still get an entry (empty array) so the
    // per-company cache seeding stays uniform in getAllJobs.
    expect(result.discord.jobs).toEqual([]);
    expect(result.discord.metadata.totalCount).toBe(0);
  });

  it('assigns the requested company id to transformed jobs', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => [makeBackendJob({ id: 'stripe-1', company: 'stripe' })],
    });

    const result = await fetchJobsForCompanies(['stripe']);
    expect(result.stripe.jobs[0].company).toBe('stripe');
    expect(result.stripe.jobs[0].source).toBe('backend-scraper');
  });

  it('throws APIError on non-OK HTTP responses', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: async () => ({}),
    });

    await expect(fetchJobsForCompanies(['stripe'])).rejects.toBeInstanceOf(APIError);
  });

  it('marks 5xx and 429 errors as retryable', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 429,
      statusText: 'Too Many Requests',
      json: async () => ({}),
    });

    try {
      await fetchJobsForCompanies(['stripe']);
      throw new Error('expected APIError');
    } catch (err) {
      expect(err).toBeInstanceOf(APIError);
      expect((err as APIError).retryable).toBe(true);
      expect((err as APIError).statusCode).toBe(429);
    }
  });

  it('wraps network errors in a retryable APIError', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'));

    try {
      await fetchJobsForCompanies(['stripe']);
      throw new Error('expected APIError');
    } catch (err) {
      expect(err).toBeInstanceOf(APIError);
      expect((err as APIError).retryable).toBe(true);
    }
  });
});
