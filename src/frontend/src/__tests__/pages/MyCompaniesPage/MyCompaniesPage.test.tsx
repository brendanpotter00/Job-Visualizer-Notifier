import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { MyCompaniesPage } from '../../../pages/MyCompaniesPage';
import type { ResolveUrlResponse } from '../../../features/userCompanies/userCompaniesApi';

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
// stub it here so these resolve-flow tests keep a single, predictable call
// ordering (the resolve POST is the only request they make).
vi.mock('../../../components/my-companies/MyCompaniesList', () => ({
  MyCompaniesList: () => <div data-testid="my-companies-list-stub" />,
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const SUCCESS: ResolveUrlResponse = {
  candidate: {
    ats: 'workday',
    boardToken: 'intel',
    providerConfig: { baseUrl: 'https://intel.wd1.myworkdayjobs.com', tenantSlug: 'intel' },
    sourceUrl: 'https://intel.wd1.myworkdayjobs.com/External',
  },
  probe: { ok: true, jobCount: 663, error: null },
  via: 'direct',
  hops: [],
  finalUrl: 'https://intel.wd1.myworkdayjobs.com/External',
};

/** The resolver's flat 422 for "we read the page and there is no board we support". */
const NO_ATS_422 = {
  reason: 'no_ats_detected',
  finalUrl: 'https://acme.example/careers',
  hops: [],
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

beforeEach(() => {
  mockAuthState.isAuthenticated = true;
  mockAuthState.isLoading = false;
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** Requests the page made to `POST /api/users/companies` — i.e. every add/discovery start. */
function addCalls(): Request[] {
  return fetchMock.mock.calls
    .map(([input]) => input as Request)
    .filter((req) => req.url.includes('/users/companies'));
}

/**
 * Answers the resolve endpoint with `resolve` and the add endpoint with `add`.
 * Routing by URL (rather than by call order) is what lets a test assert that the add
 * endpoint was never touched at all.
 */
function routeFetch(resolve: Response, add?: Response) {
  fetchMock.mockImplementation((input: Request) =>
    Promise.resolve(
      input.url.includes('/users/companies')
        ? (add ?? jsonResponse({ detail: 'unexpected add' }, 500))
        : resolve,
    ),
  );
}

async function submitUrl(url = 'https://intel.com/careers') {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/careers page url/i), url);
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
    expect(screen.queryByLabelText(/careers page url/i)).not.toBeInTheDocument();
  });

  // The page is named "Add Companies" in the sidebar, so it has to be named that here
  // too — a nav entry that lands on a differently-titled page reads as a wrong turn.
  // Both auth states carry the name, because the signed-out prompt is the first thing a
  // logged-out visitor following the nav link sees.
  it('titles the page "Add Companies" once signed in', () => {
    renderWithProviders(<MyCompaniesPage />);
    expect(screen.getByRole('heading', { level: 1, name: 'Add Companies' })).toBeInTheDocument();
  });

  describe('signed out', () => {
    it('names the page in the sign-in prompt too', () => {
      mockAuthState.isAuthenticated = false;
      renderWithProviders(<MyCompaniesPage />);

      expect(screen.getByRole('heading', { name: 'Add Companies' })).toBeInTheDocument();
    });

    it('shows a sign-in prompt instead of the form', () => {
      mockAuthState.isAuthenticated = false;
      renderWithProviders(<MyCompaniesPage />);

      expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
      expect(screen.queryByLabelText(/careers page url/i)).not.toBeInTheDocument();
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
    it('discloses both outcomes before the user pastes anything', () => {
      renderWithProviders(<MyCompaniesPage />);
      // The single submit can start a paid one-time discovery without asking again, so
      // this copy IS the consent — a recognized board is still preview-then-confirm, but
      // an unrecognized one starts work immediately and the page has to say so up front.
      expect(screen.getByText(/nothing is tracked until you press/i)).toBeInTheDocument();
      expect(screen.getByText(/that begins straight away/i)).toBeInTheDocument();
      // The field's own helper text has to carry it too — it is the last thing read
      // before the button is pressed.
      expect(screen.getByText(/we start a one-time setup to learn how to read it/i))
        .toBeInTheDocument();
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

      await user.type(screen.getByLabelText(/careers page url/i), 'https://intel.com');
      expect(button).toBeEnabled();
    });

    it('keeps submit disabled for whitespace-only input', async () => {
      const user = userEvent.setup();
      renderWithProviders(<MyCompaniesPage />);

      await user.type(screen.getByLabelText(/careers page url/i), '   ');
      expect(screen.getByRole('button', { name: /add company/i })).toBeDisabled();
    });

    it('trims whitespace before sending the URL', async () => {
      fetchMock.mockResolvedValue(jsonResponse(SUCCESS));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('  https://intel.com/careers  ');

      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      const [input] = fetchMock.mock.calls[0] as [Request];
      await expect(input.text()).resolves.toBe(
        JSON.stringify({ url: 'https://intel.com/careers' })
      );
    });

    it('submits on Enter', async () => {
      fetchMock.mockResolvedValue(jsonResponse(SUCCESS));
      const user = userEvent.setup();
      renderWithProviders(<MyCompaniesPage />);

      await user.type(screen.getByLabelText(/careers page url/i), 'https://intel.com{Enter}');

      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    });

    it('renders the job count and ATS on a successful resolve', async () => {
      fetchMock.mockResolvedValue(jsonResponse(SUCCESS));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl();

      const headline = await screen.findByTestId('resolve-headline');
      expect(headline).toHaveTextContent('663');
      expect(headline).toHaveTextContent(/workday/i);
      expect(screen.getByText('intel')).toBeInTheDocument();
    });

    it('explains `via` in plain words rather than showing the raw token', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ ...SUCCESS, via: 'embedded' }));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl();

      expect(await screen.findByText(/embedded in the page/i)).toBeInTheDocument();
    });

    it('renders the redirect chain in a collapsible section when hops exist', async () => {
      const user = userEvent.setup();
      fetchMock.mockResolvedValue(
        jsonResponse({
          ...SUCCESS,
          via: 'redirect',
          hops: ['https://intel.com/careers', 'https://intel.wd1.myworkdayjobs.com/External'],
        })
      );
      renderWithProviders(<MyCompaniesPage />);

      await user.type(screen.getByLabelText(/careers page url/i), 'https://intel.com');
      await user.click(screen.getByRole('button', { name: /add company/i }));

      const toggle = await screen.findByRole('button', { name: /redirect chain \(2\)/i });
      await user.click(toggle);
      expect(screen.getByTestId('resolve-hops')).toBeInTheDocument();
    });

    it('renders probe.ok === false as its own state, not as "0 open jobs"', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({
          ...SUCCESS,
          probe: { ok: false, jobCount: 0, error: 'Board returned HTTP 404' },
        })
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl();

      expect(await screen.findByTestId('resolve-probe-failed')).toBeInTheDocument();
      expect(screen.getByTestId('probe-error')).toHaveTextContent('Board returned HTTP 404');
      expect(screen.queryByTestId('resolve-headline')).not.toBeInTheDocument();
      expect(screen.queryByText(/found 0 open jobs/i)).not.toBeInTheDocument();
    });

    it('renders the mapped message for a 503 (server flag off)', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({ detail: 'Custom company sources are not enabled' }, 503)
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl();

      expect(await screen.findByTestId('resolve-error')).toHaveTextContent(/turned off/i);
    });

    it('does not render [object Object] for a FastAPI validation 422', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({ detail: [{ loc: ['body', 'url'], msg: 'Field required' }] }, 422)
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl();

      const alert = await screen.findByTestId('resolve-error');
      expect(alert).toHaveTextContent('Field required');
      expect(alert.textContent).not.toContain('[object Object]');
      expect(alert.textContent).not.toContain('undefined');
    });
  });

  // The defect: "There should not be two steps between checking a URL and doing the
  // one-time discovery." A URL with no supported ATS behind it must reach discovery from the
  // SAME action, while everything else keeps the behavior it had.
  describe('one-action discovery (non-ATS URL)', () => {
    it('starts discovery from a single submit, with no second button to click', async () => {
      routeFetch(jsonResponse(NO_ATS_422, 422), jsonResponse(DISCOVERY_202, 202));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://acme.example/careers');

      // No intervening click: the add POST fired off the back of the resolve failure.
      await waitFor(() => expect(addCalls()).toHaveLength(1));
      expect(await screen.findByTestId('discovery-pending')).toBeInTheDocument();
      expect(screen.queryByTestId('discovery-button')).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /try one-time discovery/i })
      ).not.toBeInTheDocument();
    });

    it('sends the URL the user submitted to the add endpoint', async () => {
      routeFetch(jsonResponse(NO_ATS_422, 422), jsonResponse(DISCOVERY_202, 202));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://acme.example/careers');

      await waitFor(() => expect(addCalls()).toHaveLength(1));
      await expect(addCalls()[0].text()).resolves.toBe(
        JSON.stringify({ url: 'https://acme.example/careers' })
      );
    });

    it('shows the one-time-setup notice instead of a red "no job board" error', async () => {
      routeFetch(jsonResponse(NO_ATS_422, 422), jsonResponse(DISCOVERY_202, 202));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://acme.example/careers');

      expect(await screen.findByTestId('discovery-pending')).toBeInTheDocument();
      // Reporting a failure above a setup that is working would be a lie.
      expect(screen.queryByTestId('resolve-error')).not.toBeInTheDocument();
    });

    it('stays visibly busy across both calls instead of going dead between them', async () => {
      // The single action is resolve-then-maybe-discover. If the busy state were derived
      // from the two mutations' own flags, the form would re-enable in the handoff and
      // flash the raw resolver error mid-action — and a second submit there would start a
      // second paid discovery.
      let releaseAdd: (response: Response) => void = () => {};
      const heldAdd = new Promise<Response>((resolve) => {
        releaseAdd = resolve;
      });
      fetchMock.mockImplementation((input: Request) =>
        input.url.includes('/users/companies')
          ? heldAdd
          : Promise.resolve(jsonResponse(NO_ATS_422, 422))
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://acme.example/careers');

      await waitFor(() =>
        expect(screen.getByRole('button', { name: /setting up/i })).toBeDisabled()
      );
      expect(screen.getByText(/setting this board up/i)).toBeInTheDocument();
      expect(screen.queryByTestId('resolve-error')).not.toBeInTheDocument();

      releaseAdd(jsonResponse(DISCOVERY_202, 202));

      expect(await screen.findByTestId('discovery-pending')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /add company/i })).toBeEnabled();
    });

    it('resolves an already-discovered board to the tracked company (idempotent 200)', async () => {
      routeFetch(
        jsonResponse(NO_ATS_422, 422),
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

      expect(await screen.findByTestId('discovery-already-tracked')).toBeInTheDocument();
      expect(screen.getByRole('link', { name: /view its trend page/i })).toHaveAttribute(
        'href',
        '/add-companies/u-abc1234567'
      );
    });

    it('links to the public page — and starts NO discovery — for a script board we already publish', async () => {
      // THE BUG THIS CLOSES, end to end. Pasting Microsoft's careers page resolved to
      // no ATS (it is published with `ats='script'`), so the page auto-started a
      // one-time discovery: a Claude call and a headless Chromium session to build a
      // private duplicate of a board on our own front page. The backend's careers-host
      // match now answers `already_public` on that same POST instead.
      const MICROSOFT_URL = 'https://jobs.careers.microsoft.com/global/en/search';
      routeFetch(
        jsonResponse({ ...NO_ATS_422, finalUrl: MICROSOFT_URL }, 422),
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
      expect(notice).toHaveTextContent(/we already track microsoft/i);
      // "the same job board", never "the same company" — we matched a host, not a job set.
      expect(notice).toHaveTextContent(/the same job board/i);
      expect(screen.getByTestId('already-public-link')).toHaveAttribute(
        'href',
        '/companies?company=microsoft'
      );
      // NOT the setting-up notice, and not an error either.
      expect(screen.queryByTestId('discovery-pending')).not.toBeInTheDocument();
      expect(screen.queryByTestId('discovery-error')).not.toBeInTheDocument();
      // Exactly one add POST — the one that answered. Nothing retried into discovery.
      expect(addCalls()).toHaveLength(1);
    });

    it('still lets the user take a private copy of a script board anyway', async () => {
      // The escape hatch must survive: some people legitimately want their own copy,
      // which is why "we already track this" is a 200 rather than a refusal.
      const AMAZON_URL = 'https://www.amazon.jobs/en/search';
      let addCallCount = 0;
      fetchMock.mockImplementation((input: Request) => {
        if (!input.url.includes('/users/companies')) {
          return Promise.resolve(jsonResponse({ ...NO_ATS_422, finalUrl: AMAZON_URL }, 422));
        }
        addCallCount += 1;
        return Promise.resolve(
          addCallCount === 1
            ? jsonResponse(
                {
                  status: 'already_public',
                  detail: 'That URL is the same job board as our public Amazon page.',
                  companyId: 'amazon',
                  displayName: 'Amazon',
                  finalUrl: AMAZON_URL,
                },
                200
              )
            : jsonResponse({ ...DISCOVERY_202, finalUrl: AMAZON_URL }, 202)
        );
      });
      renderWithProviders(<MyCompaniesPage />);

      const user = await submitUrl(AMAZON_URL);
      await screen.findByTestId('already-public');

      await user.click(screen.getByTestId('track-anyway-button'));

      expect(await screen.findByTestId('discovery-pending')).toBeInTheDocument();
      const [, second] = addCalls();
      // The override rides the SECOND add, with the URL the server settled on.
      await expect(second.clone().text()).resolves.toBe(
        JSON.stringify({ url: AMAZON_URL, trackAnyway: true })
      );
    });

    it('degrades to a truthful message — not a spinner — when discovery is disabled server-side', async () => {
      // `custom_company_discovery_enabled` OFF: the add endpoint never starts discovery
      // and answers 422 with the same "no supported ATS board" verdict.
      routeFetch(
        jsonResponse(NO_ATS_422, 422),
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

      const alert = await screen.findByTestId('discovery-error');
      expect(alert).toHaveTextContent('No supported ATS board was found behind this URL.');
      expect(alert).toHaveTextContent('Greenhouse');
      // The whole point: it settles. No spinner left running, no "Setting up…" forever.
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
      expect(screen.queryByTestId('discovery-pending')).not.toBeInTheDocument();
    });
  });

  describe('paths that must NOT auto-start discovery', () => {
    it('still requires an explicit confirm for a resolvable ATS board', async () => {
      routeFetch(
        jsonResponse(SUCCESS),
        jsonResponse(
          {
            id: 'u-intel00001',
            displayName: 'intel',
            ats: 'workday',
            boardToken: 'intel',
            sourceId: 'custom:u-intel00001',
            healthState: 'unverified',
            openJobCount: 663,
            lastSuccessAt: null,
            trackingStartedAt: null,
          },
          201
        )
      );
      renderWithProviders(<MyCompaniesPage />);

      const user = await submitUrl();

      await screen.findByTestId('resolve-headline');
      // Nothing was persisted by the check itself.
      expect(addCalls()).toHaveLength(0);

      // …and the confirm step still works.
      await user.click(screen.getByTestId('add-company-button'));
      await waitFor(() => expect(addCalls()).toHaveLength(1));
      expect(await screen.findByTestId('add-company-success')).toBeInTheDocument();
    });

    it('does not start discovery when the resolver failed for any other reason', async () => {
      routeFetch(
        jsonResponse(
          { reason: 'fetch_failed', finalUrl: 'https://acme.example/careers', hops: [] },
          422
        )
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://acme.example/careers');

      const alert = await screen.findByTestId('resolve-error');
      expect(alert).toHaveTextContent(/couldn't load that page/i);
      // Title + one plain sentence. The raw `fetch_failed` token used to be printed
      // underneath in monospace — the same fact a second time, in machine language.
      expect(alert).not.toHaveTextContent('fetch_failed');
      // A typo or a flaky site must never cost a Claude call and a browser session.
      expect(addCalls()).toHaveLength(0);
      expect(screen.queryByTestId('discovery-pending')).not.toBeInTheDocument();
      expect(screen.queryByTestId('discovery-error')).not.toBeInTheDocument();
    });

    it('does not start discovery for an SSRF-refused address', async () => {
      routeFetch(
        jsonResponse(
          { reason: 'resolves_to_private_address', finalUrl: 'https://localhost/x', hops: [] },
          422
        )
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://localhost/x');

      expect(await screen.findByTestId('resolve-error')).toHaveTextContent(/private network/i);
      expect(addCalls()).toHaveLength(0);
    });

    it('does not start discovery for a malformed URL rejected before the check', async () => {
      routeFetch(jsonResponse({ detail: [{ loc: ['body', 'url'], msg: 'Field required' }] }, 422));
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('not-a-url');

      await screen.findByTestId('resolve-error');
      expect(addCalls()).toHaveLength(0);
    });
  });
});
