import type { VercelResponse } from '@vercel/node';

const ATS_CDN_CACHE = 'public, s-maxage=1200, stale-while-revalidate=2400'; // 20 min + 40 min stale
const BACKEND_CDN_CACHE = 'public, s-maxage=300, stale-while-revalidate=600'; // 5 min + 10 min stale
const BROWSER_NO_CACHE = 'public, max-age=0, must-revalidate';

export function setAtsCacheHeaders(res: VercelResponse): void {
  res.setHeader('Vercel-CDN-Cache-Control', ATS_CDN_CACHE);
  res.setHeader('Cache-Control', BROWSER_NO_CACHE);
}

export function setBackendCacheHeaders(res: VercelResponse): void {
  res.setHeader('Vercel-CDN-Cache-Control', BACKEND_CDN_CACHE);
  res.setHeader('Cache-Control', BROWSER_NO_CACHE);
}
