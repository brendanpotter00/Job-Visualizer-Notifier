// Playwright helper: inject a minted token the app's OWN way (PLAN.md §4).
//
// GoogleCredentialProvider reads `localStorage['jvn.googleCredential.v1']`
// ONCE, in `useState(() => readStoredCredential())` at first render
// (`src/frontend/src/features/auth/GoogleCredentialContext.tsx`). That means
// `page.addInitScript` (runs before ANY page script, on every navigation in
// the context) is the only place this can be written — `page.evaluate` after
// load is too late and presents as a flaky signed-out page (PLAN.md §4's
// named risk).
//
// The token itself comes from `shared/auth/mint.py` — shelled out to rather
// than re-implemented in TypeScript, so there is exactly ONE place that knows
// how to mint a token the backend's `_get_jwks_client` patch will accept.
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import type { BrowserContext } from '@playwright/test';

const REPO_ROOT = path.resolve(__dirname, '../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');

export const GOOGLE_CREDENTIAL_STORAGE_KEY = 'jvn.googleCredential.v1';

export type TestIdentity = 'primary' | 'other';

/** Mint a token for `identity` by shelling out to shared/auth/mint.py. */
export function mintToken(identity: TestIdentity = 'primary'): string {
  const out = execFileSync(PYTHON, ['-m', 'e2e.shared.auth.mint', identity], {
    cwd: REPO_ROOT,
    encoding: 'utf-8',
  });
  const token = out.trim();
  if (!token || token.split('.').length !== 3) {
    throw new Error(`mintToken(${identity}): mint.py did not print a JWT — got: ${out}`);
  }
  return token;
}

/**
 * Register the init script that signs `context` in as `identity` for every
 * page/navigation created in it from here on. Call this BEFORE any
 * `page.goto(...)` — an init script only applies to navigations that happen
 * after it is added.
 */
export async function signInContext(
  context: BrowserContext,
  identity: TestIdentity = 'primary',
): Promise<string> {
  const token = mintToken(identity);
  await context.addInitScript(
    ({ key, value }) => {
      window.localStorage.setItem(key, value);
    },
    { key: GOOGLE_CREDENTIAL_STORAGE_KEY, value: token },
  );
  return token;
}
