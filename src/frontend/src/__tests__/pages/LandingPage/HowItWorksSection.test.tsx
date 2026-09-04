import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import { HowItWorksSection } from '../../../pages/LandingPage/sections/HowItWorksSection';

function renderSection() {
  return render(<HowItWorksSection content={LANDING_CONTENT} />);
}

describe('HowItWorksSection', () => {
  it('renders the section heading from content.ts', () => {
    renderSection();
    expect(
      screen.getByRole('heading', { name: LANDING_CONTENT.howItWorks.heading, level: 2 })
    ).toBeInTheDocument();
  });

  it('renders every step label and line, in content order', () => {
    renderSection();
    for (const step of LANDING_CONTENT.howItWorks.steps) {
      expect(screen.getByRole('heading', { name: step.label, level: 3 })).toBeInTheDocument();
      expect(screen.getByText(step.line)).toBeInTheDocument();
    }
    const rendered = screen
      .getAllByRole('heading', { level: 3 })
      .map((el) => el.textContent?.trim());
    expect(rendered).toEqual(LANDING_CONTENT.howItWorks.steps.map((s) => s.label));
  });

  it('numbers the steps by position (01, 02, 03…)', () => {
    renderSection();
    LANDING_CONTENT.howItWorks.steps.forEach((_step, index) => {
      expect(screen.getByText(String(index + 1).padStart(2, '0'))).toBeInTheDocument();
    });
  });

  it('renders the apply-early beat verbatim from the claims inventory', () => {
    renderSection();
    expect(screen.getByText(LANDING_CONTENT.claims.apply_early_rolling.body)).toBeInTheDocument();
  });

  // The section exists to be the page's still stretch — it must not smuggle in
  // links, buttons, or images alongside the noisy sections around it.
  it('is text only: no links, buttons, or images', () => {
    renderSection();
    expect(screen.queryAllByRole('link')).toHaveLength(0);
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(document.querySelectorAll('img')).toHaveLength(0);
  });
});
