import type { VercelRequest } from '@vercel/node';

// Use localhost for local development, env var for production
export const getBackendUrl = (req: VercelRequest): string => {
  const host = req.headers.host || '';
  const isLocalDev = host.includes('localhost') || host.includes('127.0.0.1');
  return isLocalDev ? 'http://localhost:5000' : (process.env.BACKEND_API_URL || 'http://localhost:5000');
};
