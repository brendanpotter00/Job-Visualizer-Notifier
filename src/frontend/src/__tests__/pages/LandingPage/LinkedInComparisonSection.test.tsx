import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import { LinkedInComparisonSection } from '../../../pages/LandingPage/sections/LinkedInComparisonSection';

const { comparison } = LANDING_CONTENT;

function renderSection() {
  return render(<LinkedInComparisonSection content={LANDING_CONTENT} />);
}

describe('LinkedInComparisonSection', () => {
  it('renders the eyebrow and heading from content.ts as a labelled section', () => {
    renderSection();
    const heading = screen.getByRole('heading', { name: comparison.heading, level: 2 });
    expect(screen.getByText(comparison.eyebrow)).toBeInTheDocument();
    const section = screen.getByTestId('linkedin-comparison');
    expect(section.tagName).toBe('SECTION');
    expect(section).toHaveAttribute('aria-labelledby', heading.id);
  });

  it('renders every row: an h3 label, the LinkedIn fact, and what onesecondswe does', () => {
    renderSection();
    for (const row of comparison.rows) {
      const region = screen.getByTestId(`comparison-row-${row.id}`);
      expect(within(region).getByRole('heading', { name: row.label, level: 3 })).toBeInTheDocument();
      expect(within(region).getByText(row.linkedin)).toBeInTheDocument();
      expect(within(region).getByText(row.onesecondswe)).toBeInTheDocument();
    }
    const rendered = screen.getAllByRole('heading', { level: 3 }).map((el) => el.textContent);
    expect(rendered).toEqual(comparison.rows.map((row) => row.label));
  });

  // On a phone there is no column-head row, so each cell names its column
  // inline; on desktop the head row carries the names once. Both column names
  // must therefore be present for every row, whichever layout is showing.
  it('names both columns on every row so the cells read correctly without the head row', () => {
    renderSection();
    for (const row of comparison.rows) {
      const region = screen.getByTestId(`comparison-row-${row.id}`);
      expect(within(region).getByText(`${comparison.columns.linkedin}:`)).toBeInTheDocument();
      expect(within(region).getByText(`${comparison.columns.onesecondswe}:`)).toBeInTheDocument();
    }
  });

  // Facts, not a scorecard: no ticks, no crosses, nothing to click.
  it('is text only: no links, buttons, or images', () => {
    renderSection();
    expect(screen.queryAllByRole('link')).toHaveLength(0);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(document.querySelectorAll('img, svg')).toHaveLength(0);
  });
});
