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
 *
 * `GET /api/jobs/search` deliberately does NOT use a header — it returns
 * `{jobs, nextCursor, meta}` — precisely so its cursor cannot be lost this way.
 */
const NEXT_CURSOR_HEADER = 'x-next-cursor';

/**
 * Repeatable query parameters on `GET /api/jobs/search` (multi-select filters).
 *
 * They must be `append`ed rather than `set`, and Vercel hands a repeated param
 * back as `string[]`. Collapsing that array to one value — which `String(x)` on
 * an array quietly does, joining with commas — would turn two selected
 * categories into one bogus slug named `a,b` that matches nothing. Commas are
 * also why these cannot be a comma-joined scalar in the first place: canonical
 * location names ("Austin, TX, US") and free-text keywords contain them.
 */
const REPEATABLE_PARAMS = ['category', 'level', 'company', 'location', 'include', 'exclude'] as const;

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path, status, company, companies, limit, offset, category, level, since, cursor } =
    req.query;

  // Sub-path routing (vercel.json rewrites /api/jobs/:path -> ?path=...).
  // Only the facets catalog and the Recent page's search endpoint are exposed;
  // the internal enrichment routes must never be reachable through this public
  // proxy.
  //
  // The allowlist was always right here — a single literal comparison can't be
  // traversed. What it lacked was NORMALIZATION: `?path=facets/` and the array
  // form `?path=facets&path=` both 404'd a legitimate caller. Sharing
  // `resolveProxyPath` with the other seven proxies fixes that and keeps one
  // implementation of the control instead of eight.
  //
  // `:source/:job` is the single-posting detail route `GET
  // /api/jobs/{source_id}/{job_id}`. It stayed off the allowlist until something
  // actually needed it — the WebMCP `get_job` tool now does, so this is the
  // deliberate decision the old comment asked for, not a cleanup. Two dynamic
  // segments matched by the `:param` form `resolveProxyPath` already supports
  // (each `:name` matches exactly one already-canonicalized segment); a
  // traversal like `/api/jobs/../admin` is rejected in canonicalization before
  // it can reach this pattern. The GET-only detail read injects the internal key
  // like every other sub-path and 404s cleanly when no row matches.
  const sub = resolveProxyPath(path, ['', 'facets', 'search', ':source/:job']);
  if (sub === null) {
    res.status(PROXY_REJECTION.status).json(PROXY_REJECTION.body);
    return;
  }

  const params = new URLSearchParams();
  if (status) params.set('status', String(status));
  if (companies) params.set('companies', String(companies));
  if (limit) params.set('limit', String(limit));
  if (offset) params.set('offset', String(offset));
  // Keyset pagination (backend contract: see src/backend/api/routers/jobs.py).
  // `since` bounds the result set by first_seen_at; `cursor` is the opaque token
  // from the previous page's X-Next-Cursor header (or `nextCursor` body field on
  // the search endpoint).
  //
  // Forwarded on PRESENCE, not truthiness, unlike the filters below. `?cursor=`
  // with an empty value is a client bug the backend answers with a 422; a
  // truthiness check would drop it here and hand back page 1 with a 200 instead —
  // converting a loud error into a silent restart of the caller's paging loop.
  if (since !== undefined) params.set('since', String(since));
  if (cursor !== undefined) params.set('cursor', String(cursor));

  if (sub === 'search') {
    // The search endpoint takes every facet filter as a REPEATABLE param, so it
    // cannot share the scalar handling below. Presence-based for the same reason
    // as since/cursor: `?include=` is a caller bug the backend reports as a 422,
    // and silently dropping it would hand back an unfiltered result set the
    // caller believes was filtered.
    for (const name of REPEATABLE_PARAMS) {
      const value = req.query[name];
      if (value === undefined) continue;
      for (const item of Array.isArray(value) ? value : [value]) {
        params.append(name, String(item));
      }
    }
  } else {
    if (company) params.set('company', String(company));
    // Enrichment facet filters, single-valued on the legacy list endpoint.
    // Truthy-checked, unlike the search params above: on this endpoint an empty
    // filter genuinely means "no filter", so dropping it is the correct reading.
    if (category) params.set('category', String(category));
    if (level) params.set('level', String(level));
  }

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
    // Edge-cache ONLY the facets catalog. It is effectively immutable — the
    // enrichment taxonomy changes only on a migration+deploy — so a full-day
    // edge TTL with a week of stale-while-revalidate removes the ~0.7 s
    // Vercel->Railway hop from every visitor after the first. `Cache-Control`
    // stays `max-age=0` so browsers always revalidate to the edge and a purge
    // is instantly visible; only `Vercel-CDN-Cache-Control` pins the edge copy.
    // Set BEFORE forwardResponse (it ends the response), and gated so `search`
    // (append-heavy, the slow query) and the legacy company list stay uncached.
    // Also gated on `response.ok`: forwardResponse preserves the upstream status,
    // so an error (a 4xx/5xx, or a `redirect:'manual'` 3xx) must not be edge-cached
    // for a day under the facets key.
    if (sub === 'facets' && response.ok) {
      res.setHeader('Cache-Control', 'public, max-age=0, must-revalidate');
      res.setHeader(
        'Vercel-CDN-Cache-Control',
        'public, s-maxage=86400, stale-while-revalidate=604800',
      );
    }
    await forwardResponse(response, res);
  } catch (error) {
    // Logged, never returned: Node's fetch errors carry the internal backend
    // hostname and port, which a public 500 must not expose. Same split as every
    // other proxy in this directory (api/locations.ts, api/admin.ts, …) — this
    // was the one that swallowed the reason entirely, leaving an opaque 500 with
    // nothing on either side of the wire to debug from.
    console.error('[api/jobs] Upstream fetch failed:', error);
    res.status(500).json({ error: 'Failed to fetch from backend' });
  }
}
