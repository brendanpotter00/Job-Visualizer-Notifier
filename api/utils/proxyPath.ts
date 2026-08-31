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
 * Reduce the raw `?path=` capture to canonical segments, or `null` if it
 * cannot be trusted. `null` means "404 without calling upstream" — never
 * "forward and let the backend decide", which is the hole being closed.
 *
 * Steps, each earning its place:
 *  - array form: Vercel yields `string[]` when `path` repeats, and
 *    `?path=companies&path=` joined naively becomes `companies/`.
 *  - percent-decode: two independent reasons. (a) Starlette/Uvicorn decode
 *    `scope["path"]` before routing, so `%2e%2e` forwarded verbatim arrives
 *    as `..`; we must compare what the BACKEND will see, not what the client
 *    typed. (b) WHATWG URL itself decodes `%2e` before collapsing dot
 *    segments — `new URL('http://h/api/users/%2e%2e/internal/x')` is
 *    `/api/internal/x` — so the traversal happens in `fetch` even if the
 *    backend never sees a literal dot. Malformed encoding (`%`, `%zz`)
 *    throws and is treated as untrusted.
 *  - structural-hazard rejection: see STRUCTURAL_HAZARDS above.
 *  - drop empty segments: collapses leading, trailing and duplicated
 *    slashes in one pass.
 *  - reject `.` / `..`: no traversal games; `./companies` is not a spelling
 *    we accept, and `..` walks out of the proxy's own prefix.
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

  if (STRUCTURAL_HAZARDS.test(decoded)) return null;

  const segments = decoded.split('/').filter((segment) => segment.length > 0);
  if (segments.some((segment) => segment === '.' || segment === '..')) return null;

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
 * Returns the canonical path (`''` for the bare prefix) to splice into the
 * upstream URL, or `null` to reject. Callers MUST build the upstream URL from
 * the returned value — the raw client-supplied path must never reach the
 * upstream request.
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
