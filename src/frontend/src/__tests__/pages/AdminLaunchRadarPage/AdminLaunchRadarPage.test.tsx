import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';
import { AdminLaunchRadarPage } from '../../../pages/AdminLaunchRadarPage/AdminLaunchRadarPage';
import { makeAthennianCard, makeCardsResponse } from './fixtures';

// Node's built-in `Request` requires absolute URLs; RTK Query passes relative
// ones. Same shim as the other admin page tests.
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
      <AdminLaunchRadarPage />
    </Provider>
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

interface Call {
  method: string;
  url: URL;
  body: unknown;
}

const ARCHIVED = makeCardsResponse({
  cards: [makeAthennianCard()],
  total: 1,
  counts: { new: 2, archived: 1 },
});

/**
 * A tiny fake backend: GET list by `status` (the counts change after a
 * mutation so the refetch is visible), PATCH and DELETE recorded.
 */
function fakeBackend(
  opts: {
    list?: (status: string, offset: number) => Response | Promise<Response>;
    patchStatus?: number;
    deleteStatus?: number;
  } = {}
) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: unknown) => {
    const req = input as Request;
    const url = new URL(req.url);
    const body = req.method === 'PATCH' ? await req.json() : undefined;
    calls.push({ method: req.method, url, body });
    if (req.method === 'PATCH') {
      return opts.patchStatus && opts.patchStatus >= 400
        ? jsonResponse({ detail: 'card is not new' }, opts.patchStatus)
        : jsonResponse(makeAthennianCard());
    }
    if (req.method === 'DELETE') {
      return opts.deleteStatus && opts.deleteStatus >= 400
        ? jsonResponse({ detail: 'a card must be archived first' }, opts.deleteStatus)
        : new Response(null, { status: 204 });
    }
    const status = url.searchParams.get('status') ?? '';
    const offset = Number(url.searchParams.get('offset'));
    if (opts.list) return opts.list(status, offset);
    return jsonResponse(status === 'archived' ? ARCHIVED : makeCardsResponse());
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  const lists = () => calls.filter((c) => c.method === 'GET');
  return { calls, lists, fetchMock };
}

