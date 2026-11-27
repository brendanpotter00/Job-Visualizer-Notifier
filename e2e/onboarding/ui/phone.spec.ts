// OB-U10 — the headline path on a 390x844 phone.
//
// What only a real phone-sized layout can show: the dialog covers the whole
// screen; Back and Continue stay on screen at the bottom even with all 17
// specialties open above them; a chip keeps ONE width picked or not (the check
// replaces padding, so a tap never reflows the row); the "Saved filters"
// toast sits under the app bar, not over it; and on the list, at the narrowest
// (375px) phone, the filter fields' picks are chips that wrap inside their
// field, and a tap on a chip's delete icon removes just that pick.
import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';
import { CORPUS } from './corpus';
import {
  HEADLINE_LABELS,
  PHONE,
  RECENT_JOBS,
  button,
  chip,
  expectJobs,
  expectNoAccountYet,
  expectQuestion,
  expectStamped,
  filterChips,
  filterField,
  freshIdentity,
  openFilterMenu,
  openSignedIn,
  questions,
  roleBox,
  savedToast,
  shot,
} from './helpers';

/** The narrowest phone the filter row must fit (iPhone SE / mini width). */
const NARROW_PHONE = { width: 375, height: 812 };

/** Levels picked on top of the headline's Entry: enough to need a second row. */
const MORE_LEVELS = ['Mid', 'Senior', 'Staff / Principal', 'Manager', 'New Grad'];

/** Every chip of a facet field sits inside the field, and the field inside the screen. */
async function expectChipsInsideField(page: Page, label: 'Job Category' | 'Level', what: string) {
  const field = await filterField(page, label).boundingBox();
  expect(field, `${what}: ${label} geometry`).toBeTruthy();
  if (!field) return;
  expect(field.x, `${what}: ${label} starts off the screen`).toBeGreaterThanOrEqual(0);
  expect(field.x + field.width, `${what}: ${label} runs off the screen`).toBeLessThanOrEqual(NARROW_PHONE.width);
  for (const c of await filterChips(page, label).all()) {
    const box = await c.boundingBox();
    expect(box, `${what}: ${label} chip geometry`).toBeTruthy();
    if (!box) continue;
    const name = await c.innerText();
    expect(box.x, `${what}: the "${name}" chip starts outside its field`).toBeGreaterThanOrEqual(field.x);
    expect(box.x + box.width, `${what}: the "${name}" chip runs past its field`).toBeLessThanOrEqual(field.x + field.width);
    expect(box.y + box.height, `${what}: the "${name}" chip hangs below its field`).toBeLessThanOrEqual(field.y + field.height);
  }
}

/** Tap a chip and prove its width did not change. */
async function tapKeepsWidth(page: Page, target: Locator, label: string) {
  const before = await target.boundingBox();
  await target.tap();
  await expect(target).toBeChecked();
  // The chip re-renders with the check in place of its left padding.
  await page.waitForTimeout(50);
  const after = await target.boundingBox();
  expect(before && after, `${label}: chip geometry`).toBeTruthy();
  if (before && after) {
    expect(Math.abs(after.width - before.width), `${label}: the chip changed width when tapped`).toBeLessThanOrEqual(0.5);
    expect(Math.abs(after.height - before.height), `${label}: the chip changed height when tapped`).toBeLessThanOrEqual(0.5);
  }
}

/** Back + Continue are on screen, at the bottom. */
async function expectFooterReachable(page: Page, dialog: Locator, primary: 'Continue' | 'Show my jobs', what: string) {
  for (const name of ['Back', primary] as const) {
    const b = button(dialog, name);
    await expect(b, `${what}: ${name} on screen`).toBeInViewport({ ratio: 1 });
    const box = await b.boundingBox();
    expect(box, `${what}: ${name} geometry`).toBeTruthy();
    if (box) {
      expect(box.y + box.height, `${what}: ${name} inside the screen`).toBeLessThanOrEqual(PHONE.height);
      expect(box.y, `${what}: ${name} in the bottom bar`).toBeGreaterThan(PHONE.height * 0.75);
    }
  }
}

