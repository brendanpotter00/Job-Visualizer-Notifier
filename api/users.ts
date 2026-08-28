import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';
import { PROXY_REJECTION, resolveProxyPath } from './utils/proxyPath';

const METHODS_WITH_BODY = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Every backend route reachable under `/api/users`, and nothing else. See
 * `api/utils/proxyPath.ts` for why this is an allowlist and not a `..` filter.
 *
 * `/api/users` is the widest of the five proxies because THREE routers mount
 * under it (`users`, `saved_filters` at `/api/users/saved-filters`, and
 * `user_companies` at `/api/users/companies`). The list below is the full
 * `app.openapi()["paths"]` set for that prefix, cross-checked against the
 * callers: `features/auth/authService.ts` (bare, `visit`, `enabled-companies`),
 * `features/savedFilters/savedFiltersApi.ts` (the `saved-filters` family),
 * `features/userCompanies/userCompaniesApi.ts` (the `companies` family) and
 * `features/userCompanies/customJobsClient.ts` (`companies/jobs`).
 *
 * `companies/jobs` is listed explicitly even though `companies/:id` would also
 * match it — FastAPI declares the literal route first and matches it first, and
 * spelling it out here keeps this table readable against the backend's.
 */
const PROXIED_ROUTES = [
  '', // GET/PUT /api/users
  'visit', // POST
  'enabled-companies', // GET/PUT
  'saved-filters', // GET/PUT
  'saved-filters/keyword-lists', // GET/POST
  'saved-filters/keyword-lists/:id', // PATCH/DELETE
  'companies', // GET/POST
  'companies/jobs', // GET (keyset-paged; see X-Next-Cursor below)
  'companies/:id', // DELETE
  'companies/:id/jobs', // GET
] as const;

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path, ...queryParams } = req.query;

  // Canonical form only, and note the upstream URL below is built from THIS
  // value: the allowlist has already constrained it to one of the shapes
  // above, so the raw client-supplied path never reaches the upstream request.
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
  const targetUrl = `${backendUrl}/api/users${targetPath ? `/${targetPath}` : ''}${queryString}`;

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
    // Never follow a redirect. Node's fetch defaults to `redirect: 'follow'`
    // and PRESERVES headers across a same-origin 3xx — including the
    // X-Internal-Key this proxy injects. The backend app runs with Starlette's
    // default `redirect_slashes=True`, so a trailing slash 307s to the
    // canonical path; 'manual' means the proxy can never be used to follow a
    // redirect into a path the allowlist above just refused. (Mirrors
    // api/jobs-qa.ts, where that exact chain was a working bypass.)
    redirect: 'manual',
  };

  // Forward the request body for any mutating method that carries one.
  // Gated on the method allowlist because Vercel Dev parses an empty GET
  // body as ``{}`` (non-null), and Node's native ``fetch`` rejects GET/HEAD
  // with a body ("Request with GET/HEAD method cannot have body"). The
  // allowlist preserves PATCH/DELETE support while keeping GET working.
  if (METHODS_WITH_BODY.has(req.method ?? '') && req.body != null) {
    fetchOptions.body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
  }

  try {
    const response = await fetch(targetUrl, fetchOptions);
    // `GET /api/users/companies/jobs` (the owner-scoped half of the Recent Jobs
    // feed) pages with the same keyset contract as `/api/jobs`, and the ABSENCE
    // of this header is its only end-of-walk signal. `forwardResponse` copies
    // status + body only, so without this line the client would see every page
    // as the last one and silently stop after the first. Copied only when
    // present, exactly as `api/jobs.ts` does, and set BEFORE `forwardResponse`
    // because that helper ends the response.
    const nextCursor = response.headers.get('X-Next-Cursor');
    if (nextCursor) res.setHeader('X-Next-Cursor', nextCursor);
    await forwardResponse(response, res);
  } catch (error) {
    // Network-level failure (DNS, connection refused, upstream down).
    // 502 signals "upstream is unavailable" rather than "we have a bug."
    console.error('[api/users] Upstream fetch failed:', error);
    res.status(502).json({
      error: 'Upstream backend unavailable',
      details: error instanceof Error ? error.message : String(error),
    });
  }
}
