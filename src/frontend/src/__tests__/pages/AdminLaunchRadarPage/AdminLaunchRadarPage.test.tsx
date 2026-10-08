import { useEffect } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { configureStore } from '@reduxjs/toolkit';
import { adminApi } from '../../../features/admin/adminApi';
import { AdminLaunchRadarPage } from '../../../pages/AdminLaunchRadarPage/AdminLaunchRadarPage';
import type { LaunchRadarCard, LaunchRadarStatus } from '../../../features/admin/launchRadarTypes';
import {
  makeAthennianCard,
  makeCardsResponse,
  makeGhostCard,
  makeKestrelCard,
  makeRaindropCard,
} from './fixtures';

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

/** Reports the router location, so a test can read what the page wrote to the URL. */
function LocationProbe({ onChange }: { onChange: (search: string) => void }) {
  const { search } = useLocation();
  useEffect(() => onChange(search), [search, onChange]);
  return null;
}

function renderPage(url = '/admin/launch-radar') {
  const location = { search: '' };
  const view = render(
    <MemoryRouter initialEntries={[url]}>
      <Provider store={makeStore()}>
        <AdminLaunchRadarPage />
      </Provider>
      <LocationProbe
        onChange={(search) => {
          location.search = search;
        }}
      />
    </MemoryRouter>
  );
  return { ...view, location };
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
  counts: { new: 2, saved: 1, archived: 1 },
});

const SAVED = makeCardsResponse({
  cards: [makeKestrelCard()],
  total: 1,
  counts: { new: 2, saved: 1, archived: 1 },
});

/**
 * A tiny fake backend: GET list by `status`, PATCH and DELETE recorded. A
 * PATCH answers with the card in the requested status.
 */
