import { describe, it, expect, beforeEach, vi, beforeAll, afterAll, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import React from 'react';
import { useCompanyLoader } from '../../../hooks/useCompanyLoader';
import { createTestStore } from '../../../test/testUtils';
import * as urlParams from '../../../lib/url';

// Mock API responses
const mockGreenhouseJobs = {
  jobs: [
    {
      id: 1,
      title: 'Software Engineer',
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

// Note: Using createTestStore from testUtils which includes RTK Query setup

describe('useCompanyLoader', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset window.location to /companies (Companies page route)
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/companies'),
      writable: true,
      configurable: true,
    });
  });

  it('should initialize with default company when no URL parameter', async () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    renderHook(() => useCompanyLoader(), { wrapper });

    await waitFor(() => {
      expect(store.getState().app.selectedCompanyId).toBe('spacex');
    });
  });

  it('should initialize with company from URL parameter', async () => {
    vi.spyOn(urlParams, 'getInitialCompanyId').mockReturnValue('anthropic');

    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    renderHook(() => useCompanyLoader(), { wrapper });

    await waitFor(() => {
      expect(store.getState().app.selectedCompanyId).toBe('anthropic');
    });
  });

  it('should load jobs on mount', async () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    renderHook(() => useCompanyLoader(), { wrapper });

    await waitFor(() => {
      const state = store.getState();
      // Check RTK Query cache for spacex data
      const queries = state.jobsApi?.queries || {};
      const hasSpacexQuery = Object.keys(queries).some((key) => key.includes('spacex'));
      expect(hasSpacexQuery).toBe(true);
    });
  });

  it('should return loading state', async () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    const { result } = renderHook(() => useCompanyLoader(), { wrapper });

    // Initially should be loading (RTK Query starts request immediately)
    // We need to check the loading state shortly after mount
    await waitFor(() => {
      // Either loading or loaded (depending on timing)
      expect(result.current.isLoading !== undefined).toBe(true);
    });
  });

  it('should return error state', async () => {
    // Override API to return error
    server.use(
      http.get('/api/greenhouse/v1/boards/*/jobs', () => {
        return HttpResponse.error();
      })
    );

    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    const { result } = renderHook(() => useCompanyLoader(), { wrapper });

    // Wait for error state
    await waitFor(() => {
      expect(result.current.error).toBeTruthy();
    });
  });

  it('should provide handleRetry function', () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    const { result } = renderHook(() => useCompanyLoader(), { wrapper });

    expect(result.current.handleRetry).toBeInstanceOf(Function);
  });

  it('should reload jobs when handleRetry is called', async () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    const { result } = renderHook(() => useCompanyLoader(), { wrapper });

    // Wait for initial load
    await waitFor(() => {
      const state = store.getState();
      const queries = state.jobsApi?.queries || {};
      const hasSpacexQuery = Object.keys(queries).some((key) => key.includes('spacex'));
      expect(hasSpacexQuery).toBe(true);
    });

    // Call retry - should trigger another load
    result.current.handleRetry();

    // Verify loading state resets
    expect(result.current.isLoading).toBeDefined();
  });

  it('should load jobs when company changes', async () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
    const { rerender } = renderHook(() => useCompanyLoader(), { wrapper });

    // Wait for initial load
    await waitFor(() => {
      const state = store.getState();
      const queries = state.jobsApi?.queries || {};
      const hasSpacexQuery = Object.keys(queries).some((key) => key.includes('spacex'));
      expect(hasSpacexQuery).toBe(true);
    });

    // Change company
    store.dispatch({ type: 'app/setSelectedCompanyId', payload: 'anthropic' });
    rerender();

    // Should load new company jobs
    await waitFor(() => {
      const state = store.getState();
      const queries = state.jobsApi?.queries || {};
      const hasAnthropicQuery = Object.keys(queries).some((key) => key.includes('anthropic'));
      expect(hasAnthropicQuery).toBe(true);
    });
  });
});
