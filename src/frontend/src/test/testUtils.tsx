import { ReactElement, ReactNode } from 'react';
import { render, RenderOptions } from '@testing-library/react';
import { Provider } from 'react-redux';
import { BrowserRouter, MemoryRouter } from 'react-router-dom';
import { configureStore } from '@reduxjs/toolkit';
import type { RootState } from '../app/store';
import appReducer from '../features/app/appSlice';
import graphFiltersReducer from '../features/filters/slices/graphFiltersSlice';
import listFiltersReducer from '../features/filters/slices/listFiltersSlice';
import recentJobsFiltersReducer from '../features/filters/slices/recentJobsFiltersSlice';
import uiReducer from '../features/ui/uiSlice';
import enabledCompaniesReducer from '../features/preferences/enabledCompaniesSlice';
import { jobsApi } from '../features/jobs/jobsApi';

/**
 * Creates a test Redux store with optional preloaded state
 *
 * @param preloadedState - Optional initial state for the store
 * @returns Configured Redux store for testing
 */
export function createTestStore(preloadedState: Partial<RootState> | Record<string, unknown> = {}) {
  return configureStore({
    reducer: {
      app: appReducer,
      graphFilters: graphFiltersReducer,
      listFilters: listFiltersReducer,
      recentJobsFilters: recentJobsFiltersReducer,
      ui: uiReducer,
      enabledCompanies: enabledCompaniesReducer,
      [jobsApi.reducerPath]: jobsApi.reducer,
    },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(jobsApi.middleware),
    preloadedState: preloadedState as RootState,
  });
}

interface CustomRenderOptions extends Omit<RenderOptions, 'wrapper'> {
  preloadedState?: Partial<RootState>;
  store?: ReturnType<typeof createTestStore>;
  /**
   * When provided, wraps the component tree in a `MemoryRouter` seeded with these entries
   * instead of the default `BrowserRouter`. Use for route-based rendering in page-level tests.
   *
   * Omit to preserve the original `BrowserRouter` behavior (default).
   */
  initialEntries?: string[];
}

/**
 * Renders a React element with Redux Provider and React Router
 *
 * This helper wraps the component with both Redux Provider and BrowserRouter,
 * allowing tests to work with components that use Redux state and React Router hooks.
 *
 * @param ui - React element to render
 * @param options - Render options including optional preloaded state and store
 * @returns Render result with store instance
 *
 * @example
 * ```tsx
 * const { store } = renderWithProviders(<MyComponent />);
 * expect(screen.getByText('Hello')).toBeInTheDocument();
 * ```
 */
export function renderWithProviders(
  ui: ReactElement,
  {
    preloadedState,
    store = createTestStore(preloadedState),
    initialEntries,
    ...renderOptions
  }: CustomRenderOptions = {}
) {
  function Wrapper({ children }: { children: ReactNode }) {
    const router =
      initialEntries !== undefined ? (
        <MemoryRouter initialEntries={initialEntries}>{children}</MemoryRouter>
      ) : (
        <BrowserRouter>{children}</BrowserRouter>
      );
    return <Provider store={store}>{router}</Provider>;
  }

  return { store, ...render(ui, { wrapper: Wrapper, ...renderOptions }) };
}
