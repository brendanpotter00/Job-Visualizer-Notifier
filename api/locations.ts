import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getBackendUrl } from "./utils/backendUrl";
import { forwardResponse } from "./utils/forwardResponse";
import { getInternalKeyHeader } from "./utils/internalKey";

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

  const sub = Array.isArray(path) ? path.join("/") : path;
  if (sub !== "search") {
    res.status(404).json({ error: "Not found" });
    return;
  }

  const params = new URLSearchParams();
  if (q) params.set("q", String(q));
  if (limit) params.set("limit", String(limit));
  if (openOnly) params.set("openOnly", String(openOnly));

  const backendUrl = getBackendUrl(req);
  const url = `${backendUrl}/api/locations/search?${params}`;

  try {
    const response = await fetch(url, { headers: getInternalKeyHeader() });
    await forwardResponse(response, res);
  } catch (error) {
    res.status(500).json({ error: "Failed to fetch from backend" });
  }
}
