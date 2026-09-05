// verify-onesecondswe :: the typed company name reaches the real endpoint VERBATIM,
// and the answer that comes back is the one the page renders (@name-search)
//
// THE BLIND SPOT THIS CLOSES
// ==========================
// `e2e/company-name-search` is the gate for this feature and it is a good one — 22 cases
// judged against the real `POST /api/companies/search-by-name` over HTTP. Its README also
// writes down the rule that makes it trustworthy:
//
//   "This harness only ever speaks HTTP to the real endpoint; it imports no service
//    module and never may."
//
// That rule is what makes it honest, and it is also exactly what it cannot see. Speaking
// HTTP itself means it composes the request BODY itself. It can never observe what the
// BROWSER sends — and the browser is the only client a user has.
//
// That gap is not hypothetical, and the suite says so in its own case file: casing is an
// input, nothing normalizes it (`company_name_search.py:597`, `models.py:1299`), and the
// two spellings do not return the same results. Measured against Browserbase 2026-09-04,
// twice each:
//
//   `Atlassian careers` -> atlassian.com/company/careers/all-jobs at RANK 2   (2/2)
//   `atlassian careers` -> that URL ABSENT from all 25 results                (2/2)
//
// Every case in the suite was capitalized and nobody types that way, so it reported 4/4
// on a query no user ever makes while the owner failed 3/3 by hand. The suite's fix was
// to add lowercase cases — the right fix for the suite. But NOTHING anywhere asserts that
// the string a person types is the string that leaves the browser. A normalization added
// to the form tomorrow (`.trim().toLowerCase()`, a "helpful" title-case) would silently
// re-open the exact bug, and every case in `cases.toml` would keep passing, because
// `intent_test.py` would still be sending its own hand-composed body.
//
// SO THIS SPEC OWNS ONE THING: the typed name arrives at the endpoint byte-identical.
// It is the layer above the gate, not a second copy of it.
//
// WHAT IT DELIBERATELY DOES NOT DO: judge answers. `judge()` in `intent_test.py` is the
// only judge — truth provenance, the job-list shape rule in both directions, the vacuous
// rule and `known_limitation` all live there and are re-run for $0 by
// `helpers/name_search.sh` via `intent_test.py --replay`. Re-implementing any of that in
// TypeScript is how assertions drift and quietly weaken, which is the failure mode this
// whole suite exists to prevent. This file asserts the REQUEST, and that the recorded
// answer reaches the screen. Nothing else.
//
// $0 AND SIDE-EFFECT FREE, BY CONSTRUCTION
// ========================================
// The endpoint is answered from the committed recording
// (`e2e/company-name-search/recorded/`), so no Browserbase Search call is made and no
// money is spent. The two cases are picked so the page cannot WRITE either:
// `MyCompaniesPage.tsx:273` returns early on `alreadyPublic`, before the two auto-add
// branches at `:278` (one candidate, one auto-addable) and `:327` (no candidates + a
// careers URL). Fulfilling a board answer or a plain careers answer would fire
// `POST /api/users/companies` and put a real owned company in `jobscraper_e2e`.
//
//   databricks  alreadyPublic, 0 candidates            -> the early return. No write.
//   facebook    0 auto-addable, careersUrl null        -> layout B, offers nothing. No write.
//
// Rather than trust that reading, the spec ASSERTS it: `POST /api/users/companies` is
// routed and must never be called. That guard is what keeps this drive read-only.
//
// HONEST ABOUT ITS OWN EVIDENCE: the Atlassian split above is measured in `cases.toml`,
// not reproduced here — reproducing it costs a paid search. What this spec proves is the
// mechanism that split depends on: the browser does not touch the string. `Databricks`
// and `Facebook` are typed with a capital because that is the shape a normalization would
// destroy; a suite that only ever typed lowercase could not tell the difference.
//
// WHY IT IS NOT DRIVEN THROUGH `window.__webmcp__`: none of the 14 tools touches the Add
// Companies surface — `features/add-companies.md` says so, and `live_view.spec.ts` hit the
// same wall. The name box is a form on a flag-gated route, not a store or endpoint the
// shim wraps. This is a real limit of the tool surface, reported rather than papered over.
// Every OTHER convention of this skill is kept: the shared `signedInPage` fixture, the
// shared Playwright base via `verify.playwright.config.ts`, and evidence written into the
// launch's artifacts dir.
//
// IT PROVES IT CAN FAIL. A test that only ever passes is what let the casing bug reach
// the owner:
//
//   NAME_SEARCH_SEED_NORMALIZED=1 npx --no-install playwright test … --grep '@name-search'
//
// lower-cases the name on its way into the box — standing in for a form that "helpfully"
// normalizes — while every assertion stays as it is. That run MUST fail on the verbatim
// check. If it ever passes, this file has stopped testing anything.
//
// Run (from `$REPO/e2e`, after `helpers/launch.sh`):
//   NODE_PATH="$REPO/e2e/node_modules" npx --no-install playwright test \
//     --config="$REPO/.claude/skills/verify-onesecondswe/helpers/verify.playwright.config.ts" \
//     --grep '@name-search'
// or, with the $0 judge run alongside it:
//   bash "$REPO/.claude/skills/verify-onesecondswe/helpers/name_search.sh"

