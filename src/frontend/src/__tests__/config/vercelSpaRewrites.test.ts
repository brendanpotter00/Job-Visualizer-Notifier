import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
import { ROUTES } from '../../config/routes';

interface Rewrite {
  source: string;
  destination: string;
}

const vercelConfig = JSON.parse(
  readFileSync(resolve(__dirname, '../../../../../vercel.json'), 'utf8')
) as { rewrites: Rewrite[] };

const SPLAT = /^:[a-z]+\(\.\*\)$/i;

function sourceMatches(source: string, path: string): boolean {
  const pattern = source
    .split(/(:[a-z]+\(\.\*\))/i)
    .map((part) => (SPLAT.test(part) ? '.*' : part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
    .join('');
  return new RegExp(`^${pattern}$`).test(path);
}

const spaRewrites = vercelConfig.rewrites.filter(
  (rewrite) => rewrite.destination === '/index.html'
);

const appPaths = Object.values(ROUTES)
  .filter((path) => path !== ROUTES.HOME)
  .map((path) => path.replace(/:[a-z]+/gi, 'u-abc123'));

describe('vercel.json SPA rewrites', () => {
  it.each(appPaths)('a hard load of %s is served the app shell', (path) => {
    expect(spaRewrites.some((rewrite) => sourceMatches(rewrite.source, path))).toBe(true);
  });

  it('has no catch-all rewrite (it would swallow Vite module URLs under vercel dev)', () => {
    expect(spaRewrites.some((rewrite) => sourceMatches(rewrite.source, '/src/main.tsx'))).toBe(
      false
    );
  });
});
