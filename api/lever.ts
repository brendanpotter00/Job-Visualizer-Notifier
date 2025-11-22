import type { VercelRequest, VercelResponse } from '@vercel/node';

/**
 * Vercel serverless function to proxy Lever API requests
 * Routes: /api/lever/* -> https://api.lever.co/*
 */
export default async function handler(req: VercelRequest, res: VercelResponse) {
  // Extract the path after /api/lever
  const { query } = req;
  const pathParts = Array.isArray(query.path) ? query.path : [query.path].filter(Boolean);
  const targetPath = pathParts.join('/');

  // Build the full Lever API URL
  const leverBaseUrl = 'https://api.lever.co';
  const targetUrl = `${leverBaseUrl}/${targetPath}${req.url?.includes('?') ? req.url.substring(req.url.indexOf('?')) : ''}`;

  console.log('[Lever Proxy] Request:', {
    method: req.method,
    targetUrl,
    headers: req.headers,
  });

  try {
    // Forward the request to Lever API
    const response = await fetch(targetUrl, {
      method: req.method,
      headers: {
        'Accept': 'application/json',
        'User-Agent': 'Job-Visualizer-Notifier/1.0',
      },
    });

    console.log('[Lever Proxy] Response status:', response.status);

    // Get response data
    const data = await response.json();

    // Set CORS headers to allow browser requests
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    // Forward the status code and data
    res.status(response.status).json(data);
  } catch (error) {
    console.error('[Lever Proxy] Error:', error);

    res.setHeader('Access-Control-Allow-Origin', '*');
    res.status(500).json({
      error: 'Proxy error',
      message: error instanceof Error ? error.message : 'Unknown error',
    });
  }
}
