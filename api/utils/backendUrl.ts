import type { VercelRequest } from '@vercel/node';

// Returns the backend API URL.
// Vercel Dev pulls cloud env vars that point to production Railway,
// so detect local dev via the request Host header and use localhost instead.
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);

export function getBackendUrl(req: VercelRequest): string {
  const rawHost = req.headers.host || '';
  // Strip port, then strip surrounding brackets for IPv6 literals ([::1]).
  const hostname = rawHost.replace(/:\d+$/, '').replace(/^\[|\]$/g, '');
  if (LOCAL_HOSTS.has(hostname)) {
    return 'http://localhost:8000';
  }
  return process.env.BACKEND_API_URL || 'http://localhost:8000';
}
