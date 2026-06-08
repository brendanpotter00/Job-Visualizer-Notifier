import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';

const METHODS_WITH_BODY = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path, ...queryParams } = req.query;

  // Build the path from the catch-all route
  const pathParts = Array.isArray(path) ? path : [path].filter(Boolean);
  const targetPath = pathParts.join('/');

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
  // /api/jobs-qa is admin-gated on the backend (require_admin). The proxy must
  // forward the caller's Bearer token or every request comes through anonymous
  // and the backend returns 401.
  if (req.headers.authorization) {
    headers['Authorization'] = req.headers.authorization;
  }

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
