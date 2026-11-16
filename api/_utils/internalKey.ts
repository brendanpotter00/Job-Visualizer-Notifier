// Shared-secret header attached by every Vercel proxy on its way to the
// Railway-hosted FastAPI. The backend's require_internal_key middleware
// matches against this header. When INTERNAL_API_KEY is unset (local dev),
// return an empty object so callers can spread `...getInternalKeyHeader()`
// into their headers map unconditionally.
export function getInternalKeyHeader(): Record<string, string> {
  const key = process.env.INTERNAL_API_KEY;
  if (!key) return {};
  return { 'X-Internal-Key': key };
}
