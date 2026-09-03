import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { MyCompaniesPage } from '../../../pages/MyCompaniesPage';

/**
 * A company we ALREADY PUBLISH, recognised by the SEARCH — before anything is offered.
 *
 * THE BUG, in the owner's words. He typed `databricks`, got the narration, then a
 * prominent card — *"No job board found for “databricks” — their careers page is the
 * way in"* — with `https://www.databricks.com/company/careers` under a filled **"Use
 * this careers page"** button. He pressed it. Only THEN did the page say *"This looks
 * like Databricks, which we already track."*
 *
 *     "There should not be that flow. If we already track it, just say that."
 *
 * The page invited him to commit to something it could already have known was a dead
 * end, and told him afterwards. The search endpoint now runs the same three checks the
 * add endpoint runs and sends the verdict back as `alreadyPublic`; these tests are
 * about the page treating that as THE ANSWER rather than a footnote.
 *
 * `matchKind` is the rule under all of them, and it is not a style choice:
 *   - `'board'` — an exact identifier. TERMINAL, no way past it.
 *   - `'name'`  — a guess from a string in a domain. Keeps the correction, because a
 *                 false positive with no way out hard-blocks a legitimately different
 *                 company that merely shares a string with one of ours.
 */

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

vi.mock('../../../components/my-companies/MyCompaniesList', () => ({
  MyCompaniesList: () => <div data-testid="my-companies-list-stub" />,
}));

