import { ReactElement, ReactNode } from 'react';
import { render, RenderOptions } from '@testing-library/react';
import { Provider } from 'react-redux';
import { BrowserRouter, MemoryRouter } from 'react-router-dom';
import { configureStore } from '@reduxjs/toolkit';
import type { RootState } from '../app/store';
import appReducer from '../features/app/appSlice';
import graphFiltersReducer from '../features/filters/slices/graphFiltersSlice';
import recentJobsFiltersReducer from '../features/filters/slices/recentJobsFiltersSlice';
import uiReducer from '../features/ui/uiSlice';
import enabledCompaniesReducer from '../features/preferences/enabledCompaniesSlice';
import { jobsApi } from '../features/jobs/jobsApi';
import { featuresApi } from '../features/features/featuresApi';
import { companiesApi } from '../features/companies/companiesApi';
import { feedbackApi } from '../features/feedback/feedbackApi';
import { adminApi } from '../features/admin/adminApi';
import { savedFiltersApi } from '../features/savedFilters/savedFiltersApi';
import { locationsApi } from '../features/locations/locationsApi';
import locationCatalogReducer from '../features/locations/locationCatalogSlice';
import { getTokenOrNull } from '../features/features/getTokenOrNull';

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
      recentJobsFilters: recentJobsFiltersReducer,
      ui: uiReducer,
      enabledCompanies: enabledCompaniesReducer,
      locationCatalog: locationCatalogReducer,
      [jobsApi.reducerPath]: jobsApi.reducer,
      [featuresApi.reducerPath]: featuresApi.reducer,
      [companiesApi.reducerPath]: companiesApi.reducer,
      [feedbackApi.reducerPath]: feedbackApi.reducer,
      [adminApi.reducerPath]: adminApi.reducer,
      [savedFiltersApi.reducerPath]: savedFiltersApi.reducer,
      [locationsApi.reducerPath]: locationsApi.reducer,
    },
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware({
        thunk: { extraArgument: { getTokenOrNull } },
      })
        .concat(jobsApi.middleware)
        .concat(featuresApi.middleware)
        .concat(companiesApi.middleware)
        .concat(feedbackApi.middleware)
        .concat(adminApi.middleware)
        .concat(savedFiltersApi.middleware)
        .concat(locationsApi.middleware),
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
