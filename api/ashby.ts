import type { VercelRequest, VercelResponse } from '@vercel/node';

/**
 * Vercel serverless function to proxy Ashby API requests
 * Routes: /api/ashby/* -> https://api.ashbyhq.com/*
 */
export default async function handler(req: VercelRequest, res: VercelResponse) {
  // Extract the path after /api/ashby
  const { query } = req;
  const pathParts = Array.isArray(query.path) ? query.path : [query.path].filter(Boolean);
  const targetPath = pathParts.join('/');

  // Build the full Ashby API URL
  const ashbyBaseUrl = 'https://api.ashbyhq.com';
  const targetUrl = `${ashbyBaseUrl}/${targetPath}${req.url?.includes('?') ? req.url.substring(req.url.indexOf('?')) : ''}`;

  console.log('[Ashby Proxy] Request:', {
    method: req.method,
    targetUrl,
    headers: req.headers,
  });

  try {
    // Forward the request to Ashby API
    const response = await fetch(targetUrl, {
      method: req.method,
      headers: {
        'Accept': 'application/json',
        'User-Agent': 'Job-Visualizer-Notifier/1.0',
      },
    });

    console.log('[Ashby Proxy] Response status:', response.status);

    // Get response data
    const data = await response.json();

    // Set CORS headers to allow browser requests
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    // Forward the status code and data
    res.status(response.status).json(data);
  } catch (error) {
    console.error('[Ashby Proxy] Error:', error);

    res.setHeader('Access-Control-Allow-Origin', '*');
    res.status(500).json({
      error: 'Proxy error',
      message: error instanceof Error ? error.message : 'Unknown error',
    });
  }
}
