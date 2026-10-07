/**
 * Shared `?path=` allowlist for every Vercel proxy that injects X-Internal-Key.
 *
 * WHY THIS EXISTS. Each `api/*.ts` function is a *public* internet endpoint
 * (vercel.json maps `/api/<name>/:path(.*)` onto it) and every one of them
 * attaches `X-Internal-Key` UNCONDITIONALLY, so every one of them always
 * clears the backend's `require_internal_key` middleware. They are second
 * front doors that are already inside the building.
 *
 * Splicing the raw `?path=` into the upstream URL therefore hands an
 * anonymous caller the internal key on any route they can name. Node's
 * `fetch` parses with WHATWG URL, which COLLAPSES dot segments, so
 *
 *     `${backend}/api/feedback/` + `../internal/enrichment/pending`
 *
 * resolves to `${backend}/api/internal/enrichment/pending` — a route whose
 * only protection is the very key the proxy just attached. That route
 * MUTATES (it flips rows to `enrichment_status='claimed'`), and the
 * sibling `POST /results` writes arbitrary enrichment data onto up to 500
 * job rows per call. This was live in production.
 *
 * A denylist cannot fix it: every path nobody thought of is forwarded, and
 * "reject `..`" is defeated by `%2e%2e`, `%252e%252e`, `.<TAB>.`, and
 * backslash separators (all verified against Node's URL parser below).
 * An allowlist inverts the default — a new internal-key-only backend route
 * is unreachable through these proxies *by default* rather than reachable
 * until someone remembers to deny it.
 *
 * AN ALLOWLIST IS NOT ENOUGH ON ITS OWN, and this was also live in production.
 * A `:id` or `*` position accepts any segment content, so the allowlist only
 * holds if no segment can still BECOME a dot segment downstream. Vercel decodes
 * the request path once before the handler runs, and the canonicalizer decoded
 * once more — so a client that sent `%25252e%25252e` handed us `%252e%252e`,
 * which decoded to `%2e%2e`: not literally `..`, so it passed, matched admin's
 * `locations/aliases/*`, and `fetch`'s WHATWG URL parser then read `%2e%2e` AS
 * `..` and collapsed it. `/api/admin/locations/aliases/%252e%252e/%252e%252e/
 * %252e%252e/internal/launch-radar/monitors` reached the backend as
 * `GET /api/internal/launch-radar/monitors` with the internal key attached.
 * Three independent layers now close that class, each sufficient on its own:
 *
 *   1. `canonicalizeProxyPath` refuses any `%` left after its one decode (an
 *      encoding layer still unpeeled is something a later parser will peel)
 *      and any all-dots segment in any encoding — also after Unicode NFKC
 *      folding (`．`, `‥`), `;` path-parameter stripping and whitespace
 *      trimming, the normalizations some layer downstream might apply.
 *   2. `buildUpstreamUrl` percent-encodes each validated segment itself, so
 *      the URL handed to `fetch` contains no `.`/`..` segment and no `%2e` for
 *      WHATWG URL to reinterpret — the backend receives exactly the segment we
 *      validated, never a re-interpretation of it.
 *   3. `buildUpstreamUrl` then parses the URL the way `fetch` will and refuses
 *      it unless the resulting pathname is still inside the proxy's own prefix
 *      and the router segment right after `/api` is not `internal`.
 *
 * Verifying the caller's JWT in the proxy instead was rejected for the same
 * reason `api/jobs-qa.ts` rejected it: a second, independently-maintained
 * Auth0 path (JWKS fetch, caching, clock skew, algorithm pinning) in a
 * serverless function is a second place to get auth subtly wrong, to protect
 * routes the backend already authenticates.
 */

