import { describe, expect, it } from 'vitest';
import { classifyCompanyInput } from '../../../features/userCompanies/companyInput';

/**
 * URL-first is the product rule, so these tests are mostly about what must NOT
 * become a name: a name costs a paid search call and produces a guess, while a
 * URL is exact and free.
 */
describe('classifyCompanyInput', () => {
  it('treats a full https URL as a URL, unchanged', () => {
    expect(classifyCompanyInput('https://careers.cisco.com/global/en/home')).toEqual({
      kind: 'url',
      url: 'https://careers.cisco.com/global/en/home',
    });
  });

  it('treats http as a URL and leaves the scheme alone for the guard to refuse', () => {
    expect(classifyCompanyInput('http://example.com/jobs')).toEqual({
      kind: 'url',
      url: 'http://example.com/jobs',
    });
  });

  it('gives a bare domain the https it is missing', () => {
    // The shipped guard rejects `cisco.com` with "only https is accepted", which
    // reads like the company is unsupported. This is that papercut.
    expect(classifyCompanyInput('cisco.com')).toEqual({
      kind: 'url',
      url: 'https://cisco.com',
    });
  });

  it('accepts a bare host with a path', () => {
    expect(classifyCompanyInput('careers.cisco.com/global/en')).toEqual({
      kind: 'url',
      url: 'https://careers.cisco.com/global/en',
    });
  });

  it('trims surrounding whitespace', () => {
    expect(classifyCompanyInput('   cisco.com  ')).toEqual({
      kind: 'url',
      url: 'https://cisco.com',
    });
  });

  it.each(['Cisco', 'Jane Street', 'Hudson River Trading', 'Y Combinator'])(
    'treats %s as a name',
    (typed) => {
      expect(classifyCompanyInput(typed)).toEqual({ kind: 'name', name: typed });
    }
  );

  it('keeps a multi-word name with a dot in it a NAME, not a host', () => {
    // A host cannot contain a space, so the space decides before the dot does.
    expect(classifyCompanyInput('Acme Corp. Ltd')).toEqual({
      kind: 'name',
      name: 'Acme Corp. Ltd',
    });
  });

  it('does not spend a search call on a non-http scheme', () => {
    // Classified as a URL so the server's SSRF guard refuses it with a reason
    // code. Calling it a name would pay a third-party search for `javascript:`.
    expect(classifyCompanyInput('javascript:alert(1)').kind).toBe('url');
    expect(classifyCompanyInput('ftp://files.example.com').kind).toBe('url');
  });

  it.each(['10.0.0.1', '169.254.169.254', '[::1]'])(
    'sends the IP literal %s to the URL path so the SSRF guard refuses it',
    (literal) => {
      // NOT a name. Calling it one would spend a paid search call on an address
      // AND skip the guard that exists to refuse exactly this input.
      expect(classifyCompanyInput(literal)).toEqual({
        kind: 'url',
        url: `https://${literal}`,
      });
    }
  );
});
