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
    fetchMock.mockResolvedValue(
      jsonResponse([
        rawJob('older', '2026-08-01T00:00:00Z'),
        rawJob('newer', '2026-08-08T00:00:00Z'),
      ])
    );

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

  it('labels the day-0 seed batch rather than showing a fake spike', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse([
        rawJob('a', '2026-08-05T12:00:00Z'),
        rawJob('b', '2026-08-05T12:20:00Z'),
      ])
    );

    renderTrendPage();

    const caption = await screen.findByTestId('day-zero-caption');
    // Both jobs are within an hour of the earliest sighting → seed count 2.
    expect(caption).toHaveTextContent(/2 openings were already live when tracking began/i);
  });

  it('renders the empty state when the board has no history yet', async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));
    renderTrendPage();

    expect(await screen.findByText(/tracking started — no history yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId('chart')).not.toBeInTheDocument();
  });

  it('renders a not-owner state on a 403', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Forbidden' }, 403));
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
