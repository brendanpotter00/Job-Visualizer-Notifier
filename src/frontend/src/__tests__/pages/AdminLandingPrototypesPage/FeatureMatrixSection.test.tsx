import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ROUTES } from '../../../config/routes';
import { LANDING_CONTENT } from '../../../pages/AdminLandingPrototypesPage/content';
import { FeatureMatrixSection } from '../../../pages/AdminLandingPrototypesPage/sections/FeatureMatrixSection';

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

  it('renders every feature name and detail, in content order', () => {
    renderSection();
    for (const feature of LANDING_CONTENT.featureMatrix.features) {
      expect(screen.getByRole('heading', { name: feature.name, level: 3 })).toBeInTheDocument();
      expect(screen.getByText(feature.detail)).toBeInTheDocument();
    }
    const rendered = screen
      .getAllByRole('heading', { level: 3 })
      .map((el) => el.textContent?.trim());
    expect(rendered).toEqual(LANDING_CONTENT.featureMatrix.features.map((f) => f.name));
  });

  it('gives every cell a decorative monochrome icon', () => {
    renderSection();
    const icons = document.querySelectorAll('svg[data-testid$="OutlinedIcon"]');
    expect(icons).toHaveLength(LANDING_CONTENT.featureMatrix.features.length);
    for (const icon of icons) {
      // Decorative: the adjacent name carries the meaning, so the icon must not
      // be announced.
      expect(icon.getAttribute('aria-hidden')).toBe('true');
    }
  });

  // The matrix ships LIVE features only — a "Soon" tier was deliberately
  // dropped so nothing unshipped can read as present-tense (business-context).
  it('advertises no unshipped features', () => {
    renderSection();
    expect(screen.queryByText(/soon/i)).toBeNull();
    expect(screen.queryByText(/coming soon|alerts|notification|saved jobs/i)).toBeNull();
  });

  it('closes with the single community-vote link', () => {
    renderSection();
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveTextContent(LANDING_CONTENT.featureMatrix.nextUp.label);
    expect(links[0]).toHaveAttribute('href', ROUTES.VOTE_FEATURES);
  });
});
