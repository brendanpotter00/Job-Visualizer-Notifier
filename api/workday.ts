import type { VercelRequest, VercelResponse } from '@vercel/node';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-Workday-Base-Url',
} as const;

const WORKDAY_URL_PATTERN = /^https:\/\/[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com$/i;

function setCorsHeaders(res: VercelResponse): void {
  Object.entries(CORS_HEADERS).forEach(([key, value]) => {
    res.setHeader(key, value);
  });
}

/**
 * Vercel serverless function to proxy Workday API requests
 * Routes: /api/workday/* -> https://{dynamic-workday-host}/*
 *
 * NOTE: Unlike Greenhouse/Lever/Ashby, Workday requires POST requests
 */
export default async function handler(req: VercelRequest, res: VercelResponse) {
  // Only allow POST and OPTIONS (for CORS preflight)
  if (req.method !== 'POST' && req.method !== 'OPTIONS') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // Handle CORS preflight
  if (req.method === 'OPTIONS') {
    setCorsHeaders(res);
    return res.status(200).end();
  }

  // Extract the path after /api/workday
  const { query } = req;
  const pathParts = Array.isArray(query.path) ? query.path : [query.path].filter(Boolean);
  const targetPath = pathParts.join('/');

  // CRITICAL: Workday client sends full base URL in request
  // Path format: /wday/cxs/{tenant}/{careerSite}/jobs
  // We need to extract the tenant from the path to build the correct target URL

  // Parse tenant from path: /wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs
  const pathMatch = targetPath.match(/^wday\/cxs\/([^/]+)\//);
  if (!pathMatch) {
    return res.status(400).json({
      error: 'Invalid Workday path format. Expected: /wday/cxs/{tenant}/{careerSite}/jobs',
    });
  }

  const tenant = pathMatch[1]; // e.g., "nvidia"

  // Get base URL from header or fallback to wd5
  const baseUrlHeader = req.headers['x-workday-base-url'];
  let workdayBaseUrl: string;

  if (typeof baseUrlHeader === 'string') {
    if (!WORKDAY_URL_PATTERN.test(baseUrlHeader)) {
      return res.status(400).json({ error: 'Invalid Workday base URL format' });
    }
    workdayBaseUrl = baseUrlHeader;
  } else {
    // Backwards compatibility: default to wd5
    workdayBaseUrl = `https://${tenant}.wd5.myworkdayjobs.com`;
  }

  // Build the full Workday API URL
  const targetUrl = `${workdayBaseUrl}/${targetPath}`;

  console.log('[Workday Proxy] Request:', {
    method: req.method,
    targetUrl,
    bodyLength: JSON.stringify(req.body).length,
  });

  try {
    // Forward the POST request to Workday API
    const response = await fetch(targetUrl, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'User-Agent': 'Job-Visualizer-Notifier/1.0',
      },
      body: JSON.stringify(req.body), // Forward the request body
    });

    console.log('[Workday Proxy] Response status:', response.status);

    // Get response data
    const data = await response.json();

    setCorsHeaders(res);

    // Forward the status code and data
    return res.status(response.status).json(data);
  } catch (error) {
    console.error('[Workday Proxy] Error:', error);

    setCorsHeaders(res);
    return res.status(500).json({
      error: 'Proxy error',
      message: error instanceof Error ? error.message : 'Unknown error',
    });
  }
}
