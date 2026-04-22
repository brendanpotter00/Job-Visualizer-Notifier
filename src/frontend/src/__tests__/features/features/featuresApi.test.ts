import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import { featuresApi, type FeatureListItem } from '../../../features/features/featuresApi';
import { logger } from '../../../lib/logger';

// Node's built-in `Request` (undici) requires absolute URLs. RTK Query's
// `fetchBaseQuery` calls `new Request('/api/features')` with a relative URL,
// which fails under Node/jsdom. Resolve relative URLs against a test origin
// so the constructor succeeds without changing production behavior.
const OriginalRequest = globalThis.Request;
class TestRequest extends OriginalRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    if (typeof input === 'string' && input.startsWith('/')) {
      super(`http://localhost${input}`, init);
    } else {
      super(input, init);
    }
  }
}
globalThis.Request = TestRequest as unknown as typeof Request;

type TestExtra = { getTokenOrNull: () => Promise<string | null> };

function makeStore(getTokenOrNull: () => Promise<string | null>) {
  return configureStore({
    reducer: { [featuresApi.reducerPath]: featuresApi.reducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: { extraArgument: { getTokenOrNull } as TestExtra },
      }).concat(featuresApi.middleware),
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function urlFromInput(input: unknown): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  if (input instanceof Request) return input.url;
  return String(input);
}

function findCall(
  fetchMock: ReturnType<typeof vi.fn>,
  urlSuffix: string
): { input: RequestInfo | URL; init: RequestInit | undefined } {
  const call = fetchMock.mock.calls.find(([input]) => {
    const url = urlFromInput(input);
    return url.endsWith(urlSuffix) || url.includes(urlSuffix);
  });
  if (!call) {
    throw new Error(
      `No fetch call matched suffix "${urlSuffix}". Calls: ${fetchMock.mock.calls
        .map(([i]) => urlFromInput(i))
        .join(', ')}`
    );
  }
  return { input: call[0] as RequestInfo | URL, init: call[1] as RequestInit | undefined };
}

function getHeader(
  input: RequestInfo | URL,
  init: RequestInit | undefined,
  name: string
): string | null {
  if (input instanceof Request) {
    return input.headers.get(name);
  }
  if (!init?.headers) return null;
  const headers = init.headers;
  if (headers instanceof Headers) return headers.get(name);
  if (Array.isArray(headers)) {
    const hit = headers.find(([k]) => k.toLowerCase() === name.toLowerCase());
    return hit ? hit[1] : null;
  }
  const rec = headers as Record<string, string>;
  const key = Object.keys(rec).find((k) => k.toLowerCase() === name.toLowerCase());
  return key ? rec[key] : null;
}

function getMethod(input: RequestInfo | URL, init: RequestInit | undefined): string | undefined {
  if (input instanceof Request) return input.method;
  return init?.method;
}

const SAMPLE_FEATURES: FeatureListItem[] = [
  {
    id: 'resume-match-ai',
    title: 'AI resume matching notifications',
    description: 'Upload your resume and get notifications when jobs match.',
    createdAt: '2026-04-10T00:00:00Z',
    upvoteCount: 3,
    hasUpvoted: false,
  },
  {
    id: 'location-normalization',
    title: 'Location normalization',
    description: 'Normalize job-posting locations.',
    createdAt: '2026-04-11T00:00:00Z',
    upvoteCount: 7,
    hasUpvoted: true,
  },
];

describe('featuresApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('listFeatures', () => {
    it('hits /api/features and returns the unwrapped array', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ features: SAMPLE_FEATURES }));
      const store = makeStore(async () => null);

      const result = await store
        .dispatch(featuresApi.endpoints.listFeatures.initiate())
        .unwrap();

      expect(result).toEqual(SAMPLE_FEATURES);
      const { input } = findCall(fetchMock, '/api/features');
      expect(urlFromInput(input)).toMatch(/\/api\/features\/?$/);
    });

    it('omits the Authorization header when no token is registered', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ features: [] }));
      const store = makeStore(async () => null);

      await store.dispatch(featuresApi.endpoints.listFeatures.initiate()).unwrap();

      const { input, init } = findCall(fetchMock, '/api/features');
      expect(getHeader(input, init, 'Authorization')).toBeNull();
    });

    it('sets Authorization: Bearer <token> when a token is registered', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ features: [] }));
      const store = makeStore(async () => 'tok-abc');

      await store.dispatch(featuresApi.endpoints.listFeatures.initiate()).unwrap();

      const { input, init } = findCall(fetchMock, '/api/features');
      expect(getHeader(input, init, 'Authorization')).toBe('Bearer tok-abc');
    });
  });

  describe('upvoteFeature', () => {
    it('POSTs to /{id}/upvote', async () => {
      fetchMock
        .mockResolvedValueOnce(jsonResponse({ features: SAMPLE_FEATURES }))
        .mockResolvedValueOnce(
          jsonResponse({
            featureId: 'resume-match-ai',
            upvoteCount: 4,
            hasUpvoted: true,
          })
        );
      const store = makeStore(async () => 'tok');

      await store.dispatch(featuresApi.endpoints.listFeatures.initiate()).unwrap();
      await store
        .dispatch(featuresApi.endpoints.upvoteFeature.initiate('resume-match-ai'))
        .unwrap();

      const { input, init } = findCall(fetchMock, '/resume-match-ai/upvote');
      expect(urlFromInput(input)).toMatch(/\/api\/features\/resume-match-ai\/upvote$/);
      expect(getMethod(input, init)).toBe('POST');
      expect(getHeader(input, init, 'Authorization')).toBe('Bearer tok');
    });

    it('optimistically increments count + sets hasUpvoted=true', async () => {
      let resolveMutation: (r: Response) => void = () => {};
      fetchMock
        .mockResolvedValueOnce(jsonResponse({ features: SAMPLE_FEATURES }))
        .mockImplementationOnce(
          () =>
            new Promise<Response>((res) => {
              resolveMutation = res;
            })
        );
      const store = makeStore(async () => 'tok');

      await store.dispatch(featuresApi.endpoints.listFeatures.initiate()).unwrap();
      store.dispatch(featuresApi.endpoints.upvoteFeature.initiate('resume-match-ai'));

      await Promise.resolve();
      await Promise.resolve();

      const cached = featuresApi.endpoints.listFeatures.select()(store.getState()).data;
      const feature = cached?.find((f) => f.id === 'resume-match-ai');
      expect(feature?.hasUpvoted).toBe(true);
      expect(feature?.upvoteCount).toBe(4);

      resolveMutation(
        jsonResponse({ featureId: 'resume-match-ai', upvoteCount: 4, hasUpvoted: true })
      );
    });

    it('reverts optimistic patch when mutation fails', async () => {
      // Spy on the shared logger (the call site now uses `logger.warn`, not
      // raw `console.warn`) so the test locks the mutation-layer contract
      // to the logger utility, not to console directly.
      const loggerWarn = vi.spyOn(logger, 'warn').mockImplementation(() => {});
      fetchMock
        .mockResolvedValueOnce(jsonResponse({ features: SAMPLE_FEATURES }))
        .mockResolvedValueOnce(jsonResponse({ detail: 'boom' }, 500));
      const store = makeStore(async () => 'tok');

      await store.dispatch(featuresApi.endpoints.listFeatures.initiate()).unwrap();
      const mutationPromise = store.dispatch(
        featuresApi.endpoints.upvoteFeature.initiate('resume-match-ai')
      );

      await Promise.resolve();
      const midFlight = featuresApi.endpoints.listFeatures
        .select()(store.getState())
        .data?.find((f) => f.id === 'resume-match-ai');
      expect(midFlight?.hasUpvoted).toBe(true);
      expect(midFlight?.upvoteCount).toBe(4);

      await mutationPromise;

      const afterFailure = featuresApi.endpoints.listFeatures
        .select()(store.getState())
        .data?.find((f) => f.id === 'resume-match-ai');
      expect(afterFailure?.hasUpvoted).toBe(false);
      expect(afterFailure?.upvoteCount).toBe(3);
      expect(loggerWarn).toHaveBeenCalledWith(
        expect.stringContaining('upvote failed'),
        expect.anything()
      );
      loggerWarn.mockRestore();
    });

    it('no-ops optimistic patch when hasUpvoted is already true', async () => {
      fetchMock
        .mockResolvedValueOnce(jsonResponse({ features: SAMPLE_FEATURES }))
        .mockImplementationOnce(() => new Promise<Response>(() => {}));
      const store = makeStore(async () => 'tok');

      await store.dispatch(featuresApi.endpoints.listFeatures.initiate()).unwrap();
      store.dispatch(featuresApi.endpoints.upvoteFeature.initiate('location-normalization'));
      await Promise.resolve();
      await Promise.resolve();

      const feature = featuresApi.endpoints.listFeatures
        .select()(store.getState())
        .data?.find((f) => f.id === 'location-normalization');
      expect(feature?.hasUpvoted).toBe(true);
      expect(feature?.upvoteCount).toBe(7);
    });
  });

  describe('removeUpvote', () => {
    it('DELETEs to /{id}/upvote', async () => {
      fetchMock
        .mockResolvedValueOnce(jsonResponse({ features: SAMPLE_FEATURES }))
        .mockResolvedValueOnce(
          jsonResponse({
            featureId: 'location-normalization',
            upvoteCount: 6,
            hasUpvoted: false,
          })
        );
      const store = makeStore(async () => 'tok');

      await store.dispatch(featuresApi.endpoints.listFeatures.initiate()).unwrap();
      await store
        .dispatch(featuresApi.endpoints.removeUpvote.initiate('location-normalization'))
        .unwrap();

      const { input, init } = findCall(fetchMock, '/location-normalization/upvote');
      expect(urlFromInput(input)).toMatch(/\/api\/features\/location-normalization\/upvote$/);
      expect(getMethod(input, init)).toBe('DELETE');
    });

    it('reverts optimistic patch when mutation fails', async () => {
      const loggerWarn = vi.spyOn(logger, 'warn').mockImplementation(() => {});
      fetchMock
        .mockResolvedValueOnce(jsonResponse({ features: SAMPLE_FEATURES }))
        .mockResolvedValueOnce(jsonResponse({ detail: 'boom' }, 500));
      const store = makeStore(async () => 'tok');

      await store.dispatch(featuresApi.endpoints.listFeatures.initiate()).unwrap();
      const mutationPromise = store.dispatch(
        featuresApi.endpoints.removeUpvote.initiate('location-normalization')
      );

      await Promise.resolve();
      const midFlight = featuresApi.endpoints.listFeatures
        .select()(store.getState())
        .data?.find((f) => f.id === 'location-normalization');
      expect(midFlight?.hasUpvoted).toBe(false);
      expect(midFlight?.upvoteCount).toBe(6);

      await mutationPromise;

      const afterFailure = featuresApi.endpoints.listFeatures
        .select()(store.getState())
        .data?.find((f) => f.id === 'location-normalization');
      expect(afterFailure?.hasUpvoted).toBe(true);
      expect(afterFailure?.upvoteCount).toBe(7);
      expect(loggerWarn).toHaveBeenCalledWith(
        expect.stringContaining('remove-upvote failed'),
        expect.anything()
      );
      loggerWarn.mockRestore();
    });

    it('no-ops optimistic patch when hasUpvoted is already false', async () => {
      // Mirror of `upvoteFeature > no-ops optimistic patch when hasUpvoted is
      // already true` — DELETE on a feature the user hasn't upvoted must not
      // mutate the cache before the server responds. The optimistic branch is
      // guarded by `if (f && f.hasUpvoted)`; removing that guard would cause
      // negative counts or a flicker to upvoteCount-1.
      fetchMock
        .mockResolvedValueOnce(jsonResponse({ features: SAMPLE_FEATURES }))
        .mockImplementationOnce(() => new Promise<Response>(() => {}));
      const store = makeStore(async () => 'tok');

      await store.dispatch(featuresApi.endpoints.listFeatures.initiate()).unwrap();
      // resume-match-ai starts with hasUpvoted=false, upvoteCount=3.
      store.dispatch(featuresApi.endpoints.removeUpvote.initiate('resume-match-ai'));
      await Promise.resolve();
      await Promise.resolve();

      const feature = featuresApi.endpoints.listFeatures
        .select()(store.getState())
        .data?.find((f) => f.id === 'resume-match-ai');
      expect(feature?.hasUpvoted).toBe(false);
      expect(feature?.upvoteCount).toBe(3);
    });
  });
});
