import type { VercelRequest } from '@vercel/node';

// Returns BACKEND_API_URL env var, falling back to localhost:8000 for local development
export const getBackendUrl = (req: VercelRequest): string => {
  return process.env.BACKEND_API_URL || 'http://localhost:8000';
};
