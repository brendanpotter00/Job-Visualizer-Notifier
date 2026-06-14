import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';

const METHODS_WITH_BODY = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path, ...queryParams } = req.query;

  const pathParts = Array.isArray(path) ? path : [path].filter(Boolean);
  const targetPath = pathParts.join('/');

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(queryParams)) {
    if (value !== undefined) {
      params.set(key, String(value));
    }
  }
  const queryString = params.size ? `?${params}` : '';

  const backendUrl = getBackendUrl(req);
  const targetUrl = `${backendUrl}/api/feedback${targetPath ? `/${targetPath}` : ''}${queryString}`;

  const headers: Record<string, string> = {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    ...getInternalKeyHeader(),
  };
  // Forward the user's Bearer token when present so the backend can attach
  // the submitter's identity; absent for anonymous feedback (stored as null).
  if (req.headers.authorization) {
    headers['Authorization'] = req.headers.authorization;
  }
  // Forward the caller's IP so the backend can rate-limit anonymous feedback
  // per-IP (this is a public, unauthenticated write endpoint). Vercel populates
  // ``x-forwarded-for`` (falling back to ``x-real-ip``); the backend keys on the
  // first token. See src/backend/api/services/rate_limit.py for the spoofing
  // caveat inherent to any IP-based throttle.
  const forwardedFor = req.headers['x-forwarded-for'] ?? req.headers['x-real-ip'];
  if (forwardedFor) {
    headers['X-Forwarded-For'] = Array.isArray(forwardedFor)
      ? forwardedFor[0]
      : forwardedFor;
  }

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
    console.error('[api/feedback] Upstream fetch failed:', error);
    res.status(502).json({
      error: 'Upstream backend unavailable',
      details: error instanceof Error ? error.message : String(error),
    });
  }
}
