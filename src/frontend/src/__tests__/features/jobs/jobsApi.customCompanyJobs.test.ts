import { describe, it, expect, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';

/**
 * `getJobsForCompany` for a user-added board — the one branch that makes the
 * whole `/companies` page work for a `u-<id>`.
 *
 * The load-bearing assertion in this file is **T2, the never-leak property on
 * the client side**: selecting a custom company must issue ZERO requests whose
 * path is `/api/jobs`. That endpoint is unauthenticated and excludes
 * `visibility='user'` rows unconditionally (a guard the backend carries named
 * tests for and this change does not touch), so asking it for a `u-<id>` would
 * be both the wrong request and a silently empty page.
 */
const { flagState } = vi.hoisted(() => ({ flagState: { isEnabled: true } }));
vi.mock('../../../config/customCompanies', () => ({
  CUSTOM_COMPANIES_CONFIG: {
    get isEnabled() {
      return flagState.isEnabled;
    },
    isDiscoveryProgressEnabled: false,
  },
}));

import { jobsApi } from '../../../features/jobs/jobsApi';

const CUSTOM_ID = 'u-jw8iz8sqvy';
const PRIVATE_PATH = `/api/users/companies/${CUSTOM_ID}/jobs`;
const PUBLIC_PATH = '/api/jobs';

function row(id: string, status: 'OPEN' | 'CLOSED' = 'OPEN'): Record<string, unknown> {
  const seen = '2026-08-20T00:00:00.000Z';
  return {
    id,
    title: `role ${id}`,
    company: CUSTOM_ID,
    location: 'Remote',
    locations: [],
    url: `https://example.com/${id}`,
    sourceId: `custom:${CUSTOM_ID}`,
    details: '{}',
    createdAt: seen,
    postedOn: seen,
    closedOn: status === 'CLOSED' ? seen : null,
    status,
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt: seen,
    lastSeenAt: seen,
    consecutiveMisses: 0,
    detailsScraped: true,
  };
}

interface Reply {
  rows?: unknown[];
  status?: number;
}

function makeFetchMock(respond: (path: string) => Reply) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).split('?')[0];
    const reply = respond(path);
    const status = reply.status ?? 200;
    return {
      ok: status < 400,
      status,
      statusText: status < 400 ? 'OK' : 'Error',
      headers: new Headers(),
      json: async () => reply.rows ?? [],
      _init: init,
    };
  });
}

function makeStore(getTokenOrNull: () => Promise<string | null>) {
  return configureStore({
    reducer: { [jobsApi.reducerPath]: jobsApi.reducer },
    middleware: (gdm) =>
      gdm({ thunk: { extraArgument: { getTokenOrNull } } }).concat(jobsApi.middleware),
  });
}

const pathsHit = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.map(([u]) => String(u).split('?')[0]);

const authHeaders = (fetchMock: ReturnType<typeof vi.fn>) =>
  fetchMock.mock.calls.map(
    ([, init]) => (init as { headers?: Record<string, string> } | undefined)?.headers?.Authorization
  );

afterEach(() => {
  vi.resetAllMocks();
  flagState.isEnabled = true;
});

describe('T2 — the never-leak property, client side', () => {
  it('asks ONLY the authed owner-scoped endpoint, never /api/jobs', async () => {
    const fetchMock = makeFetchMock(() => ({ rows: [row('a'), row('b')] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const store = makeStore(async () => 'tok-123');

    const result = await store.dispatch(
      jobsApi.endpoints.getJobsForCompany.initiate({ companyId: CUSTOM_ID })
    );

    // The whole requirement in two assertions.
    expect(pathsHit(fetchMock)).toEqual([PRIVATE_PATH]);
    expect(pathsHit(fetchMock)).not.toContain(PUBLIC_PATH);
    expect(authHeaders(fetchMock)).toEqual(['Bearer tok-123']);
    expect(result.data?.jobs.map((j) => j.id)).toEqual(['a', 'b']);
    // Rows are keyed to the runtime `u-<id>`, which is what every downstream
    // selector on the companies page reads.
    expect(result.data?.jobs.every((j) => j.company === CUSTOM_ID)).toBe(true);
    expect(result.data?.metadata.totalCount).toBe(2);
  });

  it('leaves the PUBLIC path untouched for a curated company', async () => {
    const fetchMock = makeFetchMock(() => ({ rows: [] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const store = makeStore(async () => 'tok-123');

    await store.dispatch(jobsApi.endpoints.getJobsForCompany.initiate({ companyId: 'spacex' }));

    expect(pathsHit(fetchMock)).toEqual([PUBLIC_PATH]);
    // No bearer token on the public request — it never had one and must not gain one.
    expect(authHeaders(fetchMock)).toEqual([undefined]);
  });
});

describe('T3 — signed out', () => {
  it('answers 401 without issuing ANY request', async () => {
    const fetchMock = makeFetchMock(() => ({ rows: [] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const store = makeStore(async () => null);

    const result = await store.dispatch(
      jobsApi.endpoints.getJobsForCompany.initiate({ companyId: CUSTOM_ID })
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.error).toMatchObject({ status: 401 });
  });
});

describe('T4 — flag off', () => {
  it('answers the same 404 an unknown company has always got, and issues no request', async () => {
    flagState.isEnabled = false;
    const fetchMock = makeFetchMock(() => ({ rows: [] }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const store = makeStore(async () => 'tok-123');

    const result = await store.dispatch(
      jobsApi.endpoints.getJobsForCompany.initiate({ companyId: CUSTOM_ID })
    );

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.error).toMatchObject({ status: 404 });
  });
});

describe('T10 — failures keep their HTTP status', () => {
  it('surfaces a 403 as 403, so the page can say "not your company"', async () => {
    const fetchMock = makeFetchMock(() => ({ status: 403 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const store = makeStore(async () => 'tok-123');

    const result = await store.dispatch(
      jobsApi.endpoints.getJobsForCompany.initiate({ companyId: CUSTOM_ID })
    );

    expect(result.error).toMatchObject({ status: 403 });
  });

  it('surfaces the backend flag being off (503) as an error, never an empty chart', async () => {
    const fetchMock = makeFetchMock(() => ({ status: 503 }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const store = makeStore(async () => 'tok-123');

    const result = await store.dispatch(
      jobsApi.endpoints.getJobsForCompany.initiate({ companyId: CUSTOM_ID })
    );

    expect(result.error).toMatchObject({ status: 503 });
    expect(result.data).toBeUndefined();
  });
});

describe('T11 — status parity with the public path', () => {
  it('keeps only OPEN rows, matching what /api/jobs is asked for', async () => {
    const fetchMock = makeFetchMock(() => ({
      rows: [row('open-1'), row('closed-1', 'CLOSED'), row('open-2')],
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const store = makeStore(async () => 'tok-123');

    const result = await store.dispatch(
      jobsApi.endpoints.getJobsForCompany.initiate({ companyId: CUSTOM_ID })
    );

    expect(result.data?.jobs.map((j) => j.id)).toEqual(['open-1', 'open-2']);
    expect(result.data?.metadata.totalCount).toBe(2);
  });
});
