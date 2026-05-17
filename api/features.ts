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
  };

  // Forward the request body for ANY method that has one. Parity with
  // ``api/admin.ts`` / ``api/users.ts`` / ``api/jobs-qa.ts`` — the
  // previous PUT/POST-only restriction would silently drop a PATCH or
  // DELETE body once a future endpoint started carrying one.
  if (req.body != null) {
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
