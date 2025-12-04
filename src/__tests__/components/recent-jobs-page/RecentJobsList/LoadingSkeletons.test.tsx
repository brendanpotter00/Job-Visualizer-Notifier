import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LoadingSkeletons } from '../../../../components/recent-jobs-page/RecentJobsList/LoadingSkeletons';

describe('LoadingSkeletons', () => {
  it('renders correct number of skeleton cards', () => {
    const { container } = render(<LoadingSkeletons count={3} />);

    // Count the number of Card components (they have class MuiCard-root)
    const cards = container.querySelectorAll('.MuiCard-root');
    expect(cards.length).toBe(3);
  });

  it('renders with single skeleton card', () => {
    const { container } = render(<LoadingSkeletons count={1} />);

    const cards = container.querySelectorAll('.MuiCard-root');
    expect(cards.length).toBe(1);
  });

  it('renders with many skeleton cards', () => {
    const { container } = render(<LoadingSkeletons count={10} />);

    const cards = container.querySelectorAll('.MuiCard-root');
    expect(cards.length).toBe(10);
  });

  it('has correct accessibility attributes', () => {
    render(<LoadingSkeletons count={3} />);

    const statusElement = screen.getByRole('status');
    expect(statusElement).toHaveAttribute('aria-label', 'Loading more jobs');
  });

  it('renders skeleton elements matching RecentJobCard layout', () => {
    const { container } = render(<LoadingSkeletons count={1} />);

    // Check for multiple skeleton elements (company, title, location, chips, date)
    const skeletons = container.querySelectorAll('.MuiSkeleton-root');
    expect(skeletons.length).toBeGreaterThan(5); // At least company, title, location, 3 chips, date
  });

  it('all cards are marked aria-hidden', () => {
    const { container } = render(<LoadingSkeletons count={3} />);

    const cards = container.querySelectorAll('.MuiCard-root');
    cards.forEach((card) => {
      expect(card).toHaveAttribute('aria-hidden', 'true');
    });
  });
});
