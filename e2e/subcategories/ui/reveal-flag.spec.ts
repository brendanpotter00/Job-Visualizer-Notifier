// SC-05 — the reveal flag, in a real browser. THIS is the tier the flag is
// about: it is a UI switch and nothing else, so the visible half is the half
// that matters.
//
// With the flag off, `FacetTreeMultiSelect` is handed `childOptions: []` and
// renders *byte-identically to the flat `FacetMultiSelect`* — same combobox,
// same six category rows, and no chevron anywhere. The absence of the chevron
// is the control's whole UI signature, which is why these specs assert on it
// rather than on a testid that does not exist.
//
// THE FLAG IS NOT A FEATURE GATE, and the second test below is what keeps that
// true from the user's side: with the control hidden, the results a reader
// gets must be exactly the results they got before the feature existed.
//
// ORDERING. This spec turns the flag OFF in the database. `beforeEach`
// re-seeds it to the state each test wants and `afterAll` puts it back ON, so
// the specs that run after this file cannot inherit an off flag and fail for a
// fixture reason. `run.sh` re-seeds before the UI tier for the same reason,
// belt and braces — an order-dependent landmine here would be green alone and
// the cause of a mystery failure elsewhere.
import {
  expect,
  expectResults,
  gotoRecentJobs,
  openCategoryMenu,
  parentOption,
  reseed,
  selectCategory,
  test,
} from './helpers';
import { sweTitles } from './corpus';

const SWE = 'Software Engineering';

test.afterAll(() => {
  reseed({ reveal: true });
});

test.describe('SC-05 reveal flag', () => {
  test('SC-05 with the flag ON the tree offers the subcategory children', async ({
    signedInPage: page,
  }) => {
    reseed({ reveal: true });
    await gotoRecentJobs(page);
    const menu = await openCategoryMenu(page);

    // The control half of the case. Everything the OFF test asserts is an
    // absence, and an absence proves nothing unless the presence is shown too.
    await expect(
      parentOption(menu, SWE).getByRole('button'),
      'with the flag on, the Software Engineering row must carry an expand chevron — ' +
        'that chevron IS the subcategory control',
    ).toHaveCount(1);

    await parentOption(menu, SWE).getByRole('button').click();
    await expect(menu.getByRole('option', { name: 'Backend', exact: true })).toBeVisible();
    await expect(menu.getByRole('option', { name: 'Full Stack', exact: true })).toBeVisible();
  });

  test('SC-05 with the flag OFF the subcategory control is absent', async ({
    signedInPage: page,
  }) => {
    reseed({ reveal: false });
    await gotoRecentJobs(page);
    const menu = await openCategoryMenu(page);

    await expect(
      parentOption(menu, SWE),
      'the Job Category control itself must still be there — the flag hides the TREE, ' +
        'not the category filter',
    ).toBeVisible();
    await expect(
      parentOption(menu, SWE).getByRole('button'),
      'the expand chevron is still rendered with the reveal flag off, so the ' +
        'subcategory control is reachable before the rollout says it should be',
    ).toHaveCount(0);
    await expect(
      menu.getByRole('button'),
      'NO row may carry a chevron with the flag off — with childOptions empty the ' +
        'tree must render identically to the flat category control',
    ).toHaveCount(0);
    await expect(
      menu.getByRole('option', { name: 'Backend', exact: true }),
      'a subcategory child row is in the DOM with the reveal flag off',
    ).toHaveCount(0);
  });

  test('SC-05 with the flag OFF the results are the no-subcategory results', async ({
    signedInPage: page,
  }) => {
    // "The flag gates the UI only" means a reader who cannot see the control
    // gets exactly what they got before the feature shipped: a category
    // selection returns its whole category, unlabelled rows included. Compared
    // against `sweTitles()` — the SAME expectation SC-01 asserts with the flag
    // ON — so the two states are pinned to one another rather than each to a
    // list of its own.
    reseed({ reveal: false });
    await gotoRecentJobs(page);
    await selectCategory(page, SWE);
    await expectResults(page, sweTitles());
  });
});
