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
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      const data = await response.json();
      res.status(response.status).json(data);
    } else {
      const text = await response.text();
      res.status(response.status).json({ error: text || response.statusText });
    }
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch from backend' });
  }
}
