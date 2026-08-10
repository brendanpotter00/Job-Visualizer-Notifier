import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ROUTES } from '../../../config/routes';
import { COMPANY_CATEGORIES } from '../../../pages/AdminLandingPrototypesPage/companyCategories';
import { CompanyCategoriesSection } from '../../../pages/AdminLandingPrototypesPage/sections/CompanyCategoriesSection';

/** Mirrors `VISIBLE_LOGOS` in the section — the head slice shown per card. */
const VISIBLE_LOGOS = 6;

function renderSection() {
  return render(
    <MemoryRouter>
      <CompanyCategoriesSection />
    </MemoryRouter>
  );
}

describe('CompanyCategoriesSection', () => {
  it('renders the section heading', () => {
    renderSection();
    expect(
      screen.getByRole('heading', { name: 'Browse curated companies', level: 2 })
    ).toBeInTheDocument();
  });

  it('renders every category label and blurb', () => {
    renderSection();
    for (const category of COMPANY_CATEGORIES) {
      expect(screen.getByRole('heading', { name: category.label, level: 3 })).toBeInTheDocument();
      expect(screen.getByText(category.blurb)).toBeInTheDocument();
    }
  });

  it('shows a member count matching the data for each category', () => {
    renderSection();
    for (const category of COMPANY_CATEGORIES) {
      const card = screen.getByRole('link', {
        name: `${category.label}, ${category.companyIds.length} companies`,
      });
      expect(within(card).getByText(`${category.companyIds.length} companies`)).toBeInTheDocument();
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
      const card = screen.getByRole('link', {
        name: `${category.label}, ${category.companyIds.length} companies`,
      });
      const overflow = category.companyIds.length - VISIBLE_LOGOS;
      if (overflow > 0) {
        expect(within(card).getByText(`+${overflow}`)).toBeInTheDocument();
      } else {
        expect(within(card).queryByText(/^\+\d+$/)).toBeNull();
      }
    }
  });
});
