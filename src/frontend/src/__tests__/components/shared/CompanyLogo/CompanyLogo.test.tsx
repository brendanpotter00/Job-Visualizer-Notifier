import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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

  it('falls back to the company initial when the icon fails to load', () => {
    const { container } = render(<CompanyLogo companyId="reducto" companyName="Reducto" />);
    fireEvent.error(screen.getByRole('img', { name: 'Reducto' }));
    // The <img> is replaced by an initials tile that still exposes the company name.
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByRole('img', { name: 'Reducto' })).toHaveTextContent('R');
  });

  it('is hidden from assistive tech when marked decorative (name shown elsewhere)', () => {
    render(<CompanyLogo companyId="stripe" companyName="Stripe" decorative />);
    // Decorative image has an empty alt, so it is not exposed as a named image.
    expect(screen.queryByRole('img', { name: 'Stripe' })).not.toBeInTheDocument();
  });
});
