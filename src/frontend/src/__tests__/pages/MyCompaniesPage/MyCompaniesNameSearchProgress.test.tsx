import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { MyCompaniesPage } from '../../../pages/MyCompaniesPage';

/**
 * The narrated search, ON THE PAGE — where the honesty rules are about timing rather
 * than copy (`NameSearchProgress.test.tsx` covers the copy).
 *
 * Two of these matter more than the rest:
 *
 *  - the panel must be GONE by the time an auto-add starts. A single confident result
 *    adds without ever showing a list, and four lines of narration flashing past on the
 *    way is motion for something nobody is being asked to read.
 *  - the panel must not gate the answer. The candidate list is the surface the user
 *    acts on; the narration leads into it and never delays it.
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

const TRACE_QUERY =
  'Cisco jobs myworkdayjobs.com greenhouse.io ashbyhq.com lever.co jobs.gem.com eightfold.ai';

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
      providerConfig: {},
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

async function submit(value: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/company name or careers page link/i), value);
  await user.click(screen.getByRole('button', { name: /add company/i }));
  return user;
}

describe('MyCompaniesPage — the narrated name search', () => {
  it('names the company while the request is genuinely out', async () => {
    // The one honest in-flight state, and the only spinner in the panel. Held open
    // with a deferred response so the in-flight render is observable at all.
    let release: (value: Response) => void = () => {};
    fetchMock.mockImplementation((req: Request) =>
      req.url.includes('search-by-name')
        ? new Promise<Response>((resolve) => {
            release = resolve;
          })
        : Promise.resolve(jsonResponse(CREATED, 201))
    );
    renderWithProviders(<MyCompaniesPage />);

    await submit('Cisco');

    const step = await screen.findByTestId('name-search-step-search');
    expect(step).toHaveTextContent('Searching the web for “Cisco”');
    expect(screen.getAllByLabelText('in progress')).toHaveLength(1);
    // Nothing that has not happened is on screen yet — no numbers, and no rows.
    expect(screen.queryByTestId('name-search-step-results')).not.toBeInTheDocument();
    expect(screen.queryByTestId('name-search-rows')).not.toBeInTheDocument();

    release(jsonResponse({ query: 'Cisco', candidates: [], careersUrl: null }));
  });

  it('narrates the real numbers above the question it leads into', async () => {
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
      autoAddable: false,
    });
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({
              query: 'Cisco',
              candidates: [candidate(), second],
              careersUrl: null,
              trace: {
                query: TRACE_QUERY,
                results: 25,
                filtered: 6,
                boards: 2,
                nonBoards: [
                  { url: 'https://www.linkedin.com/jobs/cisco', rank: 3, aggregator: true },
                ],
                nonBoardsOmitted: 16,
              },
            })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);

    await submit('Cisco');

    // The query we sent, verbatim — the feature's own argument, on screen.
    expect(await screen.findByTestId('name-search-detail-search')).toHaveTextContent(
      TRACE_QUERY
    );
    expect(screen.getByTestId('name-search-step-results')).toHaveTextContent(
      '25 results came back'
    );
    // The three old ticks — scored / boards / probed — merged into one sentence.
    expect(screen.getByTestId('name-search-step-boards')).toHaveTextContent(
      '2 of the 19 results we scored are real job boards'
    );
    expect(screen.getByTestId('name-search-step-boards')).toHaveTextContent(
      'Checked all 2 for open jobs'
    );

    // ...and the rows are the results themselves, never a row per count. One real
    // aggregator URL, one row standing for the sixteen we were not sent, and the two
    // boards with their tokens and live counts.
    const rows = screen.getAllByTestId('name-search-row');
    expect(rows.map((row) => row.dataset.kind)).toEqual([
      'discarded',
      'discarded',
      'answer',
      'rejected',
    ]);
    expect(rows[0]).toHaveTextContent('https://www.linkedin.com/jobs/cisco');
    expect(rows[1]).toHaveTextContent('…and 16 more results');
    expect(rows[3]).toHaveTextContent('greenhouse · cisco-meraki · 12 open jobs');

    // ...and the answer surface is right there with it, never held back by it.
    expect(screen.getByText(/which board is/i)).toBeInTheDocument();
  });

  it('is GONE by the time a confident single result auto-adds', async () => {
    // The failure this guards: a long narration flashing past on the one path where
    // the user is not being asked to read anything.
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({
              query: 'Cisco',
              candidates: [candidate()],
              careersUrl: null,
              trace: { query: TRACE_QUERY, results: 25, filtered: 6, boards: 1 },
            })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);

    await submit('Cisco');

    await waitFor(() =>
      expect(
        fetchMock.mock.calls
          .map(([input]) => input as Request)
          .filter((req) => req.url.includes('/users/companies')).length
      ).toBe(1)
    );
    expect(screen.queryByTestId('name-search-progress')).not.toBeInTheDocument();
  });

  it('takes the narration away with the question when a board is picked', async () => {
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
          ? jsonResponse({
              query: 'Cisco',
              candidates: [candidate(), second],
              careersUrl: null,
              trace: { query: TRACE_QUERY, results: 25, filtered: 0, boards: 2 },
            })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);
    const user = await submit('Cisco');

    expect(await screen.findByTestId('name-search-progress')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /track cisco-meraki on greenhouse/i }));

    await waitFor(() =>
      expect(screen.queryByTestId('name-search-progress')).not.toBeInTheDocument()
    );
  });

  it('never narrates a search for a URL, which never searches', async () => {
    fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
    renderWithProviders(<MyCompaniesPage />);

    await submit('https://boards.greenhouse.io/acme');

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByTestId('name-search-progress')).not.toBeInTheDocument();
  });

  it('narrates what it can when the backend sent no trace', async () => {
    // Vercel and Railway deploy separately; a new client talks to the previous
    // backend for a few minutes after every ship. Fewer steps, never invented ones.
    fetchMock.mockImplementation((req: Request) =>
      Promise.resolve(
        req.url.includes('search-by-name')
          ? jsonResponse({
              query: 'Databricks',
              candidates: [candidate({ autoAddable: false })],
              careersUrl: null,
            })
          : jsonResponse(CREATED, 201)
      )
    );
    renderWithProviders(<MyCompaniesPage />);

    await submit('Databricks');

    expect(await screen.findByTestId('name-search-step-search')).toHaveTextContent(
      'Asked the web for “Databricks”'
    );
    expect(screen.queryByTestId('name-search-detail-search')).not.toBeInTheDocument();
    expect(screen.queryByTestId('name-search-step-results')).not.toBeInTheDocument();
    expect(screen.getByTestId('name-search-step-boards')).toHaveTextContent(
      'Checked it for open jobs'
    );
    // The board it DID send still gets a row. The results it did not name do not:
    // there is no path from "25 results" to twenty-five rows.
    expect(screen.getAllByTestId('name-search-row')).toHaveLength(1);
  });
});
