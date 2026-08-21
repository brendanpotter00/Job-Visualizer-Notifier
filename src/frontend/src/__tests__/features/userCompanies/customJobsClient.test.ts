import { describe, it, expect, afterEach, vi } from 'vitest';
import { fetchMyCustomJobsPage } from '../../../features/userCompanies/customJobsClient';
import { APIError } from '../../../api/types';

const SINCE = '2026-05-23T00:00:00.000Z';

/**
 * A `GET /api/users/companies/jobs` row. The wire shape is the same
 * `BackendJobListing` `/api/jobs` returns — that sameness is the whole reason
 * both halves of the Recent feed share one transform and one keyset walk.
 */
function makeCustomRow(
  companyId: string,
  id: string,
  firstSeenAt = '2026-08-01T00:00:00.000Z',
  overrides: Record<string, unknown> = {}
) {
  return {
    id,
    title: `${companyId} role`,
    company: companyId,
    location: 'Remote',
    locations: [],
    url: `https://example.com/${id}`,
    sourceId: `custom:${companyId}`,
    details: JSON.stringify({ experience_level: 'L4', is_remote_eligible: true }),
    createdAt: firstSeenAt,
    postedOn: firstSeenAt,
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt,
    lastSeenAt: firstSeenAt,
    consecutiveMisses: 0,
    detailsScraped: true,
    ...overrides,
  };
}

function mockFetch(
  rows: unknown[],
  {
    nextCursor,
    ok = true,
    status = 200,
  }: { nextCursor?: string; ok?: boolean; status?: number } = {}
) {
  const fetchMock = vi.fn(() =>
    Promise.resolve({
      ok,
      status,
      statusText: ok ? 'OK' : 'Internal Server Error',
      headers: new Headers(nextCursor ? { 'X-Next-Cursor': nextCursor } : {}),
      json: async () => rows,
    })
  );
  globalThis.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

const lastCall = (fetchMock: ReturnType<typeof vi.fn>) => fetchMock.mock.calls[0];
const paramsOf = (url: unknown) => new URLSearchParams(String(url).split('?')[1]);

describe('fetchMyCustomJobsPage', () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it('calls the owner-scoped endpoint with the keyset contract and a bearer token', async () => {
    const fetchMock = mockFetch([]);

    await fetchMyCustomJobsPage('tok-123', { since: SINCE, limit: 1000 });

    const [url, init] = lastCall(fetchMock) as [string, RequestInit];
    // Must be the AUTHED endpoint. `/api/jobs` excludes private companies
    // unconditionally and that exclusion is deliberately not relaxed.
    expect(String(url).split('?')[0]).toBe('/api/users/companies/jobs');
    const params = paramsOf(url);
    expect(params.get('status')).toBe('OPEN');
    expect(params.get('since')).toBe(SINCE);
    expect(params.get('limit')).toBe('1000');
    // Page 1 carries no cursor.
    expect(params.get('cursor')).toBeNull();

    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer tok-123');
  });

  it('replays a cursor verbatim on later pages', async () => {
    const fetchMock = mockFetch([]);

    await fetchMyCustomJobsPage('tok', { since: SINCE, cursor: 'CUR-1' });

    expect(paramsOf(lastCall(fetchMock)[0]).get('cursor')).toBe('CUR-1');
  });

  it('reads X-Next-Cursor, and reports its absence as the end of the walk', async () => {
    mockFetch([makeCustomRow('u-abc', 'j1')], { nextCursor: 'CUR-2' });
    expect((await fetchMyCustomJobsPage('tok', { since: SINCE })).nextCursor).toBe('CUR-2');

    mockFetch([makeCustomRow('u-abc', 'j1')]);
    expect((await fetchMyCustomJobsPage('tok', { since: SINCE })).nextCursor).toBeNull();
  });

  it('groups rows by the company id carried in source_id, not by the company column', async () => {
    // A row whose `company` column disagrees with its `custom:<id>` namespace.
    // The namespace wins: it is what the endpoint's authorization and the rest
    // of the custom-company UI (My Companies, the trend page) are keyed on.
    mockFetch([
      makeCustomRow('u-aaa', 'j1'),
      makeCustomRow('u-bbb', 'j2'),
      makeCustomRow('u-aaa', 'j3', '2026-07-01T00:00:00.000Z', {
        company: 'Some Display Name',
        sourceId: 'custom:u-aaa',
      }),
    ]);

    const page = await fetchMyCustomJobsPage('tok', { since: SINCE });

    expect(Object.keys(page.byCompanyId).sort()).toEqual(['u-aaa', 'u-bbb']);
    expect(page.byCompanyId['u-aaa'].map((j) => j.id)).toEqual(['j1', 'j3']);
    expect(page.byCompanyId['u-aaa'].every((j) => j.company === 'u-aaa')).toBe(true);
    // `jobs` is the flat, server-ordered view of the same objects.
    expect(page.jobs).toHaveLength(3);
    expect(page.jobs[0]).toBe(page.byCompanyId['u-aaa'][0]);
  });

  it('falls back to the company column when the namespace is unrecognized', async () => {
    mockFetch([
      makeCustomRow('u-zzz', 'j1', '2026-08-01T00:00:00.000Z', { sourceId: 'greenhouse' }),
    ]);

    const page = await fetchMyCustomJobsPage('tok', { since: SINCE });

    expect(Object.keys(page.byCompanyId)).toEqual(['u-zzz']);
  });

  it('throws an APIError on a non-OK response so the caller can isolate the failure', async () => {
    mockFetch([], { ok: false, status: 500 });

    await expect(fetchMyCustomJobsPage('tok', { since: SINCE })).rejects.toBeInstanceOf(APIError);
  });
});
