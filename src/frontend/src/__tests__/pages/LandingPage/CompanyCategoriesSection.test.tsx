import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ROUTES } from '../../../config/routes';
import { COMPANY_CATEGORIES } from '../../../pages/LandingPage/companyCategories';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import { CompanyCategoriesSection } from '../../../pages/LandingPage/sections/CompanyCategoriesSection';

/** Mirrors `VISIBLE_LOGOS` in the section — the head slice shown per card. */
const VISIBLE_LOGOS = 6;

function renderSection() {
  return render(
    <MemoryRouter>
      <CompanyCategoriesSection content={LANDING_CONTENT} />
    </MemoryRouter>
  );
}

describe('CompanyCategoriesSection', () => {
  it('renders the section heading', () => {
    renderSection();
    expect(
      screen.getByRole('heading', { name: 'Curated Companies', level: 2 })
    ).toBeInTheDocument();
  });

  it('renders every category label', () => {
    renderSection();
    for (const category of COMPANY_CATEGORIES) {
      expect(screen.getByRole('heading', { name: category.label, level: 3 })).toBeInTheDocument();
    }
  });

  it('shows no member count and no description on the cards', () => {
    renderSection();
    expect(screen.queryByText(/\d+ companies/)).not.toBeInTheDocument();
    for (const category of COMPANY_CATEGORIES) {
      const card = screen.getByRole('link', { name: category.label });
      expect(card.querySelectorAll('p')).toHaveLength(0);
    }
  });

  it('renders one link per category, each pointing at the jobs board', () => {
    renderSection();
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(COMPANY_CATEGORIES.length);
    for (const link of links) {
      expect(link).toHaveAttribute('href', ROUTES.RECENT_JOBS);
    }
  });

  it('renders up to six member logos per card, each with alt text', () => {
    renderSection();
    const expectedLogos = COMPANY_CATEGORIES.reduce(
      (total, category) => total + Math.min(VISIBLE_LOGOS, category.companyIds.length),
      0
    );
    const imgs = Array.from(document.querySelectorAll('img'));
    expect(imgs).toHaveLength(expectedLogos);
    for (const img of imgs) {
      expect(img.getAttribute('alt')?.trim()).toBeTruthy();
    }
  });

  it('collapses the remaining members into a "+N" indicator', () => {
    renderSection();
    for (const category of COMPANY_CATEGORIES) {
      const card = screen.getByRole('link', { name: category.label });
      const overflow = category.companyIds.length - VISIBLE_LOGOS;
      if (overflow > 0) {
        expect(within(card).getByText(`+${overflow}`)).toBeInTheDocument();
      } else {
        expect(within(card).queryByText(/^\+\d+$/)).toBeNull();
      }
    }
  });
});
