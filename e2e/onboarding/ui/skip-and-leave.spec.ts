// OB-U3..OB-U6 — every way out of the questions other than finishing.
//
//   OB-U3  leaving half-way saves nothing, so the next sign-in asks again;
//          only a save (here, Skip) ends it for good
//   OB-U4  Skip with no answers stays on the page it was on — no redirect,
//          no toast — and still ends it for good
//   OB-U5  Skip after answering KEEPS the answers (decision `keep`) and lands
//          on the filtered list
//   OB-U6  Escape counts as Skip: it stamps the account, it does not merely
//          hide the dialog for this session
import { expect, test } from '@playwright/test';
import { CORPUS } from './corpus';
import {
  COMPANIES,
  RECENT_JOBS,
  button,
  dbState,
  expectJobs,
  expectNoAccountYet,
  expectQuestion,
  expectQuestionsNeverOpen,
  expectStamped,
  expectUnstamped,
  filterField,
  freshIdentity,
  openSignedIn,
  questions,
  roleBox,
  savedToast,
  shot,
  trackUserFetches,
  type Identity,
} from './helpers';

const EMPTY = { category: [], subcategory: [], level: [], locations: [] };

/** Sign in again in a brand-new context and prove the questions stay shut. */
async function signInAgainAndExpectNoQuestions(
  browser: import('@playwright/test').Browser,
  me: Identity,
  pathname: string,
  what: string,
) {
  const context = await openSignedIn(browser, me);
  const page = await context.newPage();
  const tracker = trackUserFetches(page);
  await page.goto(pathname);
  await expectQuestionsNeverOpen(page, tracker, what);
  await context.close();
}

test.describe('OB-U3 left half-way', () => {
  test('OB-U3 leaving half-way asks again at Q1; only a save ends it', async ({ browser }) => {
    const me = freshIdentity('OB-U3');
    expectNoAccountYet(me);

    // Session 1: open, tick something, walk away (close the context).
    const first = await openSignedIn(browser, me);
    const page1 = await first.newPage();
    await page1.goto(RECENT_JOBS);
    let dialog = await expectQuestion(page1, 0);
    await roleBox(dialog, 'Product Manager').check();
    await expect(roleBox(dialog, 'Product Manager')).toBeChecked();
    await shot(page1, 'OB-U3', '01-ticked-then-left');
    await first.close();

    const afterLeaving = expectUnstamped(me, 'OB-U3 after leaving half-way');
    expect(afterLeaving.savedFilters, 'leaving half-way must save nothing').toBeNull();

    // Session 2: asked again, from the start, with nothing carried over.
    const second = await openSignedIn(browser, me);
    const page2 = await second.newPage();
    await page2.goto(RECENT_JOBS);
    dialog = await expectQuestion(page2, 0);
    await expect(roleBox(dialog, 'Product Manager'), 'a tick from the abandoned session came back').not.toBeChecked();
    await expect(button(dialog, 'Back')).toBeDisabled();
    await button(dialog, 'Skip').click();
    await expect(questions(page2)).toHaveCount(0);
    const state = await expectStamped(me, 'OB-U3 after Skip');
    expect(state.savedFilters ?? EMPTY).toMatchObject(EMPTY);
    await second.close();

    // Session 3: a save ended it.
    await signInAgainAndExpectNoQuestions(browser, me, RECENT_JOBS, 'OB-U3 signing in after the Skip');
  });
});

test.describe('OB-U4 empty Skip', () => {
  test('OB-U4 Skip with no answers stays on /companies, shows no toast, and ends it', async ({ browser }) => {
    const me = freshIdentity('OB-U4');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me);
    const page = await context.newPage();
    await page.goto(COMPANIES);
    const dialog = await expectQuestion(page, 0);
    await button(dialog, 'Skip').click();
    await expect(questions(page)).toHaveCount(0);

    const state = await expectStamped(me, 'OB-U4 after an empty Skip');
    expect(state.savedFilters ?? EMPTY, 'an empty Skip saves no answers').toMatchObject(EMPTY);
    // Still where the reader was — the old behaviour redirected to /jobs.
    await expect(page).toHaveURL(new RegExp(`${COMPANIES}(\\?|$)`));
    await expect(page.locator('h1').first()).toBeVisible();
    // No answers, no "Saved filters" toast — held for a settle window, since
    // the toast would open only after the dialog's exit transition.
    const deadline = Date.now() + 1_500;
    do {
      expect(await savedToast(page).count(), 'an empty Skip showed the "Saved filters" toast').toBe(0);
      expect(new URL(page.url()).pathname, 'an empty Skip navigated away').toBe(COMPANIES);
      await page.waitForTimeout(100);
    } while (Date.now() < deadline);
    await shot(page, 'OB-U4', '01-stayed-on-companies');
    await context.close();

    await signInAgainAndExpectNoQuestions(browser, me, COMPANIES, 'OB-U4 signing in after the empty Skip');
  });
});

test.describe('OB-U5 Skip keeps answers', () => {
  test('OB-U5 Skip on Q2 after answering Q1 keeps Product Manager and lands on the list', async ({ browser }) => {
    const me = freshIdentity('OB-U5');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me);
    const page = await context.newPage();
    await page.goto(COMPANIES);

    let dialog = await expectQuestion(page, 0);
    await roleBox(dialog, 'Product Manager').check();
    await button(dialog, 'Continue').click();
    dialog = await expectQuestion(page, 1);
    await button(dialog, 'Skip').click();
    await expect(questions(page)).toHaveCount(0);

    // An answer was given, so it lands on Recent with it applied.
    await expect(page).toHaveURL(new RegExp(`${RECENT_JOBS}(\\?|$)`));
    await expect(savedToast(page), 'Skip with an answer still shows the toast').toBeVisible();
    await expect(filterField(page, 'Job Category')).toHaveText('Product Manager');
    await expect(filterField(page, 'Level')).toHaveText('All');
    const pmOnly = CORPUS.productManagerOnly;
    await expectJobs(page, pmOnly.expectedKeys, 'OB-U5 with Product Manager kept');
    await shot(page, 'OB-U5', '01-landed-with-pm');

    const state = await expectStamped(me, 'OB-U5 after Skip on Q2');
    expect(state.savedFilters, 'Skip must keep the Q1 answer').toMatchObject({
      category: ['product_manager'],
      subcategory: [],
      level: [],
      locations: [],
    });
    expect(dbState(me).rowCount).toBe(1);
    await context.close();
  });
});

test.describe('OB-U6 Escape', () => {
  test('OB-U6 Escape on Q1 closes the questions and stamps the account', async ({ browser }) => {
    const me = freshIdentity('OB-U6');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me);
    const page = await context.newPage();
    await page.goto(RECENT_JOBS);
    await expectQuestion(page, 0);
    await page.keyboard.press('Escape');
    await expect(questions(page), 'Escape should close the questions').toHaveCount(0);
    await expectStamped(me, 'OB-U6 after Escape');
    await context.close();

    // The mirror: a dialog that was only HIDDEN for the session would be back.
    await signInAgainAndExpectNoQuestions(browser, me, RECENT_JOBS, 'OB-U6 signing in after Escape');
  });
});