import fs from 'node:fs';
import path from 'node:path';
import type { Route } from '@playwright/test';
import { test, expect } from '../../../../e2e/shared/playwright/fixtures';

const REPO_ROOT = path.resolve(__dirname, '../../../..');
const ARTIFACTS =
  process.env.E2E_VERIFY_ARTIFACTS ?? path.resolve(__dirname, '..', 'artifacts', 'adhoc');

const ADD_COMPANIES = '/add-companies';
const SEARCH_PATH = '/api/companies/search-by-name';
/** The add endpoint. Routed only so the spec can prove it is NEVER called. */
const ADD_PATH = '/api/users/companies';

/**
 * The recorded run the answers come from. A real, paid, GREEN run (39 searches, $0.273,
 * 21/21 + citadel) whose response bodies were stored by `intent_test.py --json`. Replaying
 * it is what makes this drive free; see `e2e/company-name-search/recorded/README.md`.
 */
const RECORDING = path.join(
  REPO_ROOT,
  'e2e',
  'company-name-search',
  'recorded',
  '20260905T021303Z.json',
);

/**
 * THE TEST'S OWN PROOF THAT IT DISCRIMINATES — see the header. Lower-cases the typed name
 * to stand in for a form that normalizes, without editing any product source.
 */
const SEED_NORMALIZED = process.env.NAME_SEARCH_SEED_NORMALIZED === '1';

interface RecordedCase {
  key: string;
  input: string;
  attempts: Array<{ body: Record<string, unknown> | null }>;
}

/** Pull one case's typed input and its recorded response body out of the recording. */
function recorded(key: string): { input: string; body: Record<string, unknown> } {
  const record = JSON.parse(fs.readFileSync(RECORDING, 'utf-8')) as { cases: RecordedCase[] };
  const found = record.cases.find((c) => c.key === key);
  if (!found) {
    throw new Error(`no case '${key}' in ${RECORDING} — was the recording re-made?`);
  }
  const body = found.attempts.find((a) => a.body !== null)?.body;
  if (!body) {
    throw new Error(`case '${key}' in ${RECORDING} has no recorded body to replay`);
  }
  return { input: found.input, body };
}

function writeEvidence(name: string, body: string): void {
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  fs.writeFileSync(path.join(ARTIFACTS, name), body);
}

/**
 * Drive the real name box and capture what the browser actually sent.
 *
 * The search endpoint is fulfilled from the recording (so nothing is billed) and the ADD
 * endpoint is fulfilled with a hard failure it should never reach — a call landing there
 * is a side effect this drive must not have, and aborting it makes that loud rather than
 * letting a real row appear in `jobscraper_e2e`.
 */
async function search(
  page: import('@playwright/test').Page,
  typed: string,
  body: Record<string, unknown>,
): Promise<{ sent: string[]; addCalls: string[] }> {
  const sent: string[] = [];
  const addCalls: string[] = [];

  await page.route(`**${SEARCH_PATH}`, async (route: Route) => {
    // The REQUEST is the subject of this spec, so it is read off the wire before the
    // response is faked — post-data, exactly as the browser serialized it.
    const payload = route.request().postDataJSON() as { name?: string };
    sent.push(payload?.name ?? '');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });

  await page.route(`**${ADD_PATH}`, async (route: Route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    addCalls.push(route.request().url());
    await route.abort('failed');
  });

  await page.goto(ADD_COMPANIES);
  const box = page.getByLabel(/company name or careers page link/i);
  await expect(box, 'the name box never rendered — are both flags on?').toBeVisible({
    timeout: 30_000,
  });
  await box.fill(SEED_NORMALIZED ? typed.toLowerCase() : typed);
  await box.press('Enter');

  await expect
    .poll(() => sent.length, {
      message: `no ${SEARCH_PATH} request was ever made for "${typed}"`,
      timeout: 30_000,
    })
    .toBeGreaterThan(0);

  return { sent, addCalls };
}

