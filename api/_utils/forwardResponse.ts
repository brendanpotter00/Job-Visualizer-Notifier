import type { VercelResponse } from '@vercel/node';

/**
 * Forward a fetch Response to the Vercel response, handling both
 * JSON and non-JSON content types.
 *
 * Reads the body as text before parsing so a 204/empty body with
 * `Content-Type: application/json` doesn't crash `.json()` — that would
 * get mislabeled as an upstream fetch failure by the outer catch.
 *
 * Body-less short-circuit covers every status that RFC 9110 forbids from
 * carrying a body:
 *   - 1xx Informational (RFC 9110 §15.2): "MUST NOT include content."
 *   - 204 No Content (RFC 9110 §15.3.5): no body.
 *   - 205 Reset Content (RFC 9110 §15.3.6): "MUST NOT generate content."
 *   - 304 Not Modified (RFC 9110 §15.4.5): no body.
 *
 * FastAPI's ``Response(status_code=204)`` from grant/revoke admin
 * endpoints is the hot path that triggers this — without the short-
 * circuit, ``res.status(204).json({...})`` adds a body that violates
 * the contract and trips strict HTTP clients.
 */
export async function forwardResponse(fetchResponse: Response, res: VercelResponse): Promise<void> {
  const status = fetchResponse.status;
  if (
    status === 204 ||
    status === 205 ||
    status === 304 ||
    (status >= 100 && status < 200)
  ) {
    res.status(status).end();
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
