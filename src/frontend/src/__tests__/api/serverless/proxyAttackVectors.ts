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
  ['mixed literal + encoded dot', '.%2e/internal/enrichment/pending'],
  ['mixed encoded + literal dot', '%2E./internal/enrichment/pending'],
  // DOUBLE-encoded dots — the shape a production verifier used to get through.
  // Vercel decodes the request path ONCE before the handler runs, so a client
  // that sends `%25252e%25252e` delivers `%252e%252e` here. The canonicalizer's
  // own single decode turned that into `%2e%2e`, which is not literally `..`, so
  // it passed — and then `fetch`'s WHATWG URL parser treated `%2e%2e` AS `..`
  // and collapsed it, with the internal key attached.
  ['double-encoded dots', '%252e%252e/internal/enrichment/pending'],
  ['double-encoded dots uppercase', '%252E%252E/internal/enrichment/pending'],
  ['mixed literal + double-encoded dot', '.%252e/internal/enrichment/pending'],
  ['mixed double-encoded + literal dot', '%252E./internal/enrichment/pending'],
  ['triple-encoded dots', '%25252e%25252e/internal/enrichment/pending'],
  // A backslash IS a path separator to WHATWG URL, so it smuggles a segment
  // boundary past any check that only splits on '/'.
  ['backslash separators', '..\\internal\\enrichment\\pending'],
  ['mixed slash and backslash separators', '../..\\internal/enrichment\\pending'],
  ['encoded backslash separators', '..%5Cinternal%5Cenrichment%5Cpending'],
  ['double-encoded backslash separators', '..%255Cinternal%255Cenrichment%255Cpending'],
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
 * Every spelling of a dot segment that some layer between the client and the
 * backend can turn into `.` or `..`, written as it ARRIVES in `req.query` —
 * i.e. after Vercel's own single decode of the request path.
 *
 * WHATWG URL (what `fetch` parses with) treats `.`, `%2e`, `..`, `.%2e`, `%2e.`
 * and `%2e%2e` — case-insensitively — as dot segments and collapses them. Each
 * extra `%25` layer survives one more decode, so every encoding depth must be
 * refused, not only the ones the canonicalizer decodes.
 *
 * Used by the allowlist guard to substitute into EVERY segment of every
 * legitimate path: a `:id` or `*` position that accepts any of these is a
 * traversal out of the proxy's prefix with the internal key attached.
 */
export const DOT_SEGMENT_SPELLINGS: string[] = [
  '.',
  '..',
  '%2e',
  '%2E',
  '%2e%2e',
  '%2E%2E',
  '.%2e',
  '%2e.',
  '.%2E',
  '%2E.',
  '%252e',
  '%252e%252e',
  '%252E%252E',
  '.%252e',
  '%252e.',
  '.%252E',
  '%252E.',
  '%25252e%25252e',
  '%2525252e%2525252e',
  // Unicode NFKC look-alikes. Neither WHATWG URL nor Starlette folds these
  // today, but anything downstream that applies NFKC turns them into real dot
  // segments, and no legitimate id is spelled with one. Escapes, not literals,
  // for the same reason as TAB above.
  '．', // ． FULLWIDTH FULL STOP -> .
  '．．',
  '.．',
  '‥', // ‥ TWO DOT LEADER -> ..
  '․', // ․ ONE DOT LEADER -> .
  '․․',
  '﹒', // ﹒ SMALL FULL STOP -> .
  '﹒﹒',
  // `;` path parameters: `..;x` is `..` to a server that strips them (Tomcat,
  // Spring), including the fullwidth `；` that NFKC folds to `;`.
  '..;',
  '.;',
  '..;jsessionid=x',
  '..；',
  // Whitespace padding: `. ` / ` ..` are dot segments to anything that trims.
  '. ',
  ' ..',
  '.. ',
  '..　',
];

/**
 * Segments that carry a URL-restructuring character only after Unicode NFKC
 * folding: fullwidth `／` (U+FF0F) becomes a real separator, `＼` (U+FF3C) and
 * `﹨` (U+FE68) a backslash, `？`/`＃` a query/fragment delimiter, `％` a
 * percent escape. Refused by the canonicalizer like their ASCII originals.
 */
export const NFKC_HAZARD_SEGMENTS: string[] = [
  '／',
  'a／b',
  '..／..',
  '＼',
  'a＼b',
  'a﹨b',
  'a？b',
  'a＃b',
  '％2e％2e', // ％2e％2e -> %2e%2e
];

/**
 * Lone UTF-16 surrogates. Nothing in the canonicalizer rejects them — they
 * contain no `%`, no hazard, no dot — but `encodeURIComponent` throws URIError
 * on them, so `buildUpstreamUrl` must turn that into a refusal (the shared 404)
 * rather than let the throw escape the handler as a distinguishable 500.
 */
export const UNENCODABLE_SEGMENTS: string[] = ['\uD800', 'a\uDC00b', 'x\uDBFF'];

/**
 * Tails appended after a `*` wildcard prefix (admin's `locations/aliases/*` is
 * the only one today). The wildcard eats whatever follows it, so these are the
 * cases where a traversal sits INSIDE an allowlisted route instead of instead
 * of one. The first entry is the exact production reproduction:
 *
 *   GET /api/admin/locations/aliases/%25252e%25252e/…/internal/launch-radar/monitors
 *
 * reached the backend as `GET /api/internal/launch-radar/monitors` WITH the
 * internal key, as did the mutating `/api/internal/enrichment/pending`.
 */
export const WILDCARD_TAIL_ESCAPES: Array<[label: string, tail: string]> = [
  [
    'production repro: double-encoded dots to launch-radar monitors',
    '%252e%252e/%252e%252e/%252e%252e/internal/launch-radar/monitors',
  ],
  [
    'double-encoded dots to the mutating enrichment route',
    '%252e%252e/%252e%252e/%252e%252e/internal/enrichment/pending',
  ],
  ['single-encoded dots', '%2e%2e/%2e%2e/%2e%2e/internal/launch-radar/monitors'],
  ['mixed .%252e', '.%252e/.%252e/.%252e/internal/launch-radar/monitors'],
  ['mixed %252E.', '%252E./%252E./%252E./internal/launch-radar/monitors'],
  [
    'triple-encoded dots',
    '%25252e%25252e/%25252e%25252e/%25252e%25252e/internal/launch-radar/monitors',
  ],
  ['mixed slashes and backslashes', '..\\../..%5Cinternal/launch-radar/monitors'],
  [
    'double-encoded slashes between double-encoded dots',
    '%252e%252e%252f%252e%252e%252f%252e%252e%252finternal%252flaunch-radar%252fmonitors',
  ],
  [
    'a real-looking key, then a climb',
    'emea / remote/%252e%252e/%252e%252e/%252e%252e/%252e%252e/internal/launch-radar/monitors',
  ],
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
