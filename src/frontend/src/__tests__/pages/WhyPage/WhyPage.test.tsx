import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { WhyPage } from '../../../pages/WhyPage/WhyPage';
import { COMPANIES, COMING_SOON_SCRAPERS } from '../../../config/companies';
import type { Company } from '../../../types';

const escapeRegex = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Group companies by ATS key — mirrors `companiesByATS` useMemo in WhyPage.tsx. */
function groupCompaniesByATS(): Record<string, Company[]> {
  const grouped: Record<string, Company[]> = {};
  for (const company of COMPANIES) {
    if (!grouped[company.ats]) {
      grouped[company.ats] = [];
    }
    grouped[company.ats].push(company);
  }
  return grouped;
}

describe('WhyPage', () => {
  it('renders the "Why This Was Built" h1 heading', () => {
    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    expect(
      screen.getByRole('heading', { name: /Why This Was Built/i, level: 1 })
    ).toBeInTheDocument();
  });

  it('renders the correct total company count and ATS platform count in the Supported Companies caption', () => {
    const grouped = groupCompaniesByATS();
    const expectedCompanyCount = COMPANIES.length;
    const expectedPlatformCount = Object.entries(grouped).reduce(
      (total, [ats, cos]) => total + (ats === 'backend-scraper' ? cos.length : 1),
      0
    );

    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    expect(
      screen.getByText(
        new RegExp(
          `We currently track ${expectedCompanyCount} companies across ${expectedPlatformCount} different ATS platforms`
        )
      )
    ).toBeInTheDocument();
  });

  it('renders one ATS group header per distinct non-empty ATS in COMPANIES', () => {
    const grouped = groupCompaniesByATS();

    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    for (const ats of Object.keys(grouped)) {
      const displayName = ats === 'backend-scraper' ? 'Custom Web Scrapers' : ats;
      expect(
        screen.getByRole('heading', {
          level: 3,
          name: new RegExp(escapeRegex(displayName), 'i'),
        })
      ).toBeInTheDocument();
    }
  });

  it('renders coming-soon scrapers inside the Custom Web Scrapers group marked as (Coming Soon)', () => {
    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    if (COMING_SOON_SCRAPERS.length === 0) {
      // Current state — no coming-soon scrapers are configured, so the marker text should not appear.
      expect(screen.queryByText(/\(Coming Soon\)/i)).not.toBeInTheDocument();
    } else {
      // Future state — assert each name renders and the "(Coming Soon)" marker appears.
      for (const scraper of COMING_SOON_SCRAPERS) {
        expect(screen.getByText(scraper.name)).toBeInTheDocument();
      }
      expect(screen.getAllByText(/\(Coming Soon\)/i).length).toBeGreaterThan(0);
    }
  });

  it('renders each ATS group header with the correct company count in parentheses', () => {
    const grouped = groupCompaniesByATS();

    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    for (const [ats, companies] of Object.entries(grouped)) {
      const displayName = ats === 'backend-scraper' ? 'Custom Web Scrapers' : ats;
      expect(
        screen.getByRole('heading', {
          level: 3,
          name: new RegExp(`${escapeRegex(displayName)}\\s*\\(${companies.length}\\)`, 'i'),
        })
      ).toBeInTheDocument();
    }
  });

  it('renders all company job-board links with target="_blank" and rel="noopener noreferrer"', () => {
    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    // Snapshot all anchors once — iterating per-company with getAllByRole is O(n*n)
    // and blows past the default 5s testTimeout under v8 coverage instrumentation.
    const allLinks = screen.getAllByRole('link');
    const linksByHref = new Map<string, HTMLElement>();
    for (const link of allLinks) {
      const href = link.getAttribute('href');
      if (href && !linksByHref.has(href)) {
        linksByHref.set(href, link);
      }
    }

    for (const company of COMPANIES) {
      const link = linksByHref.get(company.jobsUrl);
      expect(link, `expected a link to ${company.jobsUrl} for ${company.name}`).toBeDefined();
      expect(link).toHaveTextContent(company.name);
      expect(link).toHaveAttribute('target', '_blank');
      expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    }

    const authorLink = screen.getByRole('link', { name: /Reach out to Brendan Potter/i });
    expect(authorLink).toHaveAttribute('target', '_blank');
    expect(authorLink).toHaveAttribute('rel', 'noopener noreferrer');
  });
});
