import type { VercelRequest, VercelResponse } from '@vercel/node';

const BACKEND_URL = process.env.BACKEND_API_URL || 'http://localhost:5000';

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

  const targetUrl = `${BACKEND_URL}/api/jobs-qa/${targetPath}${queryString}`;

  try {
    const response = await fetch(targetUrl, {
      method: req.method,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
      },
    });

    const data = await response.json();

    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    res.status(response.status).json(data);
  } catch (error) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.status(500).json({
      error: 'Proxy error',
      message: error instanceof Error ? error.message : 'Unknown error',
    });
  }
}
