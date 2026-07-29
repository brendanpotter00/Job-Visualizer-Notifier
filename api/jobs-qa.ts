import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';

const METHODS_WITH_BODY = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export default async function handler(req: VercelRequest, res: VercelResponse) {
  // ===================================================================
  // Anonymous requests are refused HERE, before any upstream call.
  //
  // This function is a *public* internet endpoint (vercel.json maps
  // `/api/jobs-qa/:path(.*)` to it) and it attaches X-Internal-Key
  // UNCONDITIONALLY via getInternalKeyHeader(). So the proxy always holds
  // the key that satisfies the backend's require_internal_key middleware —
  // it is a second front door that is already inside the building.
  //
  // Until now that was safe only by accident: every route behind
  // /api/jobs-qa also carried `Depends(require_admin)`, so a request
  // arriving without an Authorization header got a 401 from the backend.
  // `GET /scraper-health` is deliberately NOT admin-gated (the scheduled
  // GitHub Action can present a static header but cannot mint an admin
  // JWT), which removed that last line of defence for that one route —
  // exposing the full internal company roster, each company's ATS, its
  // open-job count and exactly how stale its scraper is, to
  // `curl https://<app>/api/jobs-qa/scraper-health?thresholdHours=720`
  // from anywhere. CORS does not help: it is browser-side and curl
  // ignores it. Secondary cost: that endpoint runs a full aggregate over
  // job_listings while holding a pooled backend connection — cf.
  // docs/incidents/2026-05-17-recent-jobs-pool-exhaustion.md.
  //
  // Gating at the proxy rather than per-route fixes it for every present
  // AND future jobs-qa route, and keeps the fix in one place. The GitHub
  // Action is unaffected: it calls the Railway backend directly with the
  // internal key and never transits this function.
  //
  // Every legitimate browser caller is admin-authenticated already —
  // QAPage is wrapped in AdminRoute and attaches `Bearer <token>` to both
  // of its /api/jobs-qa fetches.
  // ===================================================================
  if (!req.headers.authorization) {
    res.status(401).json({ detail: 'Unauthorized' });
    return;
  }

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

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...getInternalKeyHeader(),
  };
  // Forward the caller's Bearer token. Guaranteed present by the
  // anonymous-request gate at the top of this handler; most /api/jobs-qa
  // routes are admin-gated on the backend (require_admin) and would 401
  // without it.
  headers['Authorization'] = req.headers.authorization;

  const fetchOptions: RequestInit = {
    method: req.method,
    headers,
  };

  // Forward the request body for any mutating method that carries one.
  // Gated on the method allowlist because Vercel Dev parses an empty GET
  // body as ``{}`` (non-null), and Node's native ``fetch`` rejects GET/HEAD
  // with a body ("Request with GET/HEAD method cannot have body").
  if (METHODS_WITH_BODY.has(req.method ?? '') && req.body != null) {
    fetchOptions.body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
  }

  try {
    const response = await fetch(targetUrl, fetchOptions);
    await forwardResponse(response, res);
  } catch (error) {
    // See api/admin.ts: do not leak the upstream URL / DNS error to the
    // public client — log it server-side instead.
    console.error('[api/jobs-qa] Upstream fetch failed:', error);
    res.status(502).json({ error: 'Upstream backend unavailable' });
  }
}
