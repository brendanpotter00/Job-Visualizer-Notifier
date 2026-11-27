// OB-U7 — moving between the questions: Back is shown but disabled on Q1,
// Back keeps every answer (one draft holds all four steps), the counter and
// the progress bar advance together, and focus lands on each question's h1 so
// a screen reader hears the new question. Moving never saves anything.
import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';
import {
  QUESTION_TITLES,
  RECENT_JOBS,
  button,
  chip,
  expectNoAccountYet,
  expectQuestion,
  expectUnstamped,
  freshIdentity,
  openSignedIn,
  roleBox,
} from './helpers';

/** The bar's fill as a fraction of its track, once the slide has settled. */
async function progressFraction(page: Page): Promise<number> {
  const track = await page.getByTestId('onboarding-progress').boundingBox();
  const fill = await page.getByTestId('onboarding-progress-fill').boundingBox();
  if (!track || !fill || track.width === 0) return Number.NaN;
  return fill.width / track.width;
}

async function expectProgress(page: Page, expected: number, what: string) {
  await expect
    .poll(() => progressFraction(page), { message: `${what}: progress bar fill / track` })
    .toBeCloseTo(expected, 2);
}

async function expectFocusedOn(dialog: Locator, title: string) {
  const h1 = dialog.getByRole('heading', { level: 1, name: title });
  await expect(h1, `focus should land on the question "${title}"`).toBeFocused();
}

test.describe('OB-U7 Back and Continue', () => {
  test('OB-U7 Back is disabled on Q1, keeps answers, and the counter, bar and focus follow', async ({ browser }) => {
    const me = freshIdentity('OB-U7');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me);
    const page = await context.newPage();
    await page.goto(RECENT_JOBS);

    // Q1
    let dialog = await expectQuestion(page, 0);
    await expect(button(dialog, 'Back'), 'Back is SHOWN on question 1').toBeVisible();
    await expect(button(dialog, 'Back'), '…and disabled').toBeDisabled();
    await expectFocusedOn(dialog, QUESTION_TITLES[0]);
    await expectProgress(page, 1 / 4, 'Q1');
    await roleBox(dialog, 'Software Engineering').check();
    await chip(dialog, 'Backend').check();
    await roleBox(dialog, 'Product Manager').check();
    await button(dialog, 'Continue').click();

    // Q2
    dialog = await expectQuestion(page, 1);
    await expect(dialog.getByText('1/4', { exact: true })).toHaveCount(0);
    await expect(button(dialog, 'Back')).toBeEnabled();
    await expectFocusedOn(dialog, QUESTION_TITLES[1]);
    await expectProgress(page, 2 / 4, 'Q2');
    await chip(dialog, 'Mid').check();

    // Back to Q1: every tick is still there.
    await button(dialog, 'Back').click();
    dialog = await expectQuestion(page, 0);
    await expectFocusedOn(dialog, QUESTION_TITLES[0]);
    await expectProgress(page, 1 / 4, 'back on Q1');
    await expect(roleBox(dialog, 'Software Engineering')).toBeChecked();
    await expect(chip(dialog, 'Backend'), 'the specialty survives Back').toBeChecked();
    await expect(roleBox(dialog, 'Product Manager')).toBeChecked();
    await expect(roleBox(dialog, 'Growth'), 'an untouched role stays unticked').not.toBeChecked();

    // Forward again: the Q2 answer survived going back.
    await button(dialog, 'Continue').click();
    dialog = await expectQuestion(page, 1);
    await expect(chip(dialog, 'Mid'), 'the level survives Back then Continue').toBeChecked();
    await button(dialog, 'Continue').click();

    // Q3
    dialog = await expectQuestion(page, 2);
    await expectFocusedOn(dialog, QUESTION_TITLES[2]);
    await expectProgress(page, 3 / 4, 'Q3');
    await expect(button(dialog, 'Continue'), 'Q3 is no longer the last step').toBeVisible();
    await button(dialog, 'Continue').click();

    // Q4, the last
    dialog = await expectQuestion(page, 3);
    await expectFocusedOn(dialog, QUESTION_TITLES[3]);
    await expectProgress(page, 1, 'Q4');
    await expect(button(dialog, 'Show my jobs'), 'the last step finishes, it does not continue').toBeVisible();
    await expect(button(dialog, 'Continue')).toHaveCount(0);

    // Moving between questions never saved anything.
    const state = expectUnstamped(me, 'OB-U7 after moving through all four questions');
    expect(state.savedFilters).toBeNull();
    await context.close();
  });
});
