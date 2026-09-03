import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LogoWall } from '../../../pages/AdminLandingPrototypesPage/sections/LogoWall';
import { getCompanyById } from '../../../config/companies';

// jsdom does not implement matchMedia at all; usePrefersReducedMotion guards
// that absence (→ false). These tests define it per-case to drive both paths.
function defineMatchMedia(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }))
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('LogoWall', () => {
  it('renders marquee rows with duplicated tiles when motion is allowed', () => {
    render(<LogoWall companyIds={['apple', 'google', 'spacex', 'stripe']} rows={2} perRow={2} />);
    // 2 rows × 2 ids × 2 copies (seamless loop) = 8 tiles; duplicates are
    // aria-hidden so assistive tech hears each company once.
    const imgs = document.querySelectorAll('img');
    expect(imgs).toHaveLength(8);
    // Tiles announce the company's display name (CompanyLogo labels unnamed
    // tiles with a generic "Company" — the wall must never fall back to that).
    const appleName = getCompanyById('apple')!.name;
    expect(screen.getAllByAltText(appleName)).toHaveLength(1);
    expect(screen.queryByAltText('Company')).not.toBeInTheDocument();
  });

  it('collapses to a static wrapped grid under prefers-reduced-motion', () => {
    defineMatchMedia(true);
    render(<LogoWall companyIds={['apple', 'google', 'spacex', 'stripe']} rows={2} perRow={2} />);
    // No duplication in the static grid: one tile per company.
    expect(document.querySelectorAll('img')).toHaveLength(4);
  });

  it('defaults to the full registry spread when no ids are given', () => {
    render(<LogoWall rows={1} perRow={10} />);
    expect(document.querySelectorAll('img').length).toBe(20); // 10 ids × 2 copies
  });
});
