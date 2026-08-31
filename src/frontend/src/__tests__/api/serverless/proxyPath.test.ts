import { describe, it, expect } from 'vitest';
import { canonicalizeProxyPath, resolveProxyPath } from '../../../../../../api/utils/proxyPath';

/**
 * Unit tests for the shared canonicalizer + route matcher.
 *
 * These exist because the per-proxy guards cannot see the whole mechanism.
 * Mutation testing proved it: removing the `..` check, removing the
 * structural-hazard gate, and allowing a mid-pattern `*` all SURVIVED the
 * handler-level suites — the real allowlists are narrow enough that a mangled
 * path missed them anyway and still 404'd.
 *
 * That is a coincidence of today's route tables, not a property of the code.
 * The one allowlist entry that spans segments — admin's
 * `locations/aliases/*`, matching the backend's `{raw_text:path}` converter —
 * turns every one of those mutants into a live traversal, because the wildcard
 * will happily eat `../../../internal/enrichment/pending`. The handler-level
 * suites now cover that case too (see `admin.serverless.test.ts`); these tests
 * pin the mechanism directly so the next wildcard entry inherits the guarantee
 * instead of re-discovering it.
 */
describe('canonicalizeProxyPath', () => {
  it('joins the array form and drops empty segments', () => {
    expect(canonicalizeProxyPath(['a', '', 'b'])).toEqual(['a', 'b']);
    expect(canonicalizeProxyPath('/a//b/')).toEqual(['a', 'b']);
    expect(canonicalizeProxyPath(undefined)).toEqual([]);
    expect(canonicalizeProxyPath('')).toEqual([]);
  });

  it('percent-decodes once, so the comparison sees what the backend will', () => {
    // Uvicorn decodes scope["path"] before Starlette routes, and WHATWG URL
    // decodes %2e before collapsing dot segments.
    expect(canonicalizeProxyPath('a%2Fb')).toEqual(['a', 'b']);
    expect(canonicalizeProxyPath('%2e%2e/x')).toBeNull();
    expect(canonicalizeProxyPath('%2E%2E/x')).toBeNull();
  });

  it('rejects dot segments anywhere in the path, not only at the front', () => {
    // The "not only at the front" half is what the admin wildcard depends on.
    expect(canonicalizeProxyPath('..')).toBeNull();
    expect(canonicalizeProxyPath('../x')).toBeNull();
    expect(canonicalizeProxyPath('./x')).toBeNull();
    expect(canonicalizeProxyPath('locations/aliases/../../../internal/x')).toBeNull();
    expect(canonicalizeProxyPath('a/./b')).toBeNull();
    // ...but a dot INSIDE a segment is ordinary text and must survive.
    expect(canonicalizeProxyPath('a.b/..c/d..')).toEqual(['a.b', '..c', 'd..']);
  });

  it('rejects every character that can restructure the upstream URL', () => {
    // Each verified against Node's WHATWG URL; see api/utils/proxyPath.ts.
    expect(canonicalizeProxyPath('a\\b')).toBeNull(); // backslash IS a separator
    expect(canonicalizeProxyPath('a?b')).toBeNull(); // query injection
    expect(canonicalizeProxyPath('a#b')).toBeNull(); // fragment truncation
    expect(canonicalizeProxyPath('a\tb')).toBeNull(); // stripped by the parser
    expect(canonicalizeProxyPath('a\nb')).toBeNull();
    expect(canonicalizeProxyPath('a\rb')).toBeNull();
    expect(canonicalizeProxyPath('a%00b')).toBeNull(); // NUL truncation
    expect(canonicalizeProxyPath('a%7Fb')).toBeNull(); // DEL
  });

  it('rejects malformed percent-encoding instead of falling back to the raw string', () => {
    // The fallback is tempting and wrong: it hands the un-decoded string to
    // `fetch`, which does its own decoding of %2e — so the escape survives.
    expect(canonicalizeProxyPath('%')).toBeNull();
    expect(canonicalizeProxyPath('%zz')).toBeNull();
    expect(canonicalizeProxyPath('a/%e0%a4%a')).toBeNull();
  });
});

describe('resolveProxyPath', () => {
  const ROUTES = ['', 'visit', 'companies/:id/jobs', 'aliases/*'];

  it('returns the canonical path for an allowlisted route', () => {
    expect(resolveProxyPath(undefined, ROUTES)).toBe('');
    expect(resolveProxyPath('visit', ROUTES)).toBe('visit');
    expect(resolveProxyPath('/visit/', ROUTES)).toBe('visit');
    expect(resolveProxyPath(['companies', 'u-1', 'jobs'], ROUTES)).toBe('companies/u-1/jobs');
  });

  it('requires an exact segment count — a pattern is not a prefix', () => {
    // Without this, `companies/:id/jobs` would also match
    // `companies/x/jobs/../../../internal/enrichment/pending`.
    expect(resolveProxyPath('visit/extra', ROUTES)).toBeNull();
    expect(resolveProxyPath('companies/u-1/jobs/extra', ROUTES)).toBeNull();
    expect(resolveProxyPath('companies/u-1', ROUTES)).toBeNull();
  });

  it('matches literal segments literally', () => {
    expect(resolveProxyPath('visitor', ROUTES)).toBeNull();
    expect(resolveProxyPath('Visit', ROUTES)).toBeNull(); // case-sensitive, like FastAPI
    expect(resolveProxyPath('companies/u-1/JOBS', ROUTES)).toBeNull();
  });

  it('lets `*` span segments, but only as the final element', () => {
    expect(resolveProxyPath('aliases/emea / remote', ROUTES)).toBe('aliases/emea / remote');
    expect(resolveProxyPath('aliases/a/b/c', ROUTES)).toBe('aliases/a/b/c');
    // ONE or more, never zero: the bare collection route is a separate entry.
    expect(resolveProxyPath('aliases', ROUTES)).toBeNull();
    // A mid-pattern `*` is a typo. Treating it as a literal would silently
    // accept `a/*/b` as a real path; treating it as a wildcard would let it
    // swallow arbitrary segments in the middle of an otherwise-fixed route.
    expect(resolveProxyPath('a/x/y/b', ['a/*/b'])).toBeNull();
    expect(resolveProxyPath('a/x/b', ['a/*/b'])).toBeNull();
  });

  it('a wildcard cannot be used to climb out of its own subtree', () => {
    // The exact hazard the wildcard introduces: `*` eats anything, so the
    // dot-segment rejection in the canonicalizer is the ONLY thing standing
    // between `aliases/*` and `/api/internal/*`.
    expect(resolveProxyPath('aliases/../../../internal/enrichment/pending', ROUTES)).toBeNull();
    expect(resolveProxyPath('aliases/%2e%2e/%2e%2e/internal/x', ROUTES)).toBeNull();
    expect(resolveProxyPath('aliases/..\\..\\internal\\x', ROUTES)).toBeNull();
    expect(resolveProxyPath('aliases/x?limit=99999', ROUTES)).toBeNull();
  });

  it('an empty route list refuses everything', () => {
    expect(resolveProxyPath('', [])).toBeNull();
    expect(resolveProxyPath('anything', [])).toBeNull();
  });
});
