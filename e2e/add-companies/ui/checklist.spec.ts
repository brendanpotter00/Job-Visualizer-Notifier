// AC-06 — the discovery checklist + the "this looks like Spotify" banner, as a
// human sees them (PLAN.md §5 "AC-06", assertions 5-7). The API tier
// (test_public_match.py) covers the DB-level negatives (job_listings
// untouched, nothing merged); this covers only what a human can see, plus
// the checklist ticking through its five steps along the way.
//
// Live: real Chromium, real Haiku, real board — a genuine ~60-90s run.
import { test, expect } from '../../shared/playwright/fixtures';
import { gotoAddCompanies, waitForRowText, waitForVisibleWithReload } from './helpers';
import { SPOTIFY } from './boards';

test.describe('AC-06 discovery checklist + public-board-match banner', () => {
  test('discovering lifeatspotify.com ticks the checklist and suggests the public Spotify page', async ({
    signedInPage: page,
  }) => {
    await gotoAddCompanies(page);

    await page.getByLabel('Careers page URL').fill(SPOTIFY.url);
    await page.getByRole('button', { name: 'Add company' }).click();

    await expect(page.getByTestId('discovery-pending')).toBeVisible({ timeout: 30_000 });

    // The row appears immediately (provisional 'discovering' row) and its
    // checklist should tick through all five rungs on the way to settling.
    // A settled list stops polling (PLAN.md §5 "Polling trap"), so this
    // drives its own reloads rather than trusting the page's auto-refresh.
    await waitForRowText(page, 'lifeatspotify', 'Successfully tracking', {
      timeoutMs: 240_000,
    });

    const row = page.getByTestId('my-company-row').filter({ hasText: 'lifeatspotify' });
    const banner = row.getByTestId('public-board-match');

    // KNOWN-RISK NOTE (PLAN.md §11.2): this banner only renders once the
    // backend's suggest_published_board trigger actually fires on this
    // board. If it regresses back to "first VERIFIED harvest only", this
    // assertion goes red — do not soften it.
    //
    // A SECOND polling trap, found live (not in PLAN.md, see helpers.ts):
    // mark_last_success (drives "Successfully tracking") and
    // suggest_published_board (drives this banner) are two separate writes
    // inside the same harvest task, measured ~0.5s apart — and the list
    // stops polling the instant the first one lands. A bare toBeVisible()
    // here polls a DOM the app has already stopped refreshing.
    await waitForVisibleWithReload(page, banner, { timeoutMs: 30_000 });
    await expect(banner).toContainText('This looks like Spotify, which we already track');

    // Assertion 6: link / Delete this board / Dismiss — and NO merge control
    // anywhere in the banner's DOM.
    await expect(banner.getByTestId('public-board-match-link')).toBeVisible();
    const removeButton = banner.getByTestId('public-board-match-remove');
    await expect(removeButton).toBeVisible();
    await expect(removeButton).toContainText('Delete this board');
    const dismissButton = banner.getByTestId('public-board-match-dismiss');
    await expect(dismissButton).toBeVisible();
    await expect(dismissButton).toContainText('Dismiss');

    const bannerText = (await banner.innerText()).toLowerCase();
    expect(bannerText, 'no merge control must exist anywhere in the banner').not.toContain('merge');
    // Exactly the three controls named above: one link, two buttons.
    await expect(banner.getByRole('link')).toHaveCount(1);
    await expect(banner.getByRole('button')).toHaveCount(2);

    // Assertion 7: Dismiss persists and the banner does not return on reload.
    // (A fresh Playwright BrowserContext starts with empty localStorage on
    // every test AND every suite run, so the cross-run "DB purge doesn't
    // reset it" trap PLAN.md §8 warns about cannot bite this fixture design —
    // verified here within a single test instead, which is the assertion
    // that actually matters.)
    await dismissButton.click();
    await expect(banner).toHaveCount(0);
    await page.reload();
    await expect(row.getByTestId('public-board-match')).toHaveCount(0);
  });
});
