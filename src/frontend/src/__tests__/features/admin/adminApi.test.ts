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

    await store.dispatch(adminApi.endpoints.grantAdmin.initiate({ userId: 'target-1' }));

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(urlFromInput(call[0])).toMatch(/\/api\/admin\/users\/target-1\/admin$/);
    expect(methodFromCall(call)).toBe('POST');
    expect(getAuthHeader(call)).toBe('Bearer test-admin-token');
  });

  it('revokeAdmin DELETEs /users/{id}/admin with Authorization', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    await store.dispatch(adminApi.endpoints.revokeAdmin.initiate({ userId: 'target-2' }));

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
        visitCount: 12,
        lastVisitAt: '2025-06-10T10:00:00Z',
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

    const result = await store.dispatch(adminApi.endpoints.listAdminUsers.initiate());

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

    const result = await store.dispatch(adminApi.endpoints.listAdminUsers.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when /api/admin/users 2xx body has users as a string', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ users: 'oops' }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.listAdminUsers.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when a /api/admin/users row is missing numeric visitCount', async () => {
    // Per-row guard: the roster reads visitCount as a number for the Visits
    // column + sort. A row missing it (serializer regression / misrouted body)
    // must trip the guard rather than render ``undefined`` and sort wrong.
    fetchMock.mockResolvedValue(
      jsonResponse({
        users: [
          {
            id: 'u1',
            email: 'a@example.com',
            displayName: null,
            signupProvider: 'google',
            createdAt: '2025-01-10T10:00:00Z',
            isAdmin: false,
            // visitCount intentionally omitted
          },
        ],
      })
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.listAdminUsers.initiate());

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

    const result = await store.dispatch(adminApi.endpoints.getAdminUsersStats.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when /api/admin/users/stats 2xx body has totalUsers as a string', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ totalUsers: '42', byProvider: {} }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.getAdminUsersStats.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('surfaces an error when /api/admin/users/stats 2xx body is missing byProvider', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ totalUsers: 0 }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.getAdminUsersStats.initiate());

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

    const result = await store.dispatch(adminApi.endpoints.getAdminUsersStats.initiate());

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

    const result = await store.dispatch(adminApi.endpoints.getAdminUsersStats.initiate());

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

    const result = await store.dispatch(adminApi.endpoints.getAdminUsersStats.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  // ───────────────────────────────────────────────────────────────────────────
  // Location Normalization Monitor endpoints
  // ───────────────────────────────────────────────────────────────────────────

  function makeHealthBody(overrides: Record<string, unknown> = {}) {
    return {
      schemaPresent: true,
      windowHours: 24,
      nullBacklog: 0,
      nullAged: 0,
      done: 10,
      failed: 0,
      total: 100,
      failedBlank: 0,
      failedNonblank: 0,
      failedNonblankRatio: 0,
      heartbeatAgeMinutes: 1,
      normalizeQueue: { todo: 0, doing: 0, succeeded: 10, failed: 0 },
      throughputInWindow: 10,
      keyConfigured: true,
      dormant: false,
      ...overrides,
    };
  }

  function makeAliasBody(overrides: Record<string, unknown> = {}) {
    return {
      total: 1,
      aliases: [
        {
          rawText: 'SF, CA',
          source: 'llm',
          confidence: 0.9,
          locations: [
            {
              id: 7,
              canonicalName: 'San Francisco',
              kind: 'city',
              city: 'San Francisco',
              region: 'California',
              country: 'United States',
              remoteScope: null,
              position: 0,
            },
          ],
        },
      ],
      ...overrides,
    };
  }

  // ── getLocationHealth ──────────────────────────────────────────────────────

  it('getLocationHealth attaches auth and unwraps a valid health body', async () => {
    const body = makeHealthBody();
    fetchMock.mockResolvedValue(jsonResponse(body));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.getLocationHealth.initiate());

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(urlFromInput(call[0])).toMatch(/\/api\/admin\/locations\/health$/);
    expect(getAuthHeader(call)).toBe('Bearer test-admin-token');
    expect(result.data).toEqual(body);
  });

  it('getLocationHealth THROWS when total is not a number', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeHealthBody({ total: '100' })));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.getLocationHealth.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('getLocationHealth THROWS when heartbeatAgeMinutes is a string', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeHealthBody({ heartbeatAgeMinutes: 'soon' })));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.getLocationHealth.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('getLocationHealth accepts heartbeatAgeMinutes: null and throughputInWindow: null', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(makeHealthBody({ heartbeatAgeMinutes: null, throughputInWindow: null }))
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.getLocationHealth.initiate());

    expect(result.error).toBeUndefined();
    expect(result.data?.heartbeatAgeMinutes).toBeNull();
  });

  it('getLocationHealth THROWS when normalizeQueue has a non-number value', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeHealthBody({ normalizeQueue: { todo: 'lots' } })));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.getLocationHealth.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  // ── getLocationIntegrity ───────────────────────────────────────────────────

  it('getLocationIntegrity unwraps the checks[] array', async () => {
    const checks = [
      { id: 'orphans', label: 'Orphaned aliases', count: 0, severity: 'ok' },
      { id: 'dupes', label: 'Duplicate canonicals', count: 3, severity: 'warn' },
    ];
    fetchMock.mockResolvedValue(jsonResponse({ schemaPresent: true, checks }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.getLocationIntegrity.initiate());

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(urlFromInput(call[0])).toMatch(/\/api\/admin\/locations\/integrity$/);
    expect(getAuthHeader(call)).toBe('Bearer test-admin-token');
    expect(result.data).toEqual(checks);
  });

  it('getLocationIntegrity THROWS when checks is not an array', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ schemaPresent: true, checks: 'nope' }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.getLocationIntegrity.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('getLocationIntegrity THROWS when a check.severity is an unknown enum value', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        schemaPresent: true,
        checks: [{ id: 'x', label: 'X', count: 1, severity: 'fatal' }],
      })
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(adminApi.endpoints.getLocationIntegrity.initiate());

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  // ── listLocationAliases ────────────────────────────────────────────────────

  it('listLocationAliases includes contains/limit/offset params when contains is set', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeAliasBody()));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    await store.dispatch(
      adminApi.endpoints.listLocationAliases.initiate({ contains: 'SF', limit: 25, offset: 50 })
    );

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    const url = urlFromInput(call[0]);
    expect(url).toMatch(/contains=SF/);
    expect(url).toMatch(/limit=25/);
    expect(url).toMatch(/offset=50/);
  });

  it('listLocationAliases OMITS contains when it is an empty string', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeAliasBody()));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    await store.dispatch(
      adminApi.endpoints.listLocationAliases.initiate({ contains: '', limit: 25, offset: 0 })
    );

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    const url = urlFromInput(call[0]);
    expect(url).not.toMatch(/contains=/);
    expect(url).toMatch(/limit=25/);
    expect(url).toMatch(/offset=0/);
  });

  it('listLocationAliases unwraps a valid body', async () => {
    const body = makeAliasBody();
    fetchMock.mockResolvedValue(jsonResponse(body));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.listLocationAliases.initiate({ limit: 25, offset: 0 })
    );

    expect(result.data).toEqual(body);
  });

  it('listLocationAliases THROWS when a nested location.id is a string', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        makeAliasBody({
          aliases: [
            {
              rawText: 'SF',
              source: 'llm',
              confidence: null,
              locations: [
                {
                  id: '7',
                  canonicalName: 'SF',
                  kind: 'city',
                  city: null,
                  region: null,
                  country: null,
                  remoteScope: null,
                  position: 0,
                },
              ],
            },
          ],
        })
      )
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.listLocationAliases.initiate({ limit: 25, offset: 0 })
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('listLocationAliases THROWS when alias.source is an unknown enum value', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        makeAliasBody({
          aliases: [{ rawText: 'SF', source: 'human', confidence: null, locations: [] }],
        })
      )
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.listLocationAliases.initiate({ limit: 25, offset: 0 })
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  // ── reverseSearchLocations ─────────────────────────────────────────────────

  it('reverseSearchLocations omits contains when empty and includes limit', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ results: [] }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    await store.dispatch(
      adminApi.endpoints.reverseSearchLocations.initiate({ contains: '', limit: 50 })
    );

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    const url = urlFromInput(call[0]);
    expect(url).toMatch(/\/api\/admin\/locations\/reverse/);
    expect(url).not.toMatch(/contains=/);
    expect(url).toMatch(/limit=50/);
  });

  it('reverseSearchLocations unwraps a valid body', async () => {
    const body = {
      results: [
        {
          location: {
            id: 7,
            canonicalName: 'San Francisco',
            kind: 'city',
            city: 'San Francisco',
            region: 'CA',
            country: 'US',
            remoteScope: null,
          },
          rawTexts: ['SF', 'SF, CA'],
        },
      ],
    };
    fetchMock.mockResolvedValue(jsonResponse(body));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.reverseSearchLocations.initiate({ limit: 50 })
    );

    expect(result.data).toEqual(body);
  });

  it('reverseSearchLocations THROWS when rawTexts contains a non-string', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        results: [
          {
            location: {
              id: 7,
              canonicalName: 'SF',
              kind: 'city',
              city: null,
              region: null,
              country: null,
              remoteScope: null,
            },
            rawTexts: ['SF', 42],
          },
        ],
      })
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.reverseSearchLocations.initiate({ limit: 50 })
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  // ── getAliasOriginals ──────────────────────────────────────────────────────

  it('getAliasOriginals sends rawText + limit and unwraps a valid body', async () => {
    const body = {
      rawText: 'SF, CA',
      total: 2,
      originals: [
        { original: 'San Francisco, CA', jobIds: ['job-1', 'job-2'] },
        { original: 'SF Bay Area', jobIds: ['job-3'] },
      ],
    };
    fetchMock.mockResolvedValue(jsonResponse(body));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.getAliasOriginals.initiate({ rawText: 'SF, CA', limit: 50 })
    );

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    const url = urlFromInput(call[0]);
    expect(url).toMatch(/\/api\/admin\/locations\/alias-originals/);
    expect(url).toMatch(/limit=50/);
    expect(result.data).toEqual(body);
  });

  it('getAliasOriginals THROWS when jobIds contains a non-string', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        rawText: 'SF',
        total: 1,
        originals: [{ original: 'San Francisco', jobIds: ['job-1', 99] }],
      })
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.getAliasOriginals.initiate({ rawText: 'SF', limit: 50 })
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  // ── listProblemJobs ────────────────────────────────────────────────────────

  it('listProblemJobs sends limit/offset and unwraps a valid body', async () => {
    const body = {
      total: 1,
      jobs: [
        {
          id: 'job-1',
          title: 'Engineer',
          company: 'Acme',
          location: 'SF',
          normalizationStatus: 'failed',
          lastSeenAt: '2026-06-14T00:00:00Z',
        },
      ],
    };
    fetchMock.mockResolvedValue(jsonResponse(body));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.listProblemJobs.initiate({ limit: 25, offset: 0 })
    );

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    const url = urlFromInput(call[0]);
    expect(url).toMatch(/\/api\/admin\/locations\/problem-jobs/);
    expect(url).toMatch(/limit=25/);
    expect(url).toMatch(/offset=0/);
    expect(result.data).toEqual(body);
  });

  it('listProblemJobs THROWS when job.id is not a string', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        total: 1,
        jobs: [
          {
            id: 123,
            title: null,
            company: null,
            location: null,
            normalizationStatus: null,
            lastSeenAt: null,
          },
        ],
      })
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.listProblemJobs.initiate({ limit: 25, offset: 0 })
    );

    expect(result.data).toBeUndefined();
    expect(result.error).toBeDefined();
  });

  it('listProblemJobs accepts null nullable fields (title/company/location/status/lastSeenAt)', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        total: 1,
        jobs: [
          {
            id: 'job-x',
            title: null,
            company: null,
            location: null,
            normalizationStatus: null,
            lastSeenAt: null,
          },
        ],
      })
    );
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    const result = await store.dispatch(
      adminApi.endpoints.listProblemJobs.initiate({ limit: 25, offset: 0 })
    );

    expect(result.error).toBeUndefined();
    expect(result.data?.jobs[0].title).toBeNull();
  });

  // ── mutations: overrideAlias + renormalizeJob ──────────────────────────────

  it('overrideAlias PUTs to the encoded rawText URL with a { locations } body', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    await store.dispatch(
      adminApi.endpoints.overrideAlias.initiate({
        rawText: 'Remote / US',
        locations: [{ canonicalName: 'Remote (US)', kind: 'remote', remoteScope: 'US' }],
      })
    );

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    const url = urlFromInput(call[0]);
    // The literal "/" and spaces in rawText must be percent-encoded.
    expect(url).toContain('/api/admin/locations/aliases/');
    expect(url).toContain(encodeURIComponent('Remote / US'));
    expect(url).not.toMatch(/aliases\/Remote \/ US/);
    expect(methodFromCall(call)).toBe('PUT');
    expect(getAuthHeader(call)).toBe('Bearer test-admin-token');
  });

  it('renormalizeJob POSTs to /jobs/{id}/normalize with auth', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 202 }));
    const store = makeStore(() => Promise.resolve('test-admin-token'));

    await store.dispatch(adminApi.endpoints.renormalizeJob.initiate({ jobId: 'job-42' }));

    const call = fetchMock.mock.calls[0] as [unknown, unknown];
    expect(urlFromInput(call[0])).toMatch(/\/api\/admin\/jobs\/job-42\/normalize$/);
    expect(methodFromCall(call)).toBe('POST');
    expect(getAuthHeader(call)).toBe('Bearer test-admin-token');
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

    const pageArgs = { page: 0, rowsPerPage: 25, sortDir: 'desc' as const };

    it('GETs a page with limit/offset/sort_dir + Authorization and returns {feedback,total}', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ feedback: fakeFeedback, total: 2 }));
      const store = makeStore(() => Promise.resolve('test-admin-token'));

      const result = await store.dispatch(
        adminApi.endpoints.listAdminFeedback.initiate({
          page: 1,
          rowsPerPage: 25,
          sortDir: 'asc',
        })
      );

      const call = fetchMock.mock.calls[0] as [unknown, unknown];
      const url = urlFromInput(call[0]);
      expect(url).toMatch(/\/api\/admin\/feedback\?/);
      expect(url).toContain('limit=25');
      expect(url).toContain('offset=25'); // page 1 * 25
      expect(url).toContain('sort_dir=asc');
      expect(getAuthHeader(call)).toBe('Bearer test-admin-token');
      expect(result.data).toEqual({ feedback: fakeFeedback, total: 2 });
    });

    it('surfaces an error when the 2xx body is missing feedback[]', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ total: 0 }));
      const store = makeStore(() => Promise.resolve('test-admin-token'));

      const result = await store.dispatch(adminApi.endpoints.listAdminFeedback.initiate(pageArgs));

      expect(result.data).toBeUndefined();
      expect(result.error).toBeDefined();
    });

    it('surfaces an error when total is missing', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ feedback: fakeFeedback }));
      const store = makeStore(() => Promise.resolve('test-admin-token'));

      const result = await store.dispatch(adminApi.endpoints.listAdminFeedback.initiate(pageArgs));

      expect(result.data).toBeUndefined();
      expect(result.error).toBeDefined();
    });

    it('surfaces an error when feedback is the wrong type', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ feedback: 'oops', total: 0 }));
      const store = makeStore(() => Promise.resolve('test-admin-token'));

      const result = await store.dispatch(adminApi.endpoints.listAdminFeedback.initiate(pageArgs));

      expect(result.data).toBeUndefined();
      expect(result.error).toBeDefined();
    });
  });
});
