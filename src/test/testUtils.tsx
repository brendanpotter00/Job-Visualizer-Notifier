import { ReactElement, ReactNode } from 'react';
import { render, RenderOptions } from '@testing-library/react';
import { Provider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';
import { configureStore } from '@reduxjs/toolkit';
import type { RootState } from '../app/store';
import appReducer from '../features/app/appSlice';
import graphFiltersReducer from '../features/filters/graphFiltersSlice';
import listFiltersReducer from '../features/filters/listFiltersSlice';
import uiReducer from '../features/ui/uiSlice';
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
      ui: uiReducer,
      [jobsApi.reducerPath]: jobsApi.reducer,
    },
    middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(jobsApi.middleware),
    preloadedState: preloadedState as RootState,
  });
}

interface CustomRenderOptions extends Omit<RenderOptions, 'wrapper'> {
  preloadedState?: Partial<RootState>;
  store?: ReturnType<typeof createTestStore>;
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
    ...renderOptions
  }: CustomRenderOptions = {}
) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <Provider store={store}>
        <BrowserRouter>{children}</BrowserRouter>
      </Provider>
    );
  }

  return { store, ...render(ui, { wrapper: Wrapper, ...renderOptions }) };
}
