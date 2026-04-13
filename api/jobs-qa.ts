import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';

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

  try {
    const response = await fetch(targetUrl, {
      method: req.method,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
    });
    await forwardResponse(response, res);
  } catch (error) {
    res.status(500).json({
      error: 'Failed to fetch from backend',
      details: error instanceof Error ? error.message : String(error),
    });
  }
}
