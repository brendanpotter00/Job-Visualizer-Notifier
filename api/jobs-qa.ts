import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';

const METHODS_WITH_BODY = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * The ONLY backend jobs-qa paths this proxy will forward. Everything else
 * 404s, with or without credentials.
 *
 * WHY AN ALLOWLIST. This function is a *public* internet endpoint
 * (vercel.json maps `/api/jobs-qa/:path(.*)` here) and it attaches
 * X-Internal-Key UNCONDITIONALLY, so it always satisfies the backend's
 * `require_internal_key` middleware. It is a second front door that is
 * already inside the building. The only thing that has ever protected
 * these routes is `Depends(require_admin)` on the backend, which verifies
 * a real Auth0 JWT — and `GET /scraper-health` deliberately has none (the
 * scheduled GitHub Action can present a static header but cannot mint an
 * admin JWT). For that route the backend performs NO identity check, so
 * anything this proxy forwards is served to whoever asked.
 *
 * Two earlier shapes failed, both because they failed OPEN:
 *
 *   1. "Is an Authorization header present?" — the proxy cannot *verify* a
 *      token, so `curl -H "Authorization: x"` sailed through and returned
 *      the full internal roster. Presence is not authentication.
 *   2. A denylist (`NOT_PROXIED_PATHS = {'scraper-health'}`) compared by
 *      exact string against the raw `?path=` capture. Every spelling that
 *      was not byte-identical got proxied: `scraper-health/`,
 *      `/scraper-health`, `scraper-health//`, `./scraper-health`,
 *      `scraper%2Dhealth`, and the array form `?path=scraper-health&path=`.
 *      The trailing-slash variant is a live exploit on its own — the
 *      backend app is built with Starlette's default `redirect_slashes=True`,
 *      so `/api/jobs-qa/scraper-health/` 307s to the canonical path, and
 *      Node's fetch follows same-origin redirects WITH headers intact.
 *
 * A denylist on a key-injecting proxy is structurally wrong: every path
 * nobody thought of is forwarded. An allowlist inverts the default, so a
 * new internal-key-only backend route is unreachable here *by default*
 * rather than reachable until someone remembers to deny it.
 *
 * Verifying the JWT here was the other option. Rejected: a second,
 * independently-maintained Auth0 path (JWKS fetch, caching, clock skew,
 * algorithm pinning) in a serverless function is a second place to get
 * auth subtly wrong, to protect routes the backend already authenticates.
 *
 * These two entries are everything the browser needs — they are QAPage's
 * only two calls. The GitHub Action and the per-migration DEPLOY.md
 * operator runbooks all curl
 * `https://<RAILWAY_BACKEND>/api/jobs-qa/...` directly and never transit
 * Vercel, so the admin-gated trigger-fetch / fan-out endpoints do not need
 * to be reachable here.
 *
 * 404, not 401/403: from the public internet these paths genuinely are not
 * routed, and saying so leaks nothing about what exists behind the proxy.
 *
 * KEEPING THIS HONEST: `TestProxyAllowlistInvariant` in
 * src/backend/api/tests/test_scraper_health.py enumerates every route on
 * the backend `jobs_qa` router and asserts (a) every allowlisted path
 * exists and carries `require_admin`, and (b) every route lacking
 * `require_admin` is absent from this list.
 */
const PROXIED_PATHS = new Set(['scrape-runs', 'trigger-scrape']);

/**
 * Reduce the raw `?path=` capture to the single canonical spelling used
 * for the allowlist comparison, or `null` if it cannot be trusted.
 *
 * Normalization is required even with an allowlist: without it,
 * `scrape-runs/` would fail the lookup and 404 a legitimate caller, and
 * with a denylist it silently opened the hole documented above. Doing it
 * once, here, means the comparison and the forwarded URL agree by
 * construction.
 *
 * Steps, each earning its place:
 *  - array form: Vercel yields `string[]` when `path` repeats, and
 *    `?path=scrape-runs&path=` joined naively becomes `scrape-runs/`.
 *  - percent-decode: Starlette decodes before routing, so `scraper%2Dhealth`
 *    forwarded verbatim arrives as `scraper-health`. We must compare what
 *    the BACKEND will see, not what the client typed. Malformed encoding
 *    (`%`, `%zz`) throws — treated as untrusted.
 *  - NUL rejection: a `%00` truncation trick should never reach upstream.
 *  - drop empty segments: collapses leading, trailing and duplicated
 *    slashes in one pass.
 *  - reject `.` / `..`: no traversal games; `./scrape-runs` is not a
 *    spelling we accept, and `..` could otherwise walk out of /api/jobs-qa.
 *
 * Comparison stays case-sensitive — the backend routes are lowercase and
 * FastAPI matching is case-sensitive, so folding case here would accept
 * spellings the backend would 404 anyway.
 */
