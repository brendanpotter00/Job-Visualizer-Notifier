// OB-U8 / OB-U9 — where the questions never open, and who never sees them.
//
//   OB-U8  /pricing must stay clear (a Stripe Checkout return lands there),
//          even for an account that WILL be asked — proved by navigating on
//          to /jobs in the same session and watching them open there.
//   OB-U9  an account that existed before the feature shipped (stamped by the
//          migration's backfill) signs in and is never asked.
import { expect, test } from '@playwright/test';
import {
  PREEXISTING,
  RECENT_JOBS,
  dbState,
  expectNoAccountYet,
  expectQuestion,
  expectQuestionsNeverOpen,
  freshIdentity,
  openSignedIn,
  shot,
  trackUserFetches,
} from './helpers';
import { CORPUS } from './corpus';

test.describe('OB-U8 never on /pricing', () => {
  test('OB-U8 a fresh identity on /pricing sees no questions; on /jobs it does', async ({ browser }) => {
    const me = freshIdentity('OB-U8');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me);
    const page = await context.newPage();

    // /pricing is outside RootLayout and never asks for /api/users, so the
    // §5 evidence that the page has seen a SIGNED-IN reader is its plan read
    // (`GET /api/billing/subscription` runs only when signed in) and its h1.
    const signedInPlanRead = page.waitForResponse(
      (r) => new URL(r.url()).pathname === '/api/billing/subscription',
    );
    await page.goto('/pricing');
    await signedInPlanRead;
    await expect(page.getByRole('heading', { level: 1, name: 'Pricing' })).toBeVisible();
    await expectQuestionsNeverOpen(page, null, 'OB-U8 /pricing');
    await shot(page, 'OB-U8', '01-pricing-clear');

    // The mirror: the same reader, same session, one in-app click away — the
    // questions DO open, so their absence above was the path, not the account.
    await page.getByRole('link', { name: 'Browse jobs' }).click();
    await expect(page).toHaveURL(new RegExp(`${RECENT_JOBS}(\\?|$)`));
    await expectQuestion(page, 0);
    await context.close();
  });
});

test.describe('OB-U9 pre-existing account', () => {
  test('OB-U9 an account from before the feature is never asked', async ({ browser }) => {
    const before = dbState(PREEXISTING);
    expect(before.onboardingCompletedAt, 'the seeded account is stamped (as the backfill left it)').toBeTruthy();

    const context = await openSignedIn(browser, PREEXISTING);
    const page = await context.newPage();
    const tracker = trackUserFetches(page);
    await page.goto(RECENT_JOBS);
    await expectQuestionsNeverOpen(page, tracker, 'OB-U9 pre-existing account on /jobs');
    await shot(page, 'OB-U9', '01-no-questions');
    await context.close();

    const after = dbState(PREEXISTING);
    expect(new Date(after.onboardingCompletedAt ?? '').toISOString()).toBe(
      new Date(CORPUS.preexisting.stampedAt).toISOString(),
    );
  });
});
