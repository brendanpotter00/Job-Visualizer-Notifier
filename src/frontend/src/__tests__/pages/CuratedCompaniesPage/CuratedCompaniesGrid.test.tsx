import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../../test/testUtils';
import { CuratedCompaniesGrid } from '../../../pages/CuratedCompaniesPage/CuratedCompaniesGrid';
import type { CuratedCompany } from '../../../features/companies/companiesApi';

function c(id: string, displayName: string, blurb: string | null = null): CuratedCompany {
  return { id, displayName, ats: 'greenhouse', blurb, accomplishment: null };
}

function names() {
  return screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
}

describe('CuratedCompaniesGrid', () => {
  it('renders companies alphabetically by display name (case-insensitive)', () => {
    renderWithProviders(
      <CuratedCompaniesGrid companies={[c('zoox', 'Zoox'), c('airbnb', 'Airbnb'), c('fal', 'fal')]} />
    );
    // 'fal' (lowercase) sorts between Airbnb and Zoox, not last.
    expect(names()).toEqual(['Airbnb', 'fal', 'Zoox']);
  });

  it('filters by company name', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <CuratedCompaniesGrid companies={[c('airbnb', 'Airbnb'), c('stripe', 'Stripe')]} />
    );
    await user.type(screen.getByLabelText('Search companies'), 'stri');
    await waitFor(() =>
      expect(screen.queryByRole('heading', { level: 3, name: 'Airbnb' })).not.toBeInTheDocument()
    );
    expect(screen.getByRole('heading', { level: 3, name: 'Stripe' })).toBeInTheDocument();
  });

  it('filters by blurb text', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <CuratedCompaniesGrid
        companies={[
          c('airbnb', 'Airbnb', 'lodging marketplace'),
          c('stripe', 'Stripe', 'payments infrastructure'),
        ]}
      />
    );
    await user.type(screen.getByLabelText('Search companies'), 'payments');
    await waitFor(() =>
      expect(screen.queryByRole('heading', { level: 3, name: 'Airbnb' })).not.toBeInTheDocument()
    );
    expect(screen.getByRole('heading', { level: 3, name: 'Stripe' })).toBeInTheDocument();
  });

  it('shows an empty state when no company matches the search', async () => {
    const user = userEvent.setup();
    renderWithProviders(<CuratedCompaniesGrid companies={[c('airbnb', 'Airbnb')]} />);
    await user.type(screen.getByLabelText('Search companies'), 'zzzznomatch');
    await waitFor(() => expect(screen.getByText('No companies found')).toBeInTheDocument());
  });
});
