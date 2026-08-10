import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FAQSection } from '../../../pages/AdminLandingPrototypesPage/sections/FAQSection';
import { LANDING_CONTENT } from '../../../pages/AdminLandingPrototypesPage/content';

describe('FAQSection', () => {
  it('renders the heading and every question as a collapsed accordion', () => {
    render(<FAQSection content={LANDING_CONTENT} />);

    expect(screen.getByRole('heading', { name: 'Frequently asked questions' })).toBeInTheDocument();

    const toggles = screen.getAllByRole('button');
    expect(toggles).toHaveLength(LANDING_CONTENT.faq.length);
    for (const entry of LANDING_CONTENT.faq) {
      expect(screen.getByRole('button', { name: entry.question })).toHaveAttribute(
        'aria-expanded',
        'false'
      );
    }
  });

  // The AEO invariant: answer engines and crawlers that never execute JS must
  // still read the answers. MUI's Collapse keeps children mounted, so collapsing
  // hides the text visually without removing it from the document. A regression
  // here (unmountOnExit / keepMounted={false} on the transition slot) fails this.
  it('keeps every answer in the DOM while its accordion is collapsed', () => {
    render(<FAQSection content={LANDING_CONTENT} />);

    for (const entry of LANDING_CONTENT.faq) {
      expect(screen.getByRole('button', { name: entry.question })).toHaveAttribute(
        'aria-expanded',
        'false'
      );
      expect(screen.getByText(entry.answer)).toBeInTheDocument();
    }
  });

  it('expands only the clicked question', async () => {
    const user = userEvent.setup();
    render(<FAQSection content={LANDING_CONTENT} />);

    const [first, second] = LANDING_CONTENT.faq;
    await user.click(screen.getByRole('button', { name: first.question }));

    expect(screen.getByRole('button', { name: first.question })).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    expect(screen.getByRole('button', { name: second.question })).toHaveAttribute(
      'aria-expanded',
      'false'
    );
    // Still in the DOM either way — expanding only changes visibility.
    expect(screen.getByText(second.answer)).toBeInTheDocument();
  });
});
