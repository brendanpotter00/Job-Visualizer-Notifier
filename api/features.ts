import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';
import { PROXY_REJECTION, resolveProxyPath } from './utils/proxyPath';

const METHODS_WITH_BODY = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Every backend route reachable under `/api/features`, and nothing else. See
 * `api/utils/proxyPath.ts` for why this is an allowlist and not a `..` filter.
 *
 * The backend `features` router declares two: `GET ""` and
 * `POST|DELETE "/{feature_id}/upvote"`. `features/features/featuresApi.ts`
 * calls exactly those. A BARE feature id (`/api/features/some-slug`) is NOT a
 * backend route and is not allowlisted, even though the old proxy forwarded it.
 */
const PROXIED_ROUTES = [
  '', // GET /api/features — the vote board
  ':id/upvote', // POST/DELETE — cast or withdraw a vote
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
  const targetUrl = `${backendUrl}/api/features${targetPath ? `/${targetPath}` : ''}${queryString}`;

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
    console.error('[api/features] Upstream fetch failed:', error);
    res.status(502).json({
      error: 'Upstream backend unavailable',
      details: error instanceof Error ? error.message : String(error),
    });
  }
}
