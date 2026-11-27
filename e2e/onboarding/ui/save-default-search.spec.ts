// OB-U14..OB-U17 — the default-search buttons on Recent Jobs, end to end:
// "Save default search" (signed in: "Update default search", and a solid green
// "Default search saved" on the saved default), then "Reset to default search",
// shown only while the filters differ from the default. There is no Reset
// Filters and no confirmation text: the button is the confirmation.
//
//   OB-U14  signed in: "Default search saved" on the saved default; a change
//           offers Update and Reset; Reset before a save goes back to the server
//           defaults; Update saves the whole Recent filter set (DB + a new
//           context hydrating to it); Reset after a change goes back to the
//           SAVED default, and sends nothing.
//   OB-U15  signed out -> sign in as a BRAND-NEW account: the search survives
//           the sign-in in sessionStorage, the first-sign-in questions never
//           open, the account is stamped, and the search is saved.
//   OB-U16  signed out -> sign in as an EXISTING account: its different saved
//           default is replaced; the Companies (trend) window is not touched.
//   OB-U17  decoy: the sign-in is abandoned (the next load is still signed
//           out): the search shows once, nothing is sent, never "Default
//           search saved"; Reset to default search goes back to the site
//           defaults, and a new visit to bare /jobs is on them too.
//   OB-U19  signed in: a company type change ALONE offers Update, the save
//           writes company_category, a new context opens on it, and Reset to
//           default search puts it back.
//   OB-U20  signed out with a company type -> a brand-new account: the stamp and
//           the save both carry the company type; the questions never open.
//
// The signed-out click really calls Auth0's `loginWithRedirect`; the section's
// network fence aborts that navigation (the Auth0 domain is a fake .test host).
// "Signing in" is then the app's own minted-token path (`signInContext`) and a
// `page.goto('/jobs')` on the SAME page, so the tab's sessionStorage — where the
// pending search lives — survives, exactly as it does across a real redirect.
//
// Not driven here: the Location field (its search box needs the locations
// catalog; the field table is unit-tested in `defaultSearch.test.ts`).
import { expect, test } from '@playwright/test';
import type { Browser, BrowserContext, Locator, Page, Request } from '@playwright/test';
import { mintToken, signInContext } from '../../shared/auth/storage_state';
import {
  DESKTOP,
  RECENT_JOBS,
  button,
  dbState,
  expectNoAccountYet,
  expectQuestion,
  expectQuestionsNeverOpen,
  expectStamped,
  filterField,
  freshIdentity,
  openSignedIn,
  questions,
  shot as rawShot,
  trackUserFetches,
  type DbState,
  type Identity,
} from './helpers';

const PENDING_KEY = 'jvn.pendingDefaultSearch.v1';
const AUTH0_HOST = 'e2e.local.test';
const BACKEND = process.env.E2E_BACKEND_URL ?? 'http://127.0.0.1:8205';

// --- Drivers -------------------------------------------------------------------

/**
 * A screenshot taken once the page is still: every finite animation or
 * transition has finished (the save button fades black -> green over 250ms, and
 * a closing menu fades out), capped at 2s so a looping one can't hang it. These
 * screenshots are the PR's evidence, so a mid-fade frame misreports the design.
 */
async function shot(page: Page, caseId: string, name: string): Promise<void> {
  await page.evaluate(() =>
    Promise.race([
      Promise.all(
        document
          .getAnimations()
          .filter((a) => a.effect?.getComputedTiming().endTime !== Infinity)
          .map((a) => a.finished.catch(() => undefined)),
      ),
      new Promise((resolve) => setTimeout(resolve, 2_000)),
    ]),
  );
  // Role queries skip hidden elements, so a kept-mounted closed menu doesn't count.
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await expect(page.getByRole('menu')).toHaveCount(0);
  await rawShot(page, caseId, name);
}

