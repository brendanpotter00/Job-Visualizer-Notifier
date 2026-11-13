import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import { LinkedInComparisonSection } from '../../../pages/LandingPage/sections/LinkedInComparisonSection';

const { comparison } = LANDING_CONTENT;

function renderSection() {
  return render(<LinkedInComparisonSection content={LANDING_CONTENT} />);
}

describe('LinkedInComparisonSection', () => {
  it('renders the heading from content.ts as a labelled section', () => {
    renderSection();
    const heading = screen.getByRole('heading', { name: comparison.heading, level: 2 });
    const section = screen.getByTestId('linkedin-comparison');
    expect(section.tagName).toBe('SECTION');
    expect(section).toHaveAttribute('aria-labelledby', heading.id);
  });

  it('renders every row: an h3 label, the LinkedIn fact, and what onesecondswe does', () => {
    renderSection();
    for (const row of comparison.rows) {
      const region = screen.getByTestId(`comparison-row-${row.id}`);
      expect(
        within(region).getByRole('heading', { name: row.label, level: 3 })
      ).toBeInTheDocument();
      expect(within(region).getByText(row.linkedin)).toBeInTheDocument();
      expect(within(region).getByText(row.onesecondswe)).toBeInTheDocument();
    }
    const rendered = screen.getAllByRole('heading', { level: 3 }).map((el) => el.textContent);
    expect(rendered).toEqual(comparison.rows.map((row) => row.label));
  });

  // Every cell carries its column name in the DOM at every width: visible on a
  // phone (no head row there), visually hidden from `sm` up where the
  // decorative head row shows the names. jsdom only applies the `xs` branch,
  // so this pins presence, not the clip — the clip is CSS on the same span.
  it('names both columns on every row so no cell is ever an unattributed paragraph', () => {
    renderSection();
    for (const row of comparison.rows) {
      const region = screen.getByTestId(`comparison-row-${row.id}`);
      expect(within(region).getByText(`${comparison.columns.linkedin}:`)).toBeInTheDocument();
      expect(within(region).getByText(`${comparison.columns.onesecondswe}:`)).toBeInTheDocument();
    }
  });

  // Facts, not a scorecard: no ticks, no crosses, nothing to click.
  // Phone redesign (2026-11-12): one head row names the columns, sentence
  // case. Decorative — every cell already carries its (visually hidden)
  // column name.
  it('gives phones one decorative head row naming both columns', () => {
    renderSection();
    const head = screen.getByTestId('comparison-head-compact');
    expect(head).toHaveAttribute('aria-hidden', 'true');
    expect(head).toHaveTextContent(comparison.columns.linkedin);
    expect(head).toHaveTextContent(comparison.columns.onesecondswe);
    expect(within(head).queryByTestId('one-second-mark')).not.toBeInTheDocument();
  });

  // Ours first (owner-directed 2026-11-12): onesecondswe's answer precedes the
  // LinkedIn fact in every row and in the phone head.
  it('puts onesecondswe before LinkedIn in every row and in the head', () => {
    renderSection();
    const follows = (a: Element, b: Element) =>
      Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    for (const row of comparison.rows) {
      const region = screen.getByTestId(`comparison-row-${row.id}`);
      expect(
        follows(within(region).getByText(row.onesecondswe), within(region).getByText(row.linkedin))
      ).toBe(true);
    }
    const head = screen.getByTestId('comparison-head-compact');
    expect(head.firstElementChild).toHaveTextContent(comparison.columns.onesecondswe);
  });

  it('is text only: no links, buttons, or images', () => {
    renderSection();
    expect(screen.queryAllByRole('link')).toHaveLength(0);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(document.querySelectorAll('img, svg')).toHaveLength(0);
  });
});
