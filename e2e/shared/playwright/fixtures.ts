// Signed-in page fixture (PLAN.md §1, §4, §8). Feature-agnostic — no board
// names here; section specs import `test`/`expect` from here instead of
// `@playwright/test` directly.
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { test as base, expect } from '@playwright/test';
import type { BrowserContext, Page } from '@playwright/test';
import { signInContext, type TestIdentity } from '../auth/storage_state';

const REPO_ROOT = path.resolve(__dirname, '../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const BASE_URL = 'http://127.0.0.1:8201';

interface Fixtures {
  /** A page already signed in as the primary e2e identity. */
  signedInPage: Page;
  /** The raw context behind `signedInPage` — for a second signed-in tab, or
   * to sign in a SECOND identity in a fresh context (AC-10). */
  signedInContext: BrowserContext;
}

/**
 * Sweep every company BOTH test identities own, through the product's own
 * delete path (PLAN.md §8 — never a hand-written DELETE), by running
 * `shared/db/reset_user.py`'s own CLI (it already sweeps both users). A UI
 * spec that discovers a board (AC-06's checklist test, in particular) has no
 * reason to also drive the Remove button just to leave a clean slate —
 * `ensure_db.sh`'s full scrub on the NEXT `stack_up.sh` already guarantees
 * cross-RUN cleanliness, but sweeping here keeps one run's UI specs from
 * accumulating undeleted companies across EACH OTHER too.
 */
function sweepOwnedCompanies(): void {
  try {
    execFileSync(PYTHON, ['-m', 'e2e.shared.db.reset_user', BASE_URL], { cwd: REPO_ROOT });
  } catch (err) {
    // Best-effort: a sweep failure must not mask the test's own result, and
    // ensure_db.sh's next-run scrub is the backstop either way.
    // eslint-disable-next-line no-console
    console.warn('sweepOwnedCompanies failed (non-fatal):', err);
  }
}

export const test = base.extend<Fixtures>({
  // eslint-disable-next-line no-empty-pattern
  signedInContext: async ({ browser }, use) => {
    sweepOwnedCompanies();
    const context = await browser.newContext();
    // PLAN.md §8: the public-board-match dismissal key lives in localStorage
    // and is read once on mount, so a run that dismissed it last time would
    // otherwise pass on run 1 and fail on run 2. A brand-new context has
    // fresh, empty localStorage/origin storage by construction — nothing
    // else to clear here.
    await signInContext(context, 'primary');
    await use(context);
    await context.close();
    sweepOwnedCompanies();
  },
  signedInPage: async ({ signedInContext }, use) => {
    const page = await signedInContext.newPage();
    await use(page);
  },
});

export { expect };

/** Sign a SECOND, independent context in as `identity` (AC-10). */
export async function newSignedInContext(
  browser: import('@playwright/test').Browser,
  identity: TestIdentity,
) {
  const context = await browser.newContext();
  await signInContext(context, identity);
  return context;
}
