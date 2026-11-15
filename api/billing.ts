import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getBackendUrl } from "./utils/backendUrl";
import { forwardResponse } from "./utils/forwardResponse";
import { getInternalKeyHeader } from "./utils/internalKey";
import {
  PROXY_REJECTION,
  buildUpstreamUrl,
  resolveProxyPath,
} from "./utils/proxyPath";

/**
 * Every backend billing route reachable under `/api/billing`, and nothing else.
 * See `api/utils/proxyPath.ts` for why this is an allowlist.
 *
 * `webhook` is deliberately ABSENT. Stripe calls it directly on the Railway
 * origin: its only authentication is the `Stripe-Signature` HMAC over the RAW
 * request body, and Vercel parses JSON bodies before a handler sees them, so a
 * hop through here would re-serialize the body and every signature would fail.
 * `src/backend/api/tests/test_proxy_path_allowlists.py` pins it in NOT_PROXIED.
 */
const PROXIED_ROUTES = [
  "subscription", // GET  — the plan of the caller (DB read only)
  "checkout-session", // POST — start hosted Stripe Checkout
  "portal-session", // POST — open the Stripe Customer Portal
] as const;

export default async function handler(req: VercelRequest, res: VercelResponse) {
  const { path } = req.query;

  const targetPath = resolveProxyPath(path, PROXIED_ROUTES);
  if (targetPath === null) {
    res.status(PROXY_REJECTION.status).json(PROXY_REJECTION.body);
    return;
  }

  // No query params are forwarded: none of the three routes takes any.
  const targetUrl = buildUpstreamUrl(
    getBackendUrl(req),
    "/api/billing",
    targetPath,
    "",
  );
  if (targetUrl === null) {
    res.status(PROXY_REJECTION.status).json(PROXY_REJECTION.body);
    return;
  }

  const headers: Record<string, string> = {
    Accept: "application/json",
    ...getInternalKeyHeader(),
  };
  if (req.headers.authorization) {
    headers["Authorization"] = req.headers.authorization;
  }

  try {
    const response = await fetch(targetUrl, {
      method: req.method,
      headers,
      // Never follow a redirect: Node's fetch preserves the injected
      // X-Internal-Key across a same-origin 3xx (see api/users.ts).
      redirect: "manual",
      // The two POSTs take no body; the backend reads the user from the token.
    });
    await forwardResponse(response, res);
  } catch (error) {
    console.error("[api/billing] Upstream fetch failed:", error);
    res.status(502).json({ error: "Upstream backend unavailable" });
  }
}
