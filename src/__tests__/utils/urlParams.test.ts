import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getCompanyFromURL,
  updateURLWithCompany,
  getInitialCompanyId,
  COMPANY_PARAM,
  DEFAULT_COMPANY_ID,
} from '../../utils/urlParams';

describe('urlParams', () => {
  beforeEach(() => {
    // Reset window.location before each test
    const url = 'http://localhost:5173/';
    Object.defineProperty(window, 'location', {
      value: new URL(url),
      writable: true,
      configurable: true,
    });

    // Mock history.pushState
    vi.spyOn(window.history, 'pushState').mockImplementation(() => {});
  });

  describe('getCompanyFromURL', () => {
    it('should return undefined when no company parameter exists', () => {
      expect(getCompanyFromURL()).toBeUndefined();
    });

    it('should return valid company ID from URL', () => {
      window.location.search = '?company=spacex';
      expect(getCompanyFromURL()).toBe('spacex');
    });

    it('should return valid company ID with multiple parameters', () => {
      window.location.search = '?foo=bar&company=anthropic&baz=qux';
      expect(getCompanyFromURL()).toBe('anthropic');
    });

    it('should return undefined for invalid company ID', () => {
      window.location.search = '?company=invalid-company-id';
      expect(getCompanyFromURL()).toBeUndefined();
    });

    it('should validate against all configured companies', () => {
      // Test a few different valid companies
      const validCompanies = ['spacex', 'anthropic', 'notion', 'stripe', 'palantir'];

      validCompanies.forEach((companyId) => {
        window.location.search = `?company=${companyId}`;
        expect(getCompanyFromURL()).toBe(companyId);
      });
    });

    it('should return undefined for empty company parameter', () => {
      window.location.search = '?company=';
      expect(getCompanyFromURL()).toBeUndefined();
    });

    it('should handle URL-encoded company IDs', () => {
      window.location.search = '?company=spacex';
      expect(getCompanyFromURL()).toBe('spacex');
    });
  });

  describe('updateURLWithCompany', () => {
    it('should add company parameter to URL', () => {
      vi.clearAllMocks();
      updateURLWithCompany('anthropic');

      expect(window.history.pushState).toHaveBeenCalledWith(
        {},
        '',
        expect.stringContaining('company=anthropic')
      );
    });

    it('should replace existing company parameter', () => {
      vi.clearAllMocks();
      window.location.search = '?company=spacex';
      updateURLWithCompany('notion');

      expect(window.history.pushState).toHaveBeenCalledWith(
        {},
        '',
        expect.stringContaining('company=notion')
      );
      const call = vi.mocked(window.history.pushState).mock.calls[0];
      const url = call[2] as string;
      expect(url).not.toContain('company=spacex');
    });

    it('should preserve other URL parameters', () => {
      vi.clearAllMocks();
      // Reset location with new params
      Object.defineProperty(window, 'location', {
        value: new URL('http://localhost:5173/?foo=bar&baz=qux'),
        writable: true,
        configurable: true,
      });

      updateURLWithCompany('stripe');

      const call = vi.mocked(window.history.pushState).mock.calls[0];
      const url = call[2] as string;

      expect(url).toContain('company=stripe');
      expect(url).toContain('foo=bar');
      expect(url).toContain('baz=qux');
    });

    it('should use pushState to create history entry', () => {
      vi.clearAllMocks();
      updateURLWithCompany('spacex');

      expect(window.history.pushState).toHaveBeenCalledTimes(1);
      expect(window.history.pushState).toHaveBeenCalledWith({}, '', expect.any(String));
    });

    it('should maintain the current pathname and origin', () => {
      vi.clearAllMocks();
      Object.defineProperty(window, 'location', {
        value: new URL('http://localhost:5173/some/path'),
        writable: true,
        configurable: true,
      });

      updateURLWithCompany('palantir');

      const call = vi.mocked(window.history.pushState).mock.calls[0];
      const url = call[2] as string;

      expect(url).toContain('/some/path');
      expect(url).toContain('company=palantir');
    });
  });

  describe('getInitialCompanyId', () => {
    it('should return default company ID when no URL parameter', () => {
      expect(getInitialCompanyId()).toBe(DEFAULT_COMPANY_ID);
    });

    it('should return company ID from URL if valid', () => {
      window.location.search = '?company=anthropic';
      expect(getInitialCompanyId()).toBe('anthropic');
    });

    it('should return default company ID for invalid URL parameter', () => {
      window.location.search = '?company=invalid-company';
      expect(getInitialCompanyId()).toBe(DEFAULT_COMPANY_ID);
    });

    it('should prioritize URL parameter over default', () => {
      window.location.search = '?company=notion';
      expect(getInitialCompanyId()).not.toBe(DEFAULT_COMPANY_ID);
      expect(getInitialCompanyId()).toBe('notion');
    });
  });

  describe('constants', () => {
    it('should have correct COMPANY_PARAM value', () => {
      expect(COMPANY_PARAM).toBe('company');
    });

    it('should have correct DEFAULT_COMPANY_ID value', () => {
      expect(DEFAULT_COMPANY_ID).toBe('spacex');
    });
  });
});
