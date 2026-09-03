/**
 * The `?path=` attack corpus, shared by the allowlist guard in every
 * internal-key proxy test (`users`, `companies`, `feedback`, `features`,
 * `admin`, `jobs-qa`).
 *
 * Shared ON PURPOSE. These vectors are properties of the *mechanism* — Vercel's
 * query decoding, WHATWG URL parsing, Uvicorn's path decoding — not of any one
 * proxy. Keeping one list means a newly-discovered spelling is covered on all
 * six the moment it is added here, instead of on whichever file the next author
 * happened to open. Each proxy still owns its own allowlist and its own
 * legitimate-path assertions.
 *
 * Target for the traversal vectors is `/api/internal/enrichment/pending`: the
 * backend route that has NO JWT gate (only `require_internal_key`, which these
 * proxies satisfy unconditionally) and that MUTATES — it flips rows to
 * `enrichment_status='claimed'`, starving the real enricher.
 */

/** A `?path=` value as Vercel would hand it to the handler. */
export type PathValue = string | string[];

// Written as escapes, not literals: a raw TAB in source is invisible to a
// reviewer, and this file's whole subject is characters you cannot see.
const TAB = '\u0009';
const NUL = '%00';

export const TRAVERSAL_VECTORS: Array<[label: string, path: PathValue]> = [
  // The wire form of `?path=..%2Finternal%2F…`: Vercel's query parser has
  // already percent-decoded it by the time the handler runs. Verified against
  // the local Vercel dev server — this exact request returned live internal
  // enrichment data before the fix.
  ['plain dot-dot', '../internal/enrichment/pending'],
  // Defence in depth: if Vercel ever stops decoding, or the function is
  // invoked directly, the escape must still not survive.
  ['single-encoded slashes', '..%2Finternal%2Fenrichment%2Fpending'],
  ['double-encoded slashes', '..%252Finternal%252Fenrichment%252Fpending'],
  // WHATWG URL decodes %2e BEFORE collapsing dot segments, so this traverses
  // inside `fetch` itself even with no literal `..` anywhere in the string:
  // new URL('http://h/api/users/%2e%2e/internal/x').href === 'http://h/api/internal/x'
  ['percent-encoded dots', '%2e%2e/internal/enrichment/pending'],
  ['percent-encoded dots uppercase', '%2E%2E/internal/enrichment/pending'],
  // A backslash IS a path separator to WHATWG URL, so it smuggles a segment
  // boundary past any check that only splits on '/'.
  ['backslash separators', '..\\internal\\enrichment\\pending'],
  // TAB/LF/CR are STRIPPED by the URL parser, so `.<TAB>.` becomes `..` after
  // parsing while surviving an `=== '..'` comparison beforehand.
  ['tab-stuffed dot segment', `.${TAB}./internal/enrichment/pending`],
  ['newline-stuffed dot segment', '.\n./internal/enrichment/pending'],
  // NUL truncation.
  ['nul byte', `..${NUL}/internal/enrichment/pending`],
  // Vercel yields string[] when `path` repeats.
  ['array form', ['..', 'internal', 'enrichment', 'pending']],
  ['array form with empty tail', ['..', 'internal', 'enrichment', 'pending', '']],
  // Assorted spellings that defeated the earlier denylist on api/jobs-qa.ts.
  ['dot-slash prefix', './../internal/enrichment/pending'],
  ['leading slash', '/../internal/enrichment/pending'],
  ['duplicated slashes', '..//internal//enrichment//pending'],
  ['deep traversal', '../../../etc/passwd'],
  // Absolute and protocol-relative upstream URLs.
  ['absolute http URL', 'http://evil.example.com/steal'],
  ['absolute https URL', 'https://evil.example.com/steal'],
  ['protocol-relative URL', '//evil.example.com/steal'],
  ['absolute URL with credentials', 'http://user:pass@evil.example.com/steal'],
  // Cross-proxy hop: reach the un-allowlisted, JWT-less jobs-qa route.
  ['sibling proxy route', '../jobs-qa/scraper-health'],
  // Query / fragment injection into the upstream URL.
  ['query injection', 'x?limit=99999'],
  ['fragment injection', 'x#/../internal/enrichment/pending'],
  // Malformed percent-encoding must 404, not throw a 500 (a 500 both looks
  // like a reachable endpoint and is a different response than a real 404).
  ['bare percent', '%'],
  ['invalid escape', '%zz'],
];

/**
 * Paths that are structurally fine but are not routes on the proxy's backend
 * router. They must be refused with the SAME response as the traversal vectors
 * above — an allowlist that fails closed by default is the whole point, and a
 * distinguishable refusal would let a prober map the internal surface.
 */
export const UNKNOWN_BUT_HARMLESS: string[] = [
  'not-a-route',
  'internal',
  'internal/enrichment/pending',
  'deeply/nested/unknown/route',
];
