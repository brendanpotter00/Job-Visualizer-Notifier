import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';

const METHODS_WITH_BODY = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Backend jobs-qa paths this proxy refuses to forward, at any time, with
 * or without credentials.
 *
 * WHY A DENYLIST AND NOT AN AUTH CHECK. This function is a *public*
 * internet endpoint (vercel.json maps `/api/jobs-qa/:path(.*)` here) and
 * it attaches X-Internal-Key UNCONDITIONALLY, so it always satisfies the
 * backend's `require_internal_key` middleware. It is a second front door
 * that is already inside the building. The only thing that has ever
 * protected these routes is `Depends(require_admin)` on the backend,
 * which verifies a real Auth0 JWT.
 *
 * `GET /scraper-health` deliberately has no `require_admin` — the
 * scheduled GitHub Action can present a static header but cannot mint an
 * admin JWT. So for that one route the backend performs NO identity
 * check, and anything this proxy forwards is served.
 *
 * A previous attempt gated on "is an Authorization header present?".
 * That does not work and was proven not to: the proxy cannot *verify* a
 * token, so `curl -H "Authorization: x"` sailed straight through and
 * returned the full internal company roster — every company id, ATS,
 * openJobs, lastSeenAt, hoursStale. Presence is not authentication.
 *
 * Verifying the JWT here was the alternative. Rejected: it would mean a
 * second, independently-maintained Auth0 verification path (JWKS fetch,
 * caching, clock skew, algorithm pinning) in a serverless function, i.e.
 * a second place to get auth subtly wrong, to protect routes the backend
 * already authenticates correctly.
 *
 * So: routes with no backend identity check are simply not reachable
 * through the public proxy. Nothing needs them here — QAPage only calls
 * `scrape-runs` and `trigger-scrape`, and the GitHub Action hits Railway
 * directly with the internal key and never transits Vercel.
 *
 * 404, not 401/403: from the public internet this path genuinely is not
 * routed, and saying so leaks nothing about what exists behind the proxy.
 *
 * KEEPING THIS HONEST: `test_proxy_denies_non_admin_jobs_qa_routes` in
 * src/backend/api/tests/test_scraper_health.py enumerates every route on
 * the backend `jobs_qa` router, finds the ones lacking `require_admin`,
 * and asserts each one appears in this list. Add an internal-key-only
 * route to that router and the backend test suite fails until it is
 * denied here too.
 */
const NOT_PROXIED_PATHS = new Set(['scraper-health']);

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path, ...queryParams } = req.query;

  // Build the path from the catch-all route
  const pathParts = Array.isArray(path) ? path : [path].filter(Boolean);
  const targetPath = pathParts.join('/');

  if (NOT_PROXIED_PATHS.has(targetPath)) {
    res.status(404).json({ detail: 'Not Found' });
    return;
  }

  // Cheap pre-filter, NOT an authorization decision. Every route that IS
  // proxied is admin-gated on the backend and would 401 anyway; rejecting
  // here just avoids a pointless upstream round trip. Deliberately not
  // relied on for security — see NOT_PROXIED_PATHS above for why presence
  // of a header proves nothing.
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

  const backendUrl = getBackendUrl(req);
  const targetUrl = `${backendUrl}/api/jobs-qa${targetPath ? `/${targetPath}` : ''}${queryString}`;

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
