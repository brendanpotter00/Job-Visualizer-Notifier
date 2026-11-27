// CC-U1..CC-U5 — the Company type filter as a reader uses it.
//
// Every case asserts the EXACT rows on screen (nine seeded rows; CC-DECOY is
// a SWE job at a company in no company type) and waits for the search request
// that carries `company_category`, because the failure that matters is silent:
// a filter dropped on the way comes back as an unfiltered list.
import { expect, test } from '@playwright/test';
import type { Route } from '@playwright/test';
import { CORPUS, labelOf, union } from './corpus';
import {
  RECENT_JOBS,
  companyTypeField,
  companyTypesInUrl,
  expectJobs,
  openCompanyType,
  openContext,
  reseed,
  searchWith,
  shot,
} from './helpers';

const BIG_TECH = labelOf('big_tech');
const FINTECH = labelOf('fintech');
const BUNDLED_LABELS = CORPUS.categories.map((c) => c.label);

test.beforeEach(() => {
  reseed();
});

test.describe('CC-U1 dropdown', () => {
  test('CC-U1 checking two company types narrows the list and the URL', async ({ browser }) => {
    const context = await openContext(browser);
    const page = await context.newPage();
    await page.goto(RECENT_JOBS);
    await expect(page.getByRole('heading', { level: 1, name: 'Recent Job Postings' })).toBeVisible();
    await expect(companyTypeField(page)).toHaveText('All');
    await expectJobs(page, CORPUS.expected.all, 'CC-U1 before any company type');

    const listbox = await openCompanyType(page);
    await expect(listbox.getByRole('option')).toHaveText(BUNDLED_LABELS);
    const narrowed = searchWith(page, ['big_tech', 'fintech']);
    await listbox.getByRole('option', { name: BIG_TECH, exact: true }).click();
    await listbox.getByRole('option', { name: FINTECH, exact: true }).click();
    for (const label of [BIG_TECH, FINTECH]) {
      await expect(
        listbox.getByRole('option', { name: label, exact: true }).getByRole('checkbox'),
        `${label} is a ticked checkbox`,
      ).toBeChecked();
    }
    await expect(
      listbox.getByRole('option', { name: labelOf('ai_labs'), exact: true }).getByRole('checkbox'),
    ).not.toBeChecked();
    await shot(page, 'CC-U1', '01-dropdown-open');
    await page.keyboard.press('Escape');
    await narrowed;

    await expect(companyTypeField(page)).toHaveText(`${BIG_TECH}, ${FINTECH}`);
    await expectJobs(page, union(CORPUS.expected.bigTech, CORPUS.expected.fintech), 'CC-U1 Big Tech or Fintech');
    await expect.poll(() => companyTypesInUrl(page), { message: 'the URL carries both types' }).toEqual([
      'big_tech',
      'fintech',
    ]);
    await shot(page, 'CC-U1', '02-filtered');
    await context.close();

    // The same filter on a 375px phone: the control is compacted like its
    // siblings and the list still holds exactly the two types' rows.
    const phone = await openContext(browser, { phone: true });
    const phonePage = await phone.newPage();
    await phonePage.goto(`${RECENT_JOBS}?company_type=big_tech&company_type=fintech`);
    await expect(companyTypeField(phonePage)).toHaveText(`${BIG_TECH}, ${FINTECH}`);
    const box = await companyTypeField(phonePage).boundingBox();
    expect(box, 'the Company type field on a phone').toBeTruthy();
    if (box) expect(box.x + box.width, 'the field fits a 375px screen').toBeLessThanOrEqual(375);
    const scrollWidth = await phonePage.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollWidth, 'no horizontal page scroll at 375px').toBeLessThanOrEqual(375);
    await shot(phonePage, 'CC-U1', '03-phone-375');
    await phone.close();
  });
});

test.describe('CC-U2 landing card', () => {
  test('CC-U2 a landing card opens Recent Job Postings filtered to its type, Back then another card too', async ({
    browser,
  }) => {
    // Signed out: the landing page is for visitors (a signed-in reader is sent
    // straight to /jobs).
    const context = await openContext(browser, { anonymous: true });
    const page = await context.newPage();
    await page.goto('/');
    const bigTechCard = page.getByRole('link', { name: BIG_TECH, exact: true });
    await bigTechCard.scrollIntoViewIfNeeded();
    await expect(bigTechCard).toHaveAttribute('href', '/jobs?company_type=big_tech');
    await shot(page, 'CC-U2', '01-landing-cards');

    const bigTechSearch = searchWith(page, ['big_tech']);
    await bigTechCard.click();
    await expect(page).toHaveURL(/\/jobs\?company_type=big_tech$/);
    await bigTechSearch;
    await expect(companyTypeField(page)).toHaveText(BIG_TECH);
    await expectJobs(page, CORPUS.expected.bigTech, 'CC-U2 after the Big Tech card', { anonymous: true });
    await shot(page, 'CC-U2', '02-big-tech');

    // Back to the landing page, then a different card. The app reads the URL
    // once per load, so this only works because the card sets the filter.
    await page.goBack();
    const fintechCard = page.getByRole('link', { name: FINTECH, exact: true });
    await fintechCard.scrollIntoViewIfNeeded();
    const fintechSearch = searchWith(page, ['fintech']);
    await fintechCard.click();
    await expect(page).toHaveURL(/\/jobs\?company_type=fintech$/);
    await fintechSearch;
    await expect(companyTypeField(page)).toHaveText(FINTECH);
    await expectJobs(page, CORPUS.expected.fintech, 'CC-U2 after Back and the Fintech card', {
      anonymous: true,
    });
    expect(companyTypesInUrl(page), 'only the second card’s type').toEqual(['fintech']);
    await shot(page, 'CC-U2', '03-fintech-after-back');
    await context.close();
  });
});

