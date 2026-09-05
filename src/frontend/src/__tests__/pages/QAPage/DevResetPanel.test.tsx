import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DevResetPanel } from '../../../pages/QAPage/DevResetPanel';

const mockFetch = vi.fn();
global.fetch = mockFetch;

const mockGetToken = vi.fn().mockResolvedValue('test-token');
vi.mock('../../../features/auth/useAuth', async () => {
  const actual = await vi.importActual<
    typeof import('../../../features/auth/useAuth')
  >('../../../features/auth/useAuth');
  return {
    ...actual,
    useAuth: () => ({
      isEnabled: true,
      isAuthenticated: true,
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
      getToken: mockGetToken,
      user: { sub: 'auth0|test_admin' },
    }),
  };
});

const STATUS_OK = { enabled: true, database_host: 'localhost' };

const RESET_OK = {
  scope: 'mine',
  company_ids: ['u-abc123'],
  deleted: { companies: 1, job_listings: 12, user_companies: 1 },
  published_companies_kept: 131,
  published_jobs_kept: 49143,
};

/** Status GET answers `status`; the POST answers `reset`. */
function mockBackend(status: unknown, reset: unknown = RESET_OK) {
  mockFetch.mockImplementation((_url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(reset) });
    }
    return Promise.resolve(status);
  });
}

const okStatus = (body: unknown) => ({
  ok: true,
  status: 200,
  statusText: 'OK',
  json: () => Promise.resolve(body),
});

const errStatus = (status: number, detail?: string) => ({
  ok: false,
  status,
  statusText: 'Error',
  json: () => Promise.resolve(detail ? { detail } : {}),
});

const postCalls = () =>
  mockFetch.mock.calls.filter((call) => call[1]?.method === 'POST');

describe('DevResetPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetToken.mockResolvedValue('test-token');
  });

  // --- Availability is the backend's call, and every "no" is silent ---------

  it('renders nothing when the route is not registered (flag off → 404)', async () => {
    mockBackend(errStatus(404));
    render(<DevResetPanel />);
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('dev-reset-panel')).not.toBeInTheDocument();
  });

  it('renders nothing when the backend refuses a non-local database (403)', async () => {
    mockBackend(errStatus(403, 'refusing the dev reset: …'));
    render(<DevResetPanel />);
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('dev-reset-panel')).not.toBeInTheDocument();
  });

  it('renders nothing when the backend is unreachable', async () => {
    mockFetch.mockRejectedValue(new Error('ECONNREFUSED'));
    render(<DevResetPanel />);
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('dev-reset-panel')).not.toBeInTheDocument();
  });

  it('renders nothing when the response omits enabled:true', async () => {
    // The QA page's own test suite stubs unknown URLs with `{}`; an empty body
    // must not be read as "available".
    mockBackend(okStatus({}));
    render(<DevResetPanel />);
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(screen.queryByTestId('dev-reset-panel')).not.toBeInTheDocument();
  });

  // --- The destructive path always goes through a confirm step -------------

  it('names the database and warns before anything can be clicked', async () => {
    mockBackend(okStatus(STATUS_OK));
    render(<DevResetPanel />);
    expect(await screen.findByTestId('dev-reset-panel')).toBeInTheDocument();
    expect(screen.getByText(/local development only/i)).toBeInTheDocument();
    expect(screen.getByText(/localhost/)).toBeInTheDocument();
    expect(screen.getByText(/cannot be undone/i)).toBeInTheDocument();
  });

  it('does not POST on the first click — it asks first', async () => {
    const user = userEvent.setup();
    mockBackend(okStatus(STATUS_OK));
    render(<DevResetPanel />);
    await screen.findByTestId('dev-reset-panel');

    await user.click(screen.getByRole('button', { name: /clear custom companies/i }));

    expect(postCalls()).toHaveLength(0);
    expect(screen.getByText(/permanently delete your custom companies/i)).toBeInTheDocument();
  });

  it('cancelling leaves the database alone', async () => {
    const user = userEvent.setup();
    mockBackend(okStatus(STATUS_OK));
    render(<DevResetPanel />);
    await screen.findByTestId('dev-reset-panel');

    await user.click(screen.getByRole('button', { name: /clear custom companies/i }));
    await user.click(screen.getByRole('button', { name: /cancel/i }));

    expect(postCalls()).toHaveLength(0);
    expect(
      screen.getByRole('button', { name: /clear custom companies/i })
    ).toBeInTheDocument();
  });

  it('confirming POSTs scope=mine and shows what was deleted and what was kept', async () => {
    const user = userEvent.setup();
    mockBackend(okStatus(STATUS_OK));
    render(<DevResetPanel />);
    await screen.findByTestId('dev-reset-panel');

    await user.click(screen.getByRole('button', { name: /clear custom companies/i }));
    await user.click(screen.getByRole('button', { name: /yes, delete/i }));

    await waitFor(() => expect(postCalls()).toHaveLength(1));
    const [url, init] = postCalls()[0];
    expect(url).toContain('/api/users/dev-reset?scope=mine');
    // Direct to the backend, never through a Vercel proxy — the route is
    // deliberately absent from every PROXIED_ROUTES allowlist.
    expect(url).toMatch(/^http:\/\/localhost:\d+\//);
    expect(init?.headers).toMatchObject({ Authorization: 'Bearer test-token' });

    expect(await screen.findByText(/deleted 14 rows across 1 custom company/i)).toBeInTheDocument();
    expect(screen.getByText(/job_listings: 12/)).toBeInTheDocument();
    expect(
      screen.getByText(/131 published companies, 49143 published job rows/)
    ).toBeInTheDocument();
  });

  it('sends the chosen scope', async () => {
    const user = userEvent.setup();
    mockBackend(okStatus(STATUS_OK), { ...RESET_OK, scope: 'all' });
    render(<DevResetPanel />);
    await screen.findByTestId('dev-reset-panel');

    await user.click(screen.getByRole('combobox', { name: /scope/i }));
    await user.click(await screen.findByRole('option', { name: /every user/i }));
    await user.click(screen.getByRole('button', { name: /clear custom companies/i }));
    expect(screen.getByText(/every user’s custom companies/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /yes, delete/i }));

    await waitFor(() => expect(postCalls()).toHaveLength(1));
    expect(postCalls()[0][0]).toContain('scope=all');
  });

  it('surfaces a refusal instead of claiming success', async () => {
    const user = userEvent.setup();
    mockFetch.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return Promise.resolve(errStatus(403, 'refusing the dev reset: host is not localhost'));
      }
      return Promise.resolve(okStatus(STATUS_OK));
    });
    render(<DevResetPanel />);
    await screen.findByTestId('dev-reset-panel');

    await user.click(screen.getByRole('button', { name: /clear custom companies/i }));
    await user.click(screen.getByRole('button', { name: /yes, delete/i }));

    expect(await screen.findByText(/host is not localhost/i)).toBeInTheDocument();
    expect(screen.queryByText(/deleted/i)).not.toBeInTheDocument();
  });
});
