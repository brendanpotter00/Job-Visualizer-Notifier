// AC-08 — the human journey, end to end in a browser (PLAN.md §5 "AC-08"):
// "This is the case that would have caught 'you're just broken'. Everything
// else is a component of it." Also folds in AC-07's UI-only assertions
// (dialog copy) since this spec already drives the delete flow.
import { test, expect } from '../../shared/playwright/fixtures';
import { gotoAddCompanies, waitForRowGone, waitForRowText } from './helpers';
import { CISCO } from './boards';

test.describe('AC-08 add -> track -> remove, end to end', () => {
  test('paste Cisco, preview, track, watch it settle, then remove it', async ({
    signedInPage: page,
  }) => {
    await gotoAddCompanies(page);

    // paste -> Add company -> preview
    await page.getByLabel('Careers page URL').fill(CISCO.url);
    await page.getByRole('button', { name: 'Add company' }).click();

    const headline = page.getByTestId('resolve-headline');
    await expect(headline).toBeVisible({ timeout: 30_000 });
    await expect(headline).toHaveText(/^Found [\d,]+ open jobs on Workday$/);

    // Track this company
    await page.getByTestId('add-company-button').click();
    await expect(page.getByTestId('add-company-success')).toBeVisible({ timeout: 30_000 });

    // The row appears with a blue "Fetching all current jobs…" chip…
    const row = page.getByTestId('my-company-row').filter({ hasText: CISCO.label });
    await expect(row).toBeVisible({ timeout: 15_000 });

    // …then becomes green "Successfully tracking" with a non-zero count.
    // (Polling trap — PLAN.md §5 AC-08: a settled list stops polling, so this
    // drives its own reloads instead of trusting the page's auto-refresh.)
    await waitForRowText(page, CISCO.label, 'Successfully tracking', { timeoutMs: 180_000 });
    // Asserted POSITIVELY, and it has to be. This was
    // `expect(row).not.toContainText('0 open jobs')`, which is a plain substring test
    // over the whole row's text — so it failed the moment Cisco's live count happened
    // to end in a zero: the row read "1,230 open jobs", which literally contains
    // "0 open jobs". Measured on run 20260828T014754Z, and it would fire again on any
    // count ending in 0 (roughly one run in ten) with a message that reads like a
    // product regression. Requiring a leading 1-9 says the thing the case actually
    // means — the count is not zero — and cannot be fooled by a trailing digit.
    // No `\b` anchor: the row's text has no separators ("tracking1,230 open jobs").
    await expect(row).toContainText(/[1-9][\d,]* open jobs?/);

    // Remove -> the dialog names the destruction, not a pause (AC-07 UI).
    await row.getByTestId('my-company-remove').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByRole('heading', {
      name: 'Delete this company and its job history?',
    })).toBeVisible();
    const dialogBody = await page.getByRole('dialog').innerText();
    expect(dialogBody.toLowerCase()).toContain('not a pause');

    // Confirm — MyCompaniesList.tsx closes the dialog OPTIMISTICALLY, before
    // the DELETE resolves (PLAN.md §5 "UI timing note"), so wait for the row
    // to leave the list rather than for the dialog to close.
    await page.getByTestId('my-company-remove-confirm').click();
    await waitForRowGone(page, CISCO.label, { timeoutMs: 30_000 });

    // …and the list reads "No companies yet".
    await expect(page.getByText('No companies yet')).toBeVisible();
  });
});
