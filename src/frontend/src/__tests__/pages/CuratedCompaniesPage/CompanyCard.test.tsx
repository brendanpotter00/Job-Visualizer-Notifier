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
  it('links the whole card to hiring trends for a config-known company', () => {
    renderWithProviders(<CompanyCard company={company()} />);
    const link = screen.getByRole('link', { name: /view hiring trends for stripe/i });
    expect(link).toHaveAttribute('href', '/companies?company=stripe');
    expect(screen.getByRole('heading', { level: 3, name: 'Stripe' })).toBeInTheDocument();
    expect(screen.getByText('Payments infra.')).toBeInTheDocument();
    expect(screen.getByText('Powers checkout.')).toBeInTheDocument();
  });

  it('renders a non-link card for a DB-only company missing from the frontend config', () => {
    // `reducto` exists in the DB but not in config/companies.ts — a deep link
    // would be rejected by getInitialCompanyId, so the card must not be a link.
    renderWithProviders(
      <CompanyCard company={company({ id: 'reducto', displayName: 'Reducto' })} />
    );
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Reducto' })).toBeInTheDocument();
  });

  it('omits the blurb and accomplishment lines when they are null', () => {
    renderWithProviders(
      <CompanyCard company={company({ blurb: null, accomplishment: null })} />
    );
    expect(screen.queryByText('Payments infra.')).not.toBeInTheDocument();
    expect(screen.queryByText('Powers checkout.')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Stripe' })).toBeInTheDocument();
  });
});
