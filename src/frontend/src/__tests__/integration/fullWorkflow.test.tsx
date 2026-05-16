import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { ThemeProvider } from '@mui/material';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { createTestStore } from '../../test/testUtils';
import App from '../../app/App';
import { theme } from '../../config/theme';

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

/**
 * Integration tests for the full application workflow.
 * Tests end-to-end user interactions and data flow.
 */

// Mock API responses
const mockBackendJobs = [
  {
    id: 'greenhouse_spacex_1',
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
  {
    id: 'greenhouse_spacex_2',
    title: 'Frontend Engineer',
    company: 'spacex',
    location: 'Hawthorne, CA',
    url: 'https://spacex.com/careers/2',
    sourceId: 'greenhouse_api',
    details: JSON.stringify({ experience_level: null, is_remote_eligible: false }),
    createdAt: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
    postedOn: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
    closedOn: null,
    status: 'OPEN',
    hasMatched: false,
    aiMetadata: '{}',
    firstSeenAt: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
    lastSeenAt: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
    consecutiveMisses: 0,
    detailsScraped: true,
  },
];

const mockLeverJobs = [
  {
    id: 'spotify-1',
    text: 'Backend Engineer',
    hostedUrl: 'https://jobs.lever.co/spotify/1',
    categories: {
      commitment: 'Full-time',
      department: 'Engineering',
      location: 'Los Angeles, CA',
      team: 'Platform',
    },
    createdAt: Date.now() - 1000 * 60 * 45, // 45 min ago
    tags: ['backend', 'node'],
    workplaceType: 'remote',
  },
];

// Setup MSW server
const server = setupServer(
  http.get('/api/jobs', ({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get('company') === 'spacex') {
      return HttpResponse.json(mockBackendJobs);
    }
    return HttpResponse.json([]);
  }),
  http.get('/api/lever/v0/postings/spotify', () => {
    return HttpResponse.json(mockLeverJobs);
  })
);

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'error' });
});

afterEach(() => {
  server.resetHandlers();
  vi.clearAllMocks();
});

afterAll(() => {
  server.close();
});

describe('Full Application Workflow', () => {
  beforeEach(() => {
    // Navigate to /companies since Companies page is no longer the home page
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/companies'),
      writable: true,
      configurable: true,
    });
  });

  const renderApp = () => {
    // Create fresh store for each test using testUtils
    const testStore = createTestStore();

    return render(
      <Provider store={testStore}>
        <ThemeProvider theme={theme}>
          <App />
        </ThemeProvider>
      </Provider>
    );
  };

  it('renders application structure', () => {
    renderApp();

    // Main title should be visible
    expect(screen.getByText(/Job Posting Analytics/i)).toBeInTheDocument();
  });

  it('renders graph section', async () => {
    renderApp();

    // Graph section should render after data loads
    await waitFor(() => {
      expect(screen.getByText(/Job Posting Timeline/i)).toBeInTheDocument();
    });
  });

  it('renders list section', async () => {
    renderApp();

    // List section should render after data loads
    await waitFor(() => {
      expect(screen.getByText(/Job Listings/i)).toBeInTheDocument();
    });
  });

  it('renders company selector', () => {
    renderApp();

    // Company selector should be present (use role to distinguish from navigation item)
    expect(screen.getByRole('combobox', { name: /company/i })).toBeInTheDocument();
  });
});
