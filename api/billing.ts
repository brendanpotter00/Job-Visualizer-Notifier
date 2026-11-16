import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';
import { PROXY_REJECTION, buildUpstreamUrl, resolveProxyPath } from './utils/proxyPath';

/**
 * Every backend billing route reachable under `/api/billing` (see `api/utils/proxyPath.ts`).
 * `webhook` is absent: Stripe calls Railway directly, signing the raw body a hop would re-serialize.
 */
const PROXIED_ROUTES = ['subscription', 'checkout-session', 'portal-session'] as const;

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path } = req.query;

  const targetPath = resolveProxyPath(path, PROXIED_ROUTES);
  if (targetPath === null) {
    res.status(PROXY_REJECTION.status).json(PROXY_REJECTION.body);
    return;
  }

  const targetUrl = buildUpstreamUrl(getBackendUrl(req), '/api/billing', targetPath, '');
  if (targetUrl === null) {
    res.status(PROXY_REJECTION.status).json(PROXY_REJECTION.body);
    return;
  }

  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...getInternalKeyHeader(),
  };
  if (req.headers.authorization) {
    headers['Authorization'] = req.headers.authorization;
  }

  try {
    const response = await fetch(targetUrl, {
      method: req.method,
      headers,
      // Following a same-origin 3xx would resend X-Internal-Key (see api/users.ts).
      redirect: 'manual',
    });
    await forwardResponse(response, res);
  } catch (error) {
    console.error('[api/billing] Upstream fetch failed:', error);
    res.status(502).json({ error: 'Upstream backend unavailable' });
  }
}
