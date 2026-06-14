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

  it('grantAdmin POSTs to /users/{id}/admin with Authorization', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    await store.dispatch(
      adminApi.endpoints.grantAdmin.initiate({ userId: 'target-1' })
    );

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(urlFromInput(call[0])).toMatch(/\/api\/admin\/users\/target-1\/admin$/);
    expect(methodFromCall(call)).toBe('POST');
    expect(getAuthHeader(call)).toBe('Bearer test-admin-token');
  });

  it('revokeAdmin DELETEs /users/{id}/admin with Authorization', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    await store.dispatch(
      adminApi.endpoints.revokeAdmin.initiate({ userId: 'target-2' })
    );

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(urlFromInput(call[0])).toMatch(/\/api\/admin\/users\/target-2\/admin$/);
    expect(methodFromCall(call)).toBe('DELETE');
    expect(getAuthHeader(call)).toBe('Bearer test-admin-token');
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

  it('surfaces an error when /api/admin/users 2xx body is missing users[]', async () => {
    // Regression guard for the "proxy returns 2xx with a bad body" case
    // — e.g. a CDN error page or a future server wraps the envelope for
    // pagination. Without the runtime guard the consumer would receive
    // ``undefined`` and silently render an empty roster (the exact
    // "silently zero admins" failure mode this PR fixes).
    fetchMock.mockResolvedValue(jsonResponse({}));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.listAdminUsers.initiate()
    );

    // RTK Query surfaces the thrown error via the ``error`` field.
    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when /api/admin/users 2xx body has users: null', async () => {
    // Companion to the ``{}`` test — explicitly cover the case where
    // the envelope is present but ``users`` is the wrong type. Without
    // the ``Array.isArray`` check, ``Array.isArray(null)`` returns
    // false and the guard still fires, but adding the case pins the
    // contract so a future ``if (!res.users)`` regression (which would
    // skip a present-but-falsy value) still trips the test.
    fetchMock.mockResolvedValue(jsonResponse({ users: null }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.listAdminUsers.initiate()
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when /api/admin/users 2xx body has users as a string', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ users: 'oops' }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.listAdminUsers.initiate()
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when /api/admin/users/stats 2xx body is missing totalUsers', async () => {
    // Symmetric to the listAdminUsers runtime guard test above. Without
    // a transformResponse validator on getAdminUsersStats, a CDN error
    // page with totalUsers === undefined would cause AdminUsersPage's
    // ``stats?.totalUsers ?? users.length`` fallback to show the
    // loaded-roster-count as "Total users" — silently wrong number.
    fetchMock.mockResolvedValue(jsonResponse({ byProvider: {} }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.getAdminUsersStats.initiate()
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when /api/admin/users/stats 2xx body has totalUsers as a string', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ totalUsers: '42', byProvider: {} })
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.getAdminUsersStats.initiate()
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when /api/admin/users/stats 2xx body is missing byProvider', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ totalUsers: 0 }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.getAdminUsersStats.initiate()
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when /api/admin/users/stats byProvider has a non-number value', async () => {
    // Audit pass-3: the prior guard checked ``byProvider`` was an object
    // but NOT that its values were numbers. A CDN error page or
    // serializer regression that returned ``{ google: "5" }`` would
    // silently render a string as a count downstream. The new guard
    // iterates the values and rejects if any are non-number.
    fetchMock.mockResolvedValue(
      jsonResponse({
        totalUsers: 5,
        firstSignupAt: null,
        latestSignupAt: null,
        byProvider: { google: '5' },
      })
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.getAdminUsersStats.initiate()
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when /api/admin/users/stats firstSignupAt is a number instead of string|null', async () => {
    // Audit pass-3: the timestamp fields contract is ``string | null``.
    // A numeric value (e.g. 0) must reject — otherwise downstream
    // ``new Date(iso).getTime()`` would silently produce "1970-01-01"
    // or NaN without any error signal.
    fetchMock.mockResolvedValue(
      jsonResponse({
        totalUsers: 0,
        firstSignupAt: 0,
        latestSignupAt: null,
        byProvider: {},
      })
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.getAdminUsersStats.initiate()
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when /api/admin/users/stats latestSignupAt is a number instead of string|null', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        totalUsers: 0,
        firstSignupAt: null,
        latestSignupAt: 1234567890,
        byProvider: {},
      })
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.getAdminUsersStats.initiate()
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  describe('listAdminFeedback', () => {
    const fakeFeedback = [
      {
        id: 'fb1',
        message: 'love it',
        userId: 'u1',
        userEmail: 'a@example.com',
        displayName: 'Alice',
        createdAt: '2026-06-01T10:00:00Z',
      },
      {
        id: 'fb2',
        message: 'anon note',
        userId: null,
        userEmail: null,
        displayName: null,
        createdAt: '2026-06-02T10:00:00Z',
      },
    ];

    it('GETs /api/admin/feedback with Authorization and unwraps the envelope', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ feedback: fakeFeedback }));
      const store = makeStore(() => Promise.resolve('test-admin-token'));

      const result = await store.dispatch(
        adminApi.endpoints.listAdminFeedback.initiate()
      );

      const call = fetchMock.mock.calls[0] as [unknown, unknown];
      expect(urlFromInput(call[0])).toMatch(/\/api\/admin\/feedback$/);
      expect(getAuthHeader(call)).toBe('Bearer test-admin-token');
      expect(result.data).toEqual(fakeFeedback);
    });

    it('surfaces an error when the 2xx body is missing feedback[]', async () => {
      fetchMock.mockResolvedValue(jsonResponse({}));
      const store = makeStore(() => Promise.resolve('test-admin-token'));

      const result = await store.dispatch(
        adminApi.endpoints.listAdminFeedback.initiate()
      );

      expect(result.data).toBeUndefined();
      expect(result.error).toBeDefined();
    });

    it('surfaces an error when feedback is the wrong type', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ feedback: 'oops' }));
      const store = makeStore(() => Promise.resolve('test-admin-token'));

      const result = await store.dispatch(
        adminApi.endpoints.listAdminFeedback.initiate()
      );

      expect(result.data).toBeUndefined();
      expect(result.error).toBeDefined();
    });
  });
});
