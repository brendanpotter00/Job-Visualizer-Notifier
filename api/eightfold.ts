import type { VercelRequest, VercelResponse } from '@vercel/node';

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-Eightfold-Tenant-Host',
} as const;

/**
 * SSRF guard — only allow tenant hosts that are known Eightfold endpoints.
 * Matches either `*.eightfold.ai` (Eightfold's managed tenant subdomains) or
 * the explicit allowlist below for tenants that use vanity domains.
 *
 * To add a new Eightfold-hosted company with a vanity domain, add its host here
 * AND add the matching `createEightfoldCompany(...)` entry in
 * `src/frontend/src/config/companies.ts`. Keep the two in sync.
 */
const EIGHTFOLD_HOST_PATTERN = /^(?:[a-z0-9-]+\.)*eightfold\.ai$/i;
const EIGHTFOLD_VANITY_HOSTS: ReadonlySet<string> = new Set([
  'explore.jobs.netflix.net',
]);

function isAllowedEightfoldHost(host: string): boolean {
  const normalized = host.toLowerCase();
  return EIGHTFOLD_VANITY_HOSTS.has(normalized) || EIGHTFOLD_HOST_PATTERN.test(normalized);
}

function setCorsHeaders(res: VercelResponse): void {
  Object.entries(CORS_HEADERS).forEach(([key, value]) => {
    res.setHeader(key, value);
  });
}

/**
 * Vercel serverless function to proxy Eightfold AI job board requests.
 * Routes: /api/eightfold/api/apply/v2/jobs?... -> https://{tenantHost}/api/apply/v2/jobs?...
 *
 * The target tenant host is passed via the `X-Eightfold-Tenant-Host` header
 * (not the path), so a single proxy can serve multiple Eightfold-hosted companies.
 */
export default async function handler(req: VercelRequest, res: VercelResponse) {
  // Allow only GET and OPTIONS
  if (req.method !== 'GET' && req.method !== 'OPTIONS') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  // CORS preflight
  if (req.method === 'OPTIONS') {
    setCorsHeaders(res);
    return res.status(200).end();
  }

  // Extract path after /api/eightfold (catch-all rewrite in vercel.json)
  const { query } = req;
  const pathParts = Array.isArray(query.path) ? query.path : [query.path].filter(Boolean);
  const targetPath = pathParts.join('/');

  // Path restriction — only allow Eightfold's public apply API
  if (!targetPath || !targetPath.startsWith('api/apply/')) {
    setCorsHeaders(res);
    return res.status(400).json({
      error: 'Invalid Eightfold path. Expected prefix: api/apply/',
    });
  }

  // Tenant host header is required
  const tenantHeader = req.headers['x-eightfold-tenant-host'];
  if (typeof tenantHeader !== 'string' || !tenantHeader.trim()) {
    setCorsHeaders(res);
    return res.status(400).json({ error: 'Missing X-Eightfold-Tenant-Host header' });
  }

  const tenantHost = tenantHeader.trim();
  if (!isAllowedEightfoldHost(tenantHost)) {
    setCorsHeaders(res);
    return res.status(400).json({ error: 'Invalid X-Eightfold-Tenant-Host value' });
  }

  // Preserve query string from the original request (domain, num, start, ...).
  // `query.path` is stripped; we rebuild the querystring from everything else.
  const qsParams = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (key === 'path') continue;
    if (Array.isArray(value)) {
      for (const v of value) qsParams.append(key, v);
    } else if (typeof value === 'string') {
      qsParams.append(key, value);
    }
  }
  const qs = qsParams.toString();
  const targetUrl = `https://${tenantHost}/${targetPath}${qs ? `?${qs}` : ''}`;

  console.log('[Eightfold Proxy] Request:', {
    method: req.method,
    targetUrl,
  });

  try {
    const response = await fetch(targetUrl, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        'User-Agent': 'Job-Visualizer-Notifier/1.0',
      },
    });

    console.log('[Eightfold Proxy] Response status:', response.status);

    const data = await response.json();

    setCorsHeaders(res);
    return res.status(response.status).json(data);
  } catch (error) {
    console.error('[Eightfold Proxy] Error:', error);
    setCorsHeaders(res);
    return res.status(500).json({
      error: 'Proxy error',
      message: error instanceof Error ? error.message : 'Unknown error',
    });
  }
}