function canonicalizeProxyPath(raw: string | string[] | undefined): string | null {
  const parts = Array.isArray(raw) ? raw : [raw];
  const joined = parts.filter((part) => part != null).join('/');

  let decoded: string;
  try {
    decoded = decodeURIComponent(joined);
  } catch {
    return null; // malformed percent-encoding
  }

  if (decoded.includes('\0')) return null;

  const segments = decoded.split('/').filter((segment) => segment.length > 0);
  if (segments.some((segment) => segment === '.' || segment === '..')) return null;

  return segments.join('/');
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path, ...queryParams } = req.query;

  // Canonical form only — and note the upstream URL below is built from
  // THIS value, which the allowlist check has already constrained to one
  // of two literals. The raw client-supplied path never reaches the
  // upstream request.
  const targetPath = canonicalizeProxyPath(path);
  if (targetPath === null || !PROXIED_PATHS.has(targetPath)) {
    res.status(404).json({ detail: 'Not Found' });
    return;
  }

  // Cheap pre-filter, NOT an authorization decision. Both allowlisted
  // routes are admin-gated on the backend and would 401 there anyway;
  // rejecting here just avoids a pointless upstream round trip. Nothing
  // security-relevant rests on it — see PROXIED_PATHS above for why the
  // presence of a header proves nothing.
  if (!req.headers.authorization) {
    res.status(401).json({ detail: 'Unauthorized' });
    return;
  }

  // Build query string from remaining params
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(queryParams)) {
    if (value !== undefined) {
      params.set(key, String(value));
    }
  }
  const queryString = params.toString() ? `?${params.toString()}` : '';

  // targetPath is one of the two PROXIED_PATHS literals at this point —
  // never raw client input — so the upstream URL cannot be steered.
  const backendUrl = getBackendUrl(req);
  const targetUrl = `${backendUrl}/api/jobs-qa/${targetPath}${queryString}`;

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...getInternalKeyHeader(),
  };
  // Forward the caller's Bearer token. Guaranteed present by the
  // anonymous-request gate at the top of this handler; most /api/jobs-qa
  // routes are admin-gated on the backend (require_admin) and would 401
  // without it.
  headers['Authorization'] = req.headers.authorization;

  const fetchOptions: RequestInit = {
    method: req.method,
    headers,
    // Never follow a redirect. Node's fetch defaults to `redirect: 'follow'`
    // and PRESERVES headers across a same-origin 3xx — including the
    // X-Internal-Key this proxy injects. Combined with Starlette's default
    // `redirect_slashes=True` on the backend app, that turned a trailing
    // slash into a working bypass of the path check: the proxy forwarded
    // `/scraper-health/`, the backend 307'd to `/scraper-health`, and fetch
    // followed it with the key still attached. The allowlist above closes
    // that on its own, but 'manual' means the proxy can never be used to
    // follow a redirect into a path it just refused.
    redirect: 'manual',
  };

  // Forward the request body for any mutating method that carries one.
  // Gated on the method allowlist because Vercel Dev parses an empty GET
  // body as ``{}`` (non-null), and Node's native ``fetch`` rejects GET/HEAD
  // with a body ("Request with GET/HEAD method cannot have body").
  if (METHODS_WITH_BODY.has(req.method ?? '') && req.body != null) {
    fetchOptions.body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
  }

  try {
    const response = await fetch(targetUrl, fetchOptions);
    await forwardResponse(response, res);
  } catch (error) {
    // See api/admin.ts: do not leak the upstream URL / DNS error to the
    // public client — log it server-side instead.
    console.error('[api/jobs-qa] Upstream fetch failed:', error);
    res.status(502).json({ error: 'Upstream backend unavailable' });
  }
}
