// Shared UI-test helpers (PLAN.md §5, §8). Section-owned (not shared/) because
// it names board copy and test ids specific to Add Companies.
import type { Locator, Page } from '@playwright/test';
import { expect } from '../../shared/playwright/fixtures';

export const ADD_COMPANIES_PATH = '/add-companies';

/**
 * A settled list stops polling (`pollIntervalFor` -> 0 in
 * `MyCompaniesList.tsx`), so a bare `waitFor` on a row's text can hang to
 * timeout waiting for an auto-refresh that will never come (PLAN.md §5 AC-08
 * "Polling trap"). This drives the wait itself with explicit reloads instead
 * of trusting the page's own poll.
 */
export async function waitForRowText(
  page: Page,
  companyName: string,
  expectedText: string | RegExp,
  { timeoutMs = 180_000, reloadEveryMs = 4_000 }: { timeoutMs?: number; reloadEveryMs?: number } = {},
): Promise<void> {
  const row = page.getByTestId('my-company-row').filter({ hasText: companyName });
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      await expect(row).toContainText(expectedText, { timeout: reloadEveryMs });
      return;
    } catch (err) {
      if (Date.now() > deadline) throw err;
      await page.reload();
    }
  }
}

/** Same idea for "this row is gone" — waits past a settled/non-polling list. */
export async function waitForRowGone(
  page: Page,
  companyName: string,
  { timeoutMs = 60_000, reloadEveryMs = 3_000 }: { timeoutMs?: number; reloadEveryMs?: number } = {},
): Promise<void> {
  const row = page.getByTestId('my-company-row').filter({ hasText: companyName });
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      await expect(row).toHaveCount(0, { timeout: reloadEveryMs });
      return;
    } catch (err) {
      if (Date.now() > deadline) throw err;
      await page.reload();
    }
  }
}

/**
 * A SECOND, narrower polling trap than the one `waitForRowText` handles
 * (found live, PLAN.md §5/§8's principle applied one step further than the
 * plan spelled out): `pollIntervalFor` stops polling the MOMENT a row's
 * `openJobCount`/`healthState` settle to "Successfully tracking" — but
 * `mark_last_success` (which drives that chip) and `suggest_published_board`
 * (which writes the public-board-match suggestion) are two SEPARATE
 * sequential writes inside the same harvest task, not one atomic commit.
 * Measured live: ~0.5s apart. A page that stopped refreshing the instant the
 * chip settled can therefore never observe the suggestion landing a moment
 * later — `expect(locator).toBeVisible()` alone just polls a DOM that will
 * never change again. This drives its own reloads, exactly like
 * `waitForRowText`, so a fact that arrives slightly after "settled" still
 * gets picked up.
 */
export async function waitForVisibleWithReload(
  page: Page,
  locator: Locator,
  { timeoutMs = 30_000, reloadEveryMs = 3_000 }: { timeoutMs?: number; reloadEveryMs?: number } = {},
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    try {
      await expect(locator).toBeVisible({ timeout: reloadEveryMs });
      return;
    } catch (err) {
      if (Date.now() > deadline) throw err;
      await page.reload();
    }
  }
}

export async function gotoAddCompanies(page: Page): Promise<void> {
  await page.goto(ADD_COMPANIES_PATH);
  await expect(page.getByRole('heading', { name: 'Add Companies' })).toBeVisible();
}
