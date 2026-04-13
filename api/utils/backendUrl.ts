import type { VercelRequest } from '@vercel/node';

// Returns the backend API URL.
// Vercel Dev pulls cloud env vars that point to production Railway,
// so detect local dev via the request Host header and use localhost instead.
export function getBackendUrl(req: VercelRequest): string {
  const host = req.headers.host || '';
  if (host.startsWith('localhost') || host.startsWith('127.0.0.1') || host.startsWith('[::1]')) {
    return 'http://localhost:8000';
  }
  return process.env.BACKEND_API_URL || 'http://localhost:8000';
}
