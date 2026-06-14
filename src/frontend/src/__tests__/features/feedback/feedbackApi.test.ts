import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import { feedbackApi } from '../../../features/feedback/feedbackApi';

// Node's built-in `Request` (undici) requires absolute URLs. RTK Query's
// `fetchBaseQuery` calls `new Request('/api/feedback')` with a relative URL,
// which fails under Node/jsdom. Resolve relative URLs against a test origin —
// same shim used by featuresApi.test.ts / adminApi.test.ts.
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
    reducer: { [feedbackApi.reducerPath]: feedbackApi.reducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: { extraArgument: { getTokenOrNull } as TestExtra },
      }).concat(feedbackApi.middleware),
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

function methodFromCall(call: [unknown, unknown]): string | undefined {
  const [input, init] = call;
  if (input instanceof Request) return input.method;
  return (init as RequestInit | undefined)?.method;
}

function getAuthHeader(call: [unknown, unknown]): string | null {
  const [input, init] = call;
  if (input instanceof Request) return input.headers.get('Authorization');
  const headers = (init as RequestInit | undefined)?.headers;
  if (headers instanceof Headers) return headers.get('Authorization');
  if (headers && typeof headers === 'object') {
    const rec = headers as Record<string, string>;
    const key = Object.keys(rec).find((k) => k.toLowerCase() === 'authorization');
    return key ? rec[key] : null;
  }
  return null;
}

async function bodyFromCall(call: [unknown, unknown]): Promise<unknown> {
  const [input, init] = call;
  if (input instanceof Request) return await input.clone().json();
  const body = (init as RequestInit | undefined)?.body;
  return typeof body === 'string' ? JSON.parse(body) : body;
}

describe('feedbackApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('POSTs the message to /api/feedback', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'f1' }, 201));
    const store = makeStore(async () => null);

    await store
      .dispatch(feedbackApi.endpoints.submitFeedback.initiate({ message: 'hello' }))
      .unwrap();

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(urlFromInput(call[0])).toMatch(/\/api\/feedback\/?$/);
    expect(methodFromCall(call)).toBe('POST');
    expect(await bodyFromCall(call)).toEqual({ message: 'hello' });
  });

  it('omits Authorization when the token getter returns null (anonymous)', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'f1' }, 201));
    const store = makeStore(async () => null);

    await store
      .dispatch(feedbackApi.endpoints.submitFeedback.initiate({ message: 'anon' }))
      .unwrap();

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(getAuthHeader(call)).toBeNull();
  });

  it('sets Authorization: Bearer <token> when a token is registered', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'f1' }, 201));
    const store = makeStore(async () => 'tok-xyz');

    await store
      .dispatch(feedbackApi.endpoints.submitFeedback.initiate({ message: 'authed' }))
      .unwrap();

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(getAuthHeader(call)).toBe('Bearer tok-xyz');
  });

  it('surfaces an error when the backend returns a non-2xx status', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'boom' }, 500));
    const store = makeStore(async () => null);

    const result = await store.dispatch(
      feedbackApi.endpoints.submitFeedback.initiate({ message: 'fail' })
    );

    expect(result.error).toBeDefined();
  });
});
