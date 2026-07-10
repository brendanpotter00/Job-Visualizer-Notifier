import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import { jobsApi } from '../../../features/jobs/jobsApi';
import type { JobFacets } from '../../../types';

// getFacets uses a raw `fetch('/api/jobs/facets')` inside a queryFn (not
// fetchBaseQuery), so we mock `global.fetch` directly — same fetch-mock idiom
// as adminApi.test.ts.

function makeStore() {
  return configureStore({
    reducer: { [jobsApi.reducerPath]: jobsApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(jobsApi.middleware),
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const VALID_FACETS: JobFacets = {
  categories: [{ slug: 'software_engineering', label: 'Software Engineering', sortOrder: 0 }],
  levels: [{ slug: 'entry', label: 'Entry', sortOrder: 0, parentSlug: null }],
};

describe('jobsApi getFacets', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('returns data (and hits /api/jobs/facets) on a valid body', async () => {
    fetchMock.mockResolvedValue(jsonResponse(VALID_FACETS));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getFacets.initiate());

    expect(result.error).toBeUndefined();
    expect(result.data).toEqual(VALID_FACETS);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/jobs/facets');
  });

  it('errors when the response is not ok (500)', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 500));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getFacets.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
    expect((result.error as { status?: unknown }).status).toBe(500);
  });

  it('errors with CUSTOM_ERROR when categories is not an array', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ categories: 'x', levels: [] }));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getFacets.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
    expect((result.error as { status?: unknown }).status).toBe('CUSTOM_ERROR');
  });

  it('errors with CUSTOM_ERROR when levels is missing', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ categories: [] }));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getFacets.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
    expect((result.error as { status?: unknown }).status).toBe('CUSTOM_ERROR');
  });

  it('errors with CUSTOM_ERROR when fetch rejects (network failure)', async () => {
    fetchMock.mockRejectedValue(new Error('network down'));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getFacets.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
    expect((result.error as { status?: unknown }).status).toBe('CUSTOM_ERROR');
  });
});
