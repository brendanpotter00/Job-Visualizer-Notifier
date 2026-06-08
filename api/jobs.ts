import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { status, company, companies, limit, offset } = req.query;

  const params = new URLSearchParams();
  if (status) params.set('status', String(status));
  if (company) params.set('company', String(company));
  if (companies) params.set('companies', String(companies));
  if (limit) params.set('limit', String(limit));
  if (offset) params.set('offset', String(offset));

  const backendUrl = getBackendUrl(req);
  const url = `${backendUrl}/api/jobs?${params}`;

  try {
    const response = await fetch(url, { headers: getInternalKeyHeader() });
    await forwardResponse(response, res);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch from backend' });
  }
}
