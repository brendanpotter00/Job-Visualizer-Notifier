import { describe, it, expect, beforeEach, vi, beforeAll, afterAll, afterEach } from 'vitest';
import { screen, waitFor, render } from '@testing-library/react';
import { Provider } from 'react-redux';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import App from '../../app/App';
import { createTestStore } from '../../test/testUtils';

// Mock API responses
const mockGreenhouseJobs = {
  jobs: [
    {
      id: 1,
      title: 'Senior Software Engineer',
      absolute_url: 'https://spacex.com/careers/1',
      location: { name: 'Hawthorne, CA' },
      departments: [{ id: 1, name: 'Engineering' }],
      offices: [],
      updated_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    },
  ],
};

// Setup MSW server
const server = setupServer(
  http.get('/api/greenhouse/v1/boards/*/jobs', () => {
    return HttpResponse.json(mockGreenhouseJobs);
  }),
  http.get('/api/ashby/v1/jobBoard/:boardName/jobs', () => {
    return HttpResponse.json({ jobs: [] });
  }),
  http.get('/api/lever/v0/postings/*', () => {
    return HttpResponse.json([]);
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// Mock Recharts to avoid rendering issues in tests
vi.mock('recharts', () => ({
  LineChart: () => null,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  CartesianGrid: () => null,
  Tooltip: () => null,
  ResponsiveContainer: () => null,
  Legend: () => null,
}));

describe('App', () => {
  beforeEach(() => {
    // Reset window.location and history before each test
    const url = 'http://localhost:5173/';
    Object.defineProperty(window, 'location', {
      value: new URL(url),
      writable: true,
      configurable: true,
    });

    vi.spyOn(window.history, 'pushState').mockImplementation(() => {});
    vi.clearAllMocks();
  });

  describe('Component Composition', () => {
    it('should render Companies page with company name at root route', async () => {
      const store = createTestStore();
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      await waitFor(() => {
        expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
          /Job Posting Analytics/i
        );
      });
    });

    it('should render company selector on Companies page', async () => {
      const store = createTestStore();
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      await waitFor(() => {
        expect(screen.getByLabelText('Company')).toBeInTheDocument();
      });
    });

    it('should render navigation drawer with app name', async () => {
      const store = createTestStore();
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      await waitFor(() => {
        expect(screen.getByText('onehourswe')).toBeInTheDocument();
      });
    });
  });

  describe('Loading States', () => {
    it('should render loading indicator when globalLoading is true', async () => {
      const store = createTestStore({
        ui: { globalLoading: true, graphModal: { isOpen: false } },
      });
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      await waitFor(() => {
        expect(screen.getByRole('progressbar')).toBeInTheDocument();
      });
    });

    it('should render content when not loading', async () => {
      const store = createTestStore({
        ui: { globalLoading: false, graphModal: { isOpen: false } },
        jobs: {
          byCompany: {
            spacex: {
              jobs: [],
              loading: false,
              error: null,
              lastFetch: Date.now(),
            },
          },
        },
      });
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      await waitFor(() => {
        expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
      });
    });
  });

  describe('Error Handling', () => {
    it('should render error banner when there is an error', async () => {
      // Override the API response to return an error
      server.use(
        http.get('/api/greenhouse/v1/boards/*/jobs', () => {
          return HttpResponse.error();
        })
      );

      const store = createTestStore();
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      await waitFor(
        () => {
          expect(screen.getByText(/Failed to load job data/i)).toBeInTheDocument();
        },
        { timeout: 3000 }
      );
    });

    it('should have retry button in error state', async () => {
      // Override the API response to return an error
      server.use(
        http.get('/api/greenhouse/v1/boards/*/jobs', () => {
          return HttpResponse.error();
        })
      );

      const store = createTestStore();
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      await waitFor(
        () => {
          expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
        },
        { timeout: 3000 }
      );
    });

    it('should retry loading when retry button is clicked', async () => {
      // First call fails, second succeeds
      server.use(
        http.get('/api/greenhouse/v1/boards/*/jobs', () => {
          return HttpResponse.error();
        })
      );

      const user = userEvent.setup();
      const store = createTestStore();
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      // Wait for error to appear
      const retryButton = await screen.findByRole('button', { name: /retry/i });

      // Reset handler to succeed
      server.use(
        http.get('/api/greenhouse/v1/boards/*/jobs', () => {
          return HttpResponse.json(mockGreenhouseJobs);
        })
      );

      // Click retry
      await user.click(retryButton);

      // Error should eventually disappear
      await waitFor(
        () => {
          expect(screen.queryByText(/Failed to load job data/i)).not.toBeInTheDocument();
        },
        { timeout: 3000 }
      );
    });
  });

  describe('Integration with Custom Hooks', () => {
    it('should use useCompanyLoader hook for data fetching', async () => {
      const store = createTestStore();
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      // Should eventually load jobs data via RTK Query
      await waitFor(() => {
        const state = store.getState();
        // Check that RTK Query cache has data for spacex
        const queries = state.jobsApi?.queries || {};
        const hasSpacexQuery = Object.keys(queries).some((key) => key.includes('spacex'));
        expect(hasSpacexQuery).toBe(true);
      });
    });

    it('should use useURLSync hook for URL synchronization', async () => {
      vi.clearAllMocks();
      const store = createTestStore();
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      // URL should not be updated on initial mount
      await waitFor(() => {
        expect(window.history.pushState).not.toHaveBeenCalled();
      });
    });

    it('should display correct company name from Redux state', async () => {
      window.location.search = '?company=anthropic';

      const store = createTestStore();
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      await waitFor(() => {
        expect(screen.getByText(/Anthropic - Job Posting Analytics/i)).toBeInTheDocument();
      });
    });
  });
});
