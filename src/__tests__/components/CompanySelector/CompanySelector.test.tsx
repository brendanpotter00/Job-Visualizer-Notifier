import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import { configureStore } from '@reduxjs/toolkit';
import userEvent from '@testing-library/user-event';
import { CompanySelector } from '../../../components/CompanySelector/CompanySelector';
import { store } from '../../../app/store';
import appReducer from '../../../features/app/appSlice';
import jobsReducer from '../../../features/jobs/jobsSlice';
import graphFiltersReducer from '../../../features/filters/graphFiltersSlice';
import listFiltersReducer from '../../../features/filters/listFiltersSlice';
import uiReducer from '../../../features/ui/uiSlice';

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

describe('CompanySelector', () => {
  it('renders company selector with label', () => {
    render(
      <Provider store={store}>
        <CompanySelector />
      </Provider>
    );
    expect(screen.getByLabelText('Company')).toBeInTheDocument();
  });

  it('displays current selected company', () => {
    render(
      <Provider store={store}>
        <CompanySelector />
      </Provider>
    );
    // Default is SpaceX
    expect(screen.getByRole('combobox')).toHaveTextContent('SpaceX');
  });

  it('shows all available companies in dropdown', async () => {
    const user = userEvent.setup();

    render(
      <Provider store={store}>
        <CompanySelector />
      </Provider>
    );

    // Click to open dropdown
    const selector = screen.getByRole('combobox');
    await user.click(selector);

    // Check for both companies
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'SpaceX' })).toBeInTheDocument();
      expect(screen.getByRole('option', { name: 'Nominal' })).toBeInTheDocument();
    });
  });

  it('changes selected company when option is clicked', async () => {
    const user = userEvent.setup();

    render(
      <Provider store={store}>
        <CompanySelector />
      </Provider>
    );

    // Open dropdown
    const selector = screen.getByRole('combobox');
    await user.click(selector);

    // Select Nominal
    const nominalOption = await screen.findByRole('option', { name: 'Nominal' });
    await user.click(nominalOption);

    // Verify state changed
    await waitFor(() => {
      expect(store.getState().app.selectedCompanyId).toBe('nominal');
    });
  });

  it('has accessible label association', () => {
    render(
      <Provider store={store}>
        <CompanySelector />
      </Provider>
    );

    const select = screen.getByRole('combobox');
    expect(select).toHaveAttribute(
      'aria-labelledby',
      expect.stringContaining('company-selector-label')
    );

    // Verify the label exists with correct ID
    const label = document.getElementById('company-selector-label');
    expect(label).toBeInTheDocument();
    expect(label).toHaveTextContent('Company');
  });

  describe('URL synchronization', () => {
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

    it('should dispatch setSelectedCompanyId action when company changes', async () => {
      const user = userEvent.setup();
      const testStore = createTestStore();

      render(
        <Provider store={testStore}>
          <CompanySelector />
        </Provider>
      );

      // Open dropdown
      const selector = screen.getByRole('combobox');
      await user.click(selector);

      // Select a different company
      const anthropicOption = await screen.findByRole('option', { name: 'Anthropic' });
      await user.click(anthropicOption);

      // Verify Redux state changed
      await waitFor(() => {
        expect(testStore.getState().app.selectedCompanyId).toBe('anthropic');
      });
    });
  });
});
