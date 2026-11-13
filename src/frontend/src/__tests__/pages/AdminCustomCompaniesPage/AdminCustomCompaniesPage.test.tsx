import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';
import { AdminCustomCompaniesPage } from '../../../pages/AdminCustomCompaniesPage/AdminCustomCompaniesPage';
import { makeAttemptsResponse, makeCompaniesResponse } from './fixtures';

// Node's built-in `Request` requires absolute URLs; RTK Query passes relative
// ones. Same shim as AdminEnrichmentPage.test.tsx.
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
        thunk: { extraArgument: { getTokenOrNull: () => Promise.resolve('test-token') } },
      }).concat(adminApi.middleware),
  });
}

function renderPage() {
  return render(
    <Provider store={makeStore()}>
      <AdminCustomCompaniesPage />
    </Provider>
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function routedFetch(
  overrides: { companies?: unknown; attempts?: unknown; companiesStatus?: number } = {}
) {
  return (input: unknown) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.includes('/custom-companies/attempts')) {
      return Promise.resolve(jsonResponse(overrides.attempts ?? makeAttemptsResponse()));
    }
    if (url.includes('/custom-companies')) {
      const status = overrides.companiesStatus ?? 200;
      if (status >= 400) {
        return Promise.resolve(jsonResponse({ detail: 'boom' }, status));
      }
      return Promise.resolve(jsonResponse(overrides.companies ?? makeCompaniesResponse()));
    }
    return Promise.resolve(jsonResponse({}));
  };
}

/**
 * The StatTile Paper carrying `label`, so a bare number can be asserted inside
 * it. Two tiles share their label with a section heading below them, so this
 * matches on the tile's own `overline` <span> rather than the <h2>.
 */
function tile(label: string): HTMLElement {
  const labelNode = screen.getAllByText(label).find((el) => el.tagName === 'SPAN');
  const paper = labelNode?.parentElement;
  if (!paper) throw new Error(`No tile found for "${label}"`);
  return paper;
}

describe('AdminCustomCompaniesPage', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(routedFetch());
    global.fetch = fetchMock as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders the whole-page skeleton while both reads are pending', () => {
    fetchMock.mockImplementation(() => new Promise(() => {}));
    renderPage();

    const region = screen.getByRole('status', { name: 'Loading custom companies…' });
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
    expect(within(region).getByText('Admin · Custom Companies')).toBeInTheDocument();
    expect(within(region).getByText('Add attempts')).toBeInTheDocument();
    expect(within(region).getByText('Users')).toBeInTheDocument();
    expect(screen.queryByRole('heading')).not.toBeInTheDocument();
    expect(within(region).getByRole('columnheader', { name: 'Live?' })).toBeInTheDocument();
    expect(within(region).getByRole('columnheader', { name: 'Resolved as' })).toBeInTheDocument();
    expect(within(region).getByRole('columnheader', { name: 'Owns now' })).toBeInTheDocument();
  });

  it('renders per-slot skeletons for the boards read while attempts have landed', async () => {
    fetchMock.mockImplementation((input: unknown) => {
      const url = input instanceof Request ? input.url : String(input);
      if (url.includes('/custom-companies/attempts')) return routedFetch()(input);
      return new Promise(() => {});
    });
    renderPage();

    expect(
      await screen.findByRole('heading', { name: 'Live scrapers', level: 2 })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('status', { name: 'Loading headline counts…' })
    ).not.toBeInTheDocument();
    const boards = screen.getByRole('status', { name: 'Loading boards…' });
    expect(within(boards).getByRole('columnheader', { name: 'Transport' })).toBeInTheDocument();
    expect(screen.queryByRole('status', { name: 'Loading attempts…' })).not.toBeInTheDocument();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('renders the four headline tiles from the server summary', async () => {
    renderPage();

    // "Live scrapers" is both the first tile's label and the first section's
    // heading, so this has to say which one it means.
    expect(
      await screen.findByRole('heading', { name: 'Live scrapers', level: 2 })
    ).toBeInTheDocument();
    // 2 of 3 tracked — an orphaned board is not live, so this must not read 3.
    expect(screen.getByText('of 3 tracked')).toBeInTheDocument();
    // Scoped to the tile: "26" also appears as this user's attempt count in the
    // rollup table further down the page.
    expect(within(tile('Add attempts')).getByText('26')).toBeInTheDocument();
    expect(screen.getByText('all time')).toBeInTheDocument();
    expect(screen.getByText('4 refused · 4 stuck')).toBeInTheDocument();
    // 8 / 26 = 31%, computed from the same two numbers the tile shows.
    expect(screen.getByText('31%')).toBeInTheDocument();
    expect(screen.getByText('has ever added one')).toBeInTheDocument();
  });

  it('renders all three sections with their data-derived subtitles', async () => {
    renderPage();

    expect(await screen.findByText('3 custom boards · 3 unverified')).toBeInTheDocument();
    expect(
      await screen.findByText('26 attempts · 17 added, 1 already public, 4 stuck, 4 refused')
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Users', level: 2 })).toBeInTheDocument();
  });

  it('collapses to one empty state when nothing has ever been added', async () => {
    fetchMock.mockImplementation(
      routedFetch({
        companies: makeCompaniesResponse({
          companies: [],
          summary: {
            trackedCount: 0,
            liveCount: 0,
            byLiveStatus: {},
            byHealthState: {},
            attemptCount: 0,
            userCount: 0,
            failedCount: 0,
            refusedCount: 0,
            stuckCount: 0,
          },
        }),
        attempts: makeAttemptsResponse({ attempts: [], byOutcome: {}, users: [] }),
      })
    );
    renderPage();

    expect(await screen.findByText('No one has added a company yet')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Live scrapers' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Add attempts' })).not.toBeInTheDocument();
  });

  it('renders the empty state — not an error — when the E7 schema is absent (production today)', async () => {
    fetchMock.mockImplementation(
      routedFetch({
        companies: makeCompaniesResponse({
          companies: [],
          schemaPresent: false,
          summary: {
            trackedCount: 0,
            liveCount: 0,
            byLiveStatus: {},
            byHealthState: {},
            attemptCount: 0,
            userCount: 0,
            failedCount: 0,
            refusedCount: 0,
            stuckCount: 0,
          },
        }),
        attempts: makeAttemptsResponse({
          attempts: [],
          byOutcome: {},
          users: [],
          schemaPresent: false,
        }),
      })
    );
    renderPage();

    expect(await screen.findByText('No one has added a company yet')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('surfaces a retryable error when the companies query fails', async () => {
    fetchMock.mockImplementation(routedFetch({ companiesStatus: 500 }));
    const user = userEvent.setup();
    renderPage();

    const retry = await screen.findAllByRole('button', { name: /retry/i });
    expect(retry.length).toBeGreaterThan(0);

    const callsBefore = fetchMock.mock.calls.length;
    await user.click(retry[0]);
    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
    });
  });

  it('sends the filters the backend declares, on the paths the proxy allow-lists', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Live scrapers', level: 2 });

    const urls = fetchMock.mock.calls.map((call) =>
      call[0] instanceof Request ? call[0].url : String(call[0])
    );
    expect(urls.some((u) => u.includes('/api/admin/custom-companies?'))).toBe(true);
    expect(urls.some((u) => u.includes('/api/admin/custom-companies/attempts?'))).toBe(true);
    for (const url of urls) {
      expect(url).toContain('limit=25');
      expect(url).toContain('offset=0');
    }
  });
});
