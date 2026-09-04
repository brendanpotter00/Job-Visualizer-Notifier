import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ROUTES } from '../../../config/routes';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import { FeatureMatrixSection } from '../../../pages/LandingPage/sections/FeatureMatrixSection';

function renderSection() {
  return render(
    <MemoryRouter>
      <FeatureMatrixSection content={LANDING_CONTENT} />
    </MemoryRouter>
  );
}

describe('FeatureMatrixSection', () => {
  it('renders the section heading from content.ts', () => {
    renderSection();
    expect(
      screen.getByRole('heading', { name: LANDING_CONTENT.featureMatrix.heading, level: 2 })
    ).toBeInTheDocument();
  });

  it('renders every live feature name and detail, in content order', () => {
    renderSection();
    const live = within(screen.getByTestId('feature-matrix-live'));
    for (const feature of LANDING_CONTENT.featureMatrix.features) {
      expect(live.getByRole('heading', { name: feature.name, level: 3 })).toBeInTheDocument();
      expect(live.getByText(feature.detail)).toBeInTheDocument();
    }
    const rendered = live.getAllByRole('heading', { level: 3 }).map((el) => el.textContent?.trim());
    expect(rendered).toEqual(LANDING_CONTENT.featureMatrix.features.map((f) => f.name));
  });

  it('gives every cell in both tiers a decorative monochrome icon', () => {
    renderSection();
    const icons = document.querySelectorAll('svg[data-testid$="OutlinedIcon"]');
    const { features, comingSoon } = LANDING_CONTENT.featureMatrix;
    expect(icons).toHaveLength(features.length + comingSoon.length);
    for (const icon of icons) {
      // Decorative: the adjacent name carries the meaning, so the icon must not
      // be announced.
      expect(icon.getAttribute('aria-hidden')).toBe('true');
    }
  });

  // Unshipped work may appear ONLY inside the labeled, grayed tier (owner
  // decision 2026-08-20, docs/marketing/business-context.md). The live cells
  // stay a present-tense-only zone, so this asserts the boundary from both
  // sides: nothing roadmap-flavoured above it, the full roadmap below it.
  it('keeps every unshipped promise out of the live cells', () => {
    renderSection();
    const live = within(screen.getByTestId('feature-matrix-live'));
    expect(live.queryByText(/soon|coming|notification|alert|scraper|mcp/i)).toBeNull();
    for (const feature of LANDING_CONTENT.featureMatrix.comingSoon) {
      expect(live.queryByText(feature.name)).toBeNull();
      expect(live.queryByText(feature.detail)).toBeNull();
    }
  });

  // The graduation, asserted from the side that can regress: a shipped feature
  // sitting in the grayed tier would under-sell it, but a still-unshipped one
  // in the live tier is a false present-tense claim, which is the failure the
  // whole two-tier scheme exists to prevent.
  it('renders the shipped "Track any company" cell in the LIVE tier', () => {
    renderSection();
    const live = within(screen.getByTestId('feature-matrix-live'));
    const tier = within(screen.getByTestId('feature-matrix-coming-soon'));
    expect(live.getByRole('heading', { name: 'Track any company', level: 3 })).toBeInTheDocument();
    expect(tier.queryByRole('heading', { name: 'Track any company' })).toBeNull();
  });

  it('renders exactly the coming-soon cells under a labeled tier', () => {
    renderSection();
    const tier = within(screen.getByTestId('feature-matrix-coming-soon'));
    // The state is DISCLOSED, not merely implied by the gray.
    expect(tier.getByText(LANDING_CONTENT.featureMatrix.comingSoonLabel)).toBeInTheDocument();
    for (const feature of LANDING_CONTENT.featureMatrix.comingSoon) {
      expect(tier.getByRole('heading', { name: feature.name, level: 3 })).toBeInTheDocument();
      expect(tier.getByText(feature.detail)).toBeInTheDocument();
    }
    const rendered = tier.getAllByRole('heading', { level: 3 }).map((el) => el.textContent?.trim());
    expect(rendered).toEqual(LANDING_CONTENT.featureMatrix.comingSoon.map((f) => f.name));
  });

  // Gray is the whole disclosure mechanism, so it is asserted, not eyeballed:
  // every coming-soon name/detail resolves to a different colour than its live
  // counterpart. Compares against the live cells rather than a hard-coded rgba
  // so a theme palette change cannot silently un-gray the tier.
  it('renders the coming-soon tier in a visually distinct disabled colour', () => {
    renderSection();
    const live = screen.getByTestId('feature-matrix-live');
    const tier = screen.getByTestId('feature-matrix-coming-soon');
    const colourOf = (el: Element) => window.getComputedStyle(el).color;

    const liveName = within(live).getAllByRole('heading', { level: 3 })[0];
    const tierNames = within(tier).getAllByRole('heading', { level: 3 });
    expect(colourOf(liveName)).not.toBe('');
    for (const name of tierNames) {
      expect(colourOf(name)).not.toBe(colourOf(liveName));
    }

    const liveDetail = within(live).getByText(LANDING_CONTENT.featureMatrix.features[0].detail);
    for (const feature of LANDING_CONTENT.featureMatrix.comingSoon) {
      expect(colourOf(within(tier).getByText(feature.detail))).not.toBe(colourOf(liveDetail));
    }
  });

  it('closes with the single community-vote link', () => {
    renderSection();
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveTextContent(LANDING_CONTENT.featureMatrix.nextUp.label);
    expect(links[0]).toHaveAttribute('href', ROUTES.VOTE_FEATURES);
  });
});
