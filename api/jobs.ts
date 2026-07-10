import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path, status, company, companies, limit, offset, category, level } = req.query;

  // Sub-path routing (vercel.json rewrites /api/jobs/:path -> ?path=...).
  // Only the facets catalog is exposed; the internal enrichment routes must
  // never be reachable through this public proxy.
  const sub = Array.isArray(path) ? path.join('/') : path;
  if (sub && sub !== 'facets') {
    res.status(404).json({ error: 'Not found' });
    return;
  }

  const params = new URLSearchParams();
  if (status) params.set('status', String(status));
  if (company) params.set('company', String(company));
  if (companies) params.set('companies', String(companies));
  if (limit) params.set('limit', String(limit));
  if (offset) params.set('offset', String(offset));
  // Enrichment facet filters (server-side; the SPA also filters client-side —
  // forwarding keeps ?category=&level= usable for direct API consumers).
  if (category) params.set('category', String(category));
  if (level) params.set('level', String(level));

  const backendUrl = getBackendUrl(req);
  const queryString = params.size ? `?${params}` : '';
  const url = `${backendUrl}/api/jobs${sub ? `/${sub}` : ''}${queryString}`;

  try {
    const response = await fetch(url, { headers: getInternalKeyHeader() });
    await forwardResponse(response, res);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch from backend' });
  }
}
