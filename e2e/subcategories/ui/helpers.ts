// UI-tier helpers. Section-owned (not `shared/`) because every locator below
// names a control on the Recent Jobs page.
//
// THE RECENT PAGE HAS NO `data-testid`s. Not one, anywhere in the filters, the
// list or the job card — checked before writing this, not assumed. So every
// handle here is an ARIA role/name or one of the two attribute hooks the list
// deliberately publishes (`data-client-window`, `data-index`). Where a locator
// is structural rather than contractual it says so at the call site.
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { test as base, expect } from '@playwright/test';
import type { BrowserContext, Locator, Page } from '@playwright/test';
import { signInContext } from '../../shared/auth/storage_state';

const REPO_ROOT = path.resolve(__dirname, '../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const SEED_PY = path.join(REPO_ROOT, 'e2e', 'subcategories', 'seed.py');

export const RECENT_JOBS_PATH = '/';
/** The `FacetTreeMultiSelect`'s label — `RecentJobsFilters.tsx`. */
export const CATEGORY_CONTROL_LABEL = 'Job Category';
export const LEVEL_CONTROL_LABEL = 'Level';

interface Fixtures {
  signedInPage: Page;
  signedInContext: BrowserContext;
}

/**
 * Re-seed through the section's own seeder.
 *
 * SIGNED IN, ALWAYS. A signed-out Recent page caps the list at
 * `SIGNED_OUT_JOB_LIMIT: 12` behind an overlay and turns paging off — which
 * would silently truncate an eleven-row corpus the moment it grew, and would
 * make every "exact set" assertion below a coincidence. This fixture is
 * deliberately NOT `shared/playwright/fixtures.ts`'s: that one sweeps owned
 * companies through `reset_user.py` before and after every test, which is an
 * add-companies concern and would be pure cost here.
 */
export function reseed({ reveal = true }: { reveal?: boolean } = {}): void {
  execFileSync(PYTHON, [SEED_PY, ...(reveal ? [] : ['--reveal-off'])], {
    cwd: REPO_ROOT,
    encoding: 'utf-8',
  });
}

export const test = base.extend<Fixtures>({
  signedInContext: async ({ browser }, use) => {
    // A brand-new context every test: `getPublicSettings` is cached for 60s
    // and the reveal flag is read once per mount, so a reused context would
    // carry SC-05's flipped flag into the next spec.
    const context = await browser.newContext({
      // TALL ON PURPOSE. The list is window-virtualized (`useWindowVirtualizer`,
      // ESTIMATED_CARD_HEIGHT 200, OVERSCAN 6), so only a screenful of rows is
      // ever mounted. At 720px high, "this title is absent" would be true of a
      // row that merely had not scrolled into view — the assertion would pass
      // for the wrong reason. 2400px mounts the whole eleven-row corpus, which
      // is what lets the specs below compare exact TITLE SETS instead of
      // probing for individual rows.
      viewport: { width: 1280, height: 2400 },
    });
    await signInContext(context, 'primary');
    await use(context);
    await context.close();
  },
  signedInPage: async ({ signedInContext }, use) => {
    const page = await signedInContext.newPage();
    await use(page);
  },
});

export { expect };

/** The virtualized list container. `role="list"` alone is ambiguous — the
 * navigation drawer renders six MUI `<List>`s — so this keys on the one
 * attribute the list publishes for exactly this purpose. */
export function jobList(page: Page): Locator {
  return page.locator('div[data-client-window]');
}

/**
 * Navigate and wait until the first page of results is really on screen.
 *
 * Waits on the RESPONSE rather than on a spinner: filter edits are debounced
 * 300 ms (`useRecentJobsSearch.ts`), so a DOM-only wait races the request that
 * has not been sent yet and reads the PREVIOUS filter's rows as this one's.
 */
export async function gotoRecentJobs(page: Page): Promise<void> {
  const firstSearch = page.waitForResponse(
    (r) => r.url().includes('/api/jobs/search') && r.status() === 200,
  );
  await page.goto(RECENT_JOBS_PATH);
  await expect(page.getByRole('heading', { level: 1, name: 'Recent Job Postings' })).toBeVisible();
  await firstSearch;
  await expect(jobList(page)).toBeVisible();
}

/** How many rows the client has loaded — `data-client-window` on the list. */
export async function loadedCount(page: Page): Promise<number> {
  const raw = await jobList(page).getAttribute('data-client-window');
  return Number(raw);
}

/**
 * Every rendered job title, sorted.
 *
 * `h3` inside a row is the job title (`CompanyJobHeader.tsx` renders
 * `<Typography variant="h6" component="h3">`); there is no testid for it. With
 * the tall viewport above, every row of an eleven-row corpus is mounted, so
 * this really is the whole result set and not just the visible slice —
 * `expectResults` cross-checks it against `data-client-window` so a future
 * corpus that outgrows the viewport fails loudly instead of quietly asserting
 * a prefix.
 */
export async function renderedTitles(page: Page): Promise<string[]> {
  const titles = await jobList(page).getByRole('heading', { level: 3 }).allInnerTexts();
  return titles.map((t) => t.trim()).sort();
}

/**
 * The one assertion every result case makes: the list holds EXACTLY these
 * jobs.
 *
 * Both halves are load-bearing. The COUNT catches a filter that returned too
 * much or too little; the TITLE SET catches a filter that returned the right
 * number of the wrong rows. And comparing the two to each other is what keeps
 * `renderedTitles` honest if the corpus ever outgrows the viewport.
 */
export async function expectResults(page: Page, expectedTitles: string[]): Promise<void> {
  await expect
    .poll(() => loadedCount(page), {
      message:
        `the list should hold exactly ${expectedTitles.length} jobs ` +
        `(${expectedTitles.join(', ')})`,
    })
    .toBe(expectedTitles.length);

  const titles = await renderedTitles(page);
  expect(
    titles,
    'every loaded row must be MOUNTED for this comparison to mean anything — if the ' +
      'counts agree but the titles do not, the corpus has outgrown the 2400px viewport ' +
      'in helpers.ts and the set comparison is silently checking a prefix',
  ).toEqual([...expectedTitles].sort());
}

/** Wait for the search the next filter edit will trigger, debounce included. */
export async function withSearchResponse(page: Page, action: () => Promise<void>): Promise<void> {
  const response = page.waitForResponse(
    (r) => r.url().includes('/api/jobs/search') && r.status() === 200,
    { timeout: 20_000 },
  );
  await action();
  await response;
}

// --- The category/subcategory tree ---------------------------------------
//
// `FacetTreeMultiSelect` is a MUI `Select multiple`: the closed field is a
// `combobox`, the open menu a `listbox`, each row an `option`. It has no
// testids. Three mechanics below are not obvious and are why these helpers
// exist rather than inline clicks:
//
//  1. A PARENT option's accessible name is polluted by the chevron's
//     `aria-label` — the computed name is "Software Engineering Expand
//     Software Engineering", so an exact-name match misses it. Hence the
//     anchored regex.
//  2. COLLAPSED CHILDREN ARE NOT IN THE DOM. The parent must be expanded
//     before a child can be clicked, and the chevron — not the row — is what
//     expands it (the row click toggles the checkbox instead).
//  3. The menu stays open after a click (it is a multi-select), so it has to
//     be dismissed with Escape before the list underneath is interactable.

export function categoryTrigger(page: Page): Locator {
  return page.getByRole('combobox', { name: CATEGORY_CONTROL_LABEL });
}

export function openMenu(page: Page): Locator {
  return page.getByRole('listbox');
}

export async function openCategoryMenu(page: Page): Promise<Locator> {
  await categoryTrigger(page).click();
  const menu = openMenu(page);
  await expect(menu).toBeVisible();
  return menu;
}

/** A parent row, matched by an ANCHORED regex — see mechanic (1) above. */
export function parentOption(menu: Locator, label: string): Locator {
  return menu.getByRole('option', { name: new RegExp(`^${label}`) });
}

/** The chevron inside a parent row. Only present when the parent HAS children,
 * which is exactly what makes its absence the reveal flag's UI signature. */
export function expandToggle(menu: Locator, label: string): Locator {
  return parentOption(menu, label).getByRole('button');
}

export async function expandParent(menu: Locator, label: string): Promise<void> {
  const toggle = expandToggle(menu, label);
  if ((await toggle.getAttribute('aria-expanded')) !== 'true') {
    await toggle.click();
  }
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
}

export async function dismissMenu(page: Page): Promise<void> {
  await page.keyboard.press('Escape');
  await expect(openMenu(page)).toBeHidden();
}

/**
 * Tick one subcategory child and wait for the search it triggers.
 *
 * Ticking a child AUTO-CHECKS its parent (`FacetTreeMultiSelect.tsx`), so the
 * request this waits on carries BOTH `category=software_engineering` and the
 * child slug. That is the request shape the product actually makes, which is
 * why the API tier has a case for the redundant pair.
 */
export async function selectSubcategory(
  page: Page,
  parentLabel: string,
  childLabel: string,
): Promise<void> {
  const menu = await openCategoryMenu(page);
  await expandParent(menu, parentLabel);
  await withSearchResponse(page, async () => {
    await menu.getByRole('option', { name: childLabel, exact: true }).click();
  });
  await dismissMenu(page);
}

/** Tick a parent (category) row and wait for the search it triggers. */
export async function selectCategory(page: Page, parentLabel: string): Promise<void> {
  const menu = await openCategoryMenu(page);
  await withSearchResponse(page, async () => {
    await parentOption(menu, parentLabel).click();
  });
  await dismissMenu(page);
}

/** Tick a level in the flat `FacetMultiSelect` beside the tree. */
export async function selectLevel(page: Page, levelLabel: string): Promise<void> {
  await page.getByRole('combobox', { name: LEVEL_CONTROL_LABEL }).click();
  const menu = openMenu(page);
  await expect(menu).toBeVisible();
  await withSearchResponse(page, async () => {
    await menu.getByRole('option', { name: levelLabel, exact: true }).click();
  });
  await dismissMenu(page);
}
