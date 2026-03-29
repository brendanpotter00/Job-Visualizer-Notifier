import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';

export default async function handler(req: VercelRequest, res: VercelResponse) {
  // Handle CORS preflight (triggered by Authorization header)
  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  const { path, ...queryParams } = req.query;

  const pathParts = Array.isArray(path) ? path : [path].filter(Boolean);
  const targetPath = pathParts.join('/');

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(queryParams)) {
    if (value !== undefined) {
      params.set(key, String(value));
    }
  }
  const queryString = params.toString() ? `?${params.toString()}` : '';

  const backendUrl = getBackendUrl(req);
  const targetUrl = `${backendUrl}/api/auth/${targetPath}${queryString}`;

  try {
    const headers: Record<string, string> = {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    };

    // Forward Authorization header for authenticated endpoints (GET /me)
    const authHeader = req.headers.authorization;
    if (authHeader) {
      headers['Authorization'] = authHeader;
    }

    const fetchOptions: RequestInit = {
      method: req.method,
      headers,
    };

    // Forward body for POST requests (POST /google with credential)
    if (req.method === 'POST' && req.body) {
      fetchOptions.body = JSON.stringify(req.body);
    }

    const response = await fetch(targetUrl, fetchOptions);
    const data = await response.json();
    res.status(response.status).json(data);
  } catch (error) {
    res.status(500).json({
      error: 'Failed to fetch from backend',
      details: error instanceof Error ? error.message : String(error),
    });
  }
}