/**
 * Characters that let a path segment restructure the upstream URL. All four
 * behaviours were measured against Node 22's WHATWG `URL`, not assumed:
 *
 *   `\`        `new URL('http://h/a/x\\y')` -> `/a/x/y`. A backslash IS a
 *              path separator to WHATWG, so it smuggles a segment boundary
 *              past a naive `split('/')`.
 *   TAB/LF/CR  STRIPPED before parsing: `http://h/a/.<TAB>.` -> `/a/..`,
 *              which then collapses. A `.<TAB>.` segment survives an
 *              `=== '..'` comparison and becomes traversal anyway.
 *   `?`        `new URL('http://h/a/x?y')` -> path `/a/x`, search `?y`.
 *              Truncates the path AND injects query params we never vetted.
 *   `#`        Truncates the path into a fragment the upstream never sees.
 *
 * Rejected outright rather than escaped: none of them appear in a legitimate
 * id, and refusing is the behaviour that stays correct if a future dynamic
 * segment is added without re-reading this file.
 *
 * The range also covers NUL - a %00 truncation trick must never reach
 * upstream - along with every other C0 control and DEL.
 */
// eslint-disable-next-line no-control-regex
const STRUCTURAL_HAZARDS = /[\\?#\u0000-\u001F\u007F]/;

/**
 * A segment made only of dots, in ANY percent-encoding and case: `.`, `..`,
 * `%2e`, `.%2E`, `%2e%2e`, … WHATWG URL treats `.`/`%2e` (single) and any
 * two-character mix of them (double) as dot segments and collapses them.
 *
 * Wider than WHATWG on purpose: `...` and longer runs are ordinary segments to
 * WHATWG and Starlette, but no legitimate id is all dots, and some path
 * normalizers elsewhere (Windows, some proxies) strip trailing dots — refusing
 * them costs nothing and removes a question. The `%2e` branch is redundant
 * while `%` is refused outright below; it stays so that relaxing the `%` rule
 * later cannot silently reopen the encoded-dot hole.
 */
const DOT_SEGMENT = /^(?:\.|%2e)+$/i;

/**
 * Whether `segment` is a dot segment, or turns into one under a normalization
 * some layer between here and the backend might apply. Checked on two forms:
 *
 *  - as-is, and
 *  - Unicode NFKC-folded: `．` (U+FF0E), `․` (U+2024) and `﹒` (U+FE52) fold
 *    to `.`, and `‥` (U+2025) to `..`. Neither WHATWG URL nor Starlette folds
 *    today, but a normalizing proxy, filesystem or framework somewhere would,
 *    and no legitimate id is spelled with a look-alike dot.
 *
 * and each form is first cut at its first `;` and trimmed: `..;x` is `..` to
 * a server that strips RFC 2396 path parameters (Tomcat, Spring), and `. ` /
 * ` ..` are `.` / `..` to anything that trims.
 */
function isDotSegment(segment: string): boolean {
  return [segment, segment.normalize('NFKC')].some((form) =>
    DOT_SEGMENT.test(form.split(';')[0].trim())
  );
}

/**
 * Whether a canonical segment must be refused. The raw form has already been
 * cleared of `%` and STRUCTURAL_HAZARDS (and cannot hold `/`, having been split
 * on it); this repeats those checks on the NFKC-folded form, where fullwidth
 * `／` (U+FF0F), `＼` (U+FF3C), `？`, `＃` and `％` become the real thing, then
 * applies `isDotSegment`.
 *
 * Only ever a CHECK: the segment returned and forwarded is the original, so a
 * key like "Zürich" reaches the backend byte-for-byte as the caller sent it,
 * never re-normalized.
 */
function isUnsafeSegment(segment: string): boolean {
  const folded = segment.normalize('NFKC');
  return (
    folded.includes('/') ||
    folded.includes('%') ||
    STRUCTURAL_HAZARDS.test(folded) ||
    isDotSegment(segment)
  );
}

/**
 * Reduce the raw `?path=` capture to canonical segments, or `null` if it
 * cannot be trusted. `null` means "404 without calling upstream" — never
 * "forward and let the backend decide", which is the hole being closed.
 *
 * Steps, each earning its place:
 *  - array form: Vercel yields `string[]` when `path` repeats, and
 *    `?path=companies&path=` joined naively becomes `companies/`.
 *  - percent-decode ONCE: two independent reasons. (a) Starlette/Uvicorn
 *    decode `scope["path"]` before routing, so `%2e%2e` forwarded verbatim
 *    arrives as `..`; we must compare what the BACKEND will see, not what the
 *    client typed. (b) WHATWG URL itself decodes `%2e` before collapsing dot
 *    segments — `new URL('http://h/api/users/%2e%2e/internal/x')` is
 *    `/api/internal/x` — so the traversal happens in `fetch` even if the
 *    backend never sees a literal dot. Malformed encoding (`%`, `%zz`)
 *    throws and is treated as untrusted.
 *  - refuse any `%` that SURVIVES that decode. Vercel has already decoded the
 *    request path once before the handler runs, so a `%` still here after our
 *    decode means the client encoded at least three times — and every layer we
 *    do not peel is one some later parser will (WHATWG URL reads `%2e` as a
 *    dot). Refusing beats decoding-until-stable: there is no "how many rounds
 *    is enough" to get wrong, and no legitimate caller triple-encodes. The
 *    cost is that a key containing a literal `%` cannot transit these proxies
 *    — which was already true, since Vercel's decode leaves it bare and a bare
 *    `%` fails `decodeURIComponent` above.
 *  - structural-hazard rejection: see STRUCTURAL_HAZARDS above.
 *  - drop empty segments: collapses leading, trailing and duplicated
 *    slashes in one pass.
 *  - reject unsafe segments (see isUnsafeSegment): no traversal games;
 *    `./companies` is not a spelling we accept, `..` walks out of the proxy's
 *    own prefix, and neither do their NFKC look-alikes, `;`-parameter and
 *    whitespace-padded spellings.
 *
 * Comparison stays case-sensitive — the backend routes are lowercase and
 * FastAPI matching is case-sensitive, so folding case here would accept
 * spellings the backend would 404 anyway.
 */
export function canonicalizeProxyPath(raw: string | string[] | undefined): string[] | null {
  const parts = Array.isArray(raw) ? raw : [raw];
  const joined = parts.filter((part) => part != null).join('/');

  let decoded: string;
  try {
    decoded = decodeURIComponent(joined);
  } catch {
    return null; // malformed percent-encoding
  }

  // An encoding layer we did not peel is one a downstream parser will.
  if (decoded.includes('%')) return null;

  if (STRUCTURAL_HAZARDS.test(decoded)) return null;

  // Reject a protocol-relative / authority form (`//host/path`) outright. Empty
  // segments are dropped below, so `//evil.example.com/steal` would otherwise
  // canonicalize to `['evil.example.com', 'steal']` and match any two-segment
  // `:a/:b` route (e.g. jobs' `:source/:job` detail read) — forwarding a hostile
  // authority string as if it were an id. A SINGLE leading slash is a sloppy but
  // legitimate absolute spelling the callers below normalize (`/facets/` ->
  // `facets`); only a LEADING double slash names an authority, and no legitimate
  // sub-path does. Checked on the decoded string so `/%2fx` (-> `//x`) is caught too.
  if (decoded.startsWith('//')) return null;

  const segments = decoded.split('/').filter((segment) => segment.length > 0);
  if (segments.some(isUnsafeSegment)) return null;

  return segments;
}

/**
 * One allowlisted backend route, written the way the FastAPI decorator writes
 * it minus the router prefix:
 *
 *   `''`                     the bare prefix (`GET /api/users`)
 *   `'saved-filters'`        literal segments
 *   `'companies/:id'`        any `:name` matches EXACTLY ONE segment, any
 *                            content; the name is documentation only
 *   `'locations/aliases/*'`  `*` matches ONE OR MORE trailing segments, and is
 *                            only legitimate where the backend declared a
 *                            `{param:path}` converter (admin's alias key —
 *                            real location strings like "EMEA / Remote" carry
 *                            literal slashes on purpose)
 *
 * `:id` deliberately does not constrain the character set. By the time a
 * segment reaches here it has already been decoded, split on `/`, and cleared
 * of every character that can restructure a URL, so the only thing left for a
 * charset rule to do is reject ids the backend would 404 anyway — at the cost
 * of breaking a legitimate id nobody predicted (source ids carry `:`, alias
 * keys carry spaces and commas).
 */
export type ProxyRoute = string;

function matchesRoute(segments: string[], route: ProxyRoute): boolean {
  const pattern = route === '' ? [] : route.split('/');

  const wildcardAt = pattern.indexOf('*');
  if (wildcardAt !== -1) {
    // `*` is only meaningful as the final element; a mid-pattern `*` is a
    // typo, and silently treating it as a literal would open a hole.
    if (wildcardAt !== pattern.length - 1) return false;
    // ONE or more trailing segments — never zero, so `locations/aliases/*`
    // cannot be used to reach the bare `locations/aliases` collection route
    // (that one is allowlisted separately, on purpose).
    if (segments.length < pattern.length) return false;
  } else if (segments.length !== pattern.length) {
    return false;
  }

  return pattern.every((expected, i) => {
    if (expected === '*') return true;
    // Any `:name` segment is dynamic. The name is documentation only — it
    // exists so a route reads like the FastAPI decorator it mirrors
    // (`enrichment/jobs/:sourceId/:jobId/correct`).
    if (expected.startsWith(':')) return true;
    return segments[i] === expected;
  });
}

/**
 * Canonicalize `raw` and check it against `routes`.
 *
 * Returns the canonical, DECODED path (`''` for the bare prefix) — the form
 * to compare against route literals (`sub === 'search'`) and the only form
 * `buildUpstreamUrl` accepts — or `null` to reject. Callers MUST build the
 * upstream URL by passing the returned value to `buildUpstreamUrl`, never by
 * splicing it (or the raw client-supplied path) into a string themselves.
 */
export function resolveProxyPath(
  raw: string | string[] | undefined,
  routes: readonly ProxyRoute[]
): string | null {
  const segments = canonicalizeProxyPath(raw);
  if (segments === null) return null;
  if (!routes.some((route) => matchesRoute(segments, route))) return null;
  return segments.join('/');
}

/**
 * RFC 3986 `pchar` delimiters that `encodeURIComponent` escapes but that are
 * literal data inside a path segment (RFC 3986 §3.3) and that WHATWG URL's
 * path parser never reinterprets: `: @ $ & + , ; =`. Restored after encoding
 * so the upstream URL stays byte-identical to what these proxies always sent —
 * source ids carry `:` (`greenhouse:openai`), alias keys carry `,` — instead of
 * `%3A`/`%2C`, which the backend would decode to the same thing anyway.
 *
 * Safe to match on the raw output: `encodeURIComponent` emits `%` only as the
 * start of an escape triplet (a literal `%` becomes `%25`), so this can never
 * match across a triplet boundary.
 */
const PCHAR_DELIMITER_ESCAPES = /%(?:3A|40|24|26|2B|2C|3B|3D)/g;

function encodePathSegment(segment: string): string {
  return encodeURIComponent(segment).replace(PCHAR_DELIMITER_ESCAPES, (escape) =>
    decodeURIComponent(escape)
  );
}

/**
 * The backend router whose routes have NO JWT gate — only the internal key
 * these proxies attach unconditionally. No public proxy ever forwards to it.
 */
const INTERNAL_SEGMENT = 'internal';

/**
 * Whether the parsed upstream `pathname` is anything other than a public
 * router under `/api`: refused when it is not under `apiRoot` at all, or when
 * the ROUTER segment right after `/api` — the one that selects
 * `/api/internal/*` — is `internal` in any case, encoding or NFKC look-alike
 * (fullwidth `ｉｎｔｅｒｎａｌ`).
 *
 * Deliberately ONLY that segment. Deeper segments are data: a location alias
 * whose raw text is "Internal", or `GET /api/jobs/<source>/internal`, is a
 * legitimate request, and the internal router can only be selected by the
 * first segment under `/api`. The prefix assertion beside this check is what
 * keeps a request from climbing to that position.
 */
function targetsInternalRouter(pathname: string, apiRoot: string): boolean {
  if (!pathname.startsWith(`${apiRoot}/`)) return true;
  const [routerSegment] = pathname.slice(apiRoot.length + 1).split('/');
  try {
    return decodeURIComponent(routerSegment).normalize('NFKC').toLowerCase() === INTERNAL_SEGMENT;
  } catch {
    return true; // undecodable after our own encoding: something is wrong, refuse
  }
}

/**
 * Build the upstream URL for a proxied request, or `null` to refuse it.
 *
 * The ONLY way a proxy should turn a resolved path into a URL. Two layers, each
 * of which would have stopped the double-encoded-dot escape on its own:
 *
 *  - ENCODE: each validated segment is percent-encoded here
 *    (`encodeURIComponent`, minus the harmless pchar delimiters above), so the
 *    string `fetch` parses contains no `.`/`..` segment, no `%2e` for WHATWG to
 *    reinterpret, and no `\`/`?`/`#`/TAB that could restructure it. What the
 *    backend decodes is exactly the segment that was validated.
 *
 *  - ASSERT: the result is parsed the way `fetch` will parse it, and refused
 *    unless the pathname is still the proxy's own prefix or under it, and the
 *    router segment right after `/api` is not `internal`. The expected prefix
 *    and the `/api` root are computed by parsing `${backendUrl}${prefix}` and
 *    `${backendUrl}/api` with NO caller input, so a base path or trailing slash
 *    on `BACKEND_API_URL` is compared like-for-like.
 *
 * Never throws: every refusal is `null`, which the caller turns into the shared
 * 404. A throw here would escape the handler as a 500 — a distinguishable
 * response — and `encodeURIComponent` does throw (URIError) on a lone
 * surrogate, which a `?path=` can carry.
 *
 * `canonicalPath` is `resolveProxyPath`'s return value: decoded, `/`-joined,
 * no empty or dot segments. Anything else is refused rather than repaired —
 * this function is a backstop, and a backstop that "fixes" input hides the bug
 * that produced it. `queryString` is `''` or starts with `?`, and never holds a
 * `#` (`URLSearchParams` encodes one as `%23`, so a raw `#` means the string
 * was assembled by hand and would cut the URL into a fragment).
 */
export function buildUpstreamUrl(
  backendUrl: string,
  prefix: string,
  canonicalPath: string,
  queryString = ''
): string | null {
  return buildUpstreamUrlWithEncoder(
    encodePathSegment,
    backendUrl,
    prefix,
    canonicalPath,
    queryString
  );
}

/**
 * TEST SEAM — proxies call `buildUpstreamUrl`, never this (pinned by
 * `test_proxy_path_allowlists.py`).
 *
 * `buildUpstreamUrl` with the segment encoder injected, so a test can simulate
 * the ENCODE layer regressing (an identity encoder) and prove the ASSERT layer
 * still refuses an escape on its own. Without the seam, the encoder makes every
 * escape unreachable, so deleting the prefix assertion would fail no test.
 */
export function buildUpstreamUrlWithEncoder(
  encodeSegment: (segment: string) => string,
  backendUrl: string,
  prefix: string,
  canonicalPath: string,
  queryString = ''
): string | null {
  if (queryString !== '' && (!queryString.startsWith('?') || queryString.includes('#'))) {
    return null;
  }

  const segments = canonicalPath === '' ? [] : canonicalPath.split('/');
  if (segments.some((segment) => segment === '' || isDotSegment(segment))) return null;

  let encodedPath: string;
  try {
    encodedPath = segments.map(encodeSegment).join('/');
  } catch {
    return null; // e.g. a lone surrogate: `encodeURIComponent` throws URIError
  }

  const base = `${backendUrl}${prefix}`;
  const target = `${base}${encodedPath ? `/${encodedPath}` : ''}${queryString}`;

  let expectedPrefix: string;
  let apiRoot: string;
  let actualPath: string;
  try {
    expectedPrefix = new URL(base).pathname;
    apiRoot = new URL(`${backendUrl}/api`).pathname;
    actualPath = new URL(target).pathname;
  } catch {
    return null;
  }

  if (actualPath !== expectedPrefix && !actualPath.startsWith(`${expectedPrefix}/`)) return null;
  if (targetsInternalRouter(actualPath, apiRoot)) return null;

  return target;
}

/**
 * The single rejection response, shared by every proxy.
 *
 * 404 with FastAPI's own `{"detail": "Not Found"}` body, deliberately: from
 * the public internet these paths genuinely are not routed, and the reply is
 * byte-identical to what the backend returns for a path that does not exist.
 * A 401/403, a distinct body, or a different latency profile would let an
 * anonymous prober tell "this internal route exists but the proxy refuses it"
 * from "this route does not exist" — so the refusal must look like nothing.
 */
export const PROXY_REJECTION = { status: 404, body: { detail: 'Not Found' } } as const;
