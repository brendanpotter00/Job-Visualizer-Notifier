import { StrictMode } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { MyCompaniesPage } from '../../../pages/MyCompaniesPage';

/**
 * The typed-name path on the add page.
 *
 * The behaviour under test that actually matters is the LAST case: a search can
 * return a live board belonging to a different company, and no automated check
 * we own can tell that apart from a correct answer. The page must never add one
 * of those on its own.
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

// The name path is flag-gated; these tests are about it being ON.
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

const CREATED = {
  id: 'u-cisco00001',
  displayName: 'cisco',
  ats: 'workday',
  boardToken: 'cisco',
  sourceId: 'custom:u-cisco00001',
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

async function submit(value: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/company name or careers page link/i), value);
  await user.click(screen.getByRole('button', { name: /add company/i }));
  return user;
}

describe('MyCompaniesPage — typed company name', () => {
  it('invites a name in the field copy when the flag is on', () => {
    renderWithProviders(<MyCompaniesPage />);
    expect(screen.getByLabelText(/company name or careers page link/i)).toBeInTheDocument();
  });

  it('sends a pasted URL straight to the add endpoint and never searches', async () => {
    // URL-FIRST. A URL is exact and free; it must not cost a search call.
    fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
    renderWithProviders(<MyCompaniesPage />);

    await submit('https://boards.greenhouse.io/acme');

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    expect(callsTo('search-by-name')).toHaveLength(0);
  });

  it('gives a bare domain the scheme the guard demands', async () => {
    fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
    renderWithProviders(<MyCompaniesPage />);

    await submit('cisco.com');

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    const body = await callsTo('/users/companies')[0].clone().json();
    expect(body.url).toBe('https://cisco.com');
  });

  it('adds immediately when a name resolves to exactly one confident board', async () => {
    // ONE PRESS, ONE OUTCOME survives for the common case.
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({ query: 'Cisco', candidates: [candidate()], careersUrl: null })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);

    await submit('Cisco');

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    const body = await callsTo('/users/companies')[0].clone().json();
    expect(body.url).toBe('https://cisco.wd5.myworkdayjobs.com/Cisco_Careers');
  });

  it('NEVER auto-adds a board whose token does not name the company', async () => {
    // THE ONE THAT MATTERS. Searching "Databricks" really returned Guidehouse's
    // Workday board at rank 1 with 794 live jobs. It resolves, it probes green,
    // it returns real listings — every check we own says yes. Only a person
    // reading the name catches it, so the page must ask rather than answer.
    const wrong = candidate({
      candidate: {
        ats: 'workday',
        boardToken: 'guidehouse',
        providerConfig: { career_site_slug: 'External' },
        sourceUrl: 'https://guidehouse.wd1.myworkdayjobs.com/External',
      },
      probe: { ok: true, jobCount: 794, error: null },
      sourceUrl: 'https://guidehouse.wd1.myworkdayjobs.com/External',
      autoAddable: false,
    });
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({ query: 'Databricks', candidates: [wrong], careersUrl: null })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);

    const user = await submit('Databricks');

    await waitFor(() => expect(callsTo('search-by-name').length).toBe(1));
    // Nothing was added...
    expect(callsTo('/users/companies')).toHaveLength(0);
    // ...and nothing offers to add it in one press either: the gate rejected this
    // board, so it is folded away rather than sitting there wearing the same
    // button the right answer would wear.
    expect(screen.queryByRole('button', { name: /track guidehouse/i })).not.toBeInTheDocument();
    // The identity is still one press away, at full size — unfolding must never
    // shrink the thing a person uses to catch the wrong company.
    await user.click(await screen.findByRole('button', { name: /show 1 other board we found/i }));
    // Scoped to the fold: the narration above also names every board it checked
    // (it folds them away on screen; nothing animates in a test, so both are in the
    // DOM). This assertion is about the ANSWER surface.
    const fold = await screen.findByTestId('unconfirmed-boards');
    expect(within(fold).getByText('guidehouse')).toBeInTheDocument();
    expect(within(fold).getByText(/794 open jobs/)).toBeInTheDocument();
  });

  it('asks which board when a name returns more than one', async () => {
    const second = candidate({
      candidate: {
        ats: 'greenhouse',
        boardToken: 'cisco-meraki',
        providerConfig: {},
        sourceUrl: 'https://boards.greenhouse.io/cisco-meraki',
      },
      probe: { ok: true, jobCount: 12, error: null },
      sourceUrl: 'https://boards.greenhouse.io/cisco-meraki',
      rank: 2,
    });
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({
              query: 'Cisco',
              candidates: [candidate(), second],
              careersUrl: null,
            })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);
    const user = await submit('Cisco');

    expect(await screen.findByText(/which board is/i)).toBeInTheDocument();
    expect(callsTo('/users/companies')).toHaveLength(0);

    // Picking one is what adds it. Queried by the row's OWN accessible name —
    // the aria-label carries the board identity, the visible label does not.
    await user.click(screen.getByRole('button', { name: /track cisco-meraki on greenhouse/i }));
    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    const body = await callsTo('/users/companies')[0].clone().json();
    expect(body.url).toBe('https://boards.greenhouse.io/cisco-meraki');
  });

  it('drops a previous name\'s candidates when a URL is submitted', async () => {
    // THE REGRESSION THIS FILE EXISTS FOR. The list renders on
    // `candidates && !adding`, so a list left over from an earlier name used to
    // survive a URL submit and come BACK once the add finished — a live "Track
    // this one" for Guidehouse sitting under the success card for the company
    // you actually added. One press away from tracking the wrong company.
    const wrong = candidate({
      candidate: {
        ats: 'workday',
        boardToken: 'guidehouse',
        providerConfig: {},
        sourceUrl: 'https://guidehouse.wd1.myworkdayjobs.com/External',
      },
      probe: { ok: true, jobCount: 794, error: null },
      sourceUrl: 'https://guidehouse.wd1.myworkdayjobs.com/External',
      autoAddable: false,
    });
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({ query: 'Databricks', candidates: [wrong], careersUrl: null })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);

    const user = await submit('Databricks');
    // The rejected board is folded, so the fold itself is what has to disappear.
    expect(await screen.findByTestId('unconfirmed-boards')).toBeInTheDocument();

    // Now paste an unrelated URL and add it.
    const field = screen.getByLabelText(/company name or careers page link/i);
    await user.clear(field);
    await user.type(field, 'https://boards.greenhouse.io/stripe');
    await user.click(screen.getByRole('button', { name: /add company/i }));

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    // The stale question must be gone — before AND after the add settles.
    await waitFor(() => expect(screen.queryByTestId('unconfirmed-boards')).not.toBeInTheDocument());
    expect(screen.queryByText('guidehouse')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /track guidehouse/i })).not.toBeInTheDocument();
  });

  it('does not show a stale search failure beside a later success', async () => {
    let failSearch = true;
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name') && failSearch
          ? jsonResponse({ detail: 'unavailable' }, 503)
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);

    const user = await submit('Cisco');
    expect(await screen.findByText(/paste the link to their careers page/i)).toBeInTheDocument();

    failSearch = false;
    const field = screen.getByLabelText(/company name or careers page link/i);
    await user.clear(field);
    await user.type(field, 'https://boards.greenhouse.io/stripe');
    await user.click(screen.getByRole('button', { name: /add company/i }));

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    await waitFor(() =>
      expect(screen.queryByText(/paste the link to their careers page/i)).not.toBeInTheDocument()
    );
  });

  it('gives each candidate button its own accessible name', async () => {
    // Every row's visible label is "Track this one", so without an aria-label a
    // screen-reader user hears one identical name for every board — on the one
    // screen whose whole job is telling boards apart.
    const second = candidate({
      candidate: {
        ats: 'greenhouse',
        boardToken: 'cisco-meraki',
        providerConfig: {},
        sourceUrl: 'https://boards.greenhouse.io/cisco-meraki',
      },
      sourceUrl: 'https://boards.greenhouse.io/cisco-meraki',
      rank: 2,
    });
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({ query: 'Cisco', candidates: [candidate(), second], careersUrl: null })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);
    await submit('Cisco');

    expect(await screen.findByRole('button', { name: /track cisco on workday/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /track cisco-meraki on greenhouse/i })).toBeInTheDocument();
  });

  it('explains a failed search instead of silently clearing the spinner', async () => {
    // A 503 (flag off, Browserbase down, network dropped) used to render
    // nothing at all: the spinner cleared and the page looked like the button
    // was broken rather than the search being unavailable.
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({ detail: 'Company search is temporarily unavailable' }, 503)
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);

    await submit('Cisco');

    expect(await screen.findByText(/paste the link to their careers page/i)).toBeInTheDocument();
    expect(callsTo('/users/companies')).toHaveLength(0);
  });

  it('offers the careers page even when a STRANGER’S board came back', async () => {
    // THE IBM CASE. Searching IBM resolves Harvey's live Ashby board — a legal-AI
    // company with 334 real jobs — and a non-empty candidate list used to suppress
    // the careers page entirely, leaving the user with a stranger's board and no way
    // forward. The board is still shown (a user may recognise it) and the careers
    // page is shown beside it. The server only sends one when nothing was addable.
    const harvey = candidate({
      candidate: {
        ats: 'ashby',
        boardToken: 'harvey',
        providerConfig: {},
        sourceUrl: 'https://jobs.ashbyhq.com/harvey',
      },
      probe: { ok: true, jobCount: 334, error: null },
      sourceUrl: 'https://jobs.ashbyhq.com/harvey',
      autoAddable: false,
    });
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({
              query: 'IBM',
              candidates: [harvey],
              careersUrl: 'https://www.ibm.com/careers',
            })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);
    const user = await submit('IBM');

    // The careers page is the answer and it leads; the stranger's board is still
    // reachable, one press down, under a summary that says it was not confirmed.
    // Scoped to the answer block: the narration above ends on the same URL, which
    // is the row the morph leaves standing.
    const answer = await screen.findByTestId('careers-page-answer');
    expect(within(answer).getByText('https://www.ibm.com/careers')).toBeInTheDocument();
    // AND IT IS STILL A CHOICE. A careers page is only taken automatically when NO
    // board came back at all; Harvey's board is exactly the alternative a person
    // might recognise, so the press stays theirs to make.
    expect(callsTo('/users/companies')).toHaveLength(0);
    const fold = screen.getByRole('button', { name: /show 1 other board we found/i });
    await user.click(fold);
    expect(await screen.findByText('harvey')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /use this careers page/i }));
    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    const body = await callsTo('/users/companies')[0].clone().json();
    expect(body.url).toBe('https://www.ibm.com/careers');
  });

  it('offers NOTHING rather than a stranger’s site when nothing named them', async () => {
    // A null `careersUrl` is now a decision, not an absence: no result's host named
    // the company, and offering the top-ranked stranger would spend a paid discovery
    // run and one of the user's monthly adds on somebody else's website.
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({ query: 'Zzyzx Industries', candidates: [], careersUrl: null })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);
    await submit('Zzyzx Industries');

    expect(
      await screen.findByText(/try pasting the url of their careers page/i)
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /use this/i })).not.toBeInTheDocument();
    // Nothing offered means nothing taken: a null `careersUrl` must never be read as
    // "auto-add whatever we have", because there is nothing we would be adding.
    expect(callsTo('/users/companies')).toHaveLength(0);
  });

  it('refuses an overlong NAME before it costs a search', async () => {
    // The server caps a name at 60 characters and answers a longer one with a raw
    // Pydantic 422 nobody can act on. We can tell before the round-trip, so we do —
    // and a paid Browserbase search is not spent on an input we already know is bad.
    fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
    renderWithProviders(<MyCompaniesPage />);

    await submit('z'.repeat(61));

    expect(
      await screen.findByText(/too long to be a company name/i)
    ).toBeInTheDocument();
    expect(callsTo('search-by-name')).toHaveLength(0);
    expect(callsTo('/users/companies')).toHaveLength(0);
  });

  it('lets a long URL through untouched — the cap is the name’s, not the field’s', async () => {
    // The two kinds of value have different ceilings (2048 vs 60), so the limit has
    // to follow the classification. A long link must not be caught by the name rule.
    fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
    const long = `https://careers.example.com/${'a'.repeat(200)}`;
    renderWithProviders(<MyCompaniesPage />);

    await submit(long);

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    const body = await callsTo('/users/companies')[0].clone().json();
    expect(body.url).toBe(long);
  });

  it('USES the careers page itself when no board came back', async () => {
    // FEWER CLICKS. No board and exactly one trusted careers URL is a question with
    // one answer, so the card and its "Use this careers page" button are gone and the
    // page takes it. Note what that press was: it starts a paid discovery run and
    // spends one of the 20 monthly adds -- see the comment on the branch itself.
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({
              query: 'Obscure Co',
              candidates: [],
              careersUrl: 'https://obscure.example/careers',
            })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);
    await submit('Obscure Co');

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    const body = await callsTo('/users/companies')[0].clone().json();
    expect(body.url).toBe('https://obscure.example/careers');
    // Nothing was asked. The card that used to carry the question is not rendered
    // on the way past either.
    expect(await screen.findByTestId('add-company-success')).toBeInTheDocument();
    expect(screen.queryByTestId('careers-page-answer')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /use this careers page/i })
    ).not.toBeInTheDocument();
  });

  it('spends exactly ONE add on that careers page, StrictMode included', async () => {
    // A double fire is not cosmetic: each one POSTs the add endpoint, spends another
    // of the user's 20 monthly adds and can start a second paid discovery run.
    // StrictMode is here to catch the obvious wrong implementation -- an effect keyed
    // on the search result, which React deliberately double-invokes in development.
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({
              query: 'Obscure Co',
              candidates: [],
              careersUrl: 'https://obscure.example/careers',
            })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(
      <StrictMode>
        <MyCompaniesPage />
      </StrictMode>
    );

    await submit('Obscure Co');

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    // ...and it is still one after the outcome lands and re-renders the whole page.
    expect(await screen.findByTestId('add-company-success')).toBeInTheDocument();
    expect(callsTo('/users/companies')).toHaveLength(1);
  });

  it('re-arms for the NEXT press, and only for the next press', async () => {
    // The other half of the guard. One auto-add per press means a second search must
    // still be able to spend a second add -- a guard that never resets would silently
    // break the feature after the first company of the session.
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({
              query: 'Obscure Co',
              candidates: [],
              careersUrl: 'https://obscure.example/careers',
            })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);
    const user = await submit('Obscure Co');
    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));

    const field = screen.getByLabelText(/company name or careers page link/i);
    await user.clear(field);
    await user.type(field, 'Another Co');
    await user.click(screen.getByRole('button', { name: /add company/i }));

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(2));
    // Two presses, two adds -- never three.
    expect(await screen.findByTestId('add-company-success')).toBeInTheDocument();
    expect(callsTo('/users/companies')).toHaveLength(2);
  });
});
