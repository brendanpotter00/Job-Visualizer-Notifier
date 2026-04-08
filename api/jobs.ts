import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { status, company, limit, offset } = req.query;

  const params = new URLSearchParams();
  if (status) params.set('status', String(status));
  if (company) params.set('company', String(company));
  if (limit) params.set('limit', String(limit));
  if (offset) params.set('offset', String(offset));

  const backendUrl = getBackendUrl(req);
  const url = `${backendUrl}/api/jobs?${params}`;

  try {
    const response = await fetch(url);
    const data = await response.json();

    // Cache on Vercel CDN for 5 min, serve stale up to 10 min while revalidating
    res.setHeader('Vercel-CDN-Cache-Control', 'public, s-maxage=300, stale-while-revalidate=600');
    res.setHeader('Cache-Control', 'public, max-age=0, must-revalidate');

    res.status(response.status).json(data);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch from backend' });
  }
}
