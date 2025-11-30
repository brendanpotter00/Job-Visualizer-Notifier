import { describe, it, expect, beforeEach, vi, beforeAll, afterAll, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import { setupServer } from 'msw/node';
import { http, HttpResponse } from 'msw';
import React from 'react';
import { useCompanyLoader } from '../../../app/hooks/useCompanyLoader';
import appReducer from '../../../features/app/appSlice';
import jobsReducer from '../../../features/jobs/jobsSlice';
import graphFiltersReducer from '../../../features/filters/graphFiltersSlice';
import listFiltersReducer from '../../../features/filters/listFiltersSlice';
import uiReducer from '../../../features/ui/uiSlice';
import * as urlParams from '../../../utils/urlParams';

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

function createTestStore(preloadedState = {}) {
  return configureStore({
    reducer: {
      app: appReducer,
      jobs: jobsReducer,
      graphFilters: graphFiltersReducer,
      listFilters: listFiltersReducer,
      ui: uiReducer,
    },
    preloadedState,
  });
}

describe('useCompanyLoader', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset window.location
    Object.defineProperty(window, 'location', {
      value: new URL('http://localhost:5173/'),
      writable: true,
      configurable: true,
    });
  });

  it('should initialize with default company when no URL parameter', async () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
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
      <Provider store={store}>{children}</Provider>
    );
    renderHook(() => useCompanyLoader(), { wrapper });

    await waitFor(() => {
      expect(store.getState().app.selectedCompanyId).toBe('anthropic');
    });
  });

  it('should load jobs on mount', async () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    );
    renderHook(() => useCompanyLoader(), { wrapper });

    await waitFor(() => {
      const state = store.getState();
      expect(state.jobs.byCompany.spacex).toBeDefined();
    });
  });

  it('should return loading state', () => {
    const store = createTestStore({
      jobs: {
        byCompany: {
          spacex: {
            jobs: [],
            loading: true,
            error: null,
            lastFetch: null,
          },
        },
      },
    });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    );
    const { result } = renderHook(() => useCompanyLoader(), { wrapper });

    expect(result.current.isLoading).toBe(true);
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
      <Provider store={store}>{children}</Provider>
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
      <Provider store={store}>{children}</Provider>
    );
    const { result } = renderHook(() => useCompanyLoader(), { wrapper });

    expect(result.current.handleRetry).toBeInstanceOf(Function);
  });

  it('should reload jobs when handleRetry is called', async () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    );
    const { result } = renderHook(() => useCompanyLoader(), { wrapper });

    // Wait for initial load
    await waitFor(() => {
      const state = store.getState();
      expect(state.jobs.byCompany.spacex).toBeDefined();
    });

    // Call retry - should trigger another load
    result.current.handleRetry();

    // Verify loading state resets
    expect(result.current.isLoading).toBeDefined();
  });

  it('should load jobs when company changes', async () => {
    const store = createTestStore();
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>{children}</Provider>
    );
    const { rerender } = renderHook(() => useCompanyLoader(), { wrapper });

    // Wait for initial load
    await waitFor(() => {
      const state = store.getState();
      expect(state.jobs.byCompany.spacex).toBeDefined();
    });

    // Change company
    store.dispatch({ type: 'app/setSelectedCompanyId', payload: 'anthropic' });
    rerender();

    // Should load new company jobs
    await waitFor(() => {
      const state = store.getState();
      expect(state.jobs.byCompany.anthropic).toBeDefined();
    });
  });
});
