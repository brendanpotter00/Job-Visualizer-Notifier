import type { VercelResponse } from '@vercel/node';

/**
 * Forward a fetch Response to the Vercel response, handling both
 * JSON and non-JSON content types.
 *
 * Reads the body as text before parsing so a 204/empty body with
 * `Content-Type: application/json` doesn't crash `.json()` — that would
 * get mislabeled as an upstream fetch failure by the outer catch.
 *
 * RFC 9110 §15.3.5 / §15.4.5: 204 (No Content) and 304 (Not Modified)
 * responses MUST NOT carry a body. FastAPI's ``Response(status_code=204)``
 * from grant/revoke admin endpoints is the hot path that triggers this —
 * without the short-circuit, ``res.status(204).json({...})`` adds a body
 * that violates the contract and trips strict HTTP clients.
 */
export async function forwardResponse(fetchResponse: Response, res: VercelResponse): Promise<void> {
  if (fetchResponse.status === 204 || fetchResponse.status === 304) {
    res.status(fetchResponse.status).end();
    return;
  }
  const contentType = fetchResponse.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const text = await fetchResponse.text();
    if (!text) {
      res.status(fetchResponse.status).end();
      return;
    }
    try {
      res.status(fetchResponse.status).json(JSON.parse(text));
    } catch {
      res.status(fetchResponse.status).json({ error: text });
    }
    return;
  }
  const text = await fetchResponse.text();
  res.status(fetchResponse.status).json({ error: text || fetchResponse.statusText });
}