test.describe('CC-U3 saved default', () => {
  test('CC-U3 a default saved on Saved Filters applies when Recent Job Postings opens', async ({ browser }) => {
    const context = await openContext(browser);
    const page = await context.newPage();
    await page.goto('/saved-filters');
    await expect(page.getByText('Default company types', { exact: true })).toBeVisible();

    const field = page.getByRole('combobox', { name: 'Company type' });
    await expect(field).toHaveText('All');
    await field.click();
    await page.getByRole('listbox').getByRole('option', { name: BIG_TECH, exact: true }).click();
    await page.keyboard.press('Escape');

    const save = page.getByRole('button', { name: 'Save company types' });
    await expect(save).toBeEnabled();
    const put = page.waitForResponse(
      (r) => new URL(r.url()).pathname === '/api/users/saved-filters' && r.request().method() === 'PUT',
    );
    await save.click();
    const response = await put;
    expect(response.status(), 'the PUT is accepted').toBe(200);
    expect(response.request().postDataJSON().companyCategory, 'the PUT carries the type').toEqual(['big_tech']);
    expect((await response.json()).companyCategory).toEqual(['big_tech']);
    await shot(page, 'CC-U3', '01-saved');

    // A new device: nothing in memory, only the server's saved filters.
    await context.close();
    const later = await openContext(browser);
    const laterPage = await later.newPage();
    const applied = searchWith(laterPage, ['big_tech']);
    await laterPage.goto(RECENT_JOBS);
    await applied;
    await expect(companyTypeField(laterPage)).toHaveText(BIG_TECH);
    await expectJobs(laterPage, CORPUS.expected.bigTech, 'CC-U3 with the saved default');
    await shot(laterPage, 'CC-U3', '02-applied');
    await later.close();
  });
});

test.describe('CC-U4 reset', () => {
  test('CC-U4 Reset Filters clears the company type and the URL', async ({ browser }) => {
    const context = await openContext(browser);
    const page = await context.newPage();
    const filtered = searchWith(page, ['fintech']);
    await page.goto(`${RECENT_JOBS}?company_type=fintech`);
    await filtered;
    await expectJobs(page, CORPUS.expected.fintech, 'CC-U4 from the link');

    const cleared = searchWith(page, []);
    await page.getByRole('button', { name: /reset filters/i }).click();
    await cleared;
    await expect(companyTypeField(page)).toHaveText('All');
    await expect.poll(() => companyTypesInUrl(page), { message: 'company_type left the URL' }).toEqual([]);
    await expectJobs(page, CORPUS.expected.all, 'CC-U4 after Reset');
    await context.close();
  });
});

test.describe('CC-U5 older facets', () => {
  test('CC-U5 facets without companyCategories still offer the bundled types, and they filter', async ({
    browser,
  }) => {
    const context = await openContext(browser);
    const page = await context.newPage();
    let stripped = 0;
    await page.route(
      (url) => url.pathname === '/api/jobs/facets',
      async (route: Route) => {
        const response = await route.fetch();
        const body = (await response.json()) as Record<string, unknown>;
        expect(Object.prototype.hasOwnProperty.call(body, 'companyCategories'), 'the real backend sends it').toBe(
          true,
        );
        delete body.companyCategories;
        stripped += 1;
        await route.fulfill({ response, json: body });
      },
    );
    await page.goto(RECENT_JOBS);
    await expect(page.getByRole('heading', { level: 1, name: 'Recent Job Postings' })).toBeVisible();
    await expect.poll(() => stripped, { message: 'facets went through the older-backend shim' }).toBeGreaterThan(0);

    const listbox = await openCompanyType(page);
    await expect(listbox.getByRole('option')).toHaveText(BUNDLED_LABELS);
    const narrowed = searchWith(page, ['fintech']);
    await listbox.getByRole('option', { name: FINTECH, exact: true }).click();
    await page.keyboard.press('Escape');
    await narrowed;
    await expectJobs(page, CORPUS.expected.fintech, 'CC-U5 Fintech from the bundled list');
    await context.close();
  });
});
