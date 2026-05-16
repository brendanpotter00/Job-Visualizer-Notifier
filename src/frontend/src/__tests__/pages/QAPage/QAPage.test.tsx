import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QAPage } from '../../../pages/QAPage/QAPage';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

// QAPage now calls `useAuth().getToken()` to forward the admin Bearer token
// to /api/jobs-qa (the endpoint is gated by `require_admin`). The page is
// already wrapped in AdminRoute in production, so a real token always exists;
// here we just stub one in.
//
// The mock is variable-driven so individual tests (notably the
// NotAuthenticatedError short-circuit test) can swap the token-getter
// behavior without re-mocking the whole module.
const mockGetToken = vi.fn().mockResolvedValue('test-token');
vi.mock('../../../features/auth/useAuth', async () => {
  const actual = await vi.importActual<
    typeof import('../../../features/auth/useAuth')
  >('../../../features/auth/useAuth');
  return {
    ...actual, // preserve real NotAuthenticatedError class for instanceof
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

describe('QAPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Re-assert the default token getter — vi.clearAllMocks resets impl.
    mockGetToken.mockResolvedValue('test-token');

    // Default mock responses
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/jobs?')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url.includes('/api/jobs-qa/scrape-runs')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      });
    });
  });

  /**
   * Helper to select a company from the dropdown.
   * Required before triggering a scrape since button is disabled when 'all' is selected.
   */
  async function selectCompany(user: ReturnType<typeof userEvent.setup>, companyName: string) {
    // Click the company dropdown
    const dropdown = screen.getByRole('combobox', { name: /company/i });
    await user.click(dropdown);

    // Wait for menu to be open and option to be available
    const option = await screen.findByRole('option', { name: companyName });
    await user.click(option);

    // Wait for the menu to close and state to update
    await waitFor(() => {
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('Trigger Scrape Button', () => {
    it('renders disabled button when no company selected', async () => {
      render(<QAPage />);

      await waitFor(() => {
        const button = screen.getByRole('button', { name: /select company to scrape/i });
        expect(button).toBeInTheDocument();
        expect(button).toBeDisabled();
      });
    });

    it('renders enabled trigger button when company is selected', async () => {
      const user = userEvent.setup();
      render(<QAPage />);

      // Wait for initial load
      await waitFor(() => {
        expect(screen.getByRole('combobox', { name: /company/i })).toBeInTheDocument();
      });

      // Select Google company
      await selectCompany(user, 'Google');

      // Button should now show trigger text and be enabled
      await waitFor(() => {
        const button = screen.getByRole('button', { name: /trigger scrape.*google/i });
        expect(button).toBeInTheDocument();
        expect(button).toBeEnabled();
      });
    });

    it('handles 202 Accepted response as success', async () => {
      const user = userEvent.setup();

      // Mock the trigger-scrape endpoint to return 202
      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/api/jobs-qa/trigger-scrape') && options?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            status: 202,
            json: () =>
              Promise.resolve({
                message: 'Scrape started for google',
                company: 'google',
              }),
          });
        }
        if (url.includes('/api/jobs?')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        if (url.includes('/api/jobs-qa/scrape-runs')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({}),
        });
      });

      render(<QAPage />);

      // Wait for initial load
      await waitFor(() => {
        expect(screen.getByRole('combobox', { name: /company/i })).toBeInTheDocument();
      });

      // Select a company first (required to enable the button)
      await selectCompany(user, 'Google');

      // Wait for trigger button to be available
      const button = await screen.findByRole('button', { name: /trigger scrape.*google/i });
      await user.click(button);

      // Should show success alert with the message from 202 response
      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Scrape started for google');
      });

      // Alert should have success severity (green background)
      const alert = screen.getByRole('alert');
      expect(alert).toHaveClass('MuiAlert-standardSuccess');
    });

    it('handles 202 response with default message when message is missing', async () => {
      const user = userEvent.setup();

      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/api/jobs-qa/trigger-scrape') && options?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            status: 202,
            json: () =>
              Promise.resolve({
                company: 'google',
              }),
          });
        }
        if (url.includes('/api/jobs?')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        if (url.includes('/api/jobs-qa/scrape-runs')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({}),
        });
      });

      render(<QAPage />);

      await waitFor(() => {
        expect(screen.getByRole('combobox', { name: /company/i })).toBeInTheDocument();
      });

      await selectCompany(user, 'Google');
      const button = await screen.findByRole('button', { name: /trigger scrape.*google/i });
      await user.click(button);

      // Should show default message when message is missing
      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Scrape started');
      });
    });

    it('handles non-202 response with exitCode', async () => {
      const user = userEvent.setup();

      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/api/jobs-qa/trigger-scrape') && options?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: () =>
              Promise.resolve({
                exitCode: 0,
                output: 'Scrape completed successfully',
                error: '',
                company: 'google',
                completedAt: new Date().toISOString(),
              }),
          });
        }
        if (url.includes('/api/jobs?')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        if (url.includes('/api/jobs-qa/scrape-runs')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({}),
        });
      });

      render(<QAPage />);

      await waitFor(() => {
        expect(screen.getByRole('combobox', { name: /company/i })).toBeInTheDocument();
      });

      await selectCompany(user, 'Google');
      const button = await screen.findByRole('button', { name: /trigger scrape.*google/i });
      await user.click(button);

      // Should show success for exitCode 0
      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Scrape completed successfully');
      });
    });

    it('handles error response with non-zero exitCode', async () => {
      const user = userEvent.setup();

      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/api/jobs-qa/trigger-scrape') && options?.method === 'POST') {
          return Promise.resolve({
            ok: false,
            status: 500,
            statusText: 'Internal Server Error',
            json: () =>
              Promise.resolve({
                exitCode: 1,
                output: '',
                error: 'Process failed with error',
                company: 'google',
                completedAt: new Date().toISOString(),
              }),
          });
        }
        if (url.includes('/api/jobs?')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        if (url.includes('/api/jobs-qa/scrape-runs')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({}),
        });
      });

      render(<QAPage />);

      await waitFor(() => {
        expect(screen.getByRole('combobox', { name: /company/i })).toBeInTheDocument();
      });

      await selectCompany(user, 'Google');
      const button = await screen.findByRole('button', { name: /trigger scrape.*google/i });
      await user.click(button);

      // Should show error (uses error field from JSON response when available)
      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Scrape failed: Process failed with error');
      });

      // Alert should have error severity
      const alert = screen.getByRole('alert');
      expect(alert).toHaveClass('MuiAlert-standardError');
    });

    it('handles network error', async () => {
      const user = userEvent.setup();

      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/api/jobs-qa/trigger-scrape') && options?.method === 'POST') {
          return Promise.reject(new Error('Network error'));
        }
        if (url.includes('/api/jobs?')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        if (url.includes('/api/jobs-qa/scrape-runs')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({}),
        });
      });

      render(<QAPage />);

      await waitFor(() => {
        expect(screen.getByRole('combobox', { name: /company/i })).toBeInTheDocument();
      });

      await selectCompany(user, 'Google');
      const button = await screen.findByRole('button', { name: /trigger scrape.*google/i });
      await user.click(button);

      // Should show network error
      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Scrape failed: Network error');
      });
    });

    it('disables button while scraping and shows loading state', async () => {
      const user = userEvent.setup();

      // Create a promise that we can control
      let resolvePromise: (value: unknown) => void;
      const delayedPromise = new Promise((resolve) => {
        resolvePromise = resolve;
      });

      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/api/jobs-qa/trigger-scrape') && options?.method === 'POST') {
          return delayedPromise.then(() => ({
            ok: true,
            status: 202,
            json: () =>
              Promise.resolve({
                message: 'Scrape started for google',
                company: 'google',
              }),
          }));
        }
        if (url.includes('/api/jobs?')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        if (url.includes('/api/jobs-qa/scrape-runs')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({}),
        });
      });

      render(<QAPage />);

      await waitFor(() => {
        expect(screen.getByRole('combobox', { name: /company/i })).toBeInTheDocument();
      });

      await selectCompany(user, 'Google');
      const button = await screen.findByRole('button', { name: /trigger scrape.*google/i });
      await user.click(button);

      // Button should be disabled and show loading text
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /scraping/i })).toBeDisabled();
      });

      // Resolve the promise
      resolvePromise!(undefined);

      // Button should be enabled again
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /trigger scrape.*google/i })).toBeEnabled();
      });
    });

    it('refreshes scrape runs after triggering scrape', async () => {
      const user = userEvent.setup();
      let scrapeRunsCalled = 0;

      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (url.includes('/api/jobs-qa/trigger-scrape') && options?.method === 'POST') {
          return Promise.resolve({
            ok: true,
            status: 202,
            json: () =>
              Promise.resolve({
                message: 'Scrape started for google',
                company: 'google',
              }),
          });
        }
        if (url.includes('/api/jobs?')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        if (url.includes('/api/jobs-qa/scrape-runs')) {
          scrapeRunsCalled++;
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({}),
        });
      });

      render(<QAPage />);

      // Wait for initial fetch
      await waitFor(() => {
        expect(scrapeRunsCalled).toBeGreaterThanOrEqual(1);
      });

      const initialCalls = scrapeRunsCalled;

      await selectCompany(user, 'Google');
      const button = await screen.findByRole('button', { name: /trigger scrape.*google/i });
      await user.click(button);

      // Should fetch scrape runs again after triggering
      await waitFor(() => {
        expect(scrapeRunsCalled).toBeGreaterThan(initialCalls);
      });
    });
  });

  describe('Fetch lifecycle (useFetchWithStatus)', () => {
    it('passes an AbortSignal to fetch on mount', async () => {
      render(<QAPage />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      // Every fetch call made by the two useFetchWithStatus hooks should
      // receive an { signal } options object.
      const fetchLifecycleCalls = mockFetch.mock.calls.filter((call) => {
        const url = call[0] as string;
        return url.includes('/api/jobs?') || url.includes('/api/jobs-qa/scrape-runs');
      });
      expect(fetchLifecycleCalls.length).toBeGreaterThan(0);
      for (const [, options] of fetchLifecycleCalls) {
        expect(options).toBeDefined();
        expect(options.signal).toBeInstanceOf(AbortSignal);
      }
    });

    it('sends Authorization header on /api/jobs-qa fetches', async () => {
      // /api/jobs-qa is gated by require_admin on the backend. The page must
      // attach the admin's Bearer token to every fetch — otherwise the proxy
      // forwards an anonymous request and the backend returns 401.
      render(<QAPage />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      const scrapeRunsCalls = mockFetch.mock.calls.filter((call) =>
        (call[0] as string).includes('/api/jobs-qa/scrape-runs')
      );
      expect(scrapeRunsCalls.length).toBeGreaterThan(0);
      for (const [, options] of scrapeRunsCalls) {
        expect(options?.headers).toMatchObject({
          Authorization: 'Bearer test-token',
        });
      }
    });

    it('aborts the prior request when selectedCompany changes', async () => {
      const user = userEvent.setup();
      const signalsSeen: AbortSignal[] = [];

      mockFetch.mockImplementation((url: string, options?: RequestInit) => {
        if (options?.signal instanceof AbortSignal) {
          signalsSeen.push(options.signal);
        }
        if (url.includes('/api/jobs?')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
        }
        if (url.includes('/api/jobs-qa/scrape-runs')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      render(<QAPage />);

      await waitFor(() => {
        expect(screen.getByRole('combobox', { name: /company/i })).toBeInTheDocument();
      });

      const initialJobsSignal = signalsSeen.find((_s, i) =>
        mockFetch.mock.calls[i]?.[0]?.includes('/api/jobs?')
      );
      expect(initialJobsSignal).toBeDefined();

      await selectCompany(user, 'Google');

      // Switching the company must kick a new fetch pair AND abort the
      // initial "all companies" requests.
      await waitFor(() => {
        expect(initialJobsSignal!.aborted).toBe(true);
      });
    });

    it('does not surface an error banner when getToken throws NotAuthenticatedError', async () => {
      // Signed-out flash regression: ``useAuth().getToken()`` rejects with
      // ``NotAuthenticatedError`` on the normal anonymous path. Without the
      // short-circuit in ``fetchScrapeRunsRequest``, ``useFetchWithStatus``
      // would surface that as a page-level "Not authenticated" error before
      // AdminRoute had a chance to redirect — flashing red to the user on
      // logout or first render.
      const { NotAuthenticatedError } = await import(
        '../../../features/auth/useAuth'
      );
      mockGetToken.mockRejectedValue(new NotAuthenticatedError());

      // Jobs endpoint still resolves (it doesn't call getToken).
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/jobs?')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve([]),
          });
        }
        // Defensive: scrape-runs should never be called when getToken
        // short-circuits — but if it is, return a benign empty list so
        // the test fails on the *real* assertion (no error banner) rather
        // than an unrelated TypeError.
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      });

      render(<QAPage />);

      // Give the lifecycle a beat to run its abortable fetch.
      await waitFor(() => {
        expect(
          screen.getByRole('combobox', { name: /company/i })
        ).toBeInTheDocument();
      });

      // No error banner — the short-circuit returns [] instead of throwing.
      // The page also has a Scrape Controls section with an "alert" role
      // that ONLY appears after a scrape trigger; on initial render there
      // should be zero alerts.
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(
        screen.queryByText(/not authenticated/i)
      ).not.toBeInTheDocument();
    });
  });
});
