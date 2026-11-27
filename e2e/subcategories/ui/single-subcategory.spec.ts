// SC-02 — one subcategory, in a real browser.
//
// `Mobile` and `Security` are the pair, and neither takes part in the
// `full_stack` widening — so this case cannot pass for SC-04's reason. The
// decoy is the point: a list that showed the Security job under a Mobile
// selection is the regression, and "my job is there" would not catch it.
import {
  categoryChips,
  expect,
  expectResults,
  gotoRecentJobs,
  reseed,
  selectSubcategory,
  test,
} from './helpers';
import { job, sweTitles, titlesForSubcategory } from './corpus';

const SWE = 'Software Engineering';

test.beforeEach(() => {
  reseed({ reveal: true });
});

test.describe('SC-02 one subcategory', () => {
  test('SC-02 ticking Mobile shows only the mobile job', async ({ signedInPage: page }) => {
    await gotoRecentJobs(page);
    await selectSubcategory(page, SWE, 'Mobile');
    await expectResults(page, titlesForSubcategory('mobile'));
  });

  test('SC-02 the job carrying a different slug is not on screen', async ({
    signedInPage: page,
  }) => {
    await gotoRecentJobs(page);
    await selectSubcategory(page, SWE, 'Mobile');

    await expect(
      page.getByRole('heading', { level: 3, name: job('J-SECURITY').title }),
      'the Security job is on screen under a Mobile selection — the subcategory ' +
        'filter is not narrowing',
    ).toHaveCount(0);
    await expect(
      page.getByRole('heading', { level: 3, name: job('J-BACKEND').title }),
    ).toHaveCount(0);
  });

  test('SC-02 the decoy is reachable under its own slug', async ({ signedInPage: page }) => {
    // The mirror. Without it, "Security is absent" could just mean the job was
    // never seeded, and the case above would be green against an empty corpus.
    await gotoRecentJobs(page);
    await selectSubcategory(page, SWE, 'Security');
    await expectResults(page, titlesForSubcategory('security'));
  });

  test('SC-02 a ticked child shows beside its parent in the closed field', async ({
    signedInPage: page,
  }) => {
    // A child is only reachable under a ticked parent, which is what makes the
    // request carry BOTH slugs. Asserted on the control rather than on the
    // wire, because the closed field is what tells the user what they have
    // selected — and a child selected with no parent shown reads as a filter
    // that is not on.
    await gotoRecentJobs(page);
    await selectSubcategory(page, SWE, 'Mobile');
    await expect(categoryChips(page)).toHaveText([SWE, 'Mobile']);
  });

  test("SC-02 the child chip's delete icon unticks just the child, without opening the menu", async ({
    signedInPage: page,
  }) => {
    // The chip's x is the same edit as unticking the row: the parent stays, so
    // the list widens back to the whole category. No response wait: the
    // parent-only search was already made (ticking the parent), so it can come
    // from the cache; `expectResults` polls the list instead.
    await gotoRecentJobs(page);
    await selectSubcategory(page, SWE, 'Mobile');
    await categoryChips(page).filter({ hasText: 'Mobile' }).locator('.MuiChip-deleteIcon').click();
    await expect(categoryChips(page)).toHaveText([SWE]);
    await expect(page.getByRole('listbox')).toHaveCount(0);
    await expectResults(page, sweTitles());
  });
});
