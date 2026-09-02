import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { MyCompaniesPage } from '../../../pages/MyCompaniesPage';

/**
 * With `VITE_COMPANY_NAME_SEARCH_ENABLED` off, the page must behave EXACTLY as it
 * did before name search existed.
 *
 * "Exactly" is the whole point, and it is stricter than "no search call". The
 * classifier normalizes a bare domain to `https://cisco.com`; running it with the
 * flag off would change what the server records as `submitted_url` and turn a
 * previously-erroring input into a success — a behaviour change shipped by a
 * feature that is supposed to be dark. So with the flag off the classifier does
 * not run at all, and this file pins that.
 */

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
    isNameSearchEnabled: false,
  },
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const CREATED = {
  id: 'u-x00000001',
  displayName: 'x',
  ats: 'greenhouse',
  boardToken: 'x',
  sourceId: 'custom:u-x00000001',
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

function calls(fragment: string): Request[] {
  return fetchMock.mock.calls
    .map(([input]) => input as Request)
    .filter((req) => req.url.includes(fragment));
}

async function submit(value: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/careers page link/i), value);
  await user.click(screen.getByRole('button', { name: /add company/i }));
  return user;
}

describe('MyCompaniesPage — name search flag OFF', () => {
  it('keeps the URL-only field copy', () => {
    renderWithProviders(<MyCompaniesPage />);
    expect(screen.getByLabelText('Careers page link')).toBeInTheDocument();
    expect(
      screen.queryByLabelText(/company name or careers page link/i)
    ).not.toBeInTheDocument();
    expect(screen.getByText(/paste the link to the company’s own careers page/i)).toBeInTheDocument();
  });

  it('never calls the search endpoint, even for something that is clearly a name', async () => {
    fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
    renderWithProviders(<MyCompaniesPage />);

    await submit('Jane Street');

    await waitFor(() => expect(calls('/users/companies').length).toBe(1));
    expect(calls('search-by-name')).toHaveLength(0);
  });

  it('sends a bare domain through UNCHANGED, without adding a scheme', async () => {
    // The classifier must not run at all. Adding `https://` here would alter the
    // server's `submitted_url` audit trail and convert an input that used to be
    // refused into one that succeeds.
    fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
    renderWithProviders(<MyCompaniesPage />);

    await submit('cisco.com');

    await waitFor(() => expect(calls('/users/companies').length).toBe(1));
    const body = await calls('/users/companies')[0].clone().json();
    expect(body.url).toBe('cisco.com');
  });

  it('renders no candidate list and no search error region', async () => {
    fetchMock.mockResolvedValue(jsonResponse(CREATED, 201));
    renderWithProviders(<MyCompaniesPage />);

    await submit('Databricks');

    await waitFor(() => expect(calls('/users/companies').length).toBe(1));
    expect(screen.queryByRole('region', { name: /job boards found/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/no job board found/i)).not.toBeInTheDocument();
  });
});
