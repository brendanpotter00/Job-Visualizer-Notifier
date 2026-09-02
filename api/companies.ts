import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';
import { PROXY_REJECTION, resolveProxyPath } from './utils/proxyPath';

// Public proxy for the curated-companies directory. Mirrors api/features.ts but
// is read-only and unauthenticated (the backend endpoint takes no auth). The
// Authorization passthrough is kept harmless: forwarded only if a caller
// happens to send one, never required.
const METHODS_WITH_BODY = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Every backend route reachable under `/api/companies`, and nothing else. See
 * `api/utils/proxyPath.ts` for why this is an allowlist and not a `..` filter.
 *
 * Two routes exist on the backend `companies` router and the frontend uses
 * both: `features/companies/companiesApi.ts` reads the bare directory, and
 * `features/userCompanies/userCompaniesApi.ts` posts to `resolve` (it bases
 * itself at `/api` and spells the url `companies/resolve`).
 */
const PROXIED_ROUTES = [
  '', // GET /api/companies — curated directory
  'resolve', // POST — careers-URL resolver
  'search-by-name', // POST — typed-company-name search
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
  const targetUrl = `${backendUrl}/api/companies${targetPath ? `/${targetPath}` : ''}${queryString}`;

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

  if (METHODS_WITH_BODY.has(req.method ?? '') && req.body != null) {
    fetchOptions.body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
  }

  try {
    const response = await fetch(targetUrl, fetchOptions);
    await forwardResponse(response, res);
  } catch (error) {
    console.error('[api/companies] Upstream fetch failed:', error);
    res.status(502).json({
      error: 'Upstream backend unavailable',
      details: error instanceof Error ? error.message : String(error),
    });
  }
}
