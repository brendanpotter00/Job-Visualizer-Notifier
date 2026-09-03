import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { Routes, Route } from 'react-router-dom';
import { renderWithProviders } from '../../../test/testUtils';
import { MyCompanyTrendPage } from '../../../pages/MyCompaniesPage/MyCompanyTrendPage';
import type { BackendJobListing } from '../../../api/types';

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

// Replace the leaf visualization components with markers that echo the props
// the page feeds them — the page's job is bucketing + sorting, not chart render.
vi.mock('../../../components/companies-page/JobPostingsChart/JobPostingsChart', () => ({
  JobPostingsChart: ({ data, timeWindow }: { data: unknown[]; timeWindow: string }) => (
    <div data-testid="chart" data-buckets={data.length} data-window={timeWindow} />
  ),
}));
vi.mock('../../../components/companies-page/JobList/JobList', () => ({
  JobList: ({ jobs }: { jobs: { id: string }[] }) => (
    <div data-testid="joblist" data-count={jobs.length}>
      {jobs.map((job) => (
        <span key={job.id} data-testid="joblist-id">
          {job.id}
        </span>
      ))}
    </div>
  ),
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function rawJob(id: string, firstSeenAt: string): BackendJobListing {
  return {
    id,
    title: `Role ${id}`,
    company: 'server-value',
    location: 'Remote',
    locations: [],
    url: `https://example.com/${id}`,
    sourceId: 'custom:u-abc1234567',
    details: '{}',
    createdAt: firstSeenAt,
    postedOn: null,
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt,
    lastSeenAt: firstSeenAt,
    consecutiveMisses: 0,
    detailsScraped: false,
  };
}

function renderTrendPage(id = 'u-abc1234567') {
  return renderWithProviders(
    <Routes>
      <Route path="/add-companies/:id" element={<MyCompanyTrendPage />} />
    </Routes>,
    { initialEntries: [`/add-companies/${id}`] }
  );
}

/**
 * A fetch mock that answers every call with its OWN `Response`.
 *
 * `mockResolvedValue(jsonResponse(...))` hands the same object to every caller, and this
 * page now runs two queries — the jobs and the tracked-companies row. RTK Query clones
 * each response to read it, so the second one dies on "Body has already been consumed"
 * and the query fails for a reason that has nothing to do with the test.
 */
function mockJson(body: unknown, status = 200) {
  fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(body, status)));
}

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

describe('MyCompanyTrendPage', () => {
  it('feeds bucketed data to the chart and firstSeenAt-desc jobs to the list', async () => {
    // Two jobs, older then newer, returned server-order oldest-first.
    mockJson([rawJob('older', '2026-08-01T00:00:00Z'), rawJob('newer', '2026-08-08T00:00:00Z')]);

    renderTrendPage();

    const list = await screen.findByTestId('joblist');
    expect(list).toHaveAttribute('data-count', '2');
    // Sorted most-recent-first (newer before older).
    const ids = screen.getAllByTestId('joblist-id').map((n) => n.textContent);
    expect(ids).toEqual(['newer', 'older']);

    // Chart receives a non-empty bucket array (empty buckets fill the window).
    const chart = screen.getByTestId('chart');
    expect(Number(chart.getAttribute('data-buckets'))).toBeGreaterThan(0);
    expect(chart).toHaveAttribute('data-window', '30d');
  });

  it('names the company and links to the board it was built from', async () => {
    // THE ASK: "I can't find the initial Jane Street job link that we actually used to
    // create this job scraper." This page is where you land from the list, and it showed
    // a graph under the words "Hiring trend" — no name, no source, nothing that said
    // which board it was a trend OF. Both come from the tracked-companies row, which the
    // page now looks up by the runtime id in its own route.
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input instanceof Request ? input.url : input);
      if (url.includes('/api/users/companies') && !url.includes('/jobs')) {
        return Promise.resolve(
          jsonResponse({
            companies: [
              {
                id: 'u-abc1234567',
                displayName: 'Jane Street',
                ats: 'discovered',
                boardToken: 'https://www.janestreet.com/join-jane-street/open-roles/',
                sourceId: 'custom:u-abc1234567',
                healthState: 'unverified',
                openJobCount: 1,
                lastSuccessAt: null,
                trackingStartedAt: null,
              },
            ],
          })
        );
      }
      return Promise.resolve(jsonResponse([rawJob('a', '2026-08-05T12:00:00Z')]));
    });

    renderTrendPage();

    // The link first: the heading exists from the first frame (as the bare "Hiring
    // trend"), so asserting on it before the row lands would pass or fail on timing.
    const boardLink = await screen.findByTestId('my-company-board-link');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Jane Street hiring trend');
    expect(boardLink).toHaveAttribute(
      'href',
      'https://www.janestreet.com/join-jane-street/open-roles/'
    );
    expect(boardLink).toHaveAttribute('target', '_blank');
    expect(boardLink).toHaveTextContent('janestreet.com');
  });

  it('still renders the trend when the company row is unavailable', async () => {
    // The row is a garnish on this page and the chart is the page: a list fetch that
    // fails, or a row that is simply not in the payload, must cost the heading its name
    // and nothing else. (Every other test in this file returns jobs for BOTH calls, so
    // they already exercise this path.)
    mockJson([rawJob('a', '2026-08-05T12:00:00Z')]);

    renderTrendPage();

    expect(await screen.findByTestId('joblist')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Hiring trend');
    expect(screen.queryByTestId('my-company-board-link')).not.toBeInTheDocument();
  });

  it('labels the day-0 seed batch rather than showing a fake spike', async () => {
    mockJson([rawJob('a', '2026-08-05T12:00:00Z'), rawJob('b', '2026-08-05T12:20:00Z')]);

    renderTrendPage();

    const caption = await screen.findByTestId('day-zero-caption');
    // Both jobs are within an hour of the earliest sighting → seed count 2.
    expect(caption).toHaveTextContent(/2 openings were already live when tracking began/i);
  });

  it('renders the empty state when the board has no history yet', async () => {
    mockJson([]);
    renderTrendPage();

    expect(await screen.findByText(/tracking started — no history yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId('chart')).not.toBeInTheDocument();
  });

  it('renders a not-owner state on a 403', async () => {
    mockJson({ detail: 'Forbidden' }, 403);
    renderTrendPage();

    expect(await screen.findByText(/not your company/i)).toBeInTheDocument();
    expect(screen.queryByTestId('chart')).not.toBeInTheDocument();
  });

  it('prompts sign-in (and fetches nothing) when signed out', () => {
    mockAuthState.isAuthenticated = false;
    renderTrendPage();

    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
