import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { WhyPage } from '../../../pages/WhyPage/WhyPage';
import {
  ATS_DISPLAY_NAMES,
  getATSGroupKey,
  type ATSGroupKey,
} from '../../../pages/WhyPage/atsGrouping';
import { COMPANIES, COMING_SOON_SCRAPERS } from '../../../config/companies';
import { ROUTES } from '../../../config/routes';
import { COMPANY_PARAM } from '../../../lib/url';
import type { Company } from '../../../types';

const escapeRegex = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Group companies by ATS key — mirrors `companiesByATS` useMemo in WhyPage.tsx. */
function groupCompaniesByATS(): Partial<Record<ATSGroupKey, Company[]>> {
  const grouped: Partial<Record<ATSGroupKey, Company[]>> = {};
  for (const company of COMPANIES) {
    const key = getATSGroupKey(company);
    if (!grouped[key]) {
      grouped[key] = [];
    }
    grouped[key]!.push(company);
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
      (total, [ats, cos]) => total + (ats === 'backend-scraper' ? cos!.length : 1),
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

  it('renders a dedicated Greenhouse group containing only companies whose sourceAts === "greenhouse"', () => {
    const grouped = groupCompaniesByATS();
    const greenhouseGroup = grouped.greenhouse ?? [];

    expect(greenhouseGroup.length).toBeGreaterThan(0);
    for (const company of greenhouseGroup) {
      expect(company.sourceAts).toBe('greenhouse');
    }

    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    expect(
      screen.getByRole('heading', {
        level: 3,
        name: new RegExp(`Greenhouse\\s*\\(${greenhouseGroup.length}\\)`, 'i'),
      })
    ).toBeInTheDocument();
  });

  it('Custom Web Scrapers group excludes Greenhouse boards (true custom scrapers only)', () => {
    const grouped = groupCompaniesByATS();
    const customScrapers = grouped['backend-scraper'] ?? [];

    for (const company of customScrapers) {
      expect(company.sourceAts).not.toBe('greenhouse');
    }
  });

  it('renders a dedicated Ashby group containing only companies whose sourceAts === "ashby"', () => {
    const grouped = groupCompaniesByATS();
    const ashbyGroup = grouped.ashby ?? [];

    expect(ashbyGroup.length).toBeGreaterThan(0);
    for (const company of ashbyGroup) {
      expect(company.sourceAts).toBe('ashby');
    }

    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    expect(
      screen.getByRole('heading', {
        level: 3,
        name: new RegExp(`Ashby\\s*\\(${ashbyGroup.length}\\)`, 'i'),
      })
    ).toBeInTheDocument();
  });

  it('Custom Web Scrapers group excludes Ashby companies (true custom scrapers only)', () => {
    const grouped = groupCompaniesByATS();
    const customScrapers = grouped['backend-scraper'] ?? [];

    for (const company of customScrapers) {
      expect(company.sourceAts).not.toBe('ashby');
    }
  });

  it('renders a dedicated Lever group containing only companies whose sourceAts === "lever"', () => {
    const grouped = groupCompaniesByATS();
    const leverGroup = grouped.lever ?? [];

    expect(leverGroup.length).toBeGreaterThan(0);
    for (const company of leverGroup) {
      expect(company.sourceAts).toBe('lever');
    }

    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    expect(
      screen.getByRole('heading', {
        level: 3,
        name: new RegExp(`Lever\\s*\\(${leverGroup.length}\\)`, 'i'),
      })
    ).toBeInTheDocument();
  });

  it('Custom Web Scrapers group excludes Lever companies (true custom scrapers only)', () => {
    const grouped = groupCompaniesByATS();
    const customScrapers = grouped['backend-scraper'] ?? [];

    for (const company of customScrapers) {
      expect(company.sourceAts).not.toBe('lever');
    }
  });

  it('renders a dedicated Gem group containing only companies whose sourceAts === "gem"', () => {
    const grouped = groupCompaniesByATS();
    const gemGroup = grouped.gem ?? [];

    expect(gemGroup.length).toBeGreaterThan(0);
    for (const company of gemGroup) {
      expect(company.sourceAts).toBe('gem');
    }

    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    expect(
      screen.getByRole('heading', {
        level: 3,
        name: new RegExp(`Gem\\s*\\(${gemGroup.length}\\)`, 'i'),
      })
    ).toBeInTheDocument();
  });

  it('Custom Web Scrapers group excludes Gem companies (true custom scrapers only)', () => {
    const grouped = groupCompaniesByATS();
    const customScrapers = grouped['backend-scraper'] ?? [];

    for (const company of customScrapers) {
      expect(company.sourceAts).not.toBe('gem');
    }
  });

  it('renders a dedicated Eightfold group containing only companies whose sourceAts === "eightfold"', () => {
    const grouped = groupCompaniesByATS();
    const eightfoldGroup = grouped.eightfold ?? [];

    // Eightfold has exactly one company (Netflix) today.
    expect(eightfoldGroup.length).toBeGreaterThan(0);
    for (const company of eightfoldGroup) {
      expect(company.sourceAts).toBe('eightfold');
      // Sanity-check: the row should be backend-scraper post-migration,
      // NOT the pre-migration ats='eightfold' shape.
      expect(company.ats).toBe('backend-scraper');
    }

    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    // Display name must be capitalized "Eightfold" (not lowercase, as it
    // was before Unit 8 of the Eightfold migration).
    expect(
      screen.getByRole('heading', {
        level: 3,
        name: new RegExp(`Eightfold\\s*\\(${eightfoldGroup.length}\\)`),
      })
    ).toBeInTheDocument();
  });

  it('Custom Web Scrapers group excludes Eightfold companies (true custom scrapers only)', () => {
    const grouped = groupCompaniesByATS();
    const customScrapers = grouped['backend-scraper'] ?? [];

    for (const company of customScrapers) {
      expect(company.sourceAts).not.toBe('eightfold');
    }
  });

  it('Netflix is rendered under Eightfold, not Custom Web Scrapers', () => {
    // Tightens the symmetric tests above with the specific named company —
    // catches regressions where the seed migration / companies.ts drift
    // and Netflix accidentally falls out of the Eightfold column.
    const grouped = groupCompaniesByATS();
    const eightfoldIds = (grouped.eightfold ?? []).map((c) => c.id);
    const customScraperIds = (grouped['backend-scraper'] ?? []).map((c) => c.id);

    expect(eightfoldIds).toContain('netflix');
    expect(customScraperIds).not.toContain('netflix');
  });

  it('renders a dedicated Workday group containing only companies whose sourceAts === "workday"', () => {
    const grouped = groupCompaniesByATS();
    const workdayGroup = grouped.workday ?? [];

    expect(workdayGroup.length).toBeGreaterThan(0);
    for (const company of workdayGroup) {
      expect(company.sourceAts).toBe('workday');
      // Sanity-check: the row should be backend-scraper post-migration,
      // NOT the pre-migration ats='workday' shape.
      expect(company.ats).toBe('backend-scraper');
    }

    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    expect(
      screen.getByRole('heading', {
        level: 3,
        name: new RegExp(`Workday\\s*\\(${workdayGroup.length}\\)`),
      })
    ).toBeInTheDocument();
  });

  it('Custom Web Scrapers group excludes Workday companies (true custom scrapers only)', () => {
    const grouped = groupCompaniesByATS();
    const customScrapers = grouped['backend-scraper'] ?? [];

    for (const company of customScrapers) {
      expect(company.sourceAts).not.toBe('workday');
    }
  });


  it('renders one ATS group header per distinct non-empty ATS group in COMPANIES', () => {
    const grouped = groupCompaniesByATS();

    renderWithProviders(<WhyPage />, { initialEntries: ['/why'] });

    for (const ats of Object.keys(grouped) as ATSGroupKey[]) {
      const displayName = ATS_DISPLAY_NAMES[ats];
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

    for (const [ats, companies] of Object.entries(grouped) as [ATSGroupKey, Company[]][]) {
      const displayName = ATS_DISPLAY_NAMES[ats];
      expect(
        screen.getByRole('heading', {
          level: 3,
          name: new RegExp(`${escapeRegex(displayName)}\\s*\\(${companies.length}\\)`, 'i'),
        })
      ).toBeInTheDocument();
    }
  });

  it('renders every company as an internal link to its hiring trends page (not an external new-tab link)', () => {
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
      const expectedHref = `${ROUTES.COMPANIES}?${COMPANY_PARAM}=${company.id}`;
      const link = linksByHref.get(expectedHref);
      expect(link, `expected internal link to ${expectedHref} for ${company.name}`).toBeDefined();
      expect(link).toHaveTextContent(company.name);
      // Company links navigate within the app; they should not open a new tab.
      expect(link).not.toHaveAttribute('target', '_blank');
    }

    const authorLink = screen.getByRole('link', { name: /Reach out to Brendan Potter/i });
    expect(authorLink).toHaveAttribute('target', '_blank');
    expect(authorLink).toHaveAttribute('rel', 'noopener noreferrer');
  });
});
