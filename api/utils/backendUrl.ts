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
    // Local dev honors LOCAL_BACKEND_URL so a background / experimental stack can run
    // the backend on a non-standard port (e.g. http://localhost:8100) without
    // colliding with a developer's own stack on the default 8000. Unset => 8000.
    return process.env.LOCAL_BACKEND_URL || 'http://localhost:8000';
  }
  return process.env.BACKEND_API_URL || 'http://localhost:8000';
}
