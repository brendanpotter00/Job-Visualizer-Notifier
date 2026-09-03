import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { HeroTrendline } from '../../../pages/LandingPage/sections/HeroTrendline';
import { buildSmoothPath } from '../../../pages/LandingPage/sections/trendlinePath';

describe('buildSmoothPath', () => {
  it('returns empty for fewer than two points', () => {
    expect(buildSmoothPath([])).toBe('');
    expect(buildSmoothPath([[0, 10]])).toBe('');
  });

  it('opens with a move, smooths interior points with quadratics, and closes on the last point', () => {
    const path = buildSmoothPath([
      [0, 50],
      [100, 20],
      [200, 60],
      [300, 40],
    ]);
    expect(path.startsWith('M 0 50')).toBe(true);
    expect(path.match(/Q /g)).toHaveLength(2);
    expect(path.endsWith('L 300 40')).toBe(true);
  });
});

describe('HeroTrendline', () => {
  it('renders a decorative, pointer-transparent line', () => {
    render(<HeroTrendline />);
    const wrapper = screen.getByTestId('hero-trendline');
    expect(wrapper).toHaveAttribute('aria-hidden', 'true');
    const path = wrapper.querySelector('path');
    expect(path).not.toBeNull();
    expect(path?.getAttribute('d')?.startsWith('M ')).toBe(true);
    expect(path?.getAttribute('stroke-opacity')).toBe('0.07');
  });
});
