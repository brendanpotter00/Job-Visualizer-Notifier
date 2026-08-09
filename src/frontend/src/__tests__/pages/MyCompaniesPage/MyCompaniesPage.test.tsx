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

async function submitUrl(url = 'https://intel.com/careers') {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/careers page url/i), url);
  await user.click(screen.getByRole('button', { name: /check url/i }));
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

  describe('signed out', () => {
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
    it('states plainly that nothing is added until the user chooses to track', () => {
      renderWithProviders(<MyCompaniesPage />);
      // A page called "My Companies" that reports a job count must not imply
      // the company was added — this copy is the only thing preventing that.
      expect(
        screen.getByText(/nothing is added to your account until you choose to track it/i)
      ).toBeInTheDocument();
    });

    it('disables the submit button until a URL is entered', async () => {
      const user = userEvent.setup();
      renderWithProviders(<MyCompaniesPage />);

      const button = screen.getByRole('button', { name: /check url/i });
      expect(button).toBeDisabled();

      await user.type(screen.getByLabelText(/careers page url/i), 'https://intel.com');
      expect(button).toBeEnabled();
    });

    it('keeps submit disabled for whitespace-only input', async () => {
      const user = userEvent.setup();
      renderWithProviders(<MyCompaniesPage />);

      await user.type(screen.getByLabelText(/careers page url/i), '   ');
      expect(screen.getByRole('button', { name: /check url/i })).toBeDisabled();
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
      await user.click(screen.getByRole('button', { name: /check url/i }));

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

    it('renders the mapped message for a flat 422', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse(
          { reason: 'no_ats_detected', finalUrl: 'https://example.com', hops: [] },
          422
        )
      );
      renderWithProviders(<MyCompaniesPage />);

      await submitUrl('https://example.com');

      const alert = await screen.findByTestId('resolve-error');
      expect(alert).toHaveTextContent(/couldn't find a job board/i);
      expect(alert).toHaveTextContent('Greenhouse');
      expect(alert).toHaveTextContent('no_ats_detected');
      expect(screen.queryByTestId('resolve-result')).not.toBeInTheDocument();
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
});
