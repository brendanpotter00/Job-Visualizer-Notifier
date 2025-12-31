import type { VercelRequest, VercelResponse } from '@vercel/node';

const BACKEND_URL = process.env.BACKEND_API_URL || 'http://localhost:5000';

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { status, company, limit, offset } = req.query;

  const params = new URLSearchParams();
  if (status !== undefined) params.set('status', String(status));
  if (company) params.set('company', String(company));
  if (limit) params.set('limit', String(limit));
  if (offset) params.set('offset', String(offset));

  try {
    const response = await fetch(`${BACKEND_URL}/api/jobs?${params}`);
    const data = await response.json();
    res.status(response.status).json(data);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch from backend' });
  }
}