test.describe('OB-U10 phone', () => {
  test('OB-U10 the headline path at 390x844', async ({ browser }) => {
    const me = freshIdentity('OB-U10');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me, { phone: true });
    const page = await context.newPage();
    await page.goto(RECENT_JOBS);

    let dialog = await expectQuestion(page, 0);
    // Full screen: the dialog's paper is the whole viewport.
    const paper = await page.locator('.MuiDialog-paper').boundingBox();
    expect(paper, 'dialog geometry').toBeTruthy();
    if (paper) {
      expect(paper.x).toBeCloseTo(0, 0);
      expect(paper.y).toBeCloseTo(0, 0);
      expect(paper.width).toBeCloseTo(PHONE.width, 0);
      expect(paper.height).toBeCloseTo(PHONE.height, 0);
    }

    await roleBox(dialog, HEADLINE_LABELS.role).tap();
    await expect(roleBox(dialog, HEADLINE_LABELS.role)).toBeChecked();
    // All 17 specialties are open now; the footer must still be reachable.
    await expect(chip(dialog, 'Security')).toBeAttached();
    await expectFooterReachable(page, dialog, 'Continue', 'Q1 with the specialties open');
    await tapKeepsWidth(page, chip(dialog, HEADLINE_LABELS.specialty), 'Backend specialty chip');
    await shot(page, 'OB-U10', '01-roles');
    await button(dialog, 'Continue').tap();

    dialog = await expectQuestion(page, 1);
    await tapKeepsWidth(page, chip(dialog, HEADLINE_LABELS.level), 'Entry level chip');
    await expectFooterReachable(page, dialog, 'Continue', 'Q2');
    await shot(page, 'OB-U10', '02-levels');
    await button(dialog, 'Continue').tap();

    dialog = await expectQuestion(page, 2);
    await tapKeepsWidth(page, chip(dialog, HEADLINE_LABELS.place), 'San Francisco place chip');
    await expectFooterReachable(page, dialog, 'Continue', 'Q3');
    await shot(page, 'OB-U10', '03-places');
    await button(dialog, 'Continue').tap();

    dialog = await expectQuestion(page, 3);
    await tapKeepsWidth(page, chip(dialog, HEADLINE_LABELS.companyType), 'Big Tech company type chip');
    await expectFooterReachable(page, dialog, 'Show my jobs', 'Q4');
    await shot(page, 'OB-U10', '04-companies');
    await button(dialog, 'Show my jobs').tap();
    await expect(questions(page)).toHaveCount(0);

    // The toast sits under the app bar, never over it.
    const toast = savedToast(page);
    await expect(toast).toBeVisible();
    await toast.hover();
    const bar = await page.locator('header').first().boundingBox();
    const toastBox = await toast.boundingBox();
    expect(bar && toastBox, 'app bar + toast geometry').toBeTruthy();
    if (bar && toastBox) {
      expect(toastBox.y, 'the toast covers the app bar').toBeGreaterThanOrEqual(bar.y + bar.height);
      expect(toastBox.x + toastBox.width, 'the toast runs off the screen').toBeLessThanOrEqual(PHONE.width);
    }
    await shot(page, 'OB-U10', '05-landed');

    await expectJobs(page, CORPUS.headline.expectedKeys, 'OB-U10 with the headline answers');
    await expectStamped(me, 'OB-U10 after "Show my jobs"');

    // The filter row at the narrowest phone. The toast was hovered above, so
    // its timer is paused: Escape closes it.
    await page.keyboard.press('Escape');
    await expect(toast).toBeHidden();
    await page.setViewportSize(NARROW_PHONE);
    await expect(filterChips(page, 'Job Category')).toHaveText([HEADLINE_LABELS.role, HEADLINE_LABELS.specialty]);
    await expectChipsInsideField(page, 'Job Category', 'OB-U10 at 375px');

    // Many picks wrap onto a second row, inside the field, never off the screen.
    const menu = await openFilterMenu(page, 'Level', 'tap');
    for (const level of MORE_LEVELS) await menu.getByRole('option', { name: level, exact: true }).tap();
    await page.keyboard.press('Escape');
    await expect(menu).toBeHidden();
    // Gone, not just fading out, so the screenshot below shows the field.
    await expect(page.locator('.MuiMenu-root')).toHaveCount(0);
    const levels = filterChips(page, 'Level');
    await expect(levels).toHaveText([HEADLINE_LABELS.level, ...MORE_LEVELS]);
    await expectChipsInsideField(page, 'Level', 'OB-U10 at 375px with six levels');
    const rows = new Set<number>();
    for (const c of await levels.all()) rows.add(Math.round((await c.boundingBox())?.y ?? -1));
    expect(rows.size, 'six levels at 375px: the chips should wrap onto more than one row').toBeGreaterThan(1);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
      'the page scrolls sideways at 375px',
    ).toBeLessThanOrEqual(NARROW_PHONE.width);
    await shot(page, 'OB-U10', '10-filters-375-many-levels');

    // A tap on a chip's delete icon removes just that pick; the menu stays shut.
    await levels.filter({ hasText: 'Senior' }).locator('.MuiChip-deleteIcon').tap();
    await expect(levels).toHaveText([HEADLINE_LABELS.level, ...MORE_LEVELS.filter((l) => l !== 'Senior')]);
    await expect(page.getByRole('listbox')).toHaveCount(0);
    await shot(page, 'OB-U10', '11-filters-375-chip-removed');
    await context.close();
  });
});
