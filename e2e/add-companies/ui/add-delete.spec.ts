// AC-08 — the human journey, end to end in a browser (PLAN.md §5 "AC-08"):
// "This is the case that would have caught 'you're just broken'. Everything
// else is a component of it." Also folds in AC-07's UI-only assertions
// (dialog copy) since this spec already drives the delete flow.
import { test, expect } from '../../shared/playwright/fixtures';
import { gotoAddCompanies, waitForRowGone, waitForRowText } from './helpers';
import { CISCO } from './boards';

test.describe('AC-08 add -> remove, end to end', () => {
  test('paste Cisco, add it in one press, watch it settle, then remove it', async ({
    signedInPage: page,
  }) => {
    await gotoAddCompanies(page);

    // ONE PRESS. This used to be three steps: Add company opened a preview card
    // ("Found 1,213 open jobs on Workday" plus a board / how-we-found-it / final-URL
    // grid) and the add only happened on a second press of "Track this company". The
    // owner's objection was that the middle step decided nothing — the add endpoint
    // re-resolves the raw URL from scratch either way.
    await page.getByLabel('Careers page link').fill(CISCO.url);
    await page.getByRole('button', { name: 'Add company' }).click();

    await expect(page.getByTestId('add-company-success')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('add-company-success')).toContainText('Now tracking');
    // The confirm step and the preview it lived in are both gone.
    await expect(page.getByTestId('add-company-button')).toHaveCount(0);
    await expect(page.getByTestId('resolve-headline')).toHaveCount(0);

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

    // THE CARD IS NOW ONE CLICK TARGET, and the two row actions are icons on it. Neither
    // has visible text any more, so the aria-label is its whole accessible name — and the
    // X is still a trigger, not a delete: it opens the confirmation the text button used
    // to open.
    await expect(row.getByTestId('my-company-rename')).toHaveAttribute(
      'aria-label',
      /^Rename .+/
    );
    const remove = row.getByTestId('my-company-remove');
    await expect(remove).toHaveAttribute('aria-label', /^Remove .+/);
    // Nothing nests: no button inside a link, no link inside a button.
    await expect(page.locator('a button, button a')).toHaveCount(0);

    // Cancel first: an icon is a smaller, less deliberate target than the text button it
    // replaced, so "opened it by accident" has to be survivable.
    await remove.click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(dialog).toHaveCount(0);
    await expect(row).toBeVisible();

    // Remove -> the dialog names the destruction, not a pause (AC-07 UI).
    await remove.click();
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

    // …and the empty list says so in one line. Asserting the DRAWN text matters: this
    // used to be a `visuallyHidden` "No companies yet" behind three visible steps, and
    // `toBeVisible` passes on a 1px sr-only box.
    const empty = page.getByTestId('my-companies-empty');
    await expect(empty).toBeVisible();
    await expect(empty).toHaveText('No companies yet');
  });
});
