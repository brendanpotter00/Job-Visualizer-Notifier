import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getBackendUrl } from "./utils/backendUrl";
import { forwardResponse } from "./utils/forwardResponse";
import { getInternalKeyHeader } from "./utils/internalKey";
import { PROXY_REJECTION, resolveProxyPath } from "./utils/proxyPath";

/**
 * Public proxy for canonical-location search — forwards to the backend
 * `GET /api/locations/search` (no user auth; the internal key proves the call
 * came from this proxy). Feeds the Location filter dropdown on the signed-out-
 * friendly Recent Jobs and company hiring-trend pages.
 *
 * vercel.json rewrites `/api/locations/:path` -> `?path=...`; only the single
 * `search` sub-path is exposed.
 */
export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path, q, limit, openOnly } = req.query;

  // Single-literal allowlist, shared with the other seven proxies so there is
  // one implementation of this control rather than eight. Behaviour is
  // unchanged except that a sloppy spelling (`search/`, the array form) is now
  // normalized and forwarded instead of 404ing a legitimate caller.
  if (resolveProxyPath(path, ["search"]) === null) {
    res.status(PROXY_REJECTION.status).json(PROXY_REJECTION.body);
    return;
  }

  const params = new URLSearchParams();
  if (q) params.set("q", String(q));
  if (limit) params.set("limit", String(limit));
  if (openOnly) params.set("openOnly", String(openOnly));

  const backendUrl = getBackendUrl(req);
  const url = `${backendUrl}/api/locations/search?${params}`;

  try {
    const response = await fetch(url, {
      headers: getInternalKeyHeader(),
      // Never follow a redirect — Node's fetch preserves headers (including the
      // injected X-Internal-Key) across a same-origin 3xx. See api/jobs-qa.ts.
      redirect: "manual",
    });
    await forwardResponse(response, res);
  } catch (error) {
    console.error('[api/locations] Upstream fetch failed:', error);
    res.status(500).json({ error: "Failed to fetch from backend" });
  }
}
