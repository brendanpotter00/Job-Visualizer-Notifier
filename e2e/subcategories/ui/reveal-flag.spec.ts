// SC-05 — the reveal flag, in a real browser. THIS is the tier the flag is
// about: it is a UI switch and nothing else, so the visible half is the half
// that matters.
//
// With the flag off, `FacetTreeMultiSelect` is handed `childOptions: []` and
// renders *byte-identically to the flat `FacetMultiSelect`*: same combobox,
// same six category rows, no chevron, and no child rows even under a ticked
// Software Engineering. With it on, the Software Engineering row's accessible
// name carries a hidden ", 17 specialties" and ticking it reveals the children.
// Those two are the control's UI signature (the chevron itself is aria-hidden),
// which is why these specs assert on them.
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
  expandParent,
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
  test('SC-05 with the flag ON ticking Software Engineering reveals the children', async ({
    signedInPage: page,
  }) => {
    reseed({ reveal: true });
    await gotoRecentJobs(page);
    const menu = await openCategoryMenu(page);

    // The control half of the case. Everything the OFF test asserts is an
    // absence, and an absence proves nothing unless the presence is shown too.
    //
    // Tick to reveal: the children are hidden until their parent is ticked,
    // and the parent's name says how many it holds.
    await expect(
      menu.getByRole('option', { name: /^Software Engineering, \d+ specialties$/ }),
      'with the flag on, the Software Engineering row must announce its specialties',
    ).toBeVisible();
    await expect(
      menu.getByRole('option', { name: 'Backend', exact: true }),
      'a specialty is on screen before Software Engineering was ticked',
    ).toHaveCount(0);

    await expandParent(page, menu, SWE);
    await expect(
      menu.getByRole('option', { name: 'Backend', exact: true }),
      'ticking Software Engineering must reveal its specialties right away',
    ).toBeVisible();
    await expect(menu.getByRole('option', { name: 'Full Stack', exact: true })).toBeVisible();
    await expect(
      parentOption(menu, SWE).getByRole('button'),
      'the chevron is a cue, not a control: no row may carry a button',
    ).toHaveCount(0);
  });

  test('SC-05 with the flag OFF the subcategory control is absent', async ({
    signedInPage: page,
  }) => {
    reseed({ reveal: false });
    await gotoRecentJobs(page);
    const menu = await openCategoryMenu(page);

    await expect(
      menu.getByRole('option', { name: SWE, exact: true }),
      'the Job Category control itself must still be there, with no specialty count — ' +
        'the flag hides the TREE, not the category filter',
    ).toBeVisible();
    await expect(
      menu.getByRole('button'),
      'NO row may carry any control with the flag off — with childOptions empty the ' +
        'tree must render identically to the flat category control',
    ).toHaveCount(0);

    // Even ticked, Software Engineering has nothing to reveal.
    await expandParent(page, menu, SWE);
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
