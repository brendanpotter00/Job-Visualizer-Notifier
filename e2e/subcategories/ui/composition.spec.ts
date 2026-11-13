// SC-03 — subcategory AND level, in a real browser.
//
// `J-BACKEND-MID` is the decoy and the whole case: it carries {backend} at
// level `mid`, so it satisfies one half of the conjunction and fails the
// other. If the two controls OR rather than AND, the list GROWS when the user
// adds the second filter — which is the version of this bug a person actually
// notices.
import { expect, expectResults, gotoRecentJobs, reseed, selectLevel, selectSubcategory, test } from './helpers';
import { job, titlesFor, titlesForSubcategory } from './corpus';

const SWE = 'Software Engineering';

test.beforeEach(() => {
  reseed({ reveal: true });
});

test.describe('SC-03 filters compose', () => {
  test('SC-03 adding a level to a subcategory narrows, never widens', async ({
    signedInPage: page,
  }) => {
    await gotoRecentJobs(page);

    await selectSubcategory(page, SWE, 'Backend');
    const backendOnly = titlesForSubcategory('backend');
    await expectResults(page, backendOnly);

    await selectLevel(page, 'Senior');
    // Every senior row the backend selection reaches — the mid-level one drops.
    const expected = titlesFor('J-BACKEND', 'J-PAIR', 'J-FULLSTACK', 'J-OTHER-BACK');
    expect(
      expected.length,
      'the level filter must actually remove something, or this case proves nothing',
    ).toBeLessThan(backendOnly.length);
    await expectResults(page, expected);
  });

  test('SC-03 the job matching only the subcategory is gone', async ({ signedInPage: page }) => {
    await gotoRecentJobs(page);
    await selectSubcategory(page, SWE, 'Backend');
    await expect(
      page.getByRole('heading', { level: 3, name: job('J-BACKEND-MID').title }),
      'the mid-level backend job should be on screen BEFORE the level filter is added',
    ).toBeVisible();

    await selectLevel(page, 'Senior');
    await expect(
      page.getByRole('heading', { level: 3, name: job('J-BACKEND-MID').title }),
      'a mid-level job survived a Senior selection — the two filters are OR-ing, so ' +
        'the list widens when the user narrows',
    ).toHaveCount(0);
  });
});
