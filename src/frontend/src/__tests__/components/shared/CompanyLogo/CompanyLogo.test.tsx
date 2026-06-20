import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CompanyLogo } from '../../../../components/shared/CompanyLogo/CompanyLogo';
import { getCompanyLogoUrl } from '../../../../config/companies';

describe('getCompanyLogoUrl', () => {
  it('builds the static icon path from the company id', () => {
    expect(getCompanyLogoUrl('stripe')).toBe('/logos/icons/stripe.png');
  });

  it('preserves ids that contain dots', () => {
    expect(getCompanyLogoUrl('happyrobot.ai')).toBe('/logos/icons/happyrobot.ai.png');
  });
});

describe('CompanyLogo', () => {
  it('renders the company icon with the resolved src and a descriptive alt', () => {
    render(<CompanyLogo companyId="stripe" companyName="Stripe" />);
    const img = screen.getByRole('img', { name: 'Stripe' });
    expect(img).toHaveAttribute('src', '/logos/icons/stripe.png');
  });

  it('falls back to the company id for alt text when no name is given', () => {
    render(<CompanyLogo companyId="reducto" />);
    const img = screen.getByRole('img', { name: 'reducto' });
    expect(img).toHaveAttribute('src', '/logos/icons/reducto.png');
  });

  it('lazy-loads the icon so large grids do not fetch every logo upfront', () => {
    render(<CompanyLogo companyId="stripe" companyName="Stripe" />);
    expect(screen.getByRole('img', { name: 'Stripe' })).toHaveAttribute('loading', 'lazy');
  });
});
