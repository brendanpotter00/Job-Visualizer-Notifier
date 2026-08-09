import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { SignalPrototype } from '../../../pages/AdminLandingPrototypesPage/prototypes/SignalPrototype/SignalPrototype';
import { LANDING_CONTENT } from '../../../pages/AdminLandingPrototypesPage/content';
import { buildMockJobs, MOCK_STATS } from '../../../pages/AdminLandingPrototypesPage/mockData';

const NOW = new Date('2026-08-09T18:00:00Z').getTime();

function renderSignal() {
  return renderWithProviders(
    <SignalPrototype
      content={LANDING_CONTENT}
      jobs={buildMockJobs(NOW)}
      stats={MOCK_STATS}
      sparse={false}
      now={NOW}
    />,
    { initialEntries: ['/admin/landing-prototypes'] }
  );
}

describe('SignalPrototype', () => {
  it('renders the source-led hero as the single h1 with the primary CTA', () => {
    renderSignal();
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveTextContent(LANDING_CONTENT.heroVariants.source.headline);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(
      screen.getAllByRole('link', { name: LANDING_CONTENT.ctas.primary.label }).length
    ).toBeGreaterThan(0);
  });

  it('renders the claims trio, quotable block, FAQ, and closing tagline as DOM text', () => {
    renderSignal();
    expect(screen.getByText(LANDING_CONTENT.claims.straight_from_source.heading)).toBeInTheDocument();
    expect(screen.getByText(LANDING_CONTENT.claims.no_reposts.heading)).toBeInTheDocument();
    for (const claim of LANDING_CONTENT.quotableClaims) {
      expect(screen.getByText(claim)).toBeInTheDocument();
    }
    expect(screen.getByText(LANDING_CONTENT.faq[0].question)).toBeInTheDocument();
    // The tagline closes the page twice by design: the closing-proof section
    // and the footer (brief §11 — proof ends the page).
    expect(screen.getAllByText(LANDING_CONTENT.footer.tagline).length).toBeGreaterThanOrEqual(1);
  });

  it('shows the event-shaped activity stats and the fresh-jobs rail', () => {
    renderSignal();
    expect(screen.getByText(/tracked in the past 24 hours/)).toBeInTheDocument();
    expect(screen.getByText('Posted in the last 48 hours')).toBeInTheDocument();
  });
});
