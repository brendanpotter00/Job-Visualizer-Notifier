import { describe, it, expect } from 'vitest';
import {
  getCompanySourceLabel,
  getATSGroupKey,
  ATS_DISPLAY_NAMES,
} from '../../config/atsSource';
import { COMPANIES, getCompanyById } from '../../config/companies';
import type { Company } from '../../types';

/** Build a minimal backend-scraper Company with an optional original source ATS. */
function makeCompany(sourceAts?: Company['sourceAts']): Company {
  return {
    id: 'test-co',
    name: 'Test Co',
    ats: 'backend-scraper',
    config: { type: 'backend-scraper', companyId: 'test-co', apiBaseUrl: '/api/jobs' },
    sourceAts,
  };
}

describe('getCompanySourceLabel', () => {
  it('labels each migrated ATS provider by its true source name', () => {
    expect(getCompanySourceLabel(makeCompany('greenhouse'))).toBe('Greenhouse');
    expect(getCompanySourceLabel(makeCompany('ashby'))).toBe('Ashby');
    expect(getCompanySourceLabel(makeCompany('lever'))).toBe('Lever');
    expect(getCompanySourceLabel(makeCompany('gem'))).toBe('Gem');
    expect(getCompanySourceLabel(makeCompany('eightfold'))).toBe('Eightfold');
    expect(getCompanySourceLabel(makeCompany('workday'))).toBe('Workday');
  });

  it('labels true custom scrapers (no sourceAts) "Custom Web Scraper" (singular)', () => {
    expect(getCompanySourceLabel(makeCompany(undefined))).toBe('Custom Web Scraper');
  });

  it('never surfaces the internal "backend-scraper" code or the plural Why-page label', () => {
    for (const company of COMPANIES) {
      const label = getCompanySourceLabel(company);
      expect(label).not.toMatch(/backend.?scraper/i);
      expect(label).not.toBe('Custom Web Scrapers');
    }
  });

  it('resolves real companies to their true source', () => {
    const cases: Record<string, string> = {
      spacex: 'Greenhouse',
      notion: 'Ashby',
      palantir: 'Lever',
      retool: 'Gem',
      netflix: 'Eightfold',
      nvidia: 'Workday',
      google: 'Custom Web Scraper',
      apple: 'Custom Web Scraper',
      microsoft: 'Custom Web Scraper',
    };
    for (const [id, expected] of Object.entries(cases)) {
      const company = getCompanyById(id);
      expect(company, `expected company "${id}" to exist in config`).toBeDefined();
      expect(getCompanySourceLabel(company!)).toBe(expected);
    }
  });

  it('stays in sync with the ATS_DISPLAY_NAMES map for every configured company', () => {
    for (const company of COMPANIES) {
      const key = getATSGroupKey(company);
      const expected = key === 'backend-scraper' ? 'Custom Web Scraper' : ATS_DISPLAY_NAMES[key];
      expect(getCompanySourceLabel(company)).toBe(expected);
    }
  });
});
