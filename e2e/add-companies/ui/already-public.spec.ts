// AC-01 — the already-public notice, as a human actually sees it
// (PLAN.md §5 "AC-01/AC-02", assertions 6-7). The API tier (test_already_public.py)
// covers the DB-level negatives; this covers only what a human can see.
import { test, expect } from '../../shared/playwright/fixtures';
import { gotoAddCompanies } from './helpers';
import { MICROSOFT } from './boards';

test.describe('AC-01 already-public notice', () => {
  test('pasting Microsoft\'s careers page shows "We already track Microsoft" with the escape hatch', async ({
    signedInPage: page,
  }) => {
    await gotoAddCompanies(page);

    await page.getByLabel('Careers page URL').fill(MICROSOFT.url);
    await page.getByRole('button', { name: 'Add company' }).click();

    const notice = page.getByTestId('already-public');
    await expect(notice).toBeVisible({ timeout: 30_000 });
    await expect(notice).toContainText('We already track Microsoft');

    // The escape hatch must survive the dedupe.
    await expect(page.getByTestId('track-anyway-button')).toBeVisible();
    await expect(page.getByTestId('track-anyway-button')).toContainText(
      'Track it separately anyway',
    );
  });
});