const byName = (page: Page, name: string): Locator => page.getByRole('button', { name, exact: true });
/** Signed out (nothing saved yet). */
const saveButton = (page: Page): Locator => byName(page, 'Save default search');
/** Signed in, filters changed. */
const updateButton = (page: Page): Locator => byName(page, 'Update default search');
/** Signed in, on the saved default: the solid green button is the confirmation. */
const savedButton = (page: Page): Locator => byName(page, 'Default search saved');
const resetButton = (page: Page): Locator => byName(page, 'Reset to default search');
const timeWindowField = (page: Page): Locator => page.getByRole('combobox', { name: 'Time Window' });

function keywordChips(page: Page): Locator {
  return page
    .locator('.MuiAutocomplete-root')
    .filter({ has: page.getByRole('combobox', { name: 'Keywords' }) })
    .locator('.MuiChip-label');
}

async function addKeyword(page: Page, text: string): Promise<void> {
  const input = page.getByRole('combobox', { name: 'Keywords' });
  await input.click();
  await input.fill(text);
  await input.press('Enter');
  await page.keyboard.press('Escape');
  await expect(keywordChips(page).filter({ hasText: text })).toHaveCount(1);
}

async function pickTimeWindow(page: Page, label: string): Promise<void> {
  await page.getByRole('combobox', { name: 'Time Window' }).click();
  await page.getByRole('listbox').getByRole('option', { name: label, exact: true }).click();
  await expect(page.getByRole('listbox')).toBeHidden();
}

