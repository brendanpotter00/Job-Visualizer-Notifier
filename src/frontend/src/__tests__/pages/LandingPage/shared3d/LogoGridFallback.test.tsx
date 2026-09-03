import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { RESPONSIVE } from '../../../../config/responsive';
import { LogoGridFallback } from '../../../../pages/LandingPage/prototypes/shared3d/LogoGridFallback';
import type { LogoRosterEntry } from '../../../../pages/LandingPage/prototypes/shared3d/logoRoster';

const ROSTER: LogoRosterEntry[] = [
  { companyId: 'anthropic', logoUrl: '/logos/icons/anthropic.png' },
  { companyId: 'spacex', logoUrl: '/logos/icons/spacex.png' },
  { companyId: 'stripe', logoUrl: '/logos/icons/stripe.png' },
];

describe('LogoGridFallback', () => {
  it('renders one img tile per roster entry with the roster urls', () => {
    render(<LogoGridFallback roster={ROSTER} />);
    const grid = screen.getByLabelText('Companies tracked by onesecondswe');
    const images = within(grid).getAllByRole('img');
    expect(images).toHaveLength(ROSTER.length);
    ROSTER.forEach((entry, index) => {
      expect(images[index]).toHaveAttribute('src', entry.logoUrl);
      expect(images[index]).toHaveAttribute('alt', entry.companyId);
    });
  });

  it('renders nothing but the container for an empty roster', () => {
    render(<LogoGridFallback roster={[]} />);
    const grid = screen.getByLabelText('Companies tracked by onesecondswe');
    expect(within(grid).queryAllByRole('img')).toHaveLength(0);
  });

  it('hides a tile whose logo asset fails to load', () => {
    render(<LogoGridFallback roster={ROSTER} />);
    const grid = screen.getByLabelText('Companies tracked by onesecondswe');
    const [first] = within(grid).getAllByRole('img');
    first.dispatchEvent(new Event('error'));
    expect(first).toHaveStyle({ display: 'none' });
  });

  it('uses the compact logo-tile token on mobile viewports', () => {
    // jsdom has no matchMedia; stub it so MUI's useMediaQuery reports mobile.
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: (query: string) => ({
        matches: query.includes('max-width'),
        media: query,
        onchange: null,
        addEventListener: () => {},
        removeEventListener: () => {},
        addListener: () => {},
        removeListener: () => {},
        dispatchEvent: () => false,
      }),
    });
    render(<LogoGridFallback roster={ROSTER} />);
    const grid = screen.getByLabelText('Companies tracked by onesecondswe');
    const [first] = within(grid).getAllByRole('img');
    expect(first).toHaveStyle({
      width: `${RESPONSIVE.landingProto.logoTileSize.compact}px`,
    });
  });
});

afterEach(() => {
  Reflect.deleteProperty(window, 'matchMedia');
});
