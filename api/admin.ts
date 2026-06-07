import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path, ...queryParams } = req.query;

  const pathParts = Array.isArray(path) ? path : [path].filter(Boolean);
  const targetPath = pathParts.join('/');

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
  };

  // Forward the request body for ANY method that has one. GET typically
  // has no body so this is a no-op there; the previous PUT/POST-only
  // restriction would have silently dropped a PATCH or DELETE body once
  // a future admin endpoint started carrying one.
  if (req.body != null) {
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
