import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';
import { AdminLocationNormalizationPage } from '../../../pages/AdminLocationNormalizationPage/AdminLocationNormalizationPage';

// Node's built-in `Request` requires absolute URLs; RTK Query passes relative
// URLs. Shim the global to resolve them against a test origin — same approach
// used by adminApi.test.ts / AdminUsersPage.test.tsx.
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
    reducer: { [adminApi.reducerPath]: adminApi.reducer },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: {
          extraArgument: { getTokenOrNull: () => Promise.resolve('test-token') },
        },
      }).concat(adminApi.middleware),
  });
}

function renderPage() {
  const store = makeStore();
  return render(
    <Provider store={store}>
      <AdminLocationNormalizationPage />
    </Provider>
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const HEALTHY_BODY = {
  schemaPresent: true,
  windowHours: 24,
  nullBacklog: 10,
  nullAged: 0,
  done: 500,
  failed: 1,
  total: 1000,
  failedBlank: 0,
  failedNonblank: 1,
  failedNonblankRatio: 0.2,
  heartbeatAgeMinutes: 2,
  normalizeQueue: { todo: 0, doing: 1, succeeded: 500, failed: 0 },
  throughputInWindow: 500,
  keyConfigured: true,
  dormant: false,
};

const INTEGRITY_CLEAN = {
  schemaPresent: true,
  checks: [
    { id: 'orphans', label: 'Orphaned aliases', count: 0, severity: 'ok' },
    { id: 'dupes', label: 'Duplicate canonicals', count: 0, severity: 'ok' },
  ],
};

const ALIASES_ONE = {
  total: 1,
  aliases: [
    {
      rawText: 'SF, CA',
      source: 'manual',
      confidence: 0.95,
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
};

const PROBLEM_JOBS_ONE = {
  total: 1,
  jobs: [
    {
      id: 'job-1',
      title: 'Backend Engineer',
      company: 'Acme',
      location: 'San Francisco',
      normalizationStatus: 'failed',
      lastSeenAt: '2026-06-14T00:00:00Z',
    },
  ],
};

/**
 * Builds a fetch implementation that routes by URL. Any endpoint not given
 * an explicit handler resolves to a generic empty success so unrelated slots
 * don't hang or error.
 */
function routedFetch(handlers: {
  health?: () => Promise<Response>;
  integrity?: () => Promise<Response>;
  aliases?: () => Promise<Response>;
  reverse?: () => Promise<Response>;
  originals?: () => Promise<Response>;
  problemJobs?: () => Promise<Response>;
}) {
  return (input: unknown) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.includes('/locations/health')) {
      return handlers.health?.() ?? Promise.resolve(jsonResponse(HEALTHY_BODY));
    }
    if (url.includes('/locations/integrity')) {
      return handlers.integrity?.() ?? Promise.resolve(jsonResponse(INTEGRITY_CLEAN));
    }
    if (url.includes('/locations/alias-originals')) {
      return (
        handlers.originals?.() ??
        Promise.resolve(jsonResponse({ rawText: 'SF, CA', total: 0, originals: [] }))
      );
    }
    if (url.includes('/locations/aliases')) {
      return handlers.aliases?.() ?? Promise.resolve(jsonResponse(ALIASES_ONE));
    }
    if (url.includes('/locations/reverse')) {
      return handlers.reverse?.() ?? Promise.resolve(jsonResponse({ results: [] }));
    }
    if (url.includes('/locations/problem-jobs')) {
      return handlers.problemJobs?.() ?? Promise.resolve(jsonResponse(PROBLEM_JOBS_ONE));
    }
    return Promise.resolve(jsonResponse({}));
  };
}

describe('AdminLocationNormalizationPage', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders a page-level spinner while both health and integrity are pending', () => {
    // Never-resolving health + integrity keeps the page in the full-page
    // loading gate. (Other endpoints can resolve; the gate is on the two.)
    fetchMock.mockImplementation((input: unknown) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes('/locations/health') || url.includes('/locations/integrity')) {
        return new Promise(() => {});
      }
      // Other endpoints get valid (if empty) bodies so they don't trip a
      // runtime guard and emit unrelated unhandled-error noise.
      return routedFetch({
        aliases: () => Promise.resolve(jsonResponse({ total: 0, aliases: [] })),
        problemJobs: () => Promise.resolve(jsonResponse({ total: 0, jobs: [] })),
      })(input);
    });

    renderPage();

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.getByText(/loading location normalization data/i)).toBeInTheDocument();
  });

  it('renders all-error states with retries when health and integrity both fail', async () => {
    fetchMock.mockImplementation(
      routedFetch({
        health: () => Promise.resolve(jsonResponse({ detail: 'health boom' }, 500)),
        integrity: () => Promise.resolve(jsonResponse({ detail: 'integrity boom' }, 500)),
      })
    );

    renderPage();

    await screen.findByRole('heading', { name: /admin · location normalization/i });

    // Verdict is neutral (unknown) when health/integrity are unavailable —
    // never HEALTHY from partial data.
    expect(screen.getByText(/verdict unknown/i)).toBeInTheDocument();

    // Each failed section renders an inline error with a Retry button.
    const retries = await screen.findAllByRole('button', { name: /retry/i });
    expect(retries.length).toBeGreaterThanOrEqual(2);

    // Clicking a retry re-issues the failed query.
    const callsBefore = fetchMock.mock.calls.length;
    await userEvent.click(retries[0]);
    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it('keeps the verdict neutral when integrity errors but health succeeds (partial data)', async () => {
    fetchMock.mockImplementation(
      routedFetch({
        integrity: () => Promise.resolve(jsonResponse({ detail: 'integrity boom' }, 500)),
      })
    );

    renderPage();

    await screen.findByRole('heading', { name: /admin · location normalization/i });

    // Health still renders (its stat tiles show up)...
    expect(await screen.findByText(/health overview/i)).toBeInTheDocument();
    expect(screen.getByText(/null aged/i)).toBeInTheDocument();

    // ...but the verdict must NOT be HEALTHY from partial data.
    expect(screen.getByText(/verdict unknown/i)).toBeInTheDocument();
    expect(screen.queryByText(/^HEALTHY$/)).not.toBeInTheDocument();
  });

  it('renders the HEALTHY verdict, tiles, integrity summary, an alias row, and a problem job on success', async () => {
    fetchMock.mockImplementation(routedFetch({}));

    renderPage();

    await screen.findByRole('heading', { name: /admin · location normalization/i });

    // Verdict banner shows the HEALTHY chip.
    expect(await screen.findByText('HEALTHY')).toBeInTheDocument();

    // Health tiles.
    expect(screen.getByText(/null aged/i)).toBeInTheDocument();
    expect(screen.getByText(/done/i)).toBeInTheDocument();

    // Integrity summary line — all clean.
    expect(await screen.findByText(/all invariants clean/i)).toBeInTheDocument();

    // Alias row: rawText + a canonical chip. ("San Francisco" also appears as
    // the problem-job location, so scope the chip assertion to the alias row.)
    const aliasRawText = await screen.findByText('SF, CA');
    const aliasRow = aliasRawText.closest('tr');
    expect(aliasRow).not.toBeNull();
    expect(within(aliasRow as HTMLElement).getByText('San Francisco')).toBeInTheDocument();

    // Problem job row rendered.
    expect(await screen.findByText('Backend Engineer')).toBeInTheDocument();
  });

  it('shows the empty alias state when no aliases match', async () => {
    fetchMock.mockImplementation(
      routedFetch({
        aliases: () => Promise.resolve(jsonResponse({ total: 0, aliases: [] })),
      })
    );

    renderPage();

    await screen.findByRole('heading', { name: /admin · location normalization/i });
    expect(await screen.findByText(/no alias mappings match this search/i)).toBeInTheDocument();
  });

  it('dispatches a re-normalize POST when the Re-normalize button is clicked', async () => {
    let normalizeCalls = 0;
    fetchMock.mockImplementation((input: unknown, init?: RequestInit) => {
      const url = input instanceof Request ? input.url : String(input);
      const method =
        input instanceof Request ? input.method : (init?.method ?? 'GET');
      if (url.includes('/normalize') && method === 'POST') {
        normalizeCalls += 1;
        return Promise.resolve(new Response(null, { status: 202 }));
      }
      return routedFetch({})(input);
    });

    renderPage();

    const button = await screen.findByRole('button', { name: /re-normalize/i });
    await userEvent.click(button);

    await waitFor(() => {
      expect(normalizeCalls).toBe(1);
    });
  });

  it('debounces alias search to a single request for the settled term (not one per keystroke)', async () => {
    // The debounce *mechanics* are unit-tested in useDebouncedValue.test.ts.
    // Here we assert the page-level consequence with real timers: typing a
    // 6-character term issues exactly ONE aliases request carrying the full
    // settled term — not one per keystroke (which would be ~6 requests, and
    // would include partial-term requests like contains=r, contains=re, …).
    fetchMock.mockImplementation(routedFetch({}));

    renderPage();

    // Wait for the initial (empty-search) load to settle.
    await screen.findByText('SF, CA');

    const searchBox = screen.getByPlaceholderText(/search raw text/i);
    await userEvent.type(searchBox, 'remote');

    // After the 300ms debounce settles, exactly one request fires for the
    // fully-typed term.
    await waitFor(() => {
      const containsRemoteCalls = fetchMock.mock.calls.filter(([input]) => {
        const url = input instanceof Request ? input.url : String(input);
        return url.includes('contains=remote');
      }).length;
      expect(containsRemoteCalls).toBe(1);
    });

    // And no request fired for an intermediate partial term — proof the
    // debounce collapsed the keystrokes rather than firing per-character.
    const partialCalls = fetchMock.mock.calls.filter(([input]) => {
      const url = input instanceof Request ? input.url : String(input);
      return (
        url.includes('contains=r&') ||
        url.includes('contains=re&') ||
        url.includes('contains=rem&') ||
        url.includes('contains=remo&') ||
        url.includes('contains=remot&')
      );
    }).length;
    expect(partialCalls).toBe(0);
  });

  it('refetches health, integrity, and problem jobs when Refresh is clicked', async () => {
    fetchMock.mockImplementation(routedFetch({}));

    renderPage();

    await screen.findByRole('heading', { name: /admin · location normalization/i });
    await screen.findByText('HEALTHY');

    const callsBefore = fetchMock.mock.calls.length;
    const refresh = screen.getByRole('button', { name: /refresh/i });
    await userEvent.click(refresh);

    await waitFor(() => {
      const after = fetchMock.mock.calls.slice(callsBefore).map(([input]) =>
        input instanceof Request ? input.url : String(input)
      );
      expect(after.some((u) => u.includes('/locations/health'))).toBe(true);
      expect(after.some((u) => u.includes('/locations/integrity'))).toBe(true);
      expect(after.some((u) => u.includes('/locations/problem-jobs'))).toBe(true);
    });
  });

  it('renders the manual-source alias chip distinctly (smoke check of source chip)', async () => {
    fetchMock.mockImplementation(routedFetch({}));

    renderPage();

    const aliasRow = await screen.findByText('SF, CA');
    // The row containing the alias should also carry the "manual" source chip.
    const row = aliasRow.closest('tr');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText('manual')).toBeInTheDocument();
  });
});
