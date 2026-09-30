import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import { ClosingCtaSection } from '../../../pages/LandingPage/sections/ClosingCtaSection';

function renderSection() {
  return render(
    <MemoryRouter>
      <ClosingCtaSection content={LANDING_CONTENT} />
    </MemoryRouter>
  );
}

describe('ClosingCtaSection', () => {
  it('renders the closing line as a labelled section heading', () => {
    renderSection();
    const heading = screen.getByRole('heading', { name: LANDING_CONTENT.closing.heading, level: 2 });
    expect(screen.getByTestId('closing-cta')).toHaveAttribute('aria-labelledby', heading.id);
  });

  // The same pair as the hero, in the same order: filled primary, text secondary.
  it('renders the filled primary and the text secondary CTA, on their routes', () => {
    renderSection();
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(2);
    const [primary, secondary] = links;
    expect(primary).toHaveTextContent(LANDING_CONTENT.ctas.primary.label);
    expect(primary).toHaveClass('MuiButton-contained');
    expect(primary).toHaveAttribute('href', LANDING_CONTENT.ctas.primary.to);
    expect(secondary).toHaveTextContent(LANDING_CONTENT.ctas.secondary.label);
    expect(secondary).toHaveClass('MuiButton-text');
    expect(secondary).toHaveAttribute('href', LANDING_CONTENT.ctas.secondary.to);
  });
});
