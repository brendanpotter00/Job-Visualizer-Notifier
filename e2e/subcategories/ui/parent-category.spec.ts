// SC-01 — the parent category, in a real browser.
//
// The API tier proves the SQL. This tier proves the thing a person can see:
// tick "Software Engineering" and the list really does hold every SWE job,
// including the ones nobody has labelled. A filter that quietly narrowed to
// labelled rows would show up here as a shorter list, which is exactly how the
// user would meet the bug.
import { expect, expectResults, gotoRecentJobs, reseed, selectCategory, test } from './helpers';
import { job, sweTitles, allTitles } from './corpus';

const SWE = 'Software Engineering';

test.beforeEach(() => {
  reseed({ reveal: true });
});

test.describe('SC-01 parent category', () => {
  test('SC-01 selecting Software Engineering shows every subcategory, labelled or not', async ({
    signedInPage: page,
  }) => {
    await gotoRecentJobs(page);
    // The unfiltered list is the baseline: if it is already short, a passing
    // filtered assertion below would mean nothing.
    await expectResults(page, allTitles());

    await selectCategory(page, SWE);
    await expectResults(page, sweTitles());
  });

  test('SC-01 the unevaluated and the no-specialty rows are both on screen', async ({
    signedInPage: page,
  }) => {
    await gotoRecentJobs(page);
    await selectCategory(page, SWE);

    await expect(
      page.getByRole('heading', { level: 3, name: job('J-NULL').title }),
      'a SWE job whose subcategory array is NULL (never evaluated) vanished from a ' +
        'parent-category selection — on day 0 of the backfill that is EVERY job',
    ).toBeVisible();
    await expect(
      page.getByRole('heading', { level: 3, name: job('J-EMPTY').title }),
      "a SWE job evaluated to '{}' (no specialty applies) vanished from a " +
        'parent-category selection',
    ).toBeVisible();
  });

  test('SC-01 the selection does not reach outside its category', async ({
    signedInPage: page,
  }) => {
    await gotoRecentJobs(page);
    await selectCategory(page, SWE);

    await expect(
      page.getByRole('heading', { level: 3, name: job('J-PM').title }),
      'a Product Manager job came back under a Software Engineering selection',
    ).toHaveCount(0);
  });
});
