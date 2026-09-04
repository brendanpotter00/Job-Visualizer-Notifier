import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';
import { PROXY_REJECTION, resolveProxyPath } from './utils/proxyPath';

const METHODS_WITH_BODY = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Every backend route reachable under `/api/admin`, and nothing else. See
 * `api/utils/proxyPath.ts` for why this is an allowlist and not a `..` filter.
 *
 * Derived from `app.openapi()["paths"]` for the `/api/admin` prefix and
 * cross-checked line-by-line against `features/admin/adminApi.ts`, which is the
 * only caller (the Admin pages). Every route here is `Depends(require_admin)`
 * on the backend, so this allowlist is defence in depth rather than the
 * perimeter — but it is the thing that stops `/api/admin` being used as a
 * doorway into `/api/internal/*`, which has no JWT gate at all.
 *
 * `locations/aliases/*` is the one wildcard, and it is deliberate: the backend
 * declares `PUT /locations/aliases/{raw_text:path}` with a `:path` converter
 * because real location strings ("EMEA / Remote") carry literal slashes, so the
 * key genuinely spans several segments. The prefix is still fixed, and the
 * canonicalizer has already rejected `.`/`..` and every URL-restructuring
 * character, so the wildcard cannot escape `/api/admin/locations/aliases/`.
 */
const PROXIED_ROUTES = [
  // users
  'users', // GET
  'users/stats', // GET
  'users/:id/visits', // GET
  'users/:id/admin', // POST/DELETE — grant / revoke
  // feedback
  'feedback', // GET
  // custom companies (E7 admin oversight — read-only)
  'custom-companies', // GET
  'custom-companies/attempts', // GET
  // jobs
  'jobs/:id/normalize', // POST
  // locations
  'locations/aliases', // GET
  'locations/aliases/*', // PUT — {raw_text:path}, may span segments
  'locations/alias-originals', // GET
  'locations/health', // GET
  'locations/integrity', // GET
  'locations/problem-jobs', // GET
  'locations/re-normalize-all', // POST
  'locations/reverse', // GET
  // enrichment
  'enrichment/health', // GET
  'enrichment/needs-human', // GET
  'enrichment/recent', // GET
  'enrichment/ticks', // GET
  'enrichment/jobs/:sourceId/:jobId/correct', // POST
  'enrichment/jobs/:sourceId/:jobId/confirm', // POST
  'enrichment/jobs/:sourceId/:jobId/reenrich', // POST
  // app settings (the SWE-subcategory reveal flag lives here)
  'settings', // GET — the admin settings list
  'settings/:key', // PUT — flip one allowlisted key
] as const;

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path, ...queryParams } = req.query;

  // Canonical form only; the upstream URL below is built from THIS value, so
  // the raw client-supplied path never reaches the upstream request.
  const targetPath = resolveProxyPath(path, PROXIED_ROUTES);
  if (targetPath === null) {
    res.status(PROXY_REJECTION.status).json(PROXY_REJECTION.body);
    return;
  }

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(queryParams)) {
    if (value !== undefined) {
      params.set(key, String(value));
    }
  }
  const queryString = params.size ? `?${params}` : '';

  const backendUrl = getBackendUrl(req);
  const targetUrl = `${backendUrl}/api/admin${targetPath ? `/${targetPath}` : ''}${queryString}`;

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...getInternalKeyHeader(),
  };
  if (req.headers.authorization) {
    headers['Authorization'] = req.headers.authorization;
  }

  const fetchOptions: RequestInit = {
    method: req.method,
    headers,
    // Never follow a redirect — Node's fetch preserves headers (including the
    // injected X-Internal-Key) across a same-origin 3xx. See api/jobs-qa.ts.
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
    // Log the full error server-side for debugging, but return a generic
    // message to the client. Node's fetch errors leak internal hostnames
    // and ports (e.g. "getaddrinfo ENOTFOUND backend-prod.internal:8080")
    // which a public 502 response should not expose.
    console.error('[api/admin] Upstream fetch failed:', error);
    res.status(502).json({ error: 'Upstream backend unavailable' });
  }
}
