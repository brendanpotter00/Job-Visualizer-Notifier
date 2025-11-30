import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import appReducer from '../../../features/app/appSlice';
import jobsReducer from '../../../features/jobs/jobsSlice';
import graphFiltersReducer from '../../../features/filters/graphFiltersSlice';
import listFiltersReducer from '../../../features/filters/listFiltersSlice';
import uiReducer from '../../../features/ui/uiSlice';
import { AppHeader } from '../../../components/AppLayout/AppHeader';
import type { RootState } from '../../../app/store';

// Helper to create a store with custom initial state
function createTestStore(preloadedState?: Partial<RootState>) {
  return configureStore({
    reducer: {
      app: appReducer,
      jobs: jobsReducer,
      graphFilters: graphFiltersReducer,
      listFilters: listFiltersReducer,
      ui: uiReducer,
    },
    preloadedState: preloadedState as RootState,
  });
}

describe('AppHeader', () => {
  it('should render with company name in title', () => {
    const testStore = createTestStore({
      app: {
        selectedCompanyId: 'spacex',
        selectedATS: 'greenhouse',
        isInitialized: false,
      },
    } as Partial<RootState>);

    render(
      <Provider store={testStore}>
        <AppHeader />
      </Provider>
    );

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'SpaceX - Job Posting Analytics'
    );
  });

  it('should render company selector', () => {
    const testStore = createTestStore({
      app: {
        selectedCompanyId: 'anthropic',
        selectedATS: 'greenhouse',
        isInitialized: false,
      },
    } as Partial<RootState>);

    render(
      <Provider store={testStore}>
        <AppHeader />
      </Provider>
    );

    expect(screen.getByLabelText('Company')).toBeInTheDocument();
  });

  it('should render with default fallback name', () => {
    const testStore = createTestStore({
      app: {
        selectedCompanyId: 'invalid-company-id',
        selectedATS: 'greenhouse',
        isInitialized: false,
      },
    } as Partial<RootState>);

    render(
      <Provider store={testStore}>
        <AppHeader />
      </Provider>
    );

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
      'Job Posting Analytics - Job Posting Analytics'
    );
  });

  it('should have proper layout structure', () => {
    const testStore = createTestStore({
      app: {
        selectedCompanyId: 'notion',
        selectedATS: 'greenhouse',
        isInitialized: false,
      },
    } as Partial<RootState>);

    const { container } = render(
      <Provider store={testStore}>
        <AppHeader />
      </Provider>
    );

    // Should have a Stack container with proper spacing
    const stack = container.querySelector('.MuiStack-root');
    expect(stack).toBeInTheDocument();
  });

  it('should display different company names correctly', () => {
    const companies = [
      { id: 'spacex', name: 'SpaceX' },
      { id: 'anthropic', name: 'Anthropic' },
      { id: 'notion', name: 'Notion' },
      { id: 'stripe', name: 'Stripe' },
      { id: 'palantir', name: 'Palantir' },
    ];

    companies.forEach(({ id, name }) => {
      const testStore = createTestStore({
        app: {
          selectedCompanyId: id,
          selectedATS: 'greenhouse',
          isInitialized: false,
        },
      } as Partial<RootState>);

      const { unmount } = render(
        <Provider store={testStore}>
          <AppHeader />
        </Provider>
      );

      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        `${name} - Job Posting Analytics`
      );

      unmount();
    });
  });
});
