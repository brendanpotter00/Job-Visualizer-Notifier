import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { CompanyCard } from '../../../pages/CuratedCompaniesPage/CompanyCard';
import type { CuratedCompany } from '../../../features/companies/companiesApi';

function company(overrides: Partial<CuratedCompany> = {}): CuratedCompany {
  return {
    id: 'stripe',
    displayName: 'Stripe',
    ats: 'greenhouse',
    blurb: 'Payments infra.',
    accomplishment: 'Powers checkout.',
    ...overrides,
  };
}

describe('CompanyCard', () => {
  it('renders an explicit hiring-trends link for a config-known company', () => {
    renderWithProviders(<CompanyCard company={company()} />);
    const link = screen.getByRole('link', { name: /see company hiring trends/i });
    expect(link).toHaveAttribute('href', '/companies?company=stripe');
    expect(screen.getByRole('heading', { level: 3, name: 'Stripe' })).toBeInTheDocument();
  });

  it('combines blurb and accomplishment into one cohesive description', () => {
    renderWithProviders(<CompanyCard company={company()} />);
    expect(screen.getByText('Payments infra. Powers checkout.')).toBeInTheDocument();
  });

  it('omits the hiring-trends link for a DB-only company missing from the frontend config', () => {
    // `reducto` exists in the DB but not in config/companies.ts — a deep link
    // would be rejected by getInitialCompanyId, so the card shows no link.
    renderWithProviders(
      <CompanyCard company={company({ id: 'reducto', displayName: 'Reducto' })} />
    );
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Reducto' })).toBeInTheDocument();
  });

  it('renders no description when both blurb and accomplishment are null', () => {
    renderWithProviders(
      <CompanyCard company={company({ blurb: null, accomplishment: null })} />
    );
    expect(screen.queryByText(/Payments infra\./)).not.toBeInTheDocument();
    expect(screen.queryByText(/Powers checkout\./)).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Stripe' })).toBeInTheDocument();
    // Still linkable.
    expect(screen.getByRole('link', { name: /see company hiring trends/i })).toBeInTheDocument();
  });
});
