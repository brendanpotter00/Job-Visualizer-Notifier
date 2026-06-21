import { describe, it, expect } from 'vitest';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { COMPANIES } from '../../config/companies';

// src/__tests__/config -> src/frontend/public/logos
const logosDir = resolve(dirname(fileURLToPath(import.meta.url)), '../../../public/logos');

/**
 * Coverage guard: every configured company must ship both a brand icon (job
 * cards) and a wordmark (curated cards). Without this, adding a company to
 * companies.ts without dropping in the matching PNGs degrades silently to the
 * initials / text fallback. Keeping it a hard test surfaces the drift in CI.
 */
describe('company logo asset coverage', () => {
  it('every configured company has a committed icon and wordmark', () => {
    const missing = COMPANIES.flatMap((c) => {
      const files: string[] = [];
      if (!existsSync(resolve(logosDir, `icons/${c.id}.png`))) files.push(`icons/${c.id}.png`);
      if (!existsSync(resolve(logosDir, `wordmarks/${c.id}.png`)))
        files.push(`wordmarks/${c.id}.png`);
      return files;
    });
    expect(missing).toEqual([]);
  });
});
