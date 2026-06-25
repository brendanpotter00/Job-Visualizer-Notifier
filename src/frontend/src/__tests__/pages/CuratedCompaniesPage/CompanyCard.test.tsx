import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { useIsMobile } from '../../../hooks/useIsMobile';
import { CompanyCard } from '../../../pages/CuratedCompaniesPage/CompanyCard';
import type { CuratedCompany } from '../../../features/companies/companiesApi';

// CompanyCard reads useIsMobile() (the barrel-imported useMediaQuery underneath
// is awkward to mock, so we mock the hook directly). Default to desktop (false)
// so the existing assertions, which expect the description, keep their meaning.
vi.mock('../../../hooks/useIsMobile');

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
  beforeEach(() => {
    // Default every test to desktop unless it opts into mobile below.
    vi.mocked(useIsMobile).mockReturnValue(false);
  });

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
    // `db-only-co` exists in the DB but not in config/companies.ts — a deep
    // link would be rejected by getInitialCompanyId, so the card shows no link.
    renderWithProviders(
      <CompanyCard company={company({ id: 'db-only-co', displayName: 'DB Only Co' })} />
    );
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'DB Only Co' })).toBeInTheDocument();
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

  describe('mobile (compact 1-up card)', () => {
    beforeEach(() => vi.mocked(useIsMobile).mockReturnValue(true));

    it('still shows the description (kept, just smaller + clamped on mobile)', () => {
      renderWithProviders(<CompanyCard company={company()} />);
      expect(screen.getByText('Payments infra. Powers checkout.')).toBeInTheDocument();
    });

    it('still renders the company name and the hiring-trends link', () => {
      renderWithProviders(<CompanyCard company={company()} />);
      expect(screen.getByRole('heading', { level: 3, name: 'Stripe' })).toBeInTheDocument();
      expect(
        screen.getByRole('link', { name: /see company hiring trends/i })
      ).toBeInTheDocument();
    });
  });
});