function fakeBackend(
  opts: {
    list?: (status: string, offset: number) => Response | Promise<Response>;
    /** Called as a PATCH lands, before its response (lets a fake move its counts). */
    onPatch?: (body: unknown) => void;
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
      opts.onPatch?.(body);
      const status = (body as { status: 'new' | 'saved' | 'archived' }).status;
      return opts.patchStatus && opts.patchStatus >= 400
        ? jsonResponse({ detail: 'card is not new' }, opts.patchStatus)
        : jsonResponse(makeAthennianCard({ status }));
    }
    if (req.method === 'DELETE') {
      return opts.deleteStatus && opts.deleteStatus >= 400
        ? jsonResponse({ detail: 'a card must be archived first' }, opts.deleteStatus)
        : new Response(null, { status: 204 });
    }
    const status = url.searchParams.get('status') ?? '';
    const offset = Number(url.searchParams.get('offset'));
    if (opts.list) return opts.list(status, offset);
    if (status === 'saved') return jsonResponse(SAVED);
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

  it('renders the heading, the tab counts and the New cards', async () => {
    const { lists } = fakeBackend();
    renderPage();

    expect(await screen.findByText('Raindrop AI')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Launch Radar', level: 1 })).toBeInTheDocument();
    // No sub line under the heading: the run, host and budget are not shown.
    expect(screen.queryByText(/Startups the Parallel loop found/)).not.toBeInTheDocument();
    expect(screen.queryByText(/budget used|Last run|No runs yet/)).not.toBeInTheDocument();
    // The one link under the heading: the public explainer, which has no sidebar entry.
    expect(screen.getByRole('link', { name: 'How it works' })).toHaveAttribute(
      'href',
      '/launch-radar/how-it-works'
    );

    const newTab = screen.getByRole('tab', { name: 'New 2' });
    expect(newTab).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Saved 1' })).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByRole('tab', { name: 'Archived 1' })).toHaveAttribute(
      'aria-selected',
      'false'
    );
    // New, Saved, Archived — in that order.
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual([
      'New 2',
      'Saved 1',
      'Archived 1',
    ]);
    expect(screen.getByText('Ghost AI')).toBeInTheDocument();

    const first = lists()[0].url;
    expect(first.pathname).toBe('/api/admin/launch-radar/cards');
    expect(first.searchParams.get('status')).toBe('new');
    expect(first.searchParams.get('limit')).toBe('25');
    expect(first.searchParams.get('offset')).toBe('0');
    expect(first.searchParams.get('sort')).toBe('announced');
  });

  it('says "No new cards." when the New tab is empty', async () => {
    fakeBackend({
      list: () =>
        jsonResponse(
          makeCardsResponse({ cards: [], total: 0, counts: { new: 0, saved: 0, archived: 0 } })
        ),
    });
    renderPage();
    expect(await screen.findByText('No new cards.')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'New 0' })).toHaveAttribute('aria-selected', 'true');
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
    expect(screen.getByRole('button', { name: 'Restore Athennian' })).toBeInTheDocument();
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
    expect(screen.queryByRole('button', { name: /^Archive\b/ })).not.toBeInTheDocument();
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
            ? makeCardsResponse({ cards: [], total: 0, counts: { new: 2, saved: 1, archived: 0 } })
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

    await user.click(within(card).getByRole('button', { name: 'Archive Raindrop AI' }));

    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const patch = calls.find((c) => c.method === 'PATCH');
    expect(patch?.url.pathname).toBe('/api/admin/launch-radar/cards/1');
    expect(patch?.body).toEqual({ status: 'archived', from: 'new' });
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

    await user.click(screen.getByRole('button', { name: 'Restore Athennian' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const patch = calls.find((c) => c.method === 'PATCH');
    expect(patch?.url.pathname).toBe('/api/admin/launch-radar/cards/3');
    expect(patch?.body).toEqual({ status: 'new', from: 'archived' });
  });

  describe('Saved tab', () => {
    it('switches to Saved, fetches status=saved and shows Unsave and Archive', async () => {
      const { lists } = fakeBackend();
      const user = userEvent.setup();
      renderPage();
      await screen.findByText('Raindrop AI');

      await user.click(screen.getByRole('tab', { name: /saved/i }));
      const card = await screen.findByTestId('radar-card-4');
      expect(within(card).getByText('Kestrel Labs')).toBeInTheDocument();
      expect(screen.queryByText('Raindrop AI')).not.toBeInTheDocument();
      expect(screen.getByRole('tab', { name: 'Saved 1' })).toHaveAttribute('aria-selected', 'true');
      expect(within(card).getByRole('button', { name: 'Unsave Kestrel Labs' })).toBeInTheDocument();
      expect(
        within(card).getByRole('button', { name: 'Archive Kestrel Labs' })
      ).toBeInTheDocument();
      expect(within(card).queryByRole('button', { name: /^Save\b/ })).not.toBeInTheDocument();
      expect(within(card).queryByRole('button', { name: /^Delete\b/ })).not.toBeInTheDocument();
      const saved = lists().find((c) => c.url.searchParams.get('status') === 'saved');
      expect(saved?.url.searchParams.get('offset')).toBe('0');
      expect(saved?.url.searchParams.get('limit')).toBe('25');
    });

    it('shows the empty state for no saved cards', async () => {
      fakeBackend({
        list: (status) =>
          jsonResponse(
            status === 'saved'
              ? makeCardsResponse({
                  cards: [],
                  total: 0,
                  counts: { new: 2, saved: 0, archived: 1 },
                })
              : makeCardsResponse()
          ),
      });
      const user = userEvent.setup();
      renderPage();
      await screen.findByText('Raindrop AI');
      await user.click(screen.getByRole('tab', { name: /saved/i }));
      expect(await screen.findByText('No saved cards.')).toBeInTheDocument();
    });

    it('saves a New card with PATCH status=saved, and the refetch moves the counts', async () => {
      let saved = false;
      const { calls, lists } = fakeBackend({
        onPatch: () => {
          saved = true;
        },
        list: (status) => {
          const counts = saved
            ? { new: 1, saved: 2, archived: 1 }
            : { new: 2, saved: 1, archived: 1 };
          return jsonResponse(
            status === 'new'
              ? makeCardsResponse({ counts, total: counts.new })
              : makeCardsResponse({ cards: [], total: 0, counts })
          );
        },
      });
      const user = userEvent.setup();
      renderPage();
      const card = await screen.findByTestId('radar-card-1');
      expect(screen.getByRole('tab', { name: 'Saved 1' })).toBeInTheDocument();
      const before = lists().length;

      await user.click(within(card).getByRole('button', { name: 'Save Raindrop AI' }));

      await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
      const patch = calls.find((c) => c.method === 'PATCH');
      expect(patch?.url.pathname).toBe('/api/admin/launch-radar/cards/1');
      expect(patch?.body).toEqual({ status: 'saved', from: 'new' });
      await waitFor(() => expect(lists().length).toBeGreaterThan(before));
      expect(await screen.findByRole('tab', { name: 'Saved 2' })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: 'New 1' })).toBeInTheDocument();
    });

    it.each([
      ['Unsave', { status: 'new', from: 'saved' }],
      ['Archive', { status: 'archived', from: 'saved' }],
    ])('%s on a saved card sends PATCH %o and refetches', async (button, body) => {
      const { calls, lists } = fakeBackend();
      const user = userEvent.setup();
      renderPage();
      await screen.findByText('Raindrop AI');
      await user.click(screen.getByRole('tab', { name: /saved/i }));
      const card = await screen.findByTestId('radar-card-4');
      const before = lists().length;

      await user.click(within(card).getByRole('button', { name: `${button} Kestrel Labs` }));

      await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
      const patch = calls.find((c) => c.method === 'PATCH');
      expect(patch?.url.pathname).toBe('/api/admin/launch-radar/cards/4');
      expect(patch?.body).toEqual(body);
      await waitFor(() => expect(lists().length).toBeGreaterThan(before));
    });
  });

  describe('permanent delete', () => {
    async function openDeleteDialog() {
      const user = userEvent.setup();
      renderPage();
      await screen.findByText('Raindrop AI');
      await user.click(screen.getByRole('tab', { name: /archived/i }));
      await screen.findByText('Athennian');
      await user.click(screen.getByRole('button', { name: 'Delete Athennian' }));
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
      list: () =>
        jsonResponse(makeCardsResponse({ total: 60, counts: { new: 60, saved: 0, archived: 0 } })),
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

  describe('sort control', () => {
    const sortGroup = () => screen.getByRole('group', { name: 'Sort cards by' });
    const sortButton = (name: string) => within(sortGroup()).getByRole('button', { name });
    const lastList = (calls: Call[]) => {
      const gets = calls.filter((c) => c.method === 'GET');
      return gets[gets.length - 1].url;
    };

    it('sits on the tabs row: "Sort by" and four options, Announced selected', async () => {
      fakeBackend();
      renderPage();
      await screen.findByText('Raindrop AI');

      expect(
        within(sortGroup())
          .getAllByRole('button')
          .map((b) => b.textContent)
      ).toEqual(['Announced', 'Talent', 'VC', 'Added']);
      expect(sortButton('Announced')).toHaveAttribute('aria-pressed', 'true');
      for (const name of ['Talent', 'VC', 'Added']) {
        expect(sortButton(name)).toHaveAttribute('aria-pressed', 'false');
      }
      // Sentence case, as written: no all-caps button text.
      const label = screen.getByText('Sort by');
      expect(label.textContent).toBe('Sort by');
      expect(sortButton('Talent')).toHaveStyle({ textTransform: 'none' });
      // One flex container holds both: a single row on desktop, stacked (the
      // sort under the tabs) on a narrower screen, never scrolling sideways.
      const row = screen.getByRole('tablist').closest('.MuiTabs-root')!.parentElement!;
      expect(row).toContainElement(sortGroup());
      expect(row).toHaveStyle({ display: 'flex', flexWrap: 'wrap' });
    });

    it('reads ?sort= from the URL and asks the server for that order', async () => {
      const { lists } = fakeBackend();
      renderPage('/admin/launch-radar?sort=vc');
      await screen.findByText('Raindrop AI');
      expect(sortButton('VC')).toHaveAttribute('aria-pressed', 'true');
      expect(lists()[0].url.searchParams.get('sort')).toBe('vc');
    });

    it('reads an unknown ?sort= as Announced', async () => {
      const { lists } = fakeBackend();
      renderPage('/admin/launch-radar?sort=bogus');
      await screen.findByText('Raindrop AI');
      expect(sortButton('Announced')).toHaveAttribute('aria-pressed', 'true');
      expect(lists()[0].url.searchParams.get('sort')).toBe('announced');
    });

    it('writes the sort to the URL, refetches with it and goes back to page 1', async () => {
      const { calls } = fakeBackend({
        list: () =>
          jsonResponse(
            makeCardsResponse({ total: 60, counts: { new: 60, saved: 0, archived: 0 } })
          ),
      });
      const user = userEvent.setup();
      const { location } = renderPage();
      await screen.findByText('Raindrop AI');
      await user.click(screen.getByRole('button', { name: 'Go to page 2' }));
      await waitFor(() => expect(lastList(calls).searchParams.get('offset')).toBe('25'));

      await user.click(sortButton('Talent'));

      expect(location.search).toBe('?sort=talent');
      expect(sortButton('Talent')).toHaveAttribute('aria-pressed', 'true');
      await waitFor(() => expect(lastList(calls).searchParams.get('sort')).toBe('talent'));
      expect(lastList(calls).searchParams.get('offset')).toBe('0');
      expect(lastList(calls).searchParams.get('status')).toBe('new');
      expect(screen.getByRole('button', { name: 'page 1' })).toHaveAttribute(
        'aria-current',
        'page'
      );

      // Back to the default: it is left out of the URL.
      await user.click(sortButton('Announced'));
      expect(location.search).toBe('');
      expect(sortButton('Announced')).toHaveAttribute('aria-pressed', 'true');
    });

    it('keeps the sort when the selected option is pressed again, and keeps other params', async () => {
      fakeBackend();
      const user = userEvent.setup();
      const { location } = renderPage('/admin/launch-radar?ref=digest');
      await screen.findByText('Raindrop AI');

      await user.click(sortButton('VC'));
      await user.click(sortButton('VC'));

      expect(location.search).toBe('?ref=digest&sort=vc');
      expect(sortButton('VC')).toHaveAttribute('aria-pressed', 'true');
    });

    it('applies to every tab', async () => {
      const { lists } = fakeBackend();
      const user = userEvent.setup();
      renderPage('/admin/launch-radar?sort=added');
      await screen.findByText('Raindrop AI');

      await user.click(screen.getByRole('tab', { name: /archived/i }));
      await screen.findByText('Athennian');
      await user.click(screen.getByRole('tab', { name: /saved/i }));
      await screen.findByText('Kestrel Labs');

      const byStatus = (status: string) =>
        lists().find((c) => c.url.searchParams.get('status') === status)?.url;
      for (const status of ['new', 'archived', 'saved']) {
        expect(byStatus(status)?.searchParams.get('sort')).toBe('added');
      }
      expect(sortButton('Added')).toHaveAttribute('aria-pressed', 'true');
    });

    it('emphasizes the sorted score on every card, and only for a score sort', async () => {
      fakeBackend();
      const user = userEvent.setup();
      renderPage();
      await screen.findByText('Raindrop AI');
      const emphasis = (label: 'Talent' | 'VC') =>
        screen
          .getAllByRole('group', { name: new RegExp(`^${label}( score|:)`) })
          .map((g) => g.getAttribute('data-emphasis'));

      expect(emphasis('Talent')).toEqual(['normal', 'normal']);
      expect(emphasis('VC')).toEqual(['normal', 'normal']);

      await user.click(sortButton('Talent'));
      expect(emphasis('Talent')).toEqual(['strong', 'strong']);
      expect(emphasis('VC')).toEqual(['muted', 'muted']);

      await user.click(sortButton('VC'));
      expect(emphasis('Talent')).toEqual(['muted', 'muted']);
      expect(emphasis('VC')).toEqual(['strong', 'strong']);

      await user.click(sortButton('Added'));
      expect(emphasis('Talent')).toEqual(['normal', 'normal']);
      expect(emphasis('VC')).toEqual(['normal', 'normal']);
    });

    it('is reachable and operable from the keyboard', async () => {
      // The focus ring itself (an outline on `.Mui-focusVisible`) needs a real
      // browser's :focus-visible; jsdom cannot show it.
      const { lists } = fakeBackend();
      const user = userEvent.setup();
      const { location } = renderPage();
      await screen.findByText('Raindrop AI');

      sortButton('Announced').focus();
      await user.keyboard('{Tab}');
      expect(sortButton('Talent')).toHaveFocus();
      await user.keyboard('{Enter}');

      expect(location.search).toBe('?sort=talent');
      await waitFor(() =>
        expect(lists().some((c) => c.url.searchParams.get('sort') === 'talent')).toBe(true)
      );
    });
  });

  describe('when a card leaves the list', () => {
    /** A backend that remembers moves: a card PATCHed or DELETEd leaves its list. */
    function statefulBackend(initial: LaunchRadarCard[]) {
      const cards = new Map(initial.map((c) => [c.id, { ...c }]));
      const calls: Call[] = [];
      global.fetch = vi.fn(async (input: unknown) => {
        const req = input as Request;
        const url = new URL(req.url);
        const body = req.method === 'PATCH' ? await req.json() : undefined;
        calls.push({ method: req.method, url, body });
        const id = Number(url.pathname.split('/').pop());
        if (req.method === 'PATCH') {
          const card = cards.get(id)!;
          card.status = (body as { status: LaunchRadarStatus }).status;
          return jsonResponse(card);
        }
        if (req.method === 'DELETE') {
          cards.delete(id);
          return new Response(null, { status: 204 });
        }
        const status = url.searchParams.get('status');
        const list = [...cards.values()].filter((c) => c.status === status);
        const counts = { new: 0, saved: 0, archived: 0 };
        for (const c of cards.values()) counts[c.status] += 1;
        return jsonResponse(makeCardsResponse({ cards: list, total: list.length, counts }));
      }) as unknown as typeof fetch;
      return { calls };
    }

    const ALL = () => [makeGhostCard(), makeRaindropCard(), makeKestrelCard(), makeAthennianCard()];
    const toggleOf = (company: string) =>
      screen.getByRole('button', { name: new RegExp(`details for ${company}$`) });

    it('moves focus to the next card and announces the move', async () => {
      statefulBackend(ALL());
      const user = userEvent.setup();
      renderPage();
      await screen.findByText('Ghost AI');
      expect(screen.getByRole('status')).toHaveTextContent('');

      await user.click(screen.getByRole('button', { name: 'Archive Ghost AI' }));

      await waitFor(() => expect(screen.queryByText('Ghost AI')).not.toBeInTheDocument());
      await waitFor(() => expect(toggleOf('Raindrop AI')).toHaveFocus());
      expect(screen.getByRole('status')).toHaveTextContent('Archived Ghost AI');
      expect(await screen.findByRole('tab', { name: 'Archived 2' })).toBeInTheDocument();
    });

    it('moves focus to the tab panel when the last card leaves', async () => {
      statefulBackend(ALL());
      const user = userEvent.setup();
      renderPage();
      await screen.findByText('Raindrop AI');

      await user.click(screen.getByRole('button', { name: 'Save Raindrop AI' }));

      await waitFor(() => expect(screen.getByRole('tabpanel')).toHaveFocus());
      expect(screen.getByRole('status')).toHaveTextContent('Saved Raindrop AI');
      expect(screen.queryByText('Raindrop AI')).not.toBeInTheDocument();
      expect(screen.getByText('Ghost AI')).toBeInTheDocument();
    });

    it.each([
      ['saved', 'Unsave Kestrel Labs', 'Unsaved Kestrel Labs'],
      ['archived', 'Restore Athennian', 'Restored Athennian'],
    ])('on the %s tab: %s is announced as "%s"', async (tabName, button, said) => {
      statefulBackend(ALL());
      const user = userEvent.setup();
      renderPage();
      await screen.findByText('Raindrop AI');
      await user.click(screen.getByRole('tab', { name: new RegExp(tabName, 'i') }));

      await user.click(await screen.findByRole('button', { name: button }));

      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(said));
      await waitFor(() => expect(screen.getByRole('tabpanel')).toHaveFocus());
    });

    it('after a permanent delete, announces it and focuses the tab panel', async () => {
      const { calls } = statefulBackend(ALL());
      const user = userEvent.setup();
      renderPage();
      await screen.findByText('Raindrop AI');
      await user.click(screen.getByRole('tab', { name: /archived/i }));
      await user.click(await screen.findByRole('button', { name: 'Delete Athennian' }));
      const dialog = await screen.findByRole('dialog');

      await user.click(within(dialog).getByRole('button', { name: 'Delete' }));

      await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
      expect(calls.some((c) => c.method === 'DELETE')).toBe(true);
      expect(screen.getByRole('status')).toHaveTextContent('Deleted Athennian');
      await waitFor(() => expect(screen.getByRole('tabpanel')).toHaveFocus());
      expect(await screen.findByText('No archived cards.')).toBeInTheDocument();
    });

    it('drops the card at once, before the refetch lands, so its buttons cannot be pressed again', async () => {
      let releaseRefetch: (r: Response) => void = () => {};
      let gets = 0;
      const { calls } = fakeBackend({
        list: () => {
          gets += 1;
          if (gets === 1) return jsonResponse(makeCardsResponse());
          return new Promise<Response>((resolve) => {
            releaseRefetch = resolve;
          });
        },
      });
      const user = userEvent.setup();
      renderPage();
      await screen.findByText('Raindrop AI');

      await user.click(screen.getByRole('button', { name: 'Archive Raindrop AI' }));

      // The PATCH has landed and the refetch is still open: the card is gone
      // (no stale "Save Raindrop AI" to press into a 409) and the counts moved.
      await waitFor(() => expect(screen.queryByText('Raindrop AI')).not.toBeInTheDocument());
      expect(screen.queryByRole('button', { name: /Raindrop AI$/ })).toBeNull();
      expect(screen.getByRole('tab', { name: 'New 1' })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: 'Archived 2' })).toBeInTheDocument();
      expect(calls.filter((c) => c.method === 'PATCH')).toHaveLength(1);
      expect(gets).toBe(2); // the refetch is in flight

      releaseRefetch(
        jsonResponse(
          makeCardsResponse({
            cards: [makeGhostCard()],
            total: 1,
            counts: { new: 1, saved: 1, archived: 2 },
          })
        )
      );
      await waitFor(() => expect(screen.getByText('Ghost AI')).toBeInTheDocument());
    });
  });
});