describe('AdminLaunchRadarPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('shows a loading spinner while the first page is pending', () => {
    global.fetch = vi.fn(() => new Promise<Response>(() => {})) as unknown as typeof fetch;
    renderPage();
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });

  it('renders the header line, the tab counts and the New cards', async () => {
    const { lists } = fakeBackend();
    renderPage();

    expect(await screen.findByText('Raindrop AI')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Launch Radar', level: 1 })).toBeInTheDocument();
    expect(
      screen.getByText(
        'Startups the Parallel loop found, newest first. Last run Oct 7 at 01:31 UTC on server-laptop. $0.46 of the $5.00 budget used.'
      )
    ).toBeInTheDocument();

    const newTab = screen.getByRole('tab', { name: 'New 2' });
    expect(newTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Archived 1' })).toHaveAttribute(
      'aria-selected',
      'false'
    );
    expect(screen.getByText('Ghost AI')).toBeInTheDocument();

    const first = lists()[0].url;
    expect(first.pathname).toBe('/api/admin/launch-radar/cards');
    expect(first.searchParams.get('status')).toBe('new');
    expect(first.searchParams.get('limit')).toBe('25');
    expect(first.searchParams.get('offset')).toBe('0');
  });

  it('says "No runs yet." before the first run', async () => {
    fakeBackend({
      list: () =>
        jsonResponse(
          makeCardsResponse({
            cards: [],
            total: 0,
            counts: { new: 0, archived: 0 },
            stats: { lastRun: null, spendUsd: 0, capUsd: 5 },
          })
        ),
    });
    renderPage();
    expect(await screen.findByText('No new cards.')).toBeInTheDocument();
    expect(
      screen.getByText(/No runs yet\. \$0\.00 of the \$5\.00 budget used\./)
    ).toBeInTheDocument();
  });

  it('switches to the Archived tab and fetches that list', async () => {
    const { lists } = fakeBackend();
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Raindrop AI');

    await user.click(screen.getByRole('tab', { name: /archived/i }));
    expect(await screen.findByText('Athennian')).toBeInTheDocument();
    expect(screen.queryByText('Raindrop AI')).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Archived 1' })).toHaveAttribute(
      'aria-selected',
      'true'
    );
    expect(screen.getByRole('button', { name: 'Restore' })).toBeInTheDocument();
    expect(lists().some((c) => c.url.searchParams.get('status') === 'archived')).toBe(true);
  });

  it('never shows the New cards under the Archived tab while the archived list loads', async () => {
    let releaseArchived: (r: Response) => void = () => {};
    const archivedPending = new Promise<Response>((resolve) => {
      releaseArchived = resolve;
    });
    fakeBackend({
      list: (status) =>
        status === 'archived' ? archivedPending : jsonResponse(makeCardsResponse()),
    });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Raindrop AI');

    await user.click(screen.getByRole('tab', { name: /archived/i }));
    // The archived request is still open: RTK Query's `data` still holds the
    // New response, but none of its cards (or their Archive buttons) may render.
    expect(screen.getByRole('tab', { name: /archived/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByText('Raindrop AI')).not.toBeInTheDocument();
    expect(screen.queryByText('Ghost AI')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument();
    expect(screen.getByText('Loading cards…')).toBeInTheDocument();
    // The global header (counts, last run) stays.
    expect(screen.getByRole('tab', { name: 'New 2' })).toBeInTheDocument();

    releaseArchived(jsonResponse(ARCHIVED));
    expect(await screen.findByText('Athennian')).toBeInTheDocument();
  });

  it('shows the empty state for an empty archive', async () => {
    fakeBackend({
      list: (status) =>
        jsonResponse(
          status === 'archived'
            ? makeCardsResponse({ cards: [], total: 0, counts: { new: 2, archived: 0 } })
            : makeCardsResponse()
        ),
    });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Raindrop AI');
    await user.click(screen.getByRole('tab', { name: /archived/i }));
    expect(await screen.findByText('No archived cards.')).toBeInTheDocument();
  });

  it('archives a card with PATCH and refetches the list', async () => {
    const { calls, lists } = fakeBackend();
    const user = userEvent.setup();
    renderPage();
    const card = await screen.findByTestId('radar-card-1');
    const before = lists().length;

    await user.click(within(card).getByRole('button', { name: 'Archive' }));

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const patch = calls.find((c) => c.method === 'PATCH');
    expect(patch?.url.pathname).toBe('/api/admin/launch-radar/cards/1');
    expect(patch?.body).toEqual({ status: 'archived' });
    // invalidatesTags: the visible list refetches (counts ride on it).
    await waitFor(() => expect(lists().length).toBeGreaterThan(before));
  });

  it('restores an archived card with PATCH status=new', async () => {
    const { calls } = fakeBackend();
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Raindrop AI');
    await user.click(screen.getByRole('tab', { name: /archived/i }));
    await screen.findByText('Athennian');

    await user.click(screen.getByRole('button', { name: 'Restore' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const patch = calls.find((c) => c.method === 'PATCH');
    expect(patch?.url.pathname).toBe('/api/admin/launch-radar/cards/3');
    expect(patch?.body).toEqual({ status: 'new' });
  });

  describe('permanent delete', () => {
    async function openDeleteDialog() {
      const user = userEvent.setup();
      renderPage();
      await screen.findByText('Raindrop AI');
      await user.click(screen.getByRole('tab', { name: /archived/i }));
      await screen.findByText('Athennian');
      await user.click(screen.getByRole('button', { name: 'Delete' }));
      const dialog = await screen.findByRole('dialog');
      return { user, dialog };
    }

    it('asks first, and Cancel sends nothing', async () => {
      const { calls } = fakeBackend();
      const { user, dialog } = await openDeleteDialog();

      expect(
        within(dialog).getByRole('heading', { name: 'Delete Athennian permanently?' })
      ).toBeInTheDocument();
      expect(
        within(dialog).getByText(
          'The card and its research go away. The loop will not post athennian.com again.'
        )
      ).toBeInTheDocument();

      await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
    });

    it('sends DELETE on confirm, closes, and refetches', async () => {
      const { calls, lists } = fakeBackend();
      const { user, dialog } = await openDeleteDialog();
      const before = lists().length;

      await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      const del = calls.find((c) => c.method === 'DELETE');
      expect(del?.url.pathname).toBe('/api/admin/launch-radar/cards/3');
      await waitFor(() => expect(lists().length).toBeGreaterThan(before));
    });

    it('keeps the dialog open with an error when the delete fails', async () => {
      fakeBackend({ deleteStatus: 409 });
      const { user, dialog } = await openDeleteDialog();

      await user.click(within(dialog).getByRole('button', { name: 'Delete' }));
      expect(await within(dialog).findByText('a card must be archived first')).toBeInTheDocument();
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
  });

  it('paginates when the tab holds more than one page', async () => {
    const { lists } = fakeBackend({
      list: () => jsonResponse(makeCardsResponse({ total: 60, counts: { new: 60, archived: 0 } })),
    });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('Raindrop AI');

    expect(screen.getByRole('navigation')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Go to page 2' }));
    await waitFor(() =>
      expect(lists().some((c) => c.url.searchParams.get('offset') === '25')).toBe(true)
    );
  });

  it('shows no pager for a single page', async () => {
    fakeBackend();
    renderPage();
    await screen.findByText('Raindrop AI');
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  it('shows an inline error with retry when the first load fails', async () => {
    fakeBackend({ list: () => jsonResponse({}, 500) });
    renderPage();
    expect(await screen.findByText(/failed to load launch radar cards/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('rejects a 2xx body of the wrong shape instead of rendering an empty list', async () => {
    fakeBackend({ list: () => jsonResponse({ cards: [], total: 0 }) });
    renderPage();
    expect(
      await screen.findByText(/invalid \/api\/admin\/launch-radar\/cards response/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('No new cards.')).not.toBeInTheDocument();
  });
});
