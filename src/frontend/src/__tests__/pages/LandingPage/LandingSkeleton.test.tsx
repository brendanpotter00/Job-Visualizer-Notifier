import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LandingSkeleton } from '../../../pages/LandingPage/LandingSkeleton';

describe('LandingSkeleton', () => {
  it('is a single labelled loading region with no spinner', () => {
    render(<LandingSkeleton />);
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(screen.getByRole('status', { name: 'Loading…' })).toHaveAttribute('aria-busy', 'true');
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('lays out header bar, hero and the first section in the landing containers', () => {
    const { container } = render(<LandingSkeleton />);
    // Header bar, hero and first section each sit in their own `lg` container,
    // like LandingHeader / GravityPrototype.
    expect(container.querySelectorAll('.MuiContainer-maxWidthLg')).toHaveLength(3);
    // The first section's card row.
    expect(container.querySelectorAll('.MuiCard-root')).toHaveLength(3);
  });

  it('renders no headings or links (the real header and CTAs arrive with the scene)', () => {
    render(<LandingSkeleton />);
    expect(screen.queryByRole('heading')).not.toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});
