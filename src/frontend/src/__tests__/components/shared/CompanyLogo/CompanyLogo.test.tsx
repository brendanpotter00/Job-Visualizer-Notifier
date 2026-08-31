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
    render(<CompanyLogo companyId="stripe" displayName="Stripe" />);
    const img = screen.getByRole('img', { name: 'Stripe' });
    expect(img).toHaveAttribute('src', '/logos/icons/stripe.png');
  });

  it('never announces the raw company id when no name is given', () => {
    // The caller omits displayName when it could not resolve a human name. The
    // only other string available is the id, and for a user-added board that is
    // an opaque handle (`u-ajhs85a7y0`), so it must not reach the alt text.
    render(<CompanyLogo companyId="u-ajhs85a7y0" />);
    const img = screen.getByRole('img', { name: 'Company' });
    expect(img).toHaveAttribute('src', '/logos/icons/u-ajhs85a7y0.png');
    expect(screen.queryByRole('img', { name: 'u-ajhs85a7y0' })).not.toBeInTheDocument();
  });

  it('falls back to a neutral glyph — never an id-derived initial — when unnamed art fails', () => {
    // The reported bug: an opaque `u-…` id fell through to the label and the
    // tile rendered a literal "U" on every card of a user-added company.
    const { container } = render(<CompanyLogo companyId="u-ajhs85a7y0" />);
    fireEvent.error(container.querySelector('img')!);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.queryByText('U')).not.toBeInTheDocument();
    expect(screen.queryByText(/u-ajhs85a7y0/i)).not.toBeInTheDocument();
    // The generic company mark renders as an inline SVG icon, not text.
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('skips the request entirely for a company we hold no art for', () => {
    // A user-added board has a readable name but no committed icon, so an
    // initials tile would show an arbitrary letter and the <img> would 404.
    const { container } = render(
      <CompanyLogo companyId="u-ajhs85a7y0" displayName="www.janestreet.com" hasBrandArt={false} />
    );
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
    expect(screen.queryByText('W')).not.toBeInTheDocument();
    // The name is still the accessible name of the tile.
    expect(screen.getByRole('img', { name: 'www.janestreet.com' })).toBeInTheDocument();
  });

  it('treats a blank display name as no name at all', () => {
    // A whitespace-only `display_name` is a data gap; trimming it to "" would
    // leave an empty tile with an empty accessible name.
    const { container } = render(<CompanyLogo companyId="reducto" displayName="   " />);
    fireEvent.error(container.querySelector('img')!);
    expect(container.querySelector('svg')).not.toBeNull();
    expect(screen.getByRole('img', { name: 'Company' })).toBeInTheDocument();
  });

  it('lazy-loads the icon so large grids do not fetch every logo upfront', () => {
    render(<CompanyLogo companyId="stripe" displayName="Stripe" />);
    expect(screen.getByRole('img', { name: 'Stripe' })).toHaveAttribute('loading', 'lazy');
  });

  it('falls back to the company initial when the icon fails to load', () => {
    const { container } = render(<CompanyLogo companyId="reducto" displayName="Reducto" />);
    fireEvent.error(screen.getByRole('img', { name: 'Reducto' }));
    // The <img> is replaced by an initials tile that still exposes the company name.
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByRole('img', { name: 'Reducto' })).toHaveTextContent('R');
  });

  it('is hidden from assistive tech when marked decorative (name shown elsewhere)', () => {
    render(<CompanyLogo companyId="stripe" displayName="Stripe" decorative />);
    // Decorative image has an empty alt, so it is not exposed as a named image.
    expect(screen.queryByRole('img', { name: 'Stripe' })).not.toBeInTheDocument();
  });

  it('stays hidden from assistive tech when a decorative icon fails to load', () => {
    const { container } = render(
      <CompanyLogo companyId="reducto" displayName="Reducto" decorative />
    );
    // The decorative image has an empty alt, so trigger its onError via the element.
    fireEvent.error(container.querySelector('img')!);
    // The fallback initials tile must not be exposed as a named image (no role /
    // aria-label) so the adjacent visible name isn't announced twice.
    expect(container.querySelector('img')).toBeNull();
    expect(screen.queryByRole('img', { name: 'Reducto' })).not.toBeInTheDocument();
    expect(screen.getByText('R')).toBeInTheDocument();
  });
});
