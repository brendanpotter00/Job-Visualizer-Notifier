import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { ThemeProvider } from '@mui/material';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import { configureStore } from '@reduxjs/toolkit';
import appReducer from '../../features/app/appSlice';
import jobsReducer from '../../features/jobs/jobsSlice';
import filtersReducer from '../../features/filters/filtersSlice';
import uiReducer from '../../features/ui/uiSlice';
import App from '../../app/App';
import { theme } from '../../config/theme';

/**
 * Integration tests for the full application workflow.
 * Tests end-to-end user interactions and data flow.
 */

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
      updated_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(), // 30 min ago
    },
    {
      id: 2,
      title: 'Frontend Engineer',
      absolute_url: 'https://spacex.com/careers/2',
      location: { name: 'Hawthorne, CA' },
      departments: [{ id: 1, name: 'Engineering' }],
      offices: [],
      updated_at: new Date(Date.now() - 1000 * 60 * 60).toISOString(), // 1 hour ago
    },
  ],
};

const mockLeverJobs = [
  {
    id: 'nominal-1',
    text: 'Backend Engineer',
    hostedUrl: 'https://jobs.lever.co/nominal/1',
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
  http.get('/api/greenhouse/v1/boards/spacex/jobs', ({ request }) => {
    // Verify content=true parameter is present
    const url = new URL(request.url);
    if (url.searchParams.get('content') === 'true') {
      return HttpResponse.json(mockGreenhouseJobs);
    }
    // Return minimal response without content parameter
    return HttpResponse.json({ jobs: [] });
  }),
  http.get('/api/lever/v0/postings/nominal', () => {
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
  const renderApp = () => {
    // Create fresh store for each test
    const testStore = configureStore({
      reducer: {
        app: appReducer,
        jobs: jobsReducer,
        filters: filtersReducer,
        ui: uiReducer,
      },
    });

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

    // Company selector should be present
    expect(screen.getByLabelText(/company/i)).toBeInTheDocument();
  });
});
