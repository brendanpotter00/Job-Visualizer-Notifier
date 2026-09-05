// verify-onesecondswe :: the worked proof drive (@drive)
//
// One fully-worked feature (Recent feed, company filter) + two Tier-3 side
// effects (anonymous submit_feedback, signed-in set_enabled_companies). It
// imports `test`/`expect` from the SHARED e2e fixtures — `signedInPage` is a page
// already carrying a JWKS-seam minted token, injected the app's own way. WebMCP
// arranges/acts (via window.__webmcp__.call); the DOM and the DB (helpers/
// db_assert.py) assert.
//
// Grounded selectors (src/frontend/src/components/shared/JobCard/): a job title is
// a role=heading level=3; the company name renders as text (e.g. "Apple"); the
// metric row shows a single label, "Past 24 Hours".
import fs from 'node:fs';
import path from 'node:path';
import { test, expect } from '../../../../e2e/shared/playwright/fixtures';
import type { Page } from '@playwright/test';

declare global {
  interface Window {
    __webmcp__?: {
      list(): Array<{ name: string; inputSchema: unknown; annotations: { readOnlyHint: boolean } }>;
      call(name: string, args?: Record<string, unknown>): Promise<any>;
    };
  }
}

const ARTIFACTS = process.env.E2E_VERIFY_ARTIFACTS ?? path.resolve(__dirname, '..', 'artifacts', 'adhoc');
const FEEDBACK_MARKER = `verify-onesecondswe smoke ${new Date().toISOString()}`;

function writeEvidence(name: string, body: string): void {
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  fs.writeFileSync(path.join(ARTIFACTS, name), body);
}

/** Drive a WebMCP tool through the shim and return its structuredContent. */
async function call<T = any>(page: Page, name: string, args: Record<string, unknown> = {}): Promise<T> {
  await page.waitForFunction(() => typeof window.__webmcp__?.call === 'function', null, {
    timeout: 15_000,
  });
  return page.evaluate(
    ([n, a]) => window.__webmcp__!.call(n as string, a as Record<string, unknown>),
    [name, args] as const,
  );
}

test('[@drive] Recent feed — company filter: Tier-1 meta anchor + Tier-2 DOM reflect', async ({
  page,
}) => {
  await page.goto('/');
  // The feed's own query has to have loaded at least one card before a filter can
  // narrow it (the list filters useGetAllJobsQuery's cached set client-side).
  await expect(page.getByRole('heading', { level: 3 }).first()).toBeVisible({ timeout: 30_000 });

  // Clean slate, then the Tier-1 read whose meta is the quantitative anchor.
  await call(page, 'reset_feed_filters');
  const search = await call<{
    jobs: Array<{ company: string; url: string; title: string }>;
    meta: {
      // DEFERRED on the real server-side search path (Wave-1 B1): null when the
      // exact count is not computed. Demo mode still sends a number.
      filteredTotal: number | null;
      serverReturned: number;
      nextCursor: string | null;
      hasMore: boolean;
    };
  }>(page, 'search_jobs', { company: ['apple'], timeWindow: 'all', limit: 200 });

  // jobscraper_e2e holds thousands of open Apple jobs, so this is deterministic.
  // `serverReturned` is the rows on THIS page (≤ limit), so it is the non-empty
  // anchor; `filteredTotal` is the full filtered count and rides page 1 only,
  // deferred (null) on the server-side path — compare it only when present, and
  // then it bounds serverReturned from ABOVE (thousands ≥ one page of 200).
  expect(search.meta.serverReturned, 'expected Apple open jobs in jobscraper_e2e').toBeGreaterThan(0);
  expect(search.meta.serverReturned).toBeLessThanOrEqual(200);
  if (search.meta.filteredTotal !== null) {
    expect(search.meta.filteredTotal).toBeGreaterThan(0);
    expect(search.meta.filteredTotal).toBeGreaterThanOrEqual(search.meta.serverReturned);
  }
  for (const job of search.jobs) {
    expect(job.company, 'every returned job must be Apple after a company filter').toBe('apple');
  }
  writeEvidence('recent-company-filter.meta.json', JSON.stringify(search.meta, null, 2));

  // Tier-2: arrange the live page. The DOM must reflect it.
  const applied = await call<{ applied: { company: string[] } }>(page, 'apply_feed_filters', {
    company: ['apple'],
  });
  expect(applied.applied.company).toContain('apple');

  // DOM assert — NOT a row-count equality (the list is virtualized / capped, so it
  // never mounts all N rows). Assert the per-card invariant instead: Apple cards
  // are shown, and companies that were visible unfiltered (e.g. SpaceX) are gone.
  // toBeVisible waits, so the bounded keyset auto-deepen (RecentJobsList) can land.
  await expect(page.getByText('Apple', { exact: true }).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('SpaceX', { exact: true })).toHaveCount(0);
  // The metric row is still the proof that the header rendered. "Displayed Jobs"
  // and "Past 3 Hours" were both removed on 2026-09-05; "Past 24 Hours" is the
  // only tile left.
  await expect(page.getByText('Past 24 Hours')).toBeVisible();

  // Evidence: ARIA snapshot of the page's main region + a screenshot.
  const main = page.locator('main, [role="main"]').first();
  const region = (await main.count()) ? main : page.locator('body');
  writeEvidence('recent-company-filter.aria.txt', await region.ariaSnapshot());
  await page.screenshot({ path: path.join(ARTIFACTS, 'recent-company-filter.png'), fullPage: false });
});

test('[@drive] submit_feedback (anonymous) returns submitted:true', async ({ page }) => {
  await page.goto('/');
  const res = await call<{ submitted: boolean }>(page, 'submit_feedback', {
    message: FEEDBACK_MARKER,
  });
  expect(res.submitted).toBe(true);
  // Hand the marker to the DB-assert step (Evidence #4):
  //   .venv/bin/python helpers/db_assert.py --table feedback --contains "<marker>"
  writeEvidence('feedback.marker.txt', FEEDBACK_MARKER);
});

test('[@drive] set_enabled_companies (signed-in) echoes the set', async ({ signedInPage }) => {
  await signedInPage.goto('/');
  const res = await call<{ companyIds: string[]; autoEnroll: boolean }>(
    signedInPage,
    'set_enabled_companies',
    { companyIds: ['apple', 'spacex'], autoEnroll: true },
  );
  expect(res.companyIds).toEqual(expect.arrayContaining(['apple', 'spacex']));
  expect(res.autoEnroll).toBe(true);
  // DB proof (Evidence #4): the primary identity is e2e+add-companies@jvn.test —
  //   .venv/bin/python helpers/db_assert.py --table user_enabled_companies \
  //     --email 'e2e+add-companies@jvn.test'
  writeEvidence('set-enabled-companies.echo.json', JSON.stringify(res, null, 2));
});
