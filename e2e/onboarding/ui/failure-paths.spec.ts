// OB-U11 / OB-U12 — the two failure paths a unit test cannot see end to end.
//
//   OB-U11  the save fails: a Skip still lets the reader out (for this visit
//           only — the stamp stays NULL, so the next load asks again), and the
//           tab title goes back to the page's own. Pins the review fix and the
//           tab-title fix on this branch.
//   OB-U12  an older backend that does not send `onboardingCompletedAt` must
//           never open the questions: `undefined` is "unknown", not "ask".
import { expect, test } from '@playwright/test';
import type { Route } from '@playwright/test';
import {
  RECENT_JOBS,
  button,
  expectNoAccountYet,
  expectQuestion,
  expectQuestionsNeverOpen,
  expectStamped,
  expectUnstamped,
  freshIdentity,
  openSignedIn,
  pageOwnTitle,
  questions,
  shot,
  trackUserFetches,
} from './helpers';

const isOnboardingPost = (url: URL) => url.pathname === '/api/users/onboarding';
const isUsersGet = (url: URL) => url.pathname === '/api/users';

test.describe('OB-U11 failed save', () => {
  test('OB-U11 a failed Skip closes for this visit only and restores the tab title', async ({ browser }) => {
    const ownTitle = await pageOwnTitle(browser, RECENT_JOBS);
    expect(ownTitle, 'the title oracle').not.toMatch(/^Question /);

    const me = freshIdentity('OB-U11');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me);
    const page = await context.newPage();
    let failedPosts = 0;
    const fail500 = async (route: Route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      failedPosts += 1;
      await route.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"e2e: forced failure"}' });
    };
    await page.route(isOnboardingPost, fail500);

    await page.goto(RECENT_JOBS);
    let dialog = await expectQuestion(page, 0);
    await expect(page, 'the tab names the open question').toHaveTitle(/^Question 1 of 3: Roles \| /);

    await button(dialog, 'Skip').click();
    await expect(questions(page), 'a failed Skip must still let the reader out').toHaveCount(0);
    expect(failedPosts, 'the Skip really went to the (failing) server').toBe(1);
    await expect(page, "the tab title is back to the page's own").toHaveTitle(ownTitle);
    await expect(page.getByRole('heading', { level: 1, name: 'Recent Job Postings' })).toBeVisible();
    expectUnstamped(me, 'OB-U11 after the failed Skip');
    await shot(page, 'OB-U11', '01-closed-after-failure');

    // Same context, next page load: still NULL, so it asks again.
    await page.reload();
    dialog = await expectQuestion(page, 0);
    expect(failedPosts).toBe(1);

    // The server is back: Skip now saves, and that ends it.
    await page.unroute(isOnboardingPost, fail500);
    await button(dialog, 'Skip').click();
    await expect(questions(page)).toHaveCount(0);
    await expectStamped(me, 'OB-U11 after the Skip that saved');
    await expect(page).toHaveTitle(ownTitle);
    await context.close();
  });
});

test.describe('OB-U12 older backend', () => {
  test('OB-U12 a /api/users without onboardingCompletedAt never opens the questions', async ({ browser }) => {
    const me = freshIdentity('OB-U12');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me);
    const page = await context.newPage();
    let stripped = 0;
    const stripField = async (route: Route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      const response = await route.fetch();
      const body = (await response.json()) as Record<string, unknown>;
      expect(Object.prototype.hasOwnProperty.call(body, 'onboardingCompletedAt'), 'the real backend sends the field').toBe(true);
      delete body.onboardingCompletedAt;
      stripped += 1;
      await route.fulfill({ response, json: body });
    };
    await page.route(isUsersGet, stripField);

    const tracker = trackUserFetches(page);
    await page.goto(RECENT_JOBS);
    await expectQuestionsNeverOpen(page, tracker, 'OB-U12 with the field stripped');
    expect(stripped, 'every GET /api/users went through the older-backend shim').toBe(tracker.started());
    // The row is real and genuinely unanswered — only the field was hidden.
    expectUnstamped(me, 'OB-U12 (the real stamp is still NULL)');
    await shot(page, 'OB-U12', '01-no-questions');

    // The mirror: the same account with the field restored IS asked.
    await page.unroute(isUsersGet, stripField);
    await page.reload();
    await expectQuestion(page, 0);
    await context.close();
  });
});
