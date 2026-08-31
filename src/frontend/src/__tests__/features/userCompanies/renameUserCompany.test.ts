/**
 * `renameUserCompany` — the request it sends, the tag it invalidates, and the copy it
 * produces for every failure the endpoint can return.
 *
 * A separate file from `userCompaniesApi.test.ts` rather than a new `describe` inside
 * it: the rename brings its own error vocabulary and its own narrower, and that file is
 * already 400 lines of add/remove/jobs. The `TestRequest` shim and the store factory are
 * duplicated for the same reason they are duplicated in `featuresApi.test.ts` — they are
 * five lines of harness, and importing them across test files couples two suites that
 * have no reason to move together.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import {
  COMPANY_NAME_MAX_LENGTH,
  asRenameFailure,
  describeRenameError,
  userCompaniesApi,
  type UserCompany,
} from '../../../features/userCompanies/userCompaniesApi';

// Node's `Request` requires absolute URLs; `fetchBaseQuery` builds relative ones.
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
    reducer: { [userCompaniesApi.reducerPath]: userCompaniesApi.reducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: { extraArgument: { getTokenOrNull } as TestExtra },
      }).concat(userCompaniesApi.middleware),
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const SAMPLE_COMPANY: UserCompany = {
  id: 'u-abc1234567',
  displayName: 'Ycombinator',
  ats: 'discovered',
  boardToken: 'https://www.ycombinator.com/companies/raindrop/jobs',
  sourceId: 'custom:u-abc1234567',
  healthState: 'unverified',
  openJobCount: 4,
  lastSuccessAt: null,
  trackingStartedAt: null,
};

describe('renameUserCompany', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('PATCHes the company path with a camelCase body', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ ...SAMPLE_COMPANY, displayName: 'Raindrop' })
    );
    const store = makeStore(async () => 'tok');

    const result = await store
      .dispatch(
        userCompaniesApi.endpoints.renameUserCompany.initiate({
          id: 'u-abc1234567',
          displayName: 'Raindrop',
        })
      )
      .unwrap();

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.url).toMatch(/\/api\/users\/companies\/u-abc1234567$/);
    expect(request.method).toBe('PATCH');
    await expect(request.text()).resolves.toBe(
      JSON.stringify({ displayName: 'Raindrop' })
    );
    expect(request.headers.get('Authorization')).toBe('Bearer tok');
    // The response IS the updated row, which is what makes the pending state cheap.
    expect(result.displayName).toBe('Raindrop');
  });

  it('invalidates MyCompanies, refetching the list exactly once', async () => {
    const mock = vi.fn(async (input: RequestInfo | URL) => {
      const req = input as Request;
      if (req.method === 'PATCH') {
        return jsonResponse({ ...SAMPLE_COMPANY, displayName: 'Raindrop' });
      }
      return jsonResponse({ companies: [SAMPLE_COMPANY] });
    });
    globalThis.fetch = mock as unknown as typeof fetch;
    const store = makeStore(async () => 'tok');
    const listCalls = () =>
      mock.mock.calls.filter(([input]) => (input as Request).method === 'GET').length;

    // An active subscription, so an invalidation actually refetches.
    store.dispatch(userCompaniesApi.endpoints.getUserCompanies.initiate());
    await vi.waitFor(() => expect(listCalls()).toBe(1));

    await store
      .dispatch(
        userCompaniesApi.endpoints.renameUserCompany.initiate({
          id: 'u-abc1234567',
          displayName: 'Raindrop',
        })
      )
      .unwrap();

    await vi.waitFor(() => expect(listCalls()).toBe(2));
    // ONE refetch, not a storm: the bare `MyCompanies` tag is invalidated once, and the
    // list is the only active subscription to it.
    expect(listCalls()).toBe(2);
  });

  it('surfaces the 422 body as a rejection the caller can read', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ reason: 'name_too_long', detail: 'That name is 140 characters.' }, 422)
    );
    const store = makeStore(async () => 'tok');

    const result = await store.dispatch(
      userCompaniesApi.endpoints.renameUserCompany.initiate({
        id: 'u-abc1234567',
        displayName: 'x'.repeat(140),
      })
    );

    expect('error' in result).toBe(true);
    expect(asRenameFailure((result as { error: unknown }).error)).toEqual({
      reason: 'name_too_long',
      detail: 'That name is 140 characters.',
    });
  });
});

describe('asRenameFailure', () => {
  it('reads a 422 carrying a string reason', () => {
    expect(
      asRenameFailure({ status: 422, data: { reason: 'name_empty', detail: 'Blank.' } })
    ).toEqual({ reason: 'name_empty', detail: 'Blank.' });
  });

  it('tolerates a 422 with no detail', () => {
    expect(asRenameFailure({ status: 422, data: { reason: 'name_empty' } })).toEqual({
      reason: 'name_empty',
      detail: '',
    });
  });

  it.each([
    ['a 404', { status: 404, data: { detail: 'Company not found' } }],
    ['a 429', { status: 429, data: { detail: 'Too fast' } }],
    // 422 is a hard check for the same reason `asAddFailure` makes it: only that status
    // carries the flat {reason, detail} body.
    ['a 400 that looks the part', { status: 400, data: { reason: 'name_empty' } }],
    ['a 422 with no reason', { status: 422, data: { detail: 'x' } }],
    ['a network error', { status: 'FETCH_ERROR', error: 'boom' }],
    ['null', null],
    ['a string', 'nope'],
  ])('returns null for %s', (_label, error) => {
    expect(asRenameFailure(error)).toBeNull();
  });
});

describe('describeRenameError', () => {
  it('prefers the server sentence for a known reason', () => {
    expect(
      describeRenameError({
        status: 422,
        data: { reason: 'name_too_long', detail: 'That name is 140 characters.' },
      })
    ).toBe('That name is 140 characters.');
  });

  it('falls back to local copy when a known reason arrives with no sentence', () => {
    expect(describeRenameError({ status: 422, data: { reason: 'name_empty' } })).toBe(
      "A company name can't be blank."
    );
    expect(
      describeRenameError({ status: 422, data: { reason: 'name_too_long' } })
    ).toBe(`Keep the name to ${COMPANY_NAME_MAX_LENGTH} characters or fewer.`);
  });

  it('still says something useful for a reason code it has never seen', () => {
    // A server that grows a new code must not produce a blank alert here.
    expect(
      describeRenameError({
        status: 422,
        data: { reason: 'name_reserved', detail: 'That name is reserved.' },
      })
    ).toBe('That name is reserved.');
  });

  it.each([
    // 404 is "not yours" and "gone" at once — the endpoint deliberately does not
    // distinguish them, so neither does the copy.
    [404, "That company isn't in your list any more."],
    [401, 'Please sign in again to rename this.'],
    [403, 'Please sign in again to rename this.'],
    [429, "You're renaming too quickly. Try again in a moment."],
    [503, 'Renaming is unavailable right now.'],
  ])('maps status %i to its own sentence', (status, expected) => {
    expect(describeRenameError({ status, data: {} })).toBe(expected);
  });

  it.each([
    ['a network failure', { status: 'FETCH_ERROR', error: 'Failed to fetch' }],
    ['a 500', { status: 500, data: {} }],
    ['undefined', undefined],
    ['null', null],
  ])('never renders nothing for %s', (_label, error) => {
    const message = describeRenameError(error);
    expect(message).toBe("That didn't save. Please try again.");
    expect(message).not.toMatch(/object Object|undefined/);
  });
});
