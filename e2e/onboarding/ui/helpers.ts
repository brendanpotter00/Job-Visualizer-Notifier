// UI-tier helpers for the first-sign-in questions. Section-owned (not
// `shared/`) because every locator here names a control of the onboarding
// dialog or the Recent page.
//
// Sign-in is the app's own path (PLAN.md §4): `shared/auth/storage_state.ts`
// writes a minted token into localStorage before first paint. Every case mints
// a BRAND-NEW identity, and "sign in again" is a NEW browser context as the
// same identity — fresh storage, exactly like a new device or a later session.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { randomBytes } from 'node:crypto';
import { expect } from '@playwright/test';
import type { Browser, BrowserContext, Locator, Page, Request } from '@playwright/test';
import { signInContext } from '../../shared/auth/storage_state';
import { CORPUS, titlesFor } from './corpus';

const REPO_ROOT = path.resolve(__dirname, '../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const RUN_ID = process.env.E2E_RUN_ID ?? `local${Date.now()}`;
const ARTIFACTS_DIR = process.env.E2E_ARTIFACTS_DIR ?? path.join(__dirname, '..', 'artifacts', 'local');

export const QUESTION_TITLES = [
  'What roles are you looking for?',
  'Which levels fit you?',
  'Where do you want to work?',
  'What kinds of companies do you want?',
] as const;

/** How many questions the flow asks. */
export const STEP_COUNT = QUESTION_TITLES.length;

/** PLAN.md §6: desktop 1280x800, phone 390x844. */
export const DESKTOP = { width: 1280, height: 800 };
export const PHONE = { width: 390, height: 844 };

export interface Identity {
  sub: string;
  email: string;
}

/** A never-seen identity for `caseId` (fixtures.IDENTITY_PREFIX + run tag). */
export function freshIdentity(caseId: string): Identity {
  const slug = `${caseId}-${RUN_ID}-${randomBytes(4).toString('hex')}`;
  return {
    sub: `${CORPUS.identityPrefix}${slug}`,
    email: `${CORPUS.emailPrefix}${slug.toLowerCase()}@${CORPUS.emailDomain}`,
  };
}

export const PREEXISTING: Identity = { sub: CORPUS.preexisting.sub, email: CORPUS.preexisting.email };

export interface DbState {
  rowCount: number;
  exists: boolean;
  userId?: string;
  onboardingCompletedAt?: string | null;
  savedFilters?: {
    recentTimeWindow: string;
    trendTimeWindow: string;
    category: string[];
    subcategory: string[];
    level: string[];
    locations: string[];
    companyCategory: string[] | null;
  } | null;
}

/** The identity's row in jobscraper_e2e_onboarding, read through identities.py. */
export function dbState(identity: Identity): DbState {
  const out = execFileSync(
    PYTHON,
    ['-m', 'e2e.onboarding.identities', 'state', identity.sub, identity.email],
    { cwd: REPO_ROOT, encoding: 'utf-8' },
  );
  return JSON.parse(out.trim()) as DbState;
}

/** "First sign-in" means NO users row — asserted, never assumed. */
export function expectNoAccountYet(identity: Identity): void {
  const state = dbState(identity);
  expect(state.exists, `a users row already exists for the brand-new identity ${identity.sub}`).toBe(false);
}

/** Wait until the account is stamped; returns the DB state. */
export async function expectStamped(identity: Identity, what: string): Promise<DbState> {
  let last: DbState = dbState(identity);
  await expect
    .poll(
      () => {
        last = dbState(identity);
        return last.onboardingCompletedAt ?? null;
      },
      { message: `${what}: users.onboarding_completed_at should be stamped`, timeout: 15_000 },
    )
    .not.toBeNull();
  return last;
}

export function expectUnstamped(identity: Identity, what: string): DbState {
  const state = dbState(identity);
  expect(state.exists, `${what}: the account should exist`).toBe(true);
  expect(state.onboardingCompletedAt, `${what}: users.onboarding_completed_at should still be NULL`).toBeNull();
  return state;
}

/**
 * A new browser context signed in as `identity` — a new device, or a later
 * session: nothing carries over from any earlier context.
 *
 * NETWORK FENCE: every request that is not to this stack (127.0.0.1) is
 * aborted and recorded, so the section's "$0, no host but its own stack" is a
 * property of the browser, not a hope (the Google sign-in script, fonts, …).
 */
export async function openSignedIn(
  browser: Browser,
  identity: Identity,
  { phone = false }: { phone?: boolean } = {},
): Promise<BrowserContext> {
  const context = await browser.newContext(
    phone
      ? { viewport: PHONE, isMobile: true, hasTouch: true, deviceScaleFactor: 3 }
      : { viewport: DESKTOP },
  );
  await context.route(
    (url) => url.hostname !== '127.0.0.1' && url.hostname !== 'localhost',
    (route) => route.abort('blockedbyclient'),
  );
  await signInContext(context, identity);
  return context;
}

/**
 * Counts this page's `GET /api/users` calls (ONE per load since 2026-11-23:
 * every caller shares `CurrentUserProvider`'s; OB-U13 pins that). PLAN.md §5: "the questions do NOT appear" is asserted only
 * after every one of them has come back — the gate cannot have decided before.
 * Install BEFORE the first navigation.
 */
export function trackUserFetches(page: Page) {
  let started = 0;
  let finished = 0;
  const isUsersGet = (r: Request) => r.method() === 'GET' && new URL(r.url()).pathname === '/api/users';
  page.on('request', (r) => {
    if (isUsersGet(r)) started += 1;
  });
  const done = (r: Request) => {
    if (isUsersGet(r)) finished += 1;
  };
  page.on('requestfinished', done);
  page.on('requestfailed', done);
  return {
    started: () => started,
    reset: () => {
      started = 0;
      finished = 0;
    },
    settled: () => started > 0 && finished >= started,
  };
}
export type UserFetchTracker = ReturnType<typeof trackUserFetches>;

/** The onboarding dialog (aria-labelledby its question). */
export function questions(page: Page): Locator {
  return page.getByRole('dialog');
}

/** The dialog is open on question `step` (0-based). */
export async function expectQuestion(page: Page, step: 0 | 1 | 2 | 3): Promise<Locator> {
  const dialog = questions(page);
  await expect(dialog, `the first-sign-in questions should be open on question ${step + 1}`).toBeVisible();
  await expect(dialog).toHaveAccessibleName(QUESTION_TITLES[step]);
  await expect(dialog.getByRole('heading', { level: 1 })).toHaveText(QUESTION_TITLES[step]);
  await expect(dialog.getByText(`${step + 1}/${STEP_COUNT}`, { exact: true })).toBeVisible();
  return dialog;
}

/**
 * PLAN.md §5, the anti-flake rule for a NEGATIVE assertion. Never "no dialog
 * after a sleep". Wait for the evidence that the gate has DECIDED — every
 * `GET /api/users` back, the user menu rendered, the page's h1 visible — and
 * only then assert there is no dialog, and keep asserting for a settle window
 * so a late open is caught too.
 *
 * Locators here are CSS on purpose: if the dialog DID open, MUI marks the rest
 * of the page aria-hidden, and a role locator for the user menu would time out
 * with a message about the menu instead of the dialog.
 */
export async function expectQuestionsNeverOpen(
  page: Page,
  tracker: UserFetchTracker | null,
  what: string,
  { settleMs = 1_500 }: { settleMs?: number } = {},
): Promise<void> {
  if (tracker) {
    await expect
      .poll(() => tracker.settled(), {
        message: `${what}: every GET /api/users should have come back before judging`,
        timeout: 20_000,
      })
      .toBe(true);
    await expect(page.locator('[aria-label="user menu"]'), `${what}: the user menu`).toBeVisible();
  }
  await expect(page.locator('h1').first(), `${what}: the page's own h1`).toBeVisible();
  const deadline = Date.now() + settleMs;
  do {
    expect(await page.getByRole('dialog').count(), `${what}: the first-sign-in questions opened`).toBe(0);
    await page.waitForTimeout(100);
  } while (Date.now() < deadline);
}

// --- Controls ----------------------------------------------------------------

/** A category row on question 1. Software Engineering's accessible name also
 * carries its specialty count (Chromium computes "Software Engineering , 17
 * specialties" — the visually hidden span adds the space); the anchored end
 * keeps "Growth" from matching the "Growth Engineering" chip. */
export function roleBox(dialog: Locator, label: string): Locator {
  return dialog.getByRole('checkbox', { name: new RegExp(`^${label}( ?, \\d+ specialties)?$`) });
}

/** A chip (specialty, level or place), by its exact label. */
export function chip(dialog: Locator, label: string): Locator {
  return dialog.getByRole('checkbox', { name: label, exact: true });
}

export const button = (dialog: Locator, name: 'Skip' | 'Back' | 'Continue' | 'Show my jobs') =>
  dialog.getByRole('button', { name, exact: true });

/** The answers the headline path picks, as the dialog labels them. */
export const HEADLINE_LABELS = {
  role: 'Software Engineering',
  specialty: 'Backend',
  level: 'Entry',
  place: 'San Francisco, CA',
  companyType: 'Big Tech',
} as const;

/** Drive questions 1-4 with the headline answers, ending on "Show my jobs". */
export async function answerHeadline(page: Page, caseId: string): Promise<void> {
  let dialog = await expectQuestion(page, 0);
  await roleBox(dialog, HEADLINE_LABELS.role).check();
  await chip(dialog, HEADLINE_LABELS.specialty).check();
  await shot(page, caseId, '01-roles');
  await button(dialog, 'Continue').click();

  dialog = await expectQuestion(page, 1);
  await chip(dialog, HEADLINE_LABELS.level).check();
  await shot(page, caseId, '02-levels');
  await button(dialog, 'Continue').click();

  dialog = await expectQuestion(page, 2);
  await chip(dialog, HEADLINE_LABELS.place).check();
  await shot(page, caseId, '03-places');
  await button(dialog, 'Continue').click();

  dialog = await expectQuestion(page, 3);
  await chip(dialog, HEADLINE_LABELS.companyType).check();
  await shot(page, caseId, '04-companies');
}

// --- The Recent list ---------------------------------------------------------

export const RECENT_JOBS = '/jobs';
export const COMPANIES = '/companies';

/** The virtualized list; `data-client-window` is how many rows are loaded. */
export function jobList(page: Page): Locator {
  return page.locator('div[data-client-window]');
}

/**
 * The list holds EXACTLY these fixture rows. The COUNT (rows loaded, not just
 * mounted) catches a filter that let a decoy through even if it is scrolled
 * away; the TITLES catch the right count of the wrong rows.
 */
export async function expectJobs(page: Page, keys: string[], what: string): Promise<void> {
  const expected = titlesFor(keys);
  await expect
    .poll(async () => Number(await jobList(page).getAttribute('data-client-window')), {
      message: `${what}: the list should hold exactly ${expected.length} job(s): ${expected.join(', ')}`,
      timeout: 20_000,
    })
    .toBe(expected.length);
  const titles = (await jobList(page).getByRole('heading', { level: 3 }).allInnerTexts())
    .map((t) => t.trim())
    .sort();
  expect(titles, `${what}: the rendered job titles`).toEqual(expected);
}

/** The Recent page's filter fields, as a reader sees them. */
export function filterField(
  page: Page,
  label: 'Job Category' | 'Level' | 'Company type' | 'Location',
): Locator {
  return page.getByRole('combobox', { name: label });
}

/** The Location field's chips (an Autocomplete renders each pick as a chip). */
export function locationChips(page: Page): Locator {
  return page
    .locator('.MuiAutocomplete-root')
    .filter({ has: page.getByRole('combobox', { name: 'Location' }) })
    .locator('.MuiChip-label');
}

/** The "Saved filters" toast. */
export function savedToast(page: Page): Locator {
  return page.getByTestId('onboarding-saved-toast');
}

// --- Evidence ------------------------------------------------------------------

/** A screenshot under `<run>/screenshots/<case>/` (NOT under ui/, which
 * Playwright wipes on start). */
export async function shot(page: Page, caseId: string, name: string): Promise<void> {
  const dir = path.join(ARTIFACTS_DIR, 'screenshots', caseId);
  fs.mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: path.join(dir, `${name}.png`) });
}

/**
 * The /jobs tab title a reader sees with no questions open — read off the
 * pre-existing (already onboarded) account, so it is an independent oracle for
 * "the tab title is back to the page's own" (OB-U11), never a hard-coded string.
 */
export async function pageOwnTitle(browser: Browser, pathname: string): Promise<string> {
  const context = await openSignedIn(browser, PREEXISTING);
  try {
    const page = await context.newPage();
    const tracker = trackUserFetches(page);
    await page.goto(pathname);
    await expectQuestionsNeverOpen(page, tracker, 'the title oracle (pre-existing account)', { settleMs: 300 });
    return await page.title();
  } finally {
    await context.close();
  }
}
