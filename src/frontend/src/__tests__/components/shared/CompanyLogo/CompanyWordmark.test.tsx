import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CompanyWordmark } from '../../../../components/shared/CompanyLogo/CompanyWordmark';
import { getCompanyWordmarkUrl } from '../../../../config/companies';

describe('getCompanyWordmarkUrl', () => {
  it('builds the static wordmark path from the company id', () => {
    expect(getCompanyWordmarkUrl('stripe')).toBe('/logos/wordmarks/stripe.png');
  });

  it('preserves ids that contain dots', () => {
    expect(getCompanyWordmarkUrl('happyrobot.ai')).toBe('/logos/wordmarks/happyrobot.ai.png');
  });
});

describe('CompanyWordmark', () => {
  it('renders the wordmark as an h3 whose accessible name is the company name', () => {
    render(<CompanyWordmark companyId="stripe" displayName="Stripe" />);
    const img = screen.getByRole('img', { name: 'Stripe' });
    expect(img).toHaveAttribute('src', '/logos/wordmarks/stripe.png');
    expect(img).toHaveAttribute('loading', 'lazy');
    // The heading name is derived from the image alt, preserving h3 semantics
    // and the name-based directory search.
    expect(screen.getByRole('heading', { level: 3, name: 'Stripe' })).toBeInTheDocument();
  });

  it('falls back to the text name when the wordmark image fails to load', () => {
    render(<CompanyWordmark companyId="reducto" displayName="Reducto" />);
    fireEvent.error(screen.getByRole('img', { name: 'Reducto' }));
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 3, name: 'Reducto' })).toBeInTheDocument();
  });
});
