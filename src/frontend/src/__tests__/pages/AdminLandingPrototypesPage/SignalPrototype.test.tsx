import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { SignalPrototype } from '../../../pages/AdminLandingPrototypesPage/prototypes/SignalPrototype/SignalPrototype';
import { LANDING_CONTENT, TOP_COMPANY_IDS } from '../../../pages/AdminLandingPrototypesPage/content';
import { selectTickerJobs } from '../../../pages/AdminLandingPrototypesPage/sections/tickerJobs';
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

/** The secondary CTA rendered as a button (the footer link shares its label). */
function secondaryCtaButtons() {
  return screen
    .getAllByRole('link', { name: LANDING_CONTENT.ctas.secondary.label })
    .filter((el) => el.classList.contains('MuiButton-root'));
}

describe('SignalPrototype', () => {
  it('opens with the shared landing header above the hero', () => {
    renderSignal();
    const bar = screen.getByTestId('landing-header');
    expect(
      within(bar).getByRole('link', { name: LANDING_CONTENT.header.wordmark.label })
    ).toHaveAttribute('href', LANDING_CONTENT.header.wordmark.to);
    expect(
      within(bar).getByRole('link', { name: LANDING_CONTENT.header.signUp.label })
    ).toHaveClass('MuiButton-contained');
    // Chrome first: the bar must precede the h1 it sits above.
    expect(
      bar.compareDocumentPosition(screen.getByRole('heading', { level: 1 })) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

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

  it('offers "Create free account" as the outlined companion to the hero CTA', () => {
    renderSignal();
    // Hero + closing block. The footer carries a plain text link with the same
    // label, so filter to actual buttons.
    const secondaries = secondaryCtaButtons();
    expect(secondaries.length).toBeGreaterThanOrEqual(2);
    for (const link of secondaries) {
      expect(link).toHaveClass('MuiButton-outlined');
      expect(link).toHaveAttribute('href', LANDING_CONTENT.ctas.secondary.to);
    }
  });

  it('replaces the stats + pill rail with one rotating full job card', () => {
    renderSignal();
    const { items } = selectTickerJobs(buildMockJobs(NOW), TOP_COMPANY_IDS, NOW, 6);
    const card = screen.getByTestId('rotating-job-card');
    expect(screen.getByText('Posted in the last 48 hours')).toBeInTheDocument();
    expect(card).toHaveAttribute('data-active-job-id', items[0].id);
    // By ROLE, not by text: the card sits on a stack of hidden height sizers
    // holding the rest of the pool, and those are aria-hidden — so a role query
    // sees only the job actually on screen. See FlippingCard's SizerStack.
    expect(within(card).getByRole('heading', { name: items[0].title })).toBeInTheDocument();
    // The deleted stats strip must not come back with it.
    expect(screen.queryByText(/tracked in the past 24 hours/)).not.toBeInTheDocument();
    expect(screen.queryByText(/median from company post to on-site/)).not.toBeInTheDocument();
  });
});
