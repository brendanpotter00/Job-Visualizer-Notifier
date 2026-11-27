// OB-U1 / OB-U2 — the two headline cases.
//
// OB-U1: a brand-new identity's FIRST sign-in gets the questions, answers
// them, and lands on Recent Job Postings with the answers APPLIED — proved by
// the request the list makes and by which seeded rows it shows (one match,
// four decoys that each fail exactly one answer), not only by filter text.
//
// OB-U2: the same identity signing in AGAIN — a new browser context, so empty
// storage, like a new device — never sees them. That rejects a client-side
// "done" flag: a new context has none, only the server's stamp survives.
//
// One describe so `--case OB-U2` also runs OB-U1, which it builds on.
import { expect, test } from '@playwright/test';
import { CORPUS, decoyTitles, titlesFor } from './corpus';
import {
  COMPANIES,
  HEADLINE_LABELS,
  RECENT_JOBS,
  answerHeadline,
  button,
  dbState,
  expectJobs,
  expectNoAccountYet,
  expectQuestion,
  expectQuestionsNeverOpen,
  expectStamped,
  filterChips,
  freshIdentity,
  locationChips,
  openSignedIn,
  questions,
  savedToast,
  shot,
  trackUserFetches,
  type Identity,
} from './helpers';

const HEADLINE = CORPUS.headline;

/** The headline answers are on screen in the Recent page's three fields. */
async function expectHeadlineFilters(page: import('@playwright/test').Page, what: string) {
  await expect(filterChips(page, 'Job Category'), `${what}: Job Category`).toHaveText([
    HEADLINE_LABELS.role,
    HEADLINE_LABELS.specialty,
  ]);
  await expect(filterChips(page, 'Level'), `${what}: Level`).toHaveText([HEADLINE_LABELS.level]);
  await expect(locationChips(page), `${what}: Location`).toHaveText(HEADLINE.locations);
}

test.describe('OB-U1 / OB-U2 headline: first sign-in answers the questions; signing in again never shows them', () => {
  let identity: Identity | null = null;

  test('OB-U1 first sign-in answers the questions and lands on the filtered list', async ({ browser }) => {
    const me = freshIdentity('OB-U1');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me);
    const page = await context.newPage();

    await page.goto(RECENT_JOBS);
    await expectQuestion(page, 0);
    // A brand-new row, unstamped: what the dialog is reacting to.
    expect(dbState(me).onboardingCompletedAt, 'the first sign-in row must start NULL').toBeNull();

    await answerHeadline(page, 'OB-U1');

    // The list's next search must carry all four answers — the filters are
    // APPLIED, not just displayed.
    const applied = page.waitForResponse((r) => {
      const u = new URL(r.url());
      if (u.pathname !== '/api/jobs/search' || r.status() !== 200) return false;
      const q = u.searchParams;
      return (
        q.getAll('category').join() === HEADLINE.category.join() &&
        q.getAll('subcategory').join() === HEADLINE.subcategory.join() &&
        q.getAll('level').join() === HEADLINE.level.join() &&
        q.getAll('location').join() === HEADLINE.locations.join()
      );
    });
    await button(questions(page), 'Show my jobs').click();
    await expect(questions(page), 'the questions should close after "Show my jobs"').toHaveCount(0);
    await applied;

    await expect(page).toHaveURL(new RegExp(`${RECENT_JOBS}(\\?|$)`));
    await expect(page.getByRole('heading', { level: 1, name: 'Recent Job Postings' })).toBeVisible();

    // The toast: visible, top-right, linking to /saved-filters. Hovered first
    // so its 6 s timer cannot hide it mid-measurement.
    const toast = savedToast(page);
    await expect(toast, 'the "Saved filters" toast').toBeVisible();
    await toast.hover();
    const link = toast.getByRole('link', { name: 'Saved filters' });
    await expect(link).toHaveAttribute('href', '/saved-filters');
    const box = await toast.boundingBox();
    const viewport = page.viewportSize();
    expect(box && viewport, 'toast and viewport geometry').toBeTruthy();
    if (box && viewport) {
      expect(viewport.width - (box.x + box.width), 'the toast sits at the right edge').toBeLessThanOrEqual(40);
      expect(box.y, 'the toast sits at the top').toBeLessThan(viewport.height / 4);
    }
    await shot(page, 'OB-U1', '04-landed');

    await expectHeadlineFilters(page, 'OB-U1 after landing');
    await expectJobs(page, HEADLINE.expectedKeys, 'OB-U1 with the headline answers');
    for (const decoy of decoyTitles(HEADLINE.expectedKeys)) {
      await expect(page.getByRole('heading', { level: 3, name: decoy, exact: true }), `decoy "${decoy}"`).toHaveCount(0);
    }

    const state = await expectStamped(me, 'OB-U1 after "Show my jobs"');
    expect(state.savedFilters, 'the answers saved for the account').toMatchObject({
      category: HEADLINE.category,
      subcategory: HEADLINE.subcategory,
      level: HEADLINE.level,
      locations: HEADLINE.locations,
      recentTimeWindow: 'all',
      trendTimeWindow: '90d',
    });

    await context.close();
    identity = me;
  });

  test('OB-U2 signing in again (new context, same identity) never shows the questions', async ({ browser }) => {
    expect(identity, 'OB-U2 builds on OB-U1, which must have finished first').not.toBeNull();
    const me = identity as Identity;
    const stampedAt = dbState(me).onboardingCompletedAt;
    expect(stampedAt, 'OB-U1 should have stamped the account').toBeTruthy();

    // A second device / later session at desktop size.
    const context = await openSignedIn(browser, me);
    const page = await context.newPage();
    const tracker = trackUserFetches(page);
    await page.goto(RECENT_JOBS);
    await expectQuestionsNeverOpen(page, tracker, 'OB-U2 /jobs, signed in again');
    await expectHeadlineFilters(page, 'OB-U2 /jobs (saved answers hydrate a fresh session)');
    await expectJobs(page, HEADLINE.expectedKeys, 'OB-U2 /jobs');
    await expect(savedToast(page), 'the toast is a one-time thing').toHaveCount(0);
    await shot(page, 'OB-U2', '01-jobs-again');

    tracker.reset();
    await page.goto(COMPANIES);
    await expectQuestionsNeverOpen(page, tracker, 'OB-U2 /companies, signed in again');
    await context.close();

    // And once more on a phone.
    const phone = await openSignedIn(browser, me, { phone: true });
    const phonePage = await phone.newPage();
    const phoneTracker = trackUserFetches(phonePage);
    await phonePage.goto(RECENT_JOBS);
    await expectQuestionsNeverOpen(phonePage, phoneTracker, 'OB-U2 /jobs on a phone');
    await shot(phonePage, 'OB-U2', '02-phone-again');
    await phone.close();

    expect(dbState(me).onboardingCompletedAt, 'signing in again must not move the stamp').toBe(stampedAt);
    // Proves titlesFor is wired to the corpus, so the absence checks above
    // compared against real titles.
    expect(titlesFor(HEADLINE.expectedKeys).length).toBe(1);
  });
});