async function pickSpecialty(page: Page, parent: string, child: string): Promise<void> {
  await filterField(page, 'Job Category').click();
  const menu = page.getByRole('listbox');
  await expect(menu).toBeVisible();
  const parentRow = menu.getByRole('option', { name: new RegExp(`^${parent}`) });
  if ((await parentRow.getAttribute('aria-selected')) !== 'true') await parentRow.click();
  await expect(parentRow).toHaveAttribute('aria-selected', 'true');
  await menu.getByRole('option', { name: child, exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
}

async function pickLevel(page: Page, label: string): Promise<void> {
  await filterField(page, 'Level').click();
  const menu = page.getByRole('listbox');
  await menu.getByRole('option', { name: label, exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
}

async function pickCompanyType(page: Page, label: string): Promise<void> {
  await filterField(page, 'Company type').click();
  const menu = page.getByRole('listbox');
  await expect(menu).toBeVisible();
  await menu.getByRole('option', { name: label, exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(menu).toBeHidden();
}

/** A fenced context with NO sign-in: a signed-out visitor. */
async function openSignedOut(browser: Browser): Promise<BrowserContext> {
  const context = await browser.newContext({ viewport: DESKTOP });
  await context.route(
    (url) => url.hostname !== '127.0.0.1' && url.hostname !== 'localhost',
    (route) => route.abort('blockedbyclient'),
  );
  return context;
}

/** Every write this page sends to `/api/users*` (the decoy's "nothing sent" oracle). */
function trackUserWrites(page: Page): () => string[] {
  const writes: string[] = [];
  page.on('request', (r: Request) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith('/api/users') && r.method() !== 'GET') writes.push(`${r.method()} ${u.pathname}`);
  });
  return () => [...writes];
}

/**
 * Signed out on /jobs: set a search, press Save default search, and wait for
 * the Auth0 navigation the fence aborts.
 */
async function signedOutClick(page: Page, setSearch: () => Promise<void>, caseId: string): Promise<void> {
  await page.goto(RECENT_JOBS);
  await expect(page.getByRole('heading', { level: 1, name: 'Recent Job Postings' })).toBeVisible();
  await expect(saveButton(page), 'signed out at the site defaults: grayed out').toBeDisabled();
  await setSearch();
  await expect(saveButton(page), 'signed out, filters changed: enabled').toBeEnabled();
  await shot(page, caseId, '01-signed-out-search');
  const authNavigation = page.waitForRequest((r) => new URL(r.url()).hostname === AUTH0_HOST);
  await saveButton(page).click();
  await authNavigation;
}

/** The saved row points both keyword pointers at a "Default search" list holding `keyword`. */
function expectDefaultSearchList(state: DbState, keyword: string, what: string): void {
  const sf = state.savedFilters;
  expect(sf, `${what}: a saved-filters row`).toBeTruthy();
  const list = (state.keywordLists ?? []).find((l) => l.name === 'Default search');
  expect(list, `${what}: a "Default search" keyword list`).toBeTruthy();
  expect(list?.tags, `${what}: the list holds the typed keyword`).toEqual([{ text: keyword, mode: 'include' }]);
  expect(sf?.recentActiveKeywordListId, `${what}: the Recent pointer`).toBe(list?.id);
  expect(sf?.trendActiveKeywordListId, `${what}: the trend pointer (one active list on all pages)`).toBe(list?.id);
}

async function api(token: string, method: 'GET' | 'POST' | 'PUT', path: string, body?: unknown) {
  const res = await fetch(`${BACKEND}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  expect(res.ok, `${method} ${path} -> ${res.status}`).toBe(true);
  return res.status === 204 ? null : res.json();
}

// --- Cases ---------------------------------------------------------------------

test.describe('OB-U14 signed-in default-search buttons', () => {
  test('OB-U14 "Default search saved" on the default; Update saves; Reset goes back to the saved default', async ({ browser }) => {
    const me: Identity = freshIdentity('OB-U14');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me);
    const page = await context.newPage();
    const writes = trackUserWrites(page);
    const savedFiltersWrites = () => writes().filter((w) => w.includes('/saved-filters'));
    await page.goto(RECENT_JOBS);

    // A brand-new account: Skip the questions with no answers (stamped, stays here).
    const dialog = await expectQuestion(page, 0);
    await button(dialog, 'Skip').click();
    await expect(questions(page)).toHaveCount(0);
    await expectStamped(me, 'OB-U14 after Skip');

    await expect(savedButton(page), 'on the saved default (the server defaults): says so, not clickable').toBeDisabled();
    // The design: a solid green saved state (theme success.dark).
    await expect(savedButton(page)).toHaveCSS('background-color', 'rgb(46, 125, 50)');
    await expect(resetButton(page), 'on the default: no Reset').toHaveCount(0);
    await expect(byName(page, 'Reset Filters'), 'Reset Filters is gone').toHaveCount(0);
    await shot(page, 'OB-U14', '01-unchanged');

    await addKeyword(page, 'e2e-kw-14');
    await pickTimeWindow(page, '24 hours');
    await expect(updateButton(page), 'filters changed: Update default search').toBeEnabled();
    // Solid black Update, outlined Reset beside it.
    await expect(updateButton(page)).toHaveCSS('background-color', 'rgb(0, 0, 0)');
    await expect(resetButton(page)).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    await expect(resetButton(page), 'filters changed: Reset to default search').toBeEnabled();
    const [updateBox, resetBox] = [await updateButton(page).boundingBox(), await resetButton(page).boundingBox()];
    expect(resetBox!.x, 'Reset sits to the right of Update').toBeGreaterThan(updateBox!.x);
    await shot(page, 'OB-U14', '02-changed');

    // Reset before any save: back on the server defaults, nothing sent.
    await resetButton(page).click();
    await expect(keywordChips(page)).toHaveCount(0);
    await expect(timeWindowField(page)).toHaveText('All time');
    await expect(savedButton(page)).toBeDisabled();
    await expect(resetButton(page)).toHaveCount(0);
    expect(savedFiltersWrites(), 'OB-U14: Reset saves nothing').toEqual([]);

    await addKeyword(page, 'e2e-kw-14');
    await pickTimeWindow(page, '24 hours');
    await updateButton(page).click();
    await expect(savedButton(page), 'just saved: the button is the confirmation').toBeDisabled();
    await expect(resetButton(page), 'just saved: no Reset').toHaveCount(0);
    await expect(page.getByText('Saved default search'), 'no confirmation text beside the buttons').toHaveCount(0);
    await shot(page, 'OB-U14', '03-saved');

    await expect
      .poll(() => dbState(me).savedFilters?.recentTimeWindow, { message: 'OB-U14: the saved Recent window' })
      .toBe('24h');
    const state = dbState(me);
    expect(state.savedFilters?.trendTimeWindow, 'OB-U14: the trend window is untouched').toBe('90d');
    expectDefaultSearchList(state, 'e2e-kw-14', 'OB-U14');

    // The next edit: Update and Reset are back, and Reset now goes back to the
    // SAVED default (24 hours + the keyword), not the site defaults.
    await pickTimeWindow(page, '3 days');
    await expect(savedButton(page)).toHaveCount(0);
    await expect(updateButton(page)).toBeEnabled();
    const writesBeforeReset = savedFiltersWrites().length;
    await resetButton(page).click();
    await expect(timeWindowField(page)).toHaveText('24 hours');
    await expect(keywordChips(page)).toHaveText(['e2e-kw-14']);
    await expect(savedButton(page)).toBeDisabled();
    await expect(resetButton(page)).toHaveCount(0);
    await shot(page, 'OB-U14', '04-reset-to-saved');
    await page.waitForTimeout(500);
    expect(savedFiltersWrites(), 'OB-U14: Reset to the saved default sends nothing').toHaveLength(writesBeforeReset);
    await context.close();

    // A new device: the page opens on the saved search, button solid green.
    const again = await openSignedIn(browser, me);
    const page2 = await again.newPage();
    const tracker = trackUserFetches(page2);
    await page2.goto(RECENT_JOBS);
    await expectQuestionsNeverOpen(page2, tracker, 'OB-U14 new context');
    await expect(keywordChips(page2)).toHaveText(['e2e-kw-14']);
    await expect(timeWindowField(page2)).toHaveText('24 hours');
    await expect(savedButton(page2)).toBeDisabled();
    await expect(resetButton(page2)).toHaveCount(0);
    await shot(page2, 'OB-U14', '05-new-context');
    await again.close();
  });
});

test.describe('OB-U15 signed out, then a brand-new account', () => {
  test('OB-U15 the search survives sign-in, no questions, account stamped and saved', async ({ browser }) => {
    const me = freshIdentity('OB-U15');
    expectNoAccountYet(me);
    const context = await openSignedOut(browser);
    const page = await context.newPage();
    await signedOutClick(
      page,
      async () => {
        await pickSpecialty(page, 'Software Engineering', 'Backend');
        await pickLevel(page, 'Entry');
        await pickTimeWindow(page, '24 hours');
        await addKeyword(page, 'e2e-kw-15');
      },
      'OB-U15',
    );

    // "Sign in" and come back to /jobs in the SAME tab.
    await signInContext(context, me);
    // The questions must never open, not even for the moment between the
    // user arriving unstamped and the stamp landing. Hold the stamping POST
    // like prod latency would, and record in the page any dialog that appears
    // (a settle-window check alone misses a dialog that closes again).
    await context.route('**/api/users/onboarding', async (route) => {
      await new Promise((r) => setTimeout(r, 1_500));
      await route.continue();
    });
    await context.addInitScript(() => {
      const w = window as unknown as { __questionsSeen?: boolean };
      w.__questionsSeen = false;
      new MutationObserver(() => {
        if (document.querySelector('[role="dialog"]')) w.__questionsSeen = true;
      }).observe(document, { childList: true, subtree: true });
    });
    const tracker = trackUserFetches(page);
    await page.goto(RECENT_JOBS);
    await expectQuestionsNeverOpen(page, tracker, 'OB-U15 back from sign-in (new account)');

    await expect(savedButton(page), 'the search was saved on arrival').toBeVisible({ timeout: 15_000 });
    await expect(filterField(page, 'Job Category')).toHaveText('Software Engineering, Backend');
    await expect(filterField(page, 'Level')).toHaveText('Entry');
    await expect(page.getByRole('combobox', { name: 'Time Window' })).toHaveText('24 hours');
    await expect(keywordChips(page)).toHaveText(['e2e-kw-15']);
    await expect(savedButton(page)).toBeDisabled();
    await expect(resetButton(page)).toHaveCount(0);
    expect(
      await page.evaluate(() => (window as unknown as { __questionsSeen?: boolean }).__questionsSeen),
      'OB-U15: the first-sign-in questions appeared at some point during the load',
    ).toBe(false);
    await shot(page, 'OB-U15', '02-back-saved');

    const state = await expectStamped(me, 'OB-U15 a new account finishing a signed-out save');
    await expect
      .poll(() => dbState(me).savedFilters?.recentTimeWindow, { message: 'OB-U15: the saved Recent window' })
      .toBe('24h');
    const saved = dbState(me);
    expect(saved.savedFilters).toMatchObject({
      trendTimeWindow: '90d',
      category: ['software_engineering'],
      subcategory: ['backend'],
      level: ['entry'],
      locations: [],
    });
    expectDefaultSearchList(saved, 'e2e-kw-15', 'OB-U15');
    expect(await page.evaluate((k) => window.sessionStorage.getItem(k), PENDING_KEY), 'pending cleared').toBeNull();
    await context.close();

    // A new device: still no questions, same search.
    const again = await openSignedIn(browser, me);
    const page2 = await again.newPage();
    const tracker2 = trackUserFetches(page2);
    await page2.goto(RECENT_JOBS);
    await expectQuestionsNeverOpen(page2, tracker2, 'OB-U15 new context');
    await expect(filterField(page2, 'Level')).toHaveText('Entry');
    await expect(keywordChips(page2)).toHaveText(['e2e-kw-15']);
    await expect(savedButton(page2)).toBeDisabled();
    expect(dbState(me).onboardingCompletedAt, 'the stamp does not move').toBe(state.onboardingCompletedAt);
    await again.close();
  });
});

test.describe('OB-U16 signed out, then an existing account', () => {
  test('OB-U16 the old default is replaced; the trend window is not touched', async ({ browser }) => {
    const me = freshIdentity('OB-U16');
    expectNoAccountYet(me);
    // An existing, stamped account with a DIFFERENT default and a non-default
    // trend window, made through the API.
    const token = mintToken(me);
    await api(token, 'GET', '/api/users');
    await api(token, 'POST', '/api/users/onboarding', { skipped: true, step: 1 });
    await api(token, 'PUT', '/api/users/saved-filters', {
      recentTimeWindow: '7d',
      trendTimeWindow: '30d',
      locations: [],
      category: [],
      level: ['senior'],
      subcategory: [],
      recentActiveKeywordListId: null,
      trendActiveKeywordListId: null,
    });
    const before = dbState(me);
    expect(before.savedFilters?.level).toEqual(['senior']);

    const context = await openSignedOut(browser);
    const page = await context.newPage();
    await signedOutClick(
      page,
      async () => {
        await pickLevel(page, 'Entry');
        await addKeyword(page, 'e2e-kw-16');
      },
      'OB-U16',
    );

    await signInContext(context, me);
    const tracker = trackUserFetches(page);
    await page.goto(RECENT_JOBS);
    await expectQuestionsNeverOpen(page, tracker, 'OB-U16 back from sign-in (existing account)');
    await expect(savedButton(page), 'the search was saved on arrival').toBeVisible({ timeout: 15_000 });
    // The pending search, not the old saved default (Senior, 7 days).
    await expect(filterField(page, 'Level')).toHaveText('Entry');
    await expect(page.getByRole('combobox', { name: 'Time Window' })).toHaveText('All time');
    await shot(page, 'OB-U16', '02-back-saved');

    await expect
      .poll(() => dbState(me).savedFilters?.level, { message: 'OB-U16: the saved level' })
      .toEqual(['entry']);
    const after = dbState(me);
    expect(after.savedFilters?.recentTimeWindow, 'OB-U16: the signed-out search had the site default').toBe('all');
    expect(after.savedFilters?.trendTimeWindow, 'OB-U16: the Companies window is not touched').toBe('30d');
    expectDefaultSearchList(after, 'e2e-kw-16', 'OB-U16');
    expect(after.onboardingCompletedAt, 'OB-U16: an existing stamp does not move').toBe(before.onboardingCompletedAt);
    await context.close();
  });
});

test.describe('OB-U17 decoy: the sign-in is abandoned', () => {
  test('OB-U17 the search shows once, nothing is sent, Reset and the next visit are the site defaults', async ({ browser }) => {
    const context = await openSignedOut(browser);
    const page = await context.newPage();
    const writes = trackUserWrites(page);
    await signedOutClick(
      page,
      async () => {
        await pickLevel(page, 'Entry');
        await addKeyword(page, 'e2e-kw-17');
      },
      'OB-U17',
    );

    // Back on /jobs, still signed out.
    await page.goto(RECENT_JOBS);
    await expect(page.getByRole('heading', { level: 1, name: 'Recent Job Postings' })).toBeVisible();
    // Restored once (proof the pending search existed)...
    await expect(filterField(page, 'Level')).toHaveText('Entry');
    await expect(keywordChips(page)).toHaveText(['e2e-kw-17']);
    // ...then dropped, with nothing saved and nothing sent.
    await expect
      .poll(() => page.evaluate((k) => window.sessionStorage.getItem(k), PENDING_KEY), {
        message: 'OB-U17: the pending search is dropped once the load is signed out',
      })
      .toBeNull();
    await page.waitForTimeout(1_000);
    await expect(savedButton(page), 'signed out: never "Default search saved"').toHaveCount(0);
    await expect(saveButton(page), 'signed out, filters differ: Save default search').toBeEnabled();
    expect(writes(), 'OB-U17: no write to /api/users*').toEqual([]);
    await shot(page, 'OB-U17', '02-restored-once');

    // Signed out, the default search is the site defaults.
    await resetButton(page).click();
    await expect(filterField(page, 'Level')).toHaveText('All');
    await expect(keywordChips(page)).toHaveCount(0);
    await expect(saveButton(page), 'back on the site defaults: grayed out').toBeDisabled();
    await expect(resetButton(page)).toHaveCount(0);
    await expect(savedButton(page)).toHaveCount(0);
    await shot(page, 'OB-U17', '03-reset');

    // A new visit to bare /jobs (the URL sync wrote the filters into the address
    // bar, so a plain reload would re-apply them from the URL): site defaults.
    await page.goto(RECENT_JOBS);
    await expect(page.getByRole('heading', { level: 1, name: 'Recent Job Postings' })).toBeVisible();
    await expect(filterField(page, 'Level')).toHaveText('All');
    await expect(keywordChips(page)).toHaveCount(0);
    await expect(saveButton(page)).toBeDisabled();
    expect(writes(), 'OB-U17: still no write').toEqual([]);
    await context.close();
  });
});

test.describe('OB-U19 signed-in default search with a company type', () => {
  test('OB-U19 a company type alone is a change; the save, a new context and Reset carry it', async ({ browser }) => {
    const me: Identity = freshIdentity('OB-U19');
    expectNoAccountYet(me);
    const context = await openSignedIn(browser, me);
    const page = await context.newPage();
    await page.goto(RECENT_JOBS);

    const dialog = await expectQuestion(page, 0);
    await button(dialog, 'Skip').click();
    await expect(questions(page)).toHaveCount(0);
    await expectStamped(me, 'OB-U19 after Skip');
    await expect(savedButton(page), 'on the saved default: "Default search saved"').toBeDisabled();

    await pickCompanyType(page, 'Fintech & Trading');
    await expect(filterField(page, 'Company type')).toHaveText('Fintech & Trading');
    await expect(updateButton(page), 'only the company type changed: Update').toBeEnabled();
    await expect(resetButton(page), 'only the company type changed: Reset').toBeEnabled();
    await shot(page, 'OB-U19', '01-company-type-changed');

    await updateButton(page).click();
    await expect(savedButton(page), 'just saved: "Default search saved"').toBeDisabled();
    await expect(resetButton(page)).toHaveCount(0);
    await expect
      .poll(() => dbState(me).savedFilters?.companyCategory, { message: 'OB-U19: the saved company types' })
      .toEqual(['fintech']);
    expect(dbState(me).savedFilters?.recentTimeWindow, 'OB-U19: the rest of the search is unchanged').toBe('all');
    await shot(page, 'OB-U19', '02-saved');
    await context.close();

    // A new device opens on the saved company type, button grayed out.
    const again = await openSignedIn(browser, me);
    const page2 = await again.newPage();
    const tracker = trackUserFetches(page2);
    await page2.goto(RECENT_JOBS);
    await expectQuestionsNeverOpen(page2, tracker, 'OB-U19 new context');
    await expect(filterField(page2, 'Company type')).toHaveText('Fintech & Trading');
    await expect(savedButton(page2)).toBeDisabled();

    // Clearing it is a change again, and Reset puts the saved company type back.
    await pickCompanyType(page2, 'Fintech & Trading');
    await expect(filterField(page2, 'Company type')).not.toHaveText('Fintech & Trading');
    await expect(updateButton(page2), 'company type cleared: Update').toBeEnabled();
    await shot(page2, 'OB-U19', '03-new-context-cleared');
    await resetButton(page2).click();
    await expect(filterField(page2, 'Company type')).toHaveText('Fintech & Trading');
    await expect(savedButton(page2), 'reset: back on the saved default').toBeDisabled();
    await expect(resetButton(page2)).toHaveCount(0);
    await shot(page2, 'OB-U19', '04-reset');
    await again.close();
  });
});

test.describe('OB-U20 signed out with a company type, then a brand-new account', () => {
  test('OB-U20 the stamp and the save carry the company type', async ({ browser }) => {
    const me = freshIdentity('OB-U20');
    expectNoAccountYet(me);
    const context = await openSignedOut(browser);
    const page = await context.newPage();
    await signedOutClick(
      page,
      async () => {
        await pickLevel(page, 'Entry');
        await pickCompanyType(page, 'AI Labs');
      },
      'OB-U20',
    );

    await signInContext(context, me);
    const tracker = trackUserFetches(page);
    await page.goto(RECENT_JOBS);
    await expectQuestionsNeverOpen(page, tracker, 'OB-U20 back from sign-in (new account)');

    await expect(savedButton(page), 'the search was saved on arrival').toBeVisible({ timeout: 15_000 });
    await expect(filterField(page, 'Company type')).toHaveText('AI Labs');
    await expect(filterField(page, 'Level')).toHaveText('Entry');
    await expect(savedButton(page)).toBeDisabled();
    await shot(page, 'OB-U20', '02-back-saved');

    await expectStamped(me, 'OB-U20 a new account finishing a signed-out save');
    await expect
      .poll(() => dbState(me).savedFilters?.companyCategory, { message: 'OB-U20: the saved company types' })
      .toEqual(['ai_labs']);
    expect(dbState(me).savedFilters?.level, 'OB-U20: the saved level').toEqual(['entry']);
    expect(await page.evaluate((k) => window.sessionStorage.getItem(k), PENDING_KEY), 'pending cleared').toBeNull();
    await context.close();
  });
});

