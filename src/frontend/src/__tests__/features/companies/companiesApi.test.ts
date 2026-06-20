import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { configureStore } from '@reduxjs/toolkit';
import { companiesApi, type CuratedCompany } from '../../../features/companies/companiesApi';

// Node's built-in `Request` (undici) requires absolute URLs. fetchBaseQuery
// builds `new Request('/api/companies')` with a relative URL, which fails under
// Node/jsdom — resolve relative URLs against a test origin. Mirrors the
// featuresApi test.
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

function makeStore() {
  return configureStore({
    reducer: { [companiesApi.reducerPath]: companiesApi.reducer },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(companiesApi.middleware),
  });
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const SAMPLE: CuratedCompany[] = [
  {
    id: 'stripe',
    displayName: 'Stripe',
    ats: 'greenhouse',
    blurb: 'Payments infra.',
    accomplishment: 'Powers checkout.',
  },
  { id: 'google', displayName: 'Google', ats: 'script', blurb: 'Search.', accomplishment: null },
];

describe('companiesApi', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('hits /api/companies and unwraps the { companies } envelope', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ companies: SAMPLE }));
    const store = makeStore();

    const result = await store
      .dispatch(companiesApi.endpoints.listCuratedCompanies.initiate())
      .unwrap();

    expect(result).toEqual(SAMPLE);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = String(
      (fetchMock.mock.calls[0][0] as Request).url ?? fetchMock.mock.calls[0][0]
    );
    expect(url).toContain('/api/companies');
  });
});
