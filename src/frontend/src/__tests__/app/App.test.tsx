import { describe, it, expect, beforeEach, vi, beforeAll, afterAll, afterEach } from 'vitest';
import { screen, waitFor, render } from '@testing-library/react';
import { Provider } from 'react-redux';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import userEvent from '@testing-library/user-event';
import App from '../../app/App';
import { createTestStore } from '../../test/testUtils';
import { APP_TITLE } from '../../config/constants';

// Mock API responses
const mockBackendJobs = [
  {
    id: 'greenhouse_1',
    title: 'Senior Software Engineer',
    company: 'spacex',
    location: 'Hawthorne, CA',
    url: 'https://spacex.com/careers/1',
    sourceId: 'greenhouse_api',
    details: JSON.stringify({ experience_level: null, is_remote_eligible: false }),
    createdAt: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    postedOn: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    lastSeenAt: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    consecutiveMisses: 0,
    detailsScraped: true,
  },
];

// Setup MSW server
const server = setupServer(
  http.get('/api/jobs', () => {
    return HttpResponse.json(mockBackendJobs);
  })
);

beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// Mock auth providers and hooks
vi.mock('@auth0/auth0-react', () => ({
  useAuth0: () => ({
    isAuthenticated: false,
    isLoading: false,
    user: null,
    loginWithRedirect: vi.fn(),
    logout: vi.fn(),
    getAccessTokenSilently: vi.fn(),
  }),
}));

vi.mock('@react-oauth/google', () => ({
  useGoogleOneTapLogin: vi.fn(),
}));

vi.mock('../../features/auth/useAuth', () => ({
  useAuth: () => ({
    isEnabled: false,
    isAuthenticated: false,
    isLoading: false,
    user: null,
    login: vi.fn(),
    logout: vi.fn(),
    getToken: vi.fn(),
  }),
}));

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
    // Navigate to /companies since Companies page is no longer the home page
    const url = 'http://localhost:5173/companies';
    Object.defineProperty(window, 'location', {
      value: new URL(url),
      writable: true,
      configurable: true,
    });

    vi.spyOn(window.history, 'pushState').mockImplementation(() => {});
    vi.clearAllMocks();
  });

  describe('Component Composition', () => {
    it('should render Companies page with company name at /companies route', async () => {
      const store = createTestStore();
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      await waitFor(() => {
        // Default selected company is SpaceX; the h1 shows the company name.
        expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/SpaceX/i);
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
        expect(screen.getByLabelText(APP_TITLE)).toBeInTheDocument();
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
        http.get('/api/jobs', () => {
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
        http.get('/api/jobs', () => {
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
        http.get('/api/jobs', () => {
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
        http.get('/api/jobs', () => {
          return HttpResponse.json(mockBackendJobs);
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
      // Set location to /companies with company parameter
      Object.defineProperty(window, 'location', {
        value: new URL('http://localhost:5173/companies?company=anthropic'),
        writable: true,
        configurable: true,
      });

      const store = createTestStore();
      render(
        <Provider store={store}>
          <App />
        </Provider>
      );

      await waitFor(() => {
        expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(/Anthropic/i);
      });
    });
  });
});
