import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';

// Node's built-in `Request` (undici) requires absolute URLs. RTK Query's
// `fetchBaseQuery` calls `new Request('/api/admin/users')` with a relative
// URL, which fails under Node/jsdom. Resolve relative URLs against a test
// origin — same shim used by featuresApi.test.ts.
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
    reducer: { [adminApi.reducerPath]: adminApi.reducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: { extraArgument: { getTokenOrNull } as TestExtra },
      }).concat(adminApi.middleware),
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

describe('adminApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  // Regression guard: every /api/admin/* request must carry the admin's
  // Bearer token. This mirrors the QAPage auth regression that motivated
  // half of this PR — a structurally identical bug here (e.g. broken
  // `extra` wiring in store.ts) would silently 401 every admin call.

  it('attaches Authorization on listAdminUsers when a token is available', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ users: [] }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    await store.dispatch(adminApi.endpoints.listAdminUsers.initiate());

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(urlFromInput(call[0])).toMatch(/\/api\/admin\/users$/);
    expect(getAuthHeader(call)).toBe('Bearer test-admin-token');
  });

  it('attaches Authorization on getAdminUsersStats when a token is available', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ totalUsers: 0, firstSignupAt: null, latestSignupAt: null, byProvider: {} })
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    await store.dispatch(adminApi.endpoints.getAdminUsersStats.initiate());

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(urlFromInput(call[0])).toMatch(/\/api\/admin\/users\/stats$/);
    expect(getAuthHeader(call)).toBe('Bearer test-admin-token');
  });

  it('omits Authorization when the token getter returns null (anonymous → backend 401)', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Authentication required' }, 401));
    const store = makeStore(() => Promise.resolve(null));

    await store.dispatch(adminApi.endpoints.listAdminUsers.initiate());

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(getAuthHeader(call)).toBeNull();
  });

  it('unwraps the { users: [...] } envelope via transformResponse', async () => {
    const fakeUsers = [
      {
        id: 'u1',
        email: 'a@example.com',
        displayName: null,
        signupProvider: 'google',
        createdAt: '2025-01-10T10:00:00Z',
        isAdmin: false,
      },
    ];
    fetchMock.mockResolvedValue(jsonResponse({ users: fakeUsers }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.listAdminUsers.initiate());

    expect(result.data).toEqual(fakeUsers);
  });
});
