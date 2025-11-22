import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { Provider } from 'react-redux';
import userEvent from '@testing-library/user-event';
import { CompanySelector } from '../../../components/CompanySelector/CompanySelector';
import { store } from '../../../app/store';

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
    expect(select).toHaveAttribute('aria-labelledby', expect.stringContaining('company-selector-label'));

    // Verify the label exists with correct ID
    const label = document.getElementById('company-selector-label');
    expect(label).toBeInTheDocument();
    expect(label).toHaveTextContent('Company');
  });
});
