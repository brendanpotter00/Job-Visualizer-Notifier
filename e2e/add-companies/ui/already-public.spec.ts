// AC-01 / AC-13 — the two "we already have this" notices, as a human sees them.
// The API tiers (test_already_public.py, test_name_match.py) cover the DB-level
// negatives; this covers only what a human can see — and specifically the ONE
// difference between them: whether there is a way past the notice.
//
// The rule, which is the whole point of this file:
//
//   exact evidence (a resolved board token, a declared careers host)  -> terminal
//   a guess (the company name read out of the domain)                 -> keeps a way out
//
// An exact match has no plausible reading where the user meant a different company, and
// a private duplicate of a board we publish re-scrapes the same feed for a chart whose
// history starts today. Offering that was a trap. A NAME match can be wrong about a
// company that merely shares a string with one of ours, and a wrong guess with no way
// out would hard-block them — a worse anti-pattern than the one we removed.
import { test, expect } from '../../shared/playwright/fixtures';
import { gotoAddCompanies } from './helpers';
import { MICROSOFT, SPOTIFY } from './boards';

test.describe('AC-01 already-public notice (exact careers-host match)', () => {
  test("pasting Microsoft's careers page shows \"We already track Microsoft\" and no way past it", async ({
    signedInPage: page,
  }) => {
    await gotoAddCompanies(page);

    await page.getByLabel('Careers page link').fill(MICROSOFT.url);
    await page.getByRole('button', { name: 'Add company' }).click();

    const notice = page.getByTestId('already-public');
    await expect(notice).toBeVisible({ timeout: 30_000 });
    await expect(notice).toContainText('We already track Microsoft');
    // Stated flat — no hedging on an exact match against our own declared host table.
    await expect(notice).not.toContainText('looks like');

    // CHANGED: this used to assert the escape hatch. It is gone on purpose — the link
    // is the only way onward from an exact match.
    await expect(page.getByTestId('track-anyway-button')).toHaveCount(0);
    await expect(notice.getByTestId('already-public-link')).toBeVisible();
  });
});

test.describe('AC-13 name-guess notice (company name in the domain)', () => {
  test('pasting lifeatspotify.com hedges the claim and offers a correction', async ({
    signedInPage: page,
  }) => {
    await gotoAddCompanies(page);

    await page.getByLabel('Careers page link').fill(SPOTIFY.url);
    await page.getByRole('button', { name: 'Add company' }).click();

    const notice = page.getByTestId('already-public');
    await expect(notice).toBeVisible({ timeout: 30_000 });

    // The headline must NOT read like AC-01's. We matched a string in a web address,
    // not a board and not a job set.
    await expect(notice).toContainText('This looks like Spotify, which we already track');
    await expect(notice).toContainText('we matched the name in the web address');

    // The link is still the primary action...
    await expect(notice.getByTestId('already-public-link')).toBeVisible();
    // ...and the correction is the secondary one. Its words matter: it reads as
    // correcting a wrong guess, not as opting into a duplicate.
    const correction = page.getByTestId('track-anyway-button');
    await expect(correction).toBeVisible();
    await expect(correction).toContainText("This isn't the same company");
    await expect(correction).not.toContainText('anyway');
  });
});
