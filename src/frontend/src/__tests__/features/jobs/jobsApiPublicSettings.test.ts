import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import { jobsApi } from '../../../features/jobs/jobsApi';

// `getPublicSettings` uses a raw `fetch('/api/jobs/settings')` inside a queryFn
// (not fetchBaseQuery), so `global.fetch` is mocked directly — the same idiom as
// jobsApi.facets.test.ts.
//
// EVERY case below asserts `result.error` is undefined. That is the point of the
// endpoint: it FAILS CLOSED, resolving to data rather than surfacing an error
// state. A consumer that had to interpret an error would eventually get it
// wrong in the open direction and reveal an unfinished feature.

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

describe('jobsApi getPublicSettings', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('resolves true from a 200 carrying the flag', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ sweSubcategoriesEnabled: true }));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getPublicSettings.initiate());

    expect(result.error).toBeUndefined();
    expect(result.data).toEqual({ sweSubcategoriesEnabled: true });
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/jobs/settings');
  });

  it('resolves false from a 200 carrying the flag off', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ sweSubcategoriesEnabled: false }));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getPublicSettings.initiate());

    expect(result.error).toBeUndefined();
    expect(result.data).toEqual({ sweSubcategoriesEnabled: false });
  });

  it('resolves FALSE with NO error state on a 500', async () => {
    // A backend outage must hide the feature, not paint an error box on the
    // filter bar.
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'boom' }, 500));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getPublicSettings.initiate());

    expect(result.error).toBeUndefined();
    expect(result.data).toEqual({ sweSubcategoriesEnabled: false });
  });

  it('resolves FALSE with NO error state on a 404 — the Vercel-ahead-of-Railway window', async () => {
    // Vercel deploys before Railway on every release, so for a minute or two the
    // SPA is live against a backend that has no such route. That window is
    // ROUTINE, and it must look exactly like "the flag is off".
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Not Found' }, 404));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getPublicSettings.initiate());

    expect(result.error).toBeUndefined();
    expect(result.data).toEqual({ sweSubcategoriesEnabled: false });
  });

  it('resolves false from a 200 with an empty object (key missing)', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getPublicSettings.initiate());

    expect(result.error).toBeUndefined();
    expect(result.data).toEqual({ sweSubcategoriesEnabled: false });
  });

  it('resolves false when the key is present but not a boolean', async () => {
    // A truthy STRING is the dangerous case: `Boolean('false')` is true, so a
    // coercing implementation would reveal the feature on a malformed payload.
    fetchMock.mockResolvedValue(jsonResponse({ sweSubcategoriesEnabled: 'false' }));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getPublicSettings.initiate());

    expect(result.error).toBeUndefined();
    expect(result.data).toEqual({ sweSubcategoriesEnabled: false });
  });

  it('resolves false when the body is not an object', async () => {
    fetchMock.mockResolvedValue(jsonResponse('nope'));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getPublicSettings.initiate());

    expect(result.error).toBeUndefined();
    expect(result.data).toEqual({ sweSubcategoriesEnabled: false });
  });

  it('resolves false when fetch rejects (network failure)', async () => {
    fetchMock.mockRejectedValue(new Error('network down'));
    const store = makeStore();

    const result = await store.dispatch(jobsApi.endpoints.getPublicSettings.initiate());

    expect(result.error).toBeUndefined();
    expect(result.data).toEqual({ sweSubcategoriesEnabled: false });
  });

  it('keeps the unused cache entry for 60 seconds, NOT the 3600 of getFacets', async () => {
    // Pinned BEHAVIOURALLY rather than by reading the option back, because the
    // behaviour is the thing that matters: copying `keepUnusedDataFor: 3600`
    // from the neighbouring getFacets makes an admin who flips the switch wait
    // an hour to see it, and nothing else in the suite would notice.
    vi.useFakeTimers();
    try {
      fetchMock.mockResolvedValue(jsonResponse({ sweSubcategoriesEnabled: true }));
      const store = makeStore();

      const promise = store.dispatch(jobsApi.endpoints.getPublicSettings.initiate());
      await vi.advanceTimersByTimeAsync(0);
      await promise;
      promise.unsubscribe();

      const cacheKeys = () =>
        Object.keys(
          (store.getState() as Record<string, { queries: Record<string, unknown> }>)[
            jobsApi.reducerPath
          ].queries
        ).filter((k) => k.startsWith('getPublicSettings'));

      await vi.advanceTimersByTimeAsync(55_000);
      expect(cacheKeys()).toHaveLength(1);

      await vi.advanceTimersByTimeAsync(10_000);
      expect(cacheKeys()).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
