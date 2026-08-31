import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';
import { PROXY_REJECTION, resolveProxyPath } from './utils/proxyPath';

const METHODS_WITH_BODY = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/**
 * Every backend route reachable under `/api/feedback`, and nothing else. See
 * `api/utils/proxyPath.ts` for why this is an allowlist and not a `..` filter.
 *
 * The backend `feedback` router declares exactly ONE route — `POST ""` — and
 * `features/feedback/feedbackApi.ts` spells its url as the empty string. So the
 * legitimate surface here is a single bare path with no sub-paths at all.
 *
 * This is the proxy the production bypass was demonstrated against, and the
 * reason is precisely that it never had a sub-path to justify forwarding one:
 * `/api/feedback/:path(.*)` existed in vercel.json purely as boilerplate.
 */
const PROXIED_ROUTES = [
  '', // POST /api/feedback — the only route
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
  const targetUrl = `${backendUrl}/api/feedback${targetPath ? `/${targetPath}` : ''}${queryString}`;

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...getInternalKeyHeader(),
  };
  // Forward the user's Bearer token when present so the backend can attach
  // the submitter's identity; absent for anonymous feedback (stored as null).
  if (req.headers.authorization) {
    headers['Authorization'] = req.headers.authorization;
  }
  // Forward the caller's IP so the backend can rate-limit anonymous feedback
  // per-IP (this is a public, unauthenticated write endpoint). Vercel populates
  // ``x-forwarded-for`` (falling back to ``x-real-ip``); the backend keys on the
  // first token. See src/backend/api/services/rate_limit.py for the spoofing
  // caveat inherent to any IP-based throttle.
  const forwardedFor = req.headers['x-forwarded-for'] ?? req.headers['x-real-ip'];
  if (forwardedFor) {
    headers['X-Forwarded-For'] = Array.isArray(forwardedFor)
      ? forwardedFor[0]
      : forwardedFor;
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
    console.error('[api/feedback] Upstream fetch failed:', error);
    res.status(502).json({
      error: 'Upstream backend unavailable',
      details: error instanceof Error ? error.message : String(error),
    });
  }
}
