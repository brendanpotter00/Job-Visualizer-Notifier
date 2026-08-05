import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  chunkCompanyIds,
  fetchJobsForCompanies,
  fetchJobsPage,
} from '../../api/clients/backendScraperClient';
import type { BackendJobListing } from '../../api/types';
import { APIError } from '../../api/types';

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

  it('fits in a single call when company count is at or below the chunk size', async () => {
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

  it('splits requests into chunks of 50 when count exceeds chunk size', async () => {
    const ids = Array.from({ length: 102 }, (_, i) => `co${i}`);
    for (let i = 0; i < 3; i++) {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => [],
      });
    }

    const result = await fetchJobsForCompanies(ids);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const urls = fetchMock.mock.calls.map(([u]) => decodeURIComponent(String(u)));
    // Each call covers a disjoint slice of ids (50 + 50 + 2).
    expect(urls[0]).toContain('companies=co0,co1,');
    expect(urls[0]).toContain(',co49&');
    expect(urls[1]).toContain('companies=co50,co51,');
    expect(urls[1]).toContain(',co99&');
    expect(urls[2]).toContain('companies=co100,co101&');
    // All 102 ids are keys in the merged result.
    expect(Object.keys(result).length).toBe(102);
  });

  it('issues exactly two calls at 51 companies (boundary check)', async () => {
    const ids = Array.from({ length: 51 }, (_, i) => `co${i}`);
    for (let i = 0; i < 2; i++) {
      fetchMock.mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => [],
      });
    }

    await fetchJobsForCompanies(ids);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('rejects when any chunk fails (Promise.all semantics)', async () => {
    const ids = Array.from({ length: 102 }, (_, i) => `co${i}`);
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => [],
    });
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Server Error',
      json: async () => ({}),
    });
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => [],
    });

    await expect(fetchJobsForCompanies(ids)).rejects.toBeInstanceOf(APIError);
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

describe('fetchJobsPage (keyset-paginated backend scraper)', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  /** Mimic a real fetch Response: Headers.get is case-insensitive. */
  function okResponse(rows: BackendJobListing[], headers: Record<string, string> = {}) {
    return {
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: new Headers(headers),
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

  it('returns an empty page without calling fetch when no company IDs are passed', async () => {
    const page = await fetchJobsPage([]);
    expect(page).toEqual({ jobs: [], byCompanyId: {}, nextCursor: null });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('surfaces X-Next-Cursor from the response headers as nextCursor', async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse([makeBackendJob()], { 'X-Next-Cursor': 'CURSOR-ABC' })
    );

    const page = await fetchJobsPage(['stripe'], { since: '2026-05-01T00:00:00.000Z' });

    expect(page.nextCursor).toBe('CURSOR-ABC');
    expect(page.jobs).toHaveLength(1);
    expect(page.byCompanyId.stripe.jobs).toHaveLength(1);
  });

  it('reads the header case-insensitively (proxies may lowercase it)', async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse([], { 'x-next-cursor': 'CURSOR-LOWER' })
    );

    const page = await fetchJobsPage(['stripe'], { since: '2026-05-01T00:00:00.000Z' });

    expect(page.nextCursor).toBe('CURSOR-LOWER');
  });

  it('reports end-of-walk as null when the header is absent', async () => {
    fetchMock.mockResolvedValueOnce(okResponse([makeBackendJob()]));

    const page = await fetchJobsPage(['stripe'], { since: '2026-05-01T00:00:00.000Z' });

    expect(page.nextCursor).toBeNull();
  });

  it('sends since + cursor + limit and never sends offset', async () => {
    fetchMock.mockResolvedValueOnce(okResponse([]));

    await fetchJobsPage(['stripe', 'airbnb'], {
      since: '2026-05-01T00:00:00.000Z',
      cursor: 'CURSOR-ABC',
      limit: 250,
    });

    const url = decodeURIComponent(String(fetchMock.mock.calls[0][0]));
    expect(url).toContain('companies=stripe,airbnb');
    expect(url).toContain('status=OPEN');
    expect(url).toContain('since=2026-05-01T00:00:00.000Z');
    expect(url).toContain('cursor=CURSOR-ABC');
    expect(url).toContain('limit=250');
    // offset is a 422 in keyset mode — it must never be sent.
    expect(url).not.toMatch(/[?&]offset=/);
  });

  it('sends an empty cursor rather than dropping it, so the backend can 422', async () => {
    fetchMock.mockResolvedValueOnce(okResponse([]));

    await fetchJobsPage(['stripe'], { cursor: '' });

    const url = decodeURIComponent(String(fetchMock.mock.calls[0][0]));
    expect(url).toMatch(/[?&]cursor=(&|$)/);
  });

  it('groups rows per requested company, seeding companies with zero rows', async () => {
    fetchMock.mockResolvedValueOnce(
      okResponse([
        makeBackendJob({ id: 'a1', company: 'stripe' }),
        makeBackendJob({ id: 'b1', company: 'airbnb' }),
      ])
    );

    const page = await fetchJobsPage(['stripe', 'airbnb', 'discord'], {
      since: '2026-05-01T00:00:00.000Z',
    });

    expect(Object.keys(page.byCompanyId).sort()).toEqual(['airbnb', 'discord', 'stripe']);
    expect(page.byCompanyId.discord.jobs).toEqual([]);
    // The flat list preserves server order and shares Job identities with the map.
    expect(page.jobs.map((j) => j.id)).toEqual(['a1', 'b1']);
    expect(page.jobs[0]).toBe(page.byCompanyId.stripe.jobs[0]);
  });

  it('wraps HTTP errors in an APIError with retryability', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
      statusText: 'Service Unavailable',
      headers: new Headers(),
      json: async () => ({}),
    });

    await expect(fetchJobsPage(['stripe'], { since: 'x' })).rejects.toBeInstanceOf(APIError);
  });
});

describe('chunkCompanyIds', () => {
  it('partitions at 50 — the same boundary the batched fetch uses', () => {
    const ids = Array.from({ length: 102 }, (_, i) => `co${i}`);
    const chunks = chunkCompanyIds(ids);
    expect(chunks.map((c) => c.length)).toEqual([50, 50, 2]);
    // Deterministic and order-preserving: cursor bookkeeping keys off the
    // comma-joined ids, so the partition must be stable across pages.
    expect(chunks.flat()).toEqual(ids);
    expect(chunkCompanyIds(ids)).toEqual(chunks);
  });

  it('returns no chunks for an empty roster', () => {
    expect(chunkCompanyIds([])).toEqual([]);
  });
});
