import type { VercelRequest, VercelResponse } from '@vercel/node';

/**
 * Vercel serverless function to proxy Workday API requests
 * Routes: /api/workday/{base64url-encoded-domain}/* -> https://{decoded-domain}/*
 *
 * Unlike other ATS providers, Workday:
 * - Uses POST requests (not GET)
 * - Requires request body forwarding (pagination, filters, search)
 * - Has company-specific domains (e.g., nvidia.wd5.myworkdayjobs.com)
 */
export default async function handler(req: VercelRequest, res: VercelResponse) {
  // Extract the path after /api/workday
  const { query } = req;
  const pathParts = Array.isArray(query.path) ? query.path : [query.path].filter(Boolean);

  // First path segment is the base64url-encoded domain
  const encodedDomain = pathParts[0];
  const remainingPath = pathParts.slice(1).join('/');

  if (!encodedDomain) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    return res.status(400).json({
      error: 'Bad Request',
      message: 'Missing encoded domain in path',
    });
  }

  // Decode domain from base64url (convert base64url back to base64, then decode)
  let domain: string;
  try {
    // Convert base64url to base64
    const base64 = encodedDomain.replace(/-/g, '+').replace(/_/g, '/');
    // Decode from base64
    domain = Buffer.from(base64, 'base64').toString('utf-8');
  } catch (err) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    return res.status(400).json({
      error: 'Bad Request',
      message: 'Invalid base64url-encoded domain',
    });
  }

  // Build the full Workday API URL
  const targetUrl = `https://${domain}/${remainingPath}`;

  // Parse request body if it's a Buffer
  let requestBody = req.body;
  if (Buffer.isBuffer(requestBody)) {
    try {
      requestBody = JSON.parse(requestBody.toString('utf-8'));
    } catch (err) {
      res.setHeader('Access-Control-Allow-Origin', '*');
      return res.status(400).json({
        error: 'Bad Request',
        message: 'Invalid JSON in request body',
      });
    }
  }

  console.log('[Workday Proxy] Request:', {
    method: req.method,
    encodedDomain,
    decodedDomain: domain,
    targetUrl,
    hasBody: !!requestBody,
    bodyType: typeof requestBody,
  });

  try {
    // Forward the request to Workday API
    const response = await fetch(targetUrl, {
      method: req.method,
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'User-Agent': 'Job-Visualizer-Notifier/1.0',
      },
      // Forward POST body for pagination/filters/search
      body: req.method === 'POST' ? JSON.stringify(requestBody) : undefined,
    });

    console.log('[Workday Proxy] Response status:', response.status);

    // Get response data
    const data = await response.json();

    // Set CORS headers to allow browser requests
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    // Forward the status code and data
    res.status(response.status).json(data);
  } catch (error) {
    console.error('[Workday Proxy] Error:', error);

    res.setHeader('Access-Control-Allow-Origin', '*');
    res.status(500).json({
      error: 'Proxy error',
      message: error instanceof Error ? error.message : 'Unknown error',
    });
  }
}
