import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { MyCompaniesPage } from '../../../pages/MyCompaniesPage';
import type { GetUserCompaniesResponse } from '../../../features/userCompanies/userCompaniesApi';

// `fetchBaseQuery` builds relative URLs, which Node's `Request` rejects.
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

const mockAuthState = {
  isEnabled: true,
  isAuthenticated: true,
  isLoading: false,
  login: vi.fn(),
  logout: vi.fn(),
  getToken: vi.fn(),
  user: null,
};

vi.mock('../../../features/auth/useAuth', () => ({
  useAuth: () => mockAuthState,
}));

// The saved-companies list has its own test file and fires its own mount fetch;
// stub it here so these add-flow tests keep a single, predictable call ordering
// (the add POST is the only request they make).
vi.mock('../../../components/my-companies/MyCompaniesList', () => ({
  MyCompaniesList: () => <div data-testid="my-companies-list-stub" />,
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

/** A `201` from the add endpoint — the ordinary "it worked" answer for an ATS board. */
const CREATED = {
  id: 'u-intel00001',
  displayName: 'intel',
  ats: 'workday',
  boardToken: 'intel',
  sourceId: 'custom:u-intel00001',
  healthState: 'unverified',
  // ZERO on purpose, and it is what the real endpoint returns: the row is created and
  // its first harvest only just enqueued, so nothing has been counted yet.
  openJobCount: 0,
  lastSuccessAt: null,
  trackingStartedAt: null,
};

/** The add endpoint's `202` when a non-ATS URL is routed to one-time discovery. */
const DISCOVERY_202 = {
  status: 'discovery_pending',
  detail:
    "One-time setup — we're figuring out how to read this board; jobs appear after the first scan.",
  finalUrl: 'https://acme.example/careers',
  id: 'u-abc1234567',
  sourceId: 'custom:u-abc1234567',
};

let fetchMock: ReturnType<typeof vi.fn>;

/**
 * What `GET /api/users/companies` answers with. Only the `quota` half matters here —
 * `MyCompaniesList` is stubbed out, so nothing on this page renders the rows.
 * Reset per test; the counter tests below set it.
 */
let listBody: GetUserCompaniesResponse = { companies: [] };

/** The page's mount fetch for the add counter. NOT an add. */
function isListGet(input: Request): boolean {
  return input.method === 'GET' && input.url.includes('/users/companies');
}

beforeEach(() => {
  mockAuthState.isAuthenticated = true;
  mockAuthState.isLoading = false;
  listBody = { companies: [] };
  fetchMock = vi.fn();
  // The list GET is answered HERE, in front of `fetchMock`, so the per-test mocks
  // below never see it. Two reasons, both of which bit when it went through them:
  //
  //  * `mockResolvedValue(jsonResponse(...))` hands out ONE `Response` object, and a
  //    body can only be read once — the mount GET would consume it and every test's
  //    real assertion would then read an already-drained body.
  //  * `fetchMock.mock.calls` is what tests index into (`calls[0]` is "the add POST")
  //    and filter (`addCalls()`), and a mount GET would silently shift both.
  //
  // Set `listBody` to change what it answers.
  const delegate = fetchMock as unknown as (input: Request) => Promise<Response>;
  globalThis.fetch = ((input: Request) =>
    isListGet(input)
      ? Promise.resolve(jsonResponse(listBody))
      : delegate(input)) as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** Requests the page made to `POST /api/users/companies` — i.e. every add. */
function addCalls(): Request[] {
  return fetchMock.mock.calls
    .map(([input]) => input as Request)
    .filter((req) => req.url.includes('/users/companies'));
}

async function submitUrl(url = 'https://intel.com/careers') {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/job board link/i), url);
  await user.click(screen.getByRole('button', { name: /add company/i }));
  return user;
}

describe('MyCompaniesPage', () => {
  it('shows a spinner while auth is still resolving', () => {
    // Without this branch the page would flash the signed-out prompt at an
    // already-signed-in user on every load.
    mockAuthState.isLoading = true;
    renderWithProviders(<MyCompaniesPage />);

    expect(screen.getByRole('progressbar')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /sign in/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/job board link/i)).not.toBeInTheDocument();
  });

  // The page is named "Add Companies" in the sidebar, so it has to be named that here
  // too — a nav entry that lands on a differently-titled page reads as a wrong turn.
  // Both auth states carry the name, because the signed-out prompt is the first thing a
  // logged-out visitor following the nav link sees.
  it('titles the page "Add Companies" once signed in', () => {
    renderWithProviders(<MyCompaniesPage />);
    // "Beta" is INSIDE the <h1>, so it lands in the heading's accessible name.
    // That is the point of the badge markup: a screen reader still reads the
    // status as part of the title rather than skipping it as decoration.
    expect(
      screen.getByRole('heading', { level: 1, name: 'Add Companies Beta' })
    ).toBeInTheDocument();
  });

  describe('signed out', () => {
    it('names the page in the sign-in prompt too', () => {
      mockAuthState.isAuthenticated = false;
      renderWithProviders(<MyCompaniesPage />);

      expect(screen.getByRole('heading', { name: 'Add Companies Beta' })).toBeInTheDocument();
    });

    it('shows a sign-in prompt instead of the form', () => {
      mockAuthState.isAuthenticated = false;
      renderWithProviders(<MyCompaniesPage />);

      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
      expect(screen.queryByLabelText(/job board link/i)).not.toBeInTheDocument();
    });

    it('calls login() when the prompt button is clicked', async () => {
      mockAuthState.isAuthenticated = false;
      const user = userEvent.setup();
      renderWithProviders(<MyCompaniesPage />);

      await user.click(screen.getByRole('button', { name: /sign in/i }));
      expect(mockAuthState.login).toHaveBeenCalled();
    });

    it('makes no network call while signed out', () => {
      mockAuthState.isAuthenticated = false;
      renderWithProviders(<MyCompaniesPage />);
      expect(fetchMock).not.toHaveBeenCalled();
    });
  });

  describe('signed in', () => {
    it('says the press adds the company, and names the spend, before anything is pasted', () => {
      renderWithProviders(<MyCompaniesPage />);
      const alert = screen.getByRole('alert');

      // THE CONSENT. It used to promise "nothing is tracked until you press Track this
      // company" — a button that no longer exists. Leaving that sentence would have
      // been a lie about spending on a page whose submit can start a headless browser
      // session and an LLM call.
      expect(alert).toHaveTextContent(/press add company — that adds it/i);
      expect(alert).not.toHaveTextContent(/nothing is tracked until/i);
      expect(alert).not.toHaveTextContent(/track this company/i);
      // …and it still names the paid branch and when it starts.
      expect(alert).toHaveTextContent(/one-time setup/i);
      expect(alert).toHaveTextContent(/begins immediately/i);
      expect(alert).toHaveTextContent(/private to you/i);

      // The ALERT is where all of that lives, alone. The field's helper text used to
      // repeat the whole branch, which made it three clauses long under a one-line
      // input — a length people skip, and skipped consent is not consent.
      const helper = screen.getByText(/paste the exact job board link/i);
      expect(helper).not.toHaveTextContent(/one-time setup/i);
    });

    it('labels the button for what it actually does, not just a read-only check', () => {
      renderWithProviders(<MyCompaniesPage />);
      expect(screen.getByRole('button', { name: /add company/i })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /^check url$/i })).not.toBeInTheDocument();
    });

    it('disables the submit button until a URL is entered', async () => {
      const user = userEvent.setup();
      renderWithProviders(<MyCompaniesPage />);

      const button = screen.getByRole('button', { name: /add company/i });
      expect(button).toBeDisabled();

      await user.type(screen.getByLabelText(/job board link/i), 'https://intel.com');
      expect(button).toBeEnabled();
    });

    it('keeps submit disabled for whitespace-only input', async () => {
      const user = userEvent.setup();
      renderWithProviders(<MyCompaniesPage />);

      await user.type(screen.getByLabelText(/job board link/i), '   ');
      expect(screen.getByRole('button', { name: /add company/i })).toBeDisabled();
    });

    it('trims whitespace before sending the URL', async () => {
      fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('  https://intel.com/careers  ');

      await waitFor(() => expect(addCalls()).toHaveLength(1));
      await expect(addCalls()[0].text()).resolves.toBe(
        JSON.stringify({ url: 'https://intel.com/careers' })
      );
    });

    it('submits on Enter', async () => {
      fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
      const user = userEvent.setup();
      renderWithProviders(<MyCompaniesPage />);

      await user.type(screen.getByLabelText(/job board link/i), 'https://intel.com{Enter}');

      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    });
  });

  // THE DEFECT THIS CLOSES, in the owner's words: "We don't need this extra step. When
  // we say add company, we add it simple. And it either succeeds or fails."
  //
  // Pressing Add company used to run `POST /api/companies/resolve`, render a preview
  // card ("Found 663 open jobs on Workday") with a board / how-we-found-it / final-URL
  // grid, and wait for a SECOND press on "Track this company". The add endpoint
  // re-resolved the raw URL from scratch anyway, so that second press decided nothing.
  describe('one press, one outcome', () => {
    it('adds an ATS board from a single submit, with no confirm step', async () => {
      fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl();

      expect(await screen.findByTestId('add-company-success')).toBeInTheDocument();
      expect(screen.getByText(/now tracking intel/i)).toBeInTheDocument();
      expect(screen.getByTestId('view-company-link')).toHaveAttribute(
        'href',
        '/add-companies/u-intel00001'
      );
      // Exactly one request, and no button standing between the press and the result.
      expect(addCalls()).toHaveLength(1);
      expect(screen.queryByTestId('add-company-button')).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /track this company/i })
      ).not.toBeInTheDocument();
    });

    it('never calls the resolve endpoint', async () => {
      // `POST /api/companies/resolve` still exists and is still tested server-side —
      // the frontend just stopped calling it. Every request this page makes goes to
      // `users/companies`.
      fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl();

      await waitFor(() => expect(addCalls()).toHaveLength(1));
      const urls = fetchMock.mock.calls.map(([input]) => (input as Request).url);
      expect(urls.some((url) => url.includes('/companies/resolve'))).toBe(false);
    });

    it('drops the preview grid entirely', async () => {
      // The grid answered "is this the right board?" BEFORE committing. After a
      // one-click add there is nothing left to decide, and the board link lives on the
      // company's own page.
      fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl();

      await screen.findByTestId('add-company-success');
      expect(screen.queryByTestId('resolve-result')).not.toBeInTheDocument();
      expect(screen.queryByTestId('resolve-headline')).not.toBeInTheDocument();
      expect(screen.queryByTestId('resolve-hops')).not.toBeInTheDocument();
      expect(screen.queryByText(/how we found it/i)).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /redirect chain/i })).not.toBeInTheDocument();
    });

    it('shows one "Adding…" state while the call is in flight, not two phases', async () => {
      let release: (response: Response) => void = () => {};
      const held = new Promise<Response>((resolve) => {
        release = resolve;
      });
      fetchMock.mockImplementation(() => held);
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl();

      await waitFor(() =>
        expect(screen.getByRole('button', { name: /adding/i })).toBeDisabled()
      );
      // The two phase-specific labels are gone with the second call they named.
      expect(screen.queryByRole('button', { name: /checking/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /setting up/i })).not.toBeInTheDocument();
      expect(screen.getByText(/adding this company/i)).toBeInTheDocument();

      release(jsonResponse(CREATED, 201));
      expect(await screen.findByTestId('add-company-success')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /add company/i })).toBeEnabled();
    });

    it('starts a one-time setup for a non-ATS URL from that same press', async () => {
      fetchMock.mockResolvedValue(jsonResponse(DISCOVERY_202, 202));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://acme.example/careers');

      expect(await screen.findByTestId('discovery-pending')).toBeInTheDocument();
      expect(addCalls()).toHaveLength(1);
      expect(screen.queryByTestId('add-company-error')).not.toBeInTheDocument();
    });

    it('sends the URL the user typed, not a normalized one', async () => {
      // The endpoint records `submitted_url`, so handing it the original keeps the
      // server-side audit trail matching what was pasted.
      fetchMock.mockResolvedValue(jsonResponse(DISCOVERY_202, 202));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://acme.example/careers');

      await waitFor(() => expect(addCalls()).toHaveLength(1));
      await expect(addCalls()[0].text()).resolves.toBe(
        JSON.stringify({ url: 'https://acme.example/careers' })
      );
    });

    it('resolves an already-owned board to its tracked company (idempotent 200)', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse(
          {
            id: 'u-abc1234567',
            displayName: 'acme.example',
            ats: 'discovered',
            boardToken: 'acme',
            sourceId: 'custom:u-abc1234567',
            healthState: 'unverified',
            openJobCount: 12,
            lastSuccessAt: null,
            trackingStartedAt: null,
          },
          200
        )
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://acme.example/careers');

      expect(await screen.findByTestId('add-company-success')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /view its trend page/i })).toHaveAttribute(
        'href',
        '/add-companies/u-abc1234567'
      );
    });
  });

  describe('a company we already publish', () => {
    it('links to the public page — and starts NO discovery — for a script board', async () => {
      // Pasting Microsoft's careers page resolves to no ATS (it is published with
      // `ats='script'`), and the backend's careers-host match answers `already_public`
      // on the add POST instead of spending a Claude call and a Chromium session on a
      // private duplicate of a board on our own front page.
      const MICROSOFT_URL = 'https://jobs.careers.microsoft.com/global/en/search';
      fetchMock.mockResolvedValue(
        jsonResponse(
          {
            status: 'already_public',
            detail:
              'That URL is the same job board as our public Microsoft page, so there ' +
              'is nothing to set up — its hiring trend is already there.',
            companyId: 'microsoft',
            displayName: 'Microsoft',
            finalUrl: MICROSOFT_URL,
          },
          200
        )
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl(MICROSOFT_URL);

      const notice = await screen.findByTestId('already-public');
      // The exact-match notice is one line — headline and link, no restated server
      // detail (that's the "same job board, not the same company" nuance the mocked
      // `detail` above carries; the guessed-match notice below still surfaces it).
      expect(notice).toHaveTextContent(/we already track microsoft/i);
      expect(screen.getByTestId('already-public-link')).toHaveAttribute(
        'href',
        '/companies?company=microsoft'
      );
      // NOT the setting-up notice, and not an error either.
      expect(screen.queryByTestId('discovery-pending')).not.toBeInTheDocument();
      expect(screen.queryByTestId('add-company-error')).not.toBeInTheDocument();
      // Exactly one add POST — the one that answered. Nothing retried into discovery.
      expect(addCalls()).toHaveLength(1);
    });

    it('gives no way past an exact match', async () => {
      // A careers-host hit is an exact match against our own declared table — the user
      // pasted Amazon's board, and a private duplicate re-scrapes the same feed for a
      // chart whose history starts today while the full one is a click away. The only
      // way onward is the link.
      const AMAZON_URL = 'https://www.amazon.jobs/en/search';
      fetchMock.mockResolvedValue(
        jsonResponse(
          {
            status: 'already_public',
            detail: 'That URL is the same job board as our public Amazon page.',
            companyId: 'amazon',
            displayName: 'Amazon',
            finalUrl: AMAZON_URL,
            matchKind: 'board',
          },
          200
        )
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl(AMAZON_URL);
      const notice = await screen.findByTestId('already-public');

      expect(notice).toHaveTextContent(/we already track amazon/i);
      expect(screen.queryByTestId('track-anyway-button')).not.toBeInTheDocument();
      expect(screen.getByTestId('already-public-link')).toBeInTheDocument();
      expect(addCalls()).toHaveLength(1);
    });

    it('catches a vanity careers domain by name, and lets the user say we guessed wrong', async () => {
      // The third dedupe rung, end to end. `lifeatspotify.com` resolves to no ATS at
      // all, so the backend matches the NAME in the domain and answers before spending
      // a discovery. That is a guess, so unlike the exact rung above it keeps a way out
      // — and the correction routes to the ordinary discovery path.
      const SPOTIFY_URL = 'https://www.lifeatspotify.com/jobs';
      let addCallCount = 0;
      fetchMock.mockImplementation(() => {
        addCallCount += 1;
        return Promise.resolve(
          addCallCount === 1
            ? jsonResponse(
                {
                  status: 'already_public',
                  detail:
                    'That web address looks like Spotify, which we already publish — ' +
                    'we matched the name in the web address, not the board itself.',
                  companyId: 'spotify',
                  displayName: 'Spotify',
                  finalUrl: SPOTIFY_URL,
                  matchKind: 'name',
                },
                200
              )
            : jsonResponse({ ...DISCOVERY_202, finalUrl: SPOTIFY_URL }, 202)
        );
      });
      renderWithProviders(<MyCompaniesPage />);

      const user = await submitUrl(SPOTIFY_URL);
      const notice = await screen.findByTestId('already-public');

      // The headline must not read like the exact rung's.
      expect(notice).toHaveTextContent(/this looks like spotify, which we already track/i);

      await user.click(screen.getByTestId('track-anyway-button'));

      expect(await screen.findByTestId('discovery-pending')).toBeInTheDocument();
      const [, second] = addCalls();
      // The override rides the SECOND add, with the URL the server settled on.
      await expect(second.clone().text()).resolves.toBe(
        JSON.stringify({ url: SPOTIFY_URL, trackAnyway: true })
      );
    });
  });

  // Every failure the add endpoint can answer with now lands in ONE alert. Some of
  // these reason codes used to be answered by the separate resolve call and rendered
  // by a different component; the copy must not have degraded on the way over.
  describe('failures', () => {
    it('degrades to a truthful message — not a spinner — when discovery is disabled server-side', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse(
          {
            reason: 'no_ats_detected',
            detail: 'No supported ATS board was found behind this URL.',
            finalUrl: 'https://acme.example/careers',
          },
          422
        )
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://acme.example/careers');

      const alert = await screen.findByTestId('add-company-error');
      expect(alert).toHaveTextContent('No supported ATS board was found behind this URL.');
      expect(alert).toHaveTextContent('Greenhouse');
      // The whole point: it settles. No spinner left running, no "Adding…" forever.
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
      expect(screen.queryByTestId('discovery-pending')).not.toBeInTheDocument();
    });

    it("renders the resolver's own copy for a transport failure", async () => {
      fetchMock.mockResolvedValue(
        jsonResponse(
          { reason: 'fetch_failed', detail: 'Could not load that page.', finalUrl: 'https://acme.example' },
          422
        )
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://acme.example/careers');

      const alert = await screen.findByTestId('add-company-error');
      expect(alert).toHaveTextContent(/couldn't load that page/i);
      // Title + one plain sentence. The raw code is only printed for a reason no
      // vocabulary on this page recognises.
      expect(alert).not.toHaveTextContent('fetch_failed');
    });

    it('names a private-network address for what it is', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse(
          { reason: 'resolves_to_private_address', detail: '', finalUrl: 'https://localhost/x' },
          422
        )
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://localhost/x');

      expect(await screen.findByTestId('add-company-error')).toHaveTextContent(
        /private network/i
      );
    });

    it('does not render [object Object] for a FastAPI validation 422', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({ detail: [{ loc: ['body', 'url'], msg: 'Field required' }] }, 422)
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('not-a-url');

      const alert = await screen.findByTestId('add-company-error');
      expect(alert).toHaveTextContent('Field required');
      expect(alert.textContent).not.toContain('[object Object]');
      expect(alert.textContent).not.toContain('undefined');
    });

    it('renders the mapped message for a 503 (server flag off)', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({ detail: 'Custom company sources are not enabled' }, 503)
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl();

      expect(await screen.findByTestId('add-company-error')).toHaveTextContent(/turned off/i);
    });

    it('leaves the field editable so a bad URL can be corrected rather than retyped', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({ reason: 'no_ats_detected', detail: 'Nope.', finalUrl: '' }, 422)
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://acme.example/carrers');

      await screen.findByTestId('add-company-error');
      expect(screen.getByLabelText(/job board link/i)).toBeEnabled();
      expect(screen.getByLabelText(/job board link/i)).toHaveValue(
        'https://acme.example/carrers'
      );
    });
  });

  describe('the monthly add counter', () => {
    const RESETS_AT = '2026-09-01T00:00:00Z';

    it('states the allowance in one line at the top of the page', async () => {
      listBody = { companies: [], quota: { used: 3, limit: 20, resetsAt: RESETS_AT } };
      renderWithProviders(<MyCompaniesPage />);

      const counter = await screen.findByTestId('add-quota-counter');
      expect(counter).toHaveTextContent('17 of 20 adds left this month');
      // One line, not an alert. A notice that appears when the number gets low is an
      // interruption; a counter that is always there is a fact you can check.
      expect(screen.queryByRole('alert', { name: /adds left/i })).not.toBeInTheDocument();
    });

    it('decrements as adds are spent', async () => {
      listBody = { companies: [], quota: { used: 19, limit: 20, resetsAt: RESETS_AT } };
      renderWithProviders(<MyCompaniesPage />);

      expect(await screen.findByTestId('add-quota-counter')).toHaveTextContent(
        '1 of 20 adds left this month'
      );
    });

    it('reads "0 of 20" and disables the submit when the month is spent', async () => {
      listBody = { companies: [], quota: { used: 20, limit: 20, resetsAt: RESETS_AT } };
      const user = userEvent.setup();
      renderWithProviders(<MyCompaniesPage />);

      expect(await screen.findByTestId('add-quota-counter')).toHaveTextContent(
        '0 of 20 adds left this month'
      );
      // The FIELD stays usable — someone can still paste a URL they are queuing up
      // for next month, and a dead input reads as a broken page.
      await user.type(screen.getByLabelText(/job board link/i), 'https://intel.com/careers');
      expect(screen.getByRole('button', { name: /add company/i })).toBeDisabled();
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('reads "0 of 0" and disables the submit when the limit is 0', async () => {
      // THE CASE THAT SWAPPED. `limit: 0` used to mean unlimited — no counter, submit
      // enabled. It is now the kill switch: a cap in force that allows nothing, and it
      // gets the same treatment as a spent month because it is the same fact.
      listBody = { companies: [], quota: { used: 0, limit: 0, resetsAt: RESETS_AT } };
      const user = userEvent.setup();
      renderWithProviders(<MyCompaniesPage />);

      expect(await screen.findByTestId('add-quota-counter')).toHaveTextContent(
        '0 of 0 adds left this month'
      );
      await user.type(screen.getByLabelText(/job board link/i), 'https://intel.com/careers');
      expect(screen.getByRole('button', { name: /add company/i })).toBeDisabled();
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('renders no counter, and still lets the user add, when the server sends no quota', async () => {
      // A server older than this feature — and now the ONLY case that renders nothing.
      // "We don't know" must never be read as "you have none left": locking someone out
      // of the whole feature on a missing field is the worst possible reading of it,
      // and the server refuses over quota regardless of what this button does. This is
      // deliberately NOT the same case as `limit: 0` above.
      listBody = { companies: [] };
      const user = userEvent.setup();
      renderWithProviders(<MyCompaniesPage />);

      await user.type(screen.getByLabelText(/job board link/i), 'https://intel.com/careers');
      expect(screen.queryByTestId('add-quota-counter')).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /add company/i })).toBeEnabled();
    });
  });
});
