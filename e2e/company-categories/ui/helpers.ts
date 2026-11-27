// UI-tier helpers. Section-owned: every locator names a control on the Recent
// page, the landing page or Saved Filters. The Recent page has no testids, so
// handles are ARIA roles/names plus the list's `data-client-window` hook.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { expect } from '@playwright/test';
import type { Browser, BrowserContext, Locator, Page } from '@playwright/test';
import { signInContext } from '../../shared/auth/storage_state';
import { CORPUS, titlesFor } from './corpus';

const REPO_ROOT = path.resolve(__dirname, '../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const SEED_PY = path.join(REPO_ROOT, 'e2e', 'company-categories', 'seed.py');
const ARTIFACTS_DIR =
  process.env.E2E_ARTIFACTS_DIR ?? path.join(__dirname, '..', 'artifacts', 'local');

export const RECENT_JOBS = '/jobs';
export const COMPANY_TYPE = 'Company type';

/** Reseed: the nine rows, and no saved filters for the reader. */
export function reseed(): void {
  execFileSync(PYTHON, [SEED_PY], { cwd: REPO_ROOT, encoding: 'utf-8' });
}

/**
 * A new context. Signed in (as the section's reader) unless `anonymous`.
 *
 * 1280x1200: tall enough that the window-virtualized list mounts all nine
 * rows (visible rows plus 6 of overscan), so "this title is absent" is never
 * true only because a row has not scrolled into view.
 *
 * NETWORK FENCE: any host but this stack is aborted (the Google sign-in
 * script, fonts), so "$0, no host but its own stack" holds in the browser too.
 */
export async function openContext(
  browser: Browser,
  { anonymous = false, phone = false }: { anonymous?: boolean; phone?: boolean } = {},
): Promise<BrowserContext> {
  const context = await browser.newContext(
    phone
      ? { viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 }
      : { viewport: { width: 1280, height: 1200 } },
  );
  await context.route(
    (url) => url.hostname !== '127.0.0.1' && url.hostname !== 'localhost',
    (route) => route.abort('blockedbyclient'),
  );
  if (!anonymous) await signInContext(context, CORPUS.reader);
  return context;
}

/** The virtualized list; `data-client-window` is how many rows are loaded. */
export function jobList(page: Page): Locator {
  return page.locator('div[data-client-window]');
}

export function companyTypeField(page: Page): Locator {
  return page.getByRole('combobox', { name: COMPANY_TYPE });
}

/**
 * The list holds EXACTLY these fixture rows: the loaded COUNT catches a decoy
 * scrolled out of view, the TITLES catch the right count of the wrong rows.
 *
 * Signed in, the list is the virtualized one (`data-client-window`); signed
 * out it is a plain capped list of cards, so `anonymous` reads the titles off
 * the page's main list instead (the corpus is under the 12-card cap).
 */
export async function expectJobs(
  page: Page,
  keys: string[],
  what: string,
  { anonymous = false }: { anonymous?: boolean } = {},
): Promise<void> {
  const expected = titlesFor(keys);
  const list = anonymous ? page.getByRole('main').getByRole('list').first() : jobList(page);
  if (!anonymous) {
    await expect
      .poll(async () => Number(await jobList(page).getAttribute('data-client-window')), {
        message: `${what}: the list should hold exactly ${expected.length} job(s): ${expected.join(', ')}`,
        timeout: 20_000,
      })
      .toBe(expected.length);
  }
  await expect
    .poll(
      async () => (await list.getByRole('heading', { level: 3 }).allInnerTexts()).map((t) => t.trim()).sort(),
      { message: `${what}: the rendered job titles`, timeout: 20_000 },
    )
    .toEqual(expected);
}

/** The URL's `company_type` values, in order. */
export function companyTypesInUrl(page: Page): string[] {
  return new URL(page.url()).searchParams.getAll('company_type');
}

/** Wait for the next 200 search whose `company_category` params are exactly `slugs`. */
export function searchWith(page: Page, slugs: string[]) {
  const want = [...slugs].sort().join();
  return page.waitForResponse((r) => {
    const u = new URL(r.url());
    return (
      u.pathname === '/api/jobs/search' &&
      r.status() === 200 &&
      u.searchParams.getAll('company_category').sort().join() === want
    );
  });
}

/** Open the Company type dropdown and return its listbox. */
export async function openCompanyType(page: Page): Promise<Locator> {
  await companyTypeField(page).click();
  const listbox = page.getByRole('listbox');
  await expect(listbox).toBeVisible();
  return listbox;
}

/** A screenshot under `<run>/screenshots/<case>/` (not under ui/, which Playwright wipes). */
export async function shot(page: Page, caseId: string, name: string): Promise<void> {
  const dir = path.join(ARTIFACTS_DIR, 'screenshots', caseId);
  fs.mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: path.join(dir, `${name}.png`) });
}
