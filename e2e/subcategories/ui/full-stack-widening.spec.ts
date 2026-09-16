// SC-04 — the one-way widening, in a real browser.
//
// Two halves, and only the second one can fail quietly:
//   Frontend   -> also shows Full Stack   (a visible, checkable addition)
//   Full Stack -> shows ONLY Full Stack   (an absence, which a "did my job
//                                          come back" assertion never sees)
import { expect, expectResults, gotoRecentJobs, reseed, selectSubcategory, test } from './helpers';
import { job, titlesFor, titlesForSubcategory } from './corpus';

const SWE = 'Software Engineering';

test.beforeEach(() => {
  reseed({ reveal: true });
});

test.describe('SC-04 full_stack widening', () => {
  test('SC-04 Frontend also surfaces the Full Stack job', async ({ signedInPage: page }) => {
    await gotoRecentJobs(page);
    await selectSubcategory(page, SWE, 'Frontend');

    await expect(
      page.getByRole('heading', { level: 3, name: job('J-FULLSTACK').title }),
      'a Frontend selection did not surface the Full Stack role. The widening ' +
        '(frontend ⊃ full_stack) is the one thing this dimension does beyond plain ' +
        'membership.',
    ).toBeVisible();
    await expectResults(page, titlesForSubcategory('frontend'));
  });

  test('SC-04 Backend also surfaces the Full Stack job', async ({ signedInPage: page }) => {
    await gotoRecentJobs(page);
    await selectSubcategory(page, SWE, 'Backend');
    await expect(
      page.getByRole('heading', { level: 3, name: job('J-FULLSTACK').title }),
    ).toBeVisible();
    await expectResults(page, titlesForSubcategory('backend'));
  });

  test('SC-04 Full Stack alone stays exact', async ({ signedInPage: page }) => {
    await gotoRecentJobs(page);
    await selectSubcategory(page, SWE, 'Full Stack');

    await expectResults(page, titlesFor('J-FULLSTACK'));
    await expect(
      page.getByRole('heading', { level: 3, name: job('J-FRONTEND').title }),
      'a Full Stack selection surfaced a Frontend job — the widening has become ' +
        'symmetric, which makes Full Stack a synonym for the whole category',
    ).toHaveCount(0);
    await expect(
      page.getByRole('heading', { level: 3, name: job('J-BACKEND').title }),
      'a Full Stack selection surfaced a Backend job — the widening has become symmetric',
    ).toHaveCount(0);
  });

  test('SC-04 an unrelated slug does not pick the Full Stack job up', async ({
    signedInPage: page,
  }) => {
    await gotoRecentJobs(page);
    await selectSubcategory(page, SWE, 'Security');
    await expect(
      page.getByRole('heading', { level: 3, name: job('J-FULLSTACK').title }),
      'only Frontend and Backend widen; Security must stay exact',
    ).toHaveCount(0);
  });
});
