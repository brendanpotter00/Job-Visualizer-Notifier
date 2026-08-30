import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BetaBadge } from '../../../components/shared/BetaBadge.tsx';

/**
 * Tests for BetaBadge.
 *
 * The two things worth pinning are both accessibility rules rather than looks:
 * the badge must contribute its word to the surrounding accessible name, and it
 * must stay a plain span (no `role`, no `aria-hidden`) so it reads as part of
 * the label rather than as a separate control or as decoration.
 */
describe('BetaBadge', () => {
  it('renders the word so a screen reader picks it up', () => {
    render(<BetaBadge />);

    const badge = screen.getByText('Beta');
    expect(badge).toBeInTheDocument();
    expect(badge).not.toHaveAttribute('aria-hidden');
    expect(badge).not.toHaveAttribute('role');
  });

  it('is part of the accessible name of the heading it annotates', () => {
    render(
      <h1>
        Add Companies
        <BetaBadge />
      </h1>
    );

    // The badge is inside the heading, so the name carries it. A regression to
    // `aria-hidden` or to a sibling-of-the-heading layout drops "Beta" here.
    expect(screen.getByRole('heading', { name: 'Add Companies Beta' })).toBeInTheDocument();
  });
});
