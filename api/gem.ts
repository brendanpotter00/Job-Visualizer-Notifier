import type { VercelRequest, VercelResponse } from '@vercel/node';

/**
 * Vercel serverless function to proxy Gem API requests
 * Routes: /api/gem/* -> https://api.gem.com/*
 */
export default async function handler(req: VercelRequest, res: VercelResponse) {
  // Handle CORS preflight requests
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    return res.status(200).end();
  }

  // Extract the path after /api/gem
  const { query } = req;
  const pathParts = Array.isArray(query.path) ? query.path : [query.path].filter(Boolean);
  const targetPath = pathParts.join('/');

  // Build the full Gem API URL
  const gemBaseUrl = 'https://api.gem.com';
  const targetUrl = `${gemBaseUrl}/${targetPath}${req.url?.includes('?') ? req.url.substring(req.url.indexOf('?')) : ''}`;

  console.log('[Gem Proxy] Request:', {
    method: req.method,
    targetUrl,
  });

  try {
    // Forward the request to Gem API
    const response = await fetch(targetUrl, {
      method: req.method,
      headers: {
        'Accept': 'application/json',
        'User-Agent': 'Job-Visualizer-Notifier/1.0',
      },
    });

    console.log('[Gem Proxy] Response status:', response.status);

    // Get response data
    const data = await response.json();

    // Set CORS headers to allow browser requests
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    // Cache on Vercel CDN for 20 min, serve stale up to 40 min while revalidating
    res.setHeader('Vercel-CDN-Cache-Control', 'public, s-maxage=1200, stale-while-revalidate=2400');
    res.setHeader('Cache-Control', 'public, max-age=0, must-revalidate');

    // Forward the status code and data
    res.status(response.status).json(data);
  } catch (error) {
    console.error('[Gem Proxy] Error:', error);

    res.setHeader('Access-Control-Allow-Origin', '*');
    res.status(500).json({
      error: 'Proxy error',
      message: error instanceof Error ? error.message : 'Unknown error',
    });
  }
}
