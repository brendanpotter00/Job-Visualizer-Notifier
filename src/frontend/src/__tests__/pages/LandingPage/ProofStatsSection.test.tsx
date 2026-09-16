import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import { ProofStatsSection } from '../../../pages/LandingPage/sections/ProofStatsSection';

const { proof } = LANDING_CONTENT;

function renderSection() {
  return render(<ProofStatsSection content={LANDING_CONTENT} />);
}

describe('ProofStatsSection', () => {
  it('renders the eyebrow and heading from content.ts as a labelled section', () => {
    renderSection();
    const heading = screen.getByRole('heading', { name: proof.heading, level: 2 });
    expect(screen.getByText(proof.eyebrow)).toBeInTheDocument();
    expect(screen.getByTestId('proof-stats')).toHaveAttribute('aria-labelledby', heading.id);
  });

  // The sentences are the brief §10 P1 quotable claims; they must render
  // verbatim, each under its own number, in content order.
  it('renders every stat as its value over its sentence, verbatim and in order', () => {
    renderSection();
    for (const stat of proof.stats) {
      const tile = screen.getByTestId(`proof-stat-${stat.id}`);
      expect(within(tile).getByText(stat.value)).toBeInTheDocument();
      expect(within(tile).getByText(stat.sentence)).toBeInTheDocument();
      expect(
        within(tile)
          .getByText(stat.value)
          .compareDocumentPosition(within(tile).getByText(stat.sentence)) &
          Node.DOCUMENT_POSITION_FOLLOWING
      ).toBeTruthy();
    }
    const tiles = screen.getAllByTestId(/^proof-stat-/);
    expect(tiles.map((tile) => tile.getAttribute('data-testid'))).toEqual(
      proof.stats.map((stat) => `proof-stat-${stat.id}`)
    );
  });

  it('is text only: no links, buttons, or images', () => {
    renderSection();
    expect(screen.queryAllByRole('link')).toHaveLength(0);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(document.querySelectorAll('img, svg')).toHaveLength(0);
  });
});