test('[@name-search] the typed name reaches search-by-name byte-identical, and its answer reaches the screen', async ({
  signedInPage,
}) => {
  // ---- CASE 1: databricks — the "we already track this" channel -------------------
  const databricks = recorded('databricks');
  const first = await search(signedInPage, databricks.input, databricks.body);

  // THE BACKBONE ASSERTION. Byte-identical, not case-insensitive, not trimmed: the whole
  // point is that no layer between the keyboard and the endpoint is allowed to touch it.
  for (const name of first.sent) {
    expect
      .soft(
        name,
        'the browser did not send the typed name verbatim. Casing is an INPUT to ' +
          'Browserbase Search — `Atlassian careers` ranks the right answer 2nd and ' +
          '`atlassian careers` does not return it at all — so a normalization here ' +
          'changes the answers while every case in cases.toml keeps passing.',
      )
      .toBe(databricks.input);
  }

  // The recorded answer has to reach the screen, or "the request was right" proves
  // nothing about what the user is told. `databricks` is an `alreadyPublic` / `name`
  // match, which renders the guessed layout with its correction link.
  const notice = signedInPage.getByTestId('already-public');
  await expect(
    notice,
    'the already-public answer never rendered for Databricks',
  ).toBeVisible({ timeout: 15_000 });
  await expect(notice).toContainText(/already track/i);
  await expect(notice).toContainText(/Databricks/);

  // ---- CASE 2: facebook — the "nothing offered" channel ---------------------------
  // A different answer SHAPE, and the one that matters most for this product: the
  // endpoint found no board and no careers page it would vouch for. `cases.toml` records
  // this as `nothing = true` — a positive expectation that silence is right — because
  // the alternative the picker used to reach was facebook.it/careers, a different
  // company's site. The page must offer nothing rather than a brochure.
  const facebook = recorded('facebook');
  const second = await search(signedInPage, facebook.input, facebook.body);
  for (const name of second.sent) {
    expect.soft(name, 'the browser did not send "Facebook" verbatim').toBe(facebook.input);
  }

  const answer = signedInPage.getByTestId('careers-page-answer');
  await expect(answer, 'the no-board answer never rendered for Facebook').toBeVisible({
    timeout: 15_000,
  });
  // THE ACCESSIBLE NAME IS THE LOAD-BEARING SIGNAL, not the heading. `CareersPageAnswer`
  // sets `aria-label` from `url === null` alone, while the heading additionally depends on
  // how many unconfirmed boards are folded underneath ("No job board found for X" with
  // none, "No board we can confirm belongs to X" with some — Facebook has two). So the
  // aria-label is the one that says "nothing was offered", which is the assertion here.
  await expect
    .soft(answer, 'the answer region is not in its no-URL state')
    .toHaveAttribute('aria-label', 'No job board found');
  await expect(answer).toContainText(/No board we can confirm belongs to/i);
  await expect(answer).toContainText(/Facebook/);
  // The offer itself must be ABSENT — `careers-page-url` only renders when the server
  // vouched for a URL. Its presence here would mean a brochure was offered, which is the
  // `nothing = true` expectation cases.toml records for this name.
  await expect
    .soft(
      answer.getByTestId('careers-page-url'),
      'a careers URL was offered for a name the endpoint answered nothing for',
    )
    .toHaveCount(0);

  // ---- THE READ-ONLY GUARD --------------------------------------------------------
  // Both auto-add branches (`MyCompaniesPage.tsx:278` and `:327`) fire
  // POST /api/users/companies, which writes an owned company. Neither case above should
  // reach them; this is the assertion rather than the assumption.
  const addCalls = [...first.addCalls, ...second.addCalls];
  expect(
    addCalls,
    `this drive is meant to be read-only, but it issued POST ${ADD_PATH} — a company ` +
      'row was written into jobscraper_e2e and cleanup.sh will have to sweep it',
  ).toEqual([]);

  writeEvidence(
    'name-search.meta.json',
    JSON.stringify(
      {
        recording: path.relative(REPO_ROOT, RECORDING),
        seededNormalized: SEED_NORMALIZED,
        cases: [
          { key: 'databricks', typed: databricks.input, sent: first.sent, channel: 'alreadyPublic' },
          { key: 'facebook', typed: facebook.input, sent: second.sent, channel: 'nothing-offered' },
        ],
        verbatim:
          first.sent.every((n) => n === databricks.input) &&
          second.sent.every((n) => n === facebook.input),
        addRequestsIssued: addCalls.length,
        searchesBilled: 0,
      },
      null,
      2,
    ),
  );
  writeEvidence('name-search.aria.txt', await answer.ariaSnapshot());
  await signedInPage.screenshot({ path: path.join(ARTIFACTS, 'name-search.png') });
});
