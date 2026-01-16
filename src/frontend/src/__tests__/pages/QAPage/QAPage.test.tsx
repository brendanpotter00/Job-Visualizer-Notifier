import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QAPage } from '../../../pages/QAPage/QAPage';

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('QAPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();

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

    // Select the company from the menu
    const option = await screen.findByRole('option', { name: companyName });
    await user.click(option);
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
});
