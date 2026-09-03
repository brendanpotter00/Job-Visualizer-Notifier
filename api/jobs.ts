import type { VercelRequest, VercelResponse } from '@vercel/node';
import { getBackendUrl } from './utils/backendUrl';
import { forwardResponse } from './utils/forwardResponse';
import { getInternalKeyHeader } from './utils/internalKey';
import { PROXY_REJECTION, resolveProxyPath } from './utils/proxyPath';

/**
 * Opaque keyset-pagination token minted by the backend's `GET /api/jobs`.
 *
 * `forwardResponse` copies status + body ONLY, so a response header dies at this
 * proxy unless it is explicitly re-emitted. That failure is silent in exactly the
 * way this pagination work exists to prevent: the array forwards fine, the SPA
 * sees no next-page token, and the walk stops after page 1 looking like a
 * legitimate end-of-results.
 */
const NEXT_CURSOR_HEADER = 'x-next-cursor';

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path, status, company, companies, limit, offset, category, level, since, cursor } =
    req.query;

  // Sub-path routing (vercel.json rewrites /api/jobs/:path -> ?path=...).
  // Only the facets catalog is exposed; the internal enrichment routes must
  // never be reachable through this public proxy.
  //
  // The allowlist was always right here — a single literal comparison can't be
  // traversed. What it lacked was NORMALIZATION: `?path=facets/` and the array
  // form `?path=facets&path=` both 404'd a legitimate caller. Sharing
  // `resolveProxyPath` with the other seven proxies fixes that and keeps one
  // implementation of the control instead of eight.
  //
  // NOT allowlisted, deliberately: `GET /api/jobs/{source_id}/{job_id}` exists
  // on the backend but no frontend caller uses it, and widening a public
  // key-injecting proxy is a decision, not a cleanup. Add it here (with a test)
  // when something actually needs it.
  const sub = resolveProxyPath(path, ['', 'facets']);
  if (sub === null) {
    res.status(PROXY_REJECTION.status).json(PROXY_REJECTION.body);
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
  // Keyset pagination (backend contract: see src/backend/api/routers/jobs.py).
  // `since` bounds the result set by first_seen_at; `cursor` is the opaque token
  // from the previous page's X-Next-Cursor header.
  //
  // Forwarded on PRESENCE, not truthiness, unlike the filters above. `?cursor=`
  // with an empty value is a client bug the backend answers with a 422; a
  // truthiness check would drop it here and hand back page 1 with a 200 instead —
  // converting a loud error into a silent restart of the caller's paging loop.
  // The filters above can stay truthy-checked: an empty filter genuinely means
  // "no filter", so dropping it is the correct reading.
  if (since !== undefined) params.set('since', String(since));
  if (cursor !== undefined) params.set('cursor', String(cursor));

  const backendUrl = getBackendUrl(req);
  const queryString = params.size ? `?${params}` : '';
  const url = `${backendUrl}/api/jobs${sub ? `/${sub}` : ''}${queryString}`;

  try {
    const response = await fetch(url, {
      headers: getInternalKeyHeader(),
      // Never follow a redirect — Node's fetch preserves headers (including the
      // injected X-Internal-Key) across a same-origin 3xx. See api/jobs-qa.ts.
      redirect: 'manual',
    });
    // Must be set BEFORE forwardResponse — that helper ends the response.
    // Absent on the last page and on the legacy (no since/cursor) path, which is
    // the contract's "end of results" signal, so only copy it when present.
    const nextCursor = response.headers.get(NEXT_CURSOR_HEADER);
    if (nextCursor) res.setHeader('X-Next-Cursor', nextCursor);
    await forwardResponse(response, res);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch from backend' });
  }
}
