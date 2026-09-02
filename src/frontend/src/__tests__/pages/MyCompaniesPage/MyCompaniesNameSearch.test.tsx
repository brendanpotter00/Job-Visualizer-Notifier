import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
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

    await submit('Databricks');

    await waitFor(() => expect(callsTo('search-by-name').length).toBe(1));
    // Nothing was added...
    expect(callsTo('/users/companies')).toHaveLength(0);
    // ...and the user is shown the identity that makes it obviously wrong.
    expect(await screen.findByText('guidehouse')).toBeInTheDocument();
    expect(screen.getByText(/794 open jobs/)).toBeInTheDocument();
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
    expect(await screen.findByText('guidehouse')).toBeInTheDocument();

    // Now paste an unrelated URL and add it.
    const field = screen.getByLabelText(/company name or careers page link/i);
    await user.clear(field);
    await user.type(field, 'https://boards.greenhouse.io/stripe');
    await user.click(screen.getByRole('button', { name: /add company/i }));

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    // The stale question must be gone — before AND after the add settles.
    await waitFor(() => expect(screen.queryByText('guidehouse')).not.toBeInTheDocument());
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

  it('offers the careers page when no board was found', async () => {
    // "We looked and found nothing" is a real answer, and the careers page is
    // exactly what the paste-a-URL path takes.
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

    expect(await screen.findByText(/no job board found/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /use this/i }));

    await waitFor(() => expect(callsTo('/users/companies').length).toBe(1));
    const body = await callsTo('/users/companies')[0].clone().json();
    expect(body.url).toBe('https://obscure.example/careers');
  });
});
