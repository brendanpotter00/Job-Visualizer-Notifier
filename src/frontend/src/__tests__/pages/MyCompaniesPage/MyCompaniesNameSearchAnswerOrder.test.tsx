import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { MyCompaniesPage } from '../../../pages/MyCompaniesPage';

/**
 * WHICH ANSWER LEADS — and the thing under test is the ORDER, not the presence.
 *
 * Typing "meta" returned five real job boards: anthropic (582 jobs), cohere (144),
 * gleanwork (111), headway (83), gc-ai (27). Not one of them was Meta. The server
 * was right about all of it — every candidate came back `autoAddable: false`,
 * nothing was auto-added, and a second search found `metacareers.com`.
 *
 * The PAGE was inverted. Five large cards with five black "Track this one" buttons,
 * and the right answer underneath in caption-sized grey text behind a small
 * outlined "Use this": *"the choices drowned out that option at the bottom… my eyes
 * didn't go down and look at it."* Every element in that screenshot was PRESENT, so
 * presence assertions could never have caught it. These pin document order and
 * which control carries the filled button, because that is the whole bug.
 *
 * Two states that must not look alike:
 *   A — at least one candidate is `autoAddable` → the list is a real question and leads.
 *   B — none is → the careers page is the answer, leads, and the boards fold away.
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

const CREATED = {
  id: 'u-meta000001',
  displayName: 'meta',
  ats: 'greenhouse',
  boardToken: 'meta',
  sourceId: 'custom:u-meta000001',
  healthState: 'unverified',
  openJobCount: 0,
  lastSuccessAt: null,
  trackingStartedAt: null,
};

/** One probed candidate. Confident (`autoAddable: true`) unless told otherwise. */
function candidate(overrides: Record<string, unknown> = {}) {
  return {
    candidate: {
      ats: 'workday',
      boardToken: 'cisco',
      providerConfig: { career_site_slug: 'Cisco_Careers' },
      sourceUrl: 'https://cisco.wd5.myworkdayjobs.com/Cisco_Careers',
    },
    probe: { ok: true, jobCount: 1248, error: null },
    sourceUrl: 'https://cisco.wd5.myworkdayjobs.com/Cisco_Careers',
    title: 'Cisco Careers',
    rank: 1,
    autoAddable: true,
    ...overrides,
  };
}

/** A greenhouse board the name gate REJECTED — the shape of every "meta" result. */
function rejected(boardToken: string, jobCount: number, rank: number) {
  return candidate({
    candidate: {
      ats: 'greenhouse',
      boardToken,
      providerConfig: {},
      sourceUrl: `https://boards.greenhouse.io/${boardToken}`,
    },
    probe: { ok: true, jobCount, error: null },
    sourceUrl: `https://boards.greenhouse.io/${boardToken}`,
    rank,
    autoAddable: false,
  });
}

/** The five boards a real search for "meta" returned, at their real ranks. */
const META_REJECTS = [
  rejected('anthropic', 582, 15),
  rejected('cohere', 144, 16),
  rejected('gleanwork', 111, 19),
  rejected('headway', 83, 23),
  rejected('gc-ai', 27, 24),
];

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