vi.mock('../../../config/customCompanies', () => ({
  CUSTOM_COMPANIES_CONFIG: {
    isEnabled: true,
    isDiscoveryProgressEnabled: false,
    isNameSearchEnabled: true,
  },
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const DATABRICKS_CAREERS = 'https://www.databricks.com/company/careers';

/** Guidehouse's real Workday board, which really did come back for "Databricks". */
const STRANGERS_BOARD = {
  candidate: {
    ats: 'workday',
    boardToken: 'guidehouse',
    providerConfig: { career_site_slug: 'External' },
    sourceUrl: 'https://guidehouse.wd1.myworkdayjobs.com/External',
  },
  probe: { ok: true, jobCount: 794, error: null },
  sourceUrl: 'https://guidehouse.wd1.myworkdayjobs.com/External',
  title: 'Guidehouse Careers',
  rank: 1,
  autoAddable: false,
};

/** Stripe's own Greenhouse board, resolved and confirmed by the name gate. */
const OWN_BOARD = {
  candidate: {
    ats: 'greenhouse',
    boardToken: 'stripe',
    providerConfig: {},
    sourceUrl: 'https://boards.greenhouse.io/stripe',
  },
  probe: { ok: true, jobCount: 412, error: null },
  sourceUrl: 'https://boards.greenhouse.io/stripe',
  title: 'Stripe Careers',
  rank: 1,
  autoAddable: true,
};

const CREATED = {
  id: 'u-databrick1',
  displayName: 'databricks',
  ats: 'custom',
  boardToken: 'databricks',
  sourceId: 'custom:u-databrick1',
  healthState: 'unverified',
  openJobCount: 0,
  lastSuccessAt: null,
  trackingStartedAt: null,
};

let fetchMock: ReturnType<typeof vi.fn>;

function isListGet(input: Request): boolean {
  return input.method === 'GET' && input.url.includes('/users/companies');
}

beforeEach(() => {
  fetchMock = vi.fn();
  const delegate = fetchMock as unknown as (input: Request) => Promise<Response>;
  globalThis.fetch = ((input: Request) =>
    isListGet(input)
      ? Promise.resolve(jsonResponse({ companies: [] }))
      : delegate(input)) as unknown as typeof fetch;
});

afterEach(() => {
  vi.restoreAllMocks();
});

function callsTo(fragment: string): Request[] {
  return fetchMock.mock.calls
    .map(([input]) => input as Request)
    .filter((req) => req.url.includes(fragment));
}

/** Answer the search with `body`, and any add with a created company. */
function serve(body: unknown) {
  fetchMock.mockImplementation((req: Request) =>
    Promise.resolve(
      req.url.includes('search-by-name') ? jsonResponse(body) : jsonResponse(CREATED, 201)
    )
  );
}

async function submit(value: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/company name or careers page link/i), value);
  await user.click(screen.getByRole('button', { name: /add company/i }));
  return user;
}

describe('MyCompaniesPage — a name we already publish', () => {
  it('answers a GUESSED match in place of the careers-page card, with the way out', async () => {
    // THE DATABRICKS CASE. The server matched the name inside the careers domain,
    // which is a guess, so the notice hedges and keeps the correction.
    serve({
      query: 'databricks',
      candidates: [STRANGERS_BOARD],
      careersUrl: DATABRICKS_CAREERS,
      alreadyPublic: {
        status: 'already_public',
        detail:
          'The careers page we found looks like Databricks, which we already publish.',
        companyId: 'databricks',
        displayName: 'Databricks',
        finalUrl: DATABRICKS_CAREERS,
        matchKind: 'name',
      },
    });
    renderWithProviders(<MyCompaniesPage />);

    await submit('databricks');

    const notice = await screen.findByTestId('already-public');
    expect(notice).toHaveTextContent(/This looks like Databricks, which we already track/i);
    // The link to the trend we already have is the primary action.
    expect(screen.getByTestId('already-public-link')).toHaveAttribute(
      'href',
      '/companies?company=databricks'
    );
    // IN PLACE OF, not stacked above: the card that used to invite the dead end is
    // gone, and so is its button.
    expect(screen.queryByRole('button', { name: /use this careers page/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/no board we can confirm belongs to/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/no job board found for/i)).not.toBeInTheDocument();
    // Nothing was added, and nothing needed to be.
    expect(callsTo('/users/companies')).toHaveLength(0);
  });

  it('lets a wrong guess be corrected, and clears the question when it is', async () => {
    // A guess with no way out would HARD-BLOCK somebody adding a legitimately
    // different company that merely shares a string with one of ours.
    serve({
      query: 'databricks',
      candidates: [],
      careersUrl: DATABRICKS_CAREERS,
      alreadyPublic: {
        status: 'already_public',
        detail: 'We matched the name in the web address, not the board itself.',
        companyId: 'databricks',
        displayName: 'Databricks',
        finalUrl: DATABRICKS_CAREERS,
        matchKind: 'name',
      },
    });
    renderWithProviders(<MyCompaniesPage />);
    const user = await submit('databricks');

    // NOT AUTO-ADDED, and this is the shape that would otherwise be: zero boards and
    // one trusted careers URL is exactly the auto-add case, so `alreadyPublic` has to
    // win over it. The answer here is "we already track this", never an add.
    const trackAnyway = await screen.findByTestId('track-anyway-button');
    expect(callsTo('/users/companies')).toHaveLength(0);

    await user.click(trackAnyway);

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    const body = await callsTo('/users/companies')[0].clone().json();
    expect(body).toEqual({ url: DATABRICKS_CAREERS, trackAnyway: true });
    // The notice came from PAGE state, not from the add mutation, so it has to be
    // cleared here — otherwise it returns beside the success card for the board the
    // correction just created, still claiming we already track it.
    await waitFor(() => expect(screen.queryByTestId('already-public')).not.toBeInTheDocument());
  });

  it('is TERMINAL on an exact board match — no way past it, and no auto-add', async () => {
    // An exact identifier leaves no reading where a different company was meant, and
    // a private duplicate re-scrapes the same feed for a chart whose history starts
    // today. Offering that is a trap dressed as a choice.
    //
    // This is also the case that would otherwise have been added SILENTLY: one
    // candidate, auto-addable, which is the page's auto-add shape.
    serve({
      query: 'stripe',
      candidates: [OWN_BOARD],
      careersUrl: null,
      alreadyPublic: {
        status: 'already_public',
        detail: 'That board is our public Stripe page.',
        companyId: 'stripe',
        displayName: 'Stripe',
        finalUrl: 'https://boards.greenhouse.io/stripe',
        matchKind: 'board',
      },
    });
    renderWithProviders(<MyCompaniesPage />);

    await submit('stripe');

    const notice = await screen.findByTestId('already-public');
    expect(notice).toHaveTextContent(/We already track Stripe/i);
    expect(notice).not.toHaveTextContent(/looks like/i);
    expect(screen.queryByTestId('track-anyway-button')).not.toBeInTheDocument();
    // Not added, not asked about, not offered as a board to track.
    expect(callsTo('/users/companies')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: /track this one/i })).not.toBeInTheDocument();
  });

  it('takes the careers page for a company we do NOT publish', async () => {
    // The mirror of the guard above: with no published match the same shape (no board,
    // one trusted careers URL) IS the auto-add case, and `alreadyPublic: null` must
    // not block it.
    serve({
      query: 'oracle',
      candidates: [],
      careersUrl: 'https://www.oracle.com/careers/',
      alreadyPublic: null,
    });
    renderWithProviders(<MyCompaniesPage />);

    await submit('oracle');

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    const body = await callsTo('/users/companies')[0].clone().json();
    expect(body.url).toBe('https://www.oracle.com/careers/');
    expect(screen.queryByTestId('already-public')).not.toBeInTheDocument();
  });

  it('reads an older backend, which simply omits the field, as no match', async () => {
    // Vercel and Railway deploy separately, so a fresh client talks to the previous
    // API for a few minutes after every ship. Absent must mean "no match", never a
    // blank notice -- and never a suppressed add.
    serve({
      query: 'oracle',
      candidates: [],
      careersUrl: 'https://www.oracle.com/careers/',
    });
    renderWithProviders(<MyCompaniesPage />);

    await submit('oracle');

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    expect(screen.queryByTestId('already-public')).not.toBeInTheDocument();
  });
});
