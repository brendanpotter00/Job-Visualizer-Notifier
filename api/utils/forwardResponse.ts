import type { VercelResponse } from '@vercel/node';

/**
 * Forward a fetch Response to the Vercel response, handling both
 * JSON and non-JSON content types.
 */
export async function forwardResponse(fetchResponse: Response, res: VercelResponse): Promise<void> {
  const contentType = fetchResponse.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const data = await fetchResponse.json();
    res.status(fetchResponse.status).json(data);
  } else {
    const text = await fetchResponse.text();
    res.status(fetchResponse.status).json({ error: text || fetchResponse.statusText });
  }
}