/** Every search answers with `body`; every add succeeds. */
function answerWith(body: unknown) {
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

/** True when `first` comes before `second` in document order. */
function precedes(first: Element, second: Element): boolean {
  return Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe('MyCompaniesPage — which answer leads', () => {
  it('leads with the careers page, not the boards, when NOTHING was confirmed', async () => {
    answerWith({
      query: 'meta',
      candidates: META_REJECTS,
      careersUrl: 'https://www.metacareers.com/',
    });
    renderWithProviders(<MyCompaniesPage />);
    await submit('meta');

    const answer = await screen.findByTestId('careers-page-answer');
    const boards = screen.getByTestId('unconfirmed-boards');
    // THE FIX, in one line.
    expect(precedes(answer, boards)).toBe(true);

    // The heading must not presuppose one of the rejects is right — "Which board
    // is meta?" is a false question once the server has said none of them is.
    expect(screen.queryByText(/which board is/i)).not.toBeInTheDocument();
    expect(screen.getByText('No board we can confirm belongs to “meta”')).toBeInTheDocument();

    // The URL is readable rather than caption-grey (a person has to RECOGNISE
    // metacareers.com), and the action carries the page's only filled button.
    expect(screen.getByTestId('careers-page-url')).toHaveClass('MuiTypography-body1');
    expect(screen.getByRole('button', { name: /use this careers page/i })).toHaveClass(
      'MuiButton-contained'
    );

    // ...and not one of the five offers a one-press add beside it.
    expect(screen.queryByRole('button', { name: /^track /i })).not.toBeInTheDocument();
    expect(screen.queryByText('anthropic')).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', {
        name: /show 5 other boards we found \(none confirmed as “meta”\)/i,
      })
    ).toBeInTheDocument();
  });

  it('keeps the rejected boards recoverable in two presses, at secondary weight', async () => {
    // The fold is not a delete, and that is deliberate: the name gate is
    // occasionally too strict — measured, it suppressed exactly one right answer
    // across the whole evaluation (Poke, whose board token is `interaction`).
    // Opening the fold and overruling us must still work.
    answerWith({
      query: 'meta',
      candidates: META_REJECTS,
      careersUrl: 'https://www.metacareers.com/',
    });
    renderWithProviders(<MyCompaniesPage />);
    const user = await submit('meta');

    await user.click(await screen.findByRole('button', { name: /show 5 other boards/i }));

    // Identity at FULL size once open — folding the list must never shrink what a
    // row says about which company it is. That display is the mitigation.
    //
    // Scoped to the fold, because the narration above also names every board it
    // checked (it folds them away on screen; in a test nothing animates, so both
    // are in the DOM). This assertion is about the ANSWER surface.
    const fold = await screen.findByTestId('unconfirmed-boards');
    expect(within(fold).getByText('anthropic')).toBeInTheDocument();
    expect(within(fold).getByText(/582 open jobs/)).toBeInTheDocument();

    const track = screen.getByRole('button', { name: 'Track anthropic on greenhouse' });
    // Outlined, not filled: below the answer in weight even when open.
    expect(track).toHaveClass('MuiButton-outlined');
    expect(track).toHaveTextContent('Track this one anyway');

    await user.click(track);
    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    const body = await callsTo('/users/companies')[0].clone().json();
    expect(body.url).toBe('https://boards.greenhouse.io/anthropic');
  });

  it('leads with the BOARDS when one of them is confirmed', async () => {
    // State A is unchanged and must stay that way: a confirmed candidate makes this
    // a real question between plausible boards, so the list keeps its heading, its
    // full-size identity and its prominent per-row button, and anything else is
    // the footnote underneath.
    answerWith({
      query: 'Cisco',
      candidates: [candidate(), rejected('cisco-meraki', 12, 2)],
      careersUrl: 'https://www.cisco.com/careers',
    });
    renderWithProviders(<MyCompaniesPage />);
    await submit('Cisco');

    const question = await screen.findByRole('region', { name: 'Job boards found' });
    expect(screen.getByText('Which board is “Cisco”?')).toBeInTheDocument();
    // Rows are visible immediately — no fold, nothing to press first.
    expect(screen.queryByTestId('unconfirmed-boards')).not.toBeInTheDocument();
    expect(screen.getByText('cisco')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Track cisco on workday' })).toHaveClass(
      'MuiButton-contained'
    );

    // ...and the careers page is the footnote UNDER them, not the lead.
    const footnote = screen.getByRole('button', { name: /use this careers page for “Cisco”/i });
    expect(precedes(question, footnote)).toBe(true);
    expect(footnote).toHaveClass('MuiButton-outlined');
  });

  it('leads with the careers page when the search found no board at all', async () => {
    answerWith({
      query: 'Obscure Co',
      candidates: [],
      careersUrl: 'https://obscure.example/careers',
    });
    renderWithProviders(<MyCompaniesPage />);
    await submit('Obscure Co');

    expect(await screen.findByText('No job board found for “Obscure Co”')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /use this careers page/i })).toHaveClass(
      'MuiButton-contained'
    );
    // Nothing to fold, so no fold is drawn.
    expect(screen.queryByTestId('unconfirmed-boards')).not.toBeInTheDocument();
  });

  it('still says what to do next when there is no careers page either', async () => {
    // Boards came back, none was confirmed, and no result's host named the company
    // — so there is nothing we can honestly offer to press. The block must still
    // lead, still refuse to call the rejects an answer, and point at the one thing
    // that moves this on.
    answerWith({ query: 'meta', candidates: META_REJECTS, careersUrl: null });
    renderWithProviders(<MyCompaniesPage />);
    await submit('meta');

    const answer = await screen.findByTestId('careers-page-answer');
    expect(answer).toHaveTextContent('No board we can confirm belongs to “meta”');
    expect(answer).toHaveTextContent(/try pasting the url of their careers page/i);
    expect(precedes(answer, screen.getByTestId('unconfirmed-boards'))).toBe(true);
    expect(screen.queryByRole('button', { name: /use this/i })).not.toBeInTheDocument();
  });
});
