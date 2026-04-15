import type { VercelResponse } from '@vercel/node';

/**
 * Forward a fetch Response to the Vercel response, handling both
 * JSON and non-JSON content types.
 *
 * Reads the body as text before parsing so a 204/empty body with
 * `Content-Type: application/json` doesn't crash `.json()` — that would
 * get mislabeled as an upstream fetch failure by the outer catch.
 */
export async function forwardResponse(fetchResponse: Response, res: VercelResponse): Promise<void> {
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
