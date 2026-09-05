// verify-onesecondswe :: the live view's URL survives the backend, and the frame is
// ALIVE rather than merely mounted (@live-view)
//
// THE BLIND SPOT THIS CLOSES
// ==========================
// `e2e/live-view` is the gate for this panel and it is a good one — five scripted
// sessions proving the frame is continuously on screen until the session really ends.
// Its README also writes down what it cannot see:
//
//   "the deterministic gate serves its own stand-in at its own URL, so it can prove
//    every closer in the component and still be blind to a URL the backend mangled on
//    the way out."
//
// It was blind to exactly that. `progress.py` bounded EVERY url in the discovery blob
// at 400 characters — right for the network log, where a URL is a label; wrong for
// `live_view_url`, which goes in an `<iframe src>`. Browserbase's
// `debuggerFullscreenUrl` measures 479, essentially all of it one signed `?wss=`
// parameter, so the iframe loaded a truncated websocket address and painted "Debugging
// connection was closed. Reason: WebSocket disconnected" ~700ms after every load. Three
// rounds of unit tests missed it; only `e2e/live-view --live` — one billed Browserbase
// minute — caught it.
//
// PRESENCE IS NOT LIVENESS, and that distinction is why this file has two halves.
// Measured across the regression (one instrument, app source untouched):
//
//   commit                   URL served   clipped   on-screen   what the frame PAINTED
//   b86f5b1f (pre-closers)      400         yes       98.7%     "Debugging connection was closed"
//   e48257fe                    400         yes        4.7%     blank
//   047db740 (the fix)          479         NO        92.1%     the real careers page
//
// A frame nobody unmounts scores 98.7% while being completely dead. So an on-screen
// percentage MUST NOT stand alone — that is the same shape of false green that let this
// bug survive three rounds.
//
// SO THIS SPEC ASSERTS TWO THINGS, and the first is the backbone:
//   1. URL INTEGRITY — the live-view URL delivered to the client is not truncated:
//      byte-identical to what the ledger was handed, and carrying no `…`. Deterministic,
//      free, and false at every commit before the fix.
//   2. LIVENESS — what the iframe actually RENDERED, not whether it was mounted. The
//      stand-in models the vendor's measured behaviour: a frame handed a mangled signed
//      URL cannot connect and paints the disconnect dialog, which is precisely what the
//      real one did. So a clip is observable as a dead frame here too, for $0.
//
// The list endpoint is NOT scripted: the row is arranged through the product's own
// writers (`helpers/seed_live_view.py` -> `add_discovering_placeholder` +
// `ProgressLedger` + `record_discovery_progress`), the real e2e backend answers the real
// poll, and the assertions are on the URL that comes back and the frame that paints.
// A clip anywhere between the ledger and the iframe fails it.
//
// Assertions are `expect.soft` on purpose: when this regresses, every layer it broke at
// (write bound, wire, `<iframe src>`, rendered frame) should appear in ONE failure
// report rather than one per re-run.
//
// WHAT IT DOES NOT COVER, stated rather than implied: the trust lease and the
// `browserbase-disconnected` grace bound. Those are about the ORDER of a poll and a
// disconnect, which needs a scriptable list endpoint — `e2e/live-view` LV-02/LV-03/LV-05
// own them and should keep owning them. This file owns the one thing that gate cannot
// see, and nothing else.
//
// WHO OWNS WHAT, so the two cannot drift into asserting the same thing:
//
//   e2e/live-view  LV-01..LV-05   CONTINUITY — is the frame on screen from the moment it
//                                 appears until the session really ends, and which closer
//                                 fired when it is not. Scripted list endpoint.
//   this file      @live-view     INTEGRITY + LIVENESS — is the URL that reaches the
//                                 iframe byte-identical to what the ledger was handed,
//                                 and is the frame ALIVE. Real list endpoint.
//
// The one thing they genuinely shared was the stand-in frame server, and it now has a
// single home: `serveVendorLikeStandIn` in `e2e/live-view/standin.ts`, imported below
// beside `STANDIN_ORIGIN`. That file owns the seam; the two specs own their own
// assertions. The `toBeVisible()` re-check late in this test is NOT a continuity
// assertion — it is the cheap guard that a GOOD url does not get retired mid-session,
// and LV-01/LV-03 remain the place continuity is actually measured.
//
// WHY IT IS NOT DRIVEN THROUGH `window.__webmcp__`: none of the 14 tools touches the
// Add Companies surface, and `features/add-companies.md` says so — it is a form-driven,
// browser-backed pipeline, not a store/endpoint the shim wraps. Every OTHER convention
// of this skill is kept: the shared `signedInPage` fixture, the shared Playwright base
// via `verify.playwright.config.ts`, the `assertions.connect` DB guard, and evidence
// written into the launch's artifacts dir.
//
// Run (from `$REPO/e2e`, after `helpers/launch.sh`):
//   NODE_PATH="$REPO/e2e/node_modules" npx --no-install playwright test \
//     --config="$REPO/.claude/skills/verify-onesecondswe/helpers/verify.playwright.config.ts" \
//     --grep '@live-view'

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { test, expect } from '../../../../e2e/shared/playwright/fixtures';
import {
  STANDIN_ORIGIN,
  VENDOR_ALIVE_TEXT as ALIVE_TEXT,
  serveVendorLikeStandIn,
} from '../../../../e2e/live-view/standin';

const REPO_ROOT = path.resolve(__dirname, '../../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');
const SEED = path.join(__dirname, 'seed_live_view.py');
const ARTIFACTS =
  process.env.E2E_VERIFY_ARTIFACTS ?? path.resolve(__dirname, '..', 'artifacts', 'adhoc');

const ADD_COMPANIES = '/add-companies';

/**
 * The measured length of Browserbase's `debuggerFullscreenUrl` — the number the old
 * 400-character bound was 79 short of. This pins the FIXTURE, never the product: every
 * assertion below is "identical to what we handed the ledger", so the bound can sit at
 * 2048 (it does) without this file caring.
 */
const BROWSERBASE_URL_CHARS = 479;

/**
 * The last characters of the synthetic signature. It sits past the 400-character mark,
 * so "did the tail survive?" and "was this clipped?" are the same question.
 */
const TAIL_MARKER = 'ENDOFSIGNATURE';

/**
 * A stand-in URL of exactly the measured length, shaped like the real one: everything
 * after `wss=` is one opaque signed blob, so a clip lands in the middle of the parameter
 * the frame's socket needs rather than somewhere harmless.
 *
 * It lives on `e2e/live-view`'s stand-in origin — a `.test` name that cannot resolve,
 * answered by `page.route` before DNS — so this spec opens no Browserbase session and
 * makes no outbound request. The origin is imported from that section rather than
 * copied: this file exists to cover that gate's blind spot, so if its stand-in moves,
 * this must move with it.
 */
function browserbaseShapedUrl(): string {
  const prefix = `${STANDIN_ORIGIN}/devtools-fullscreen/inspector.html?debug=true&wss=`;
  const padding = BROWSERBASE_URL_CHARS - prefix.length;
  if (padding <= 0) {
    throw new Error(`stand-in prefix is already ${prefix.length} chars`);
  }
  return prefix + 'S'.repeat(padding - TAIL_MARKER.length) + TAIL_MARKER;
}

/**
 * THE TEST'S OWN PROOF THAT IT DISCRIMINATES.
 *
 * A test that only ever passes is exactly what let this bug survive three rounds of
 * "fixed". So the failing case is reproducible on demand, by anyone, WITHOUT editing
 * `progress.py` (which the owner's dev stack serves live out of this tree):
 *
 *   LIVE_VIEW_SEED_CLIPPED=1 npx --no-install playwright test … --grep '@live-view'
 *
 * seeds the URL byte-for-byte as the PRE-FIX backend would have stored it — clipped to
 * `_MAX_TEXT_CHARS` (400) with the ellipsis `_safe_url` appends — while every assertion
 * stays as it is. That run MUST fail, at the wire, at the `<iframe src>`, and at the
 * painted frame. If it ever passes, this file has stopped testing anything.
 */
const SEED_CLIPPED = process.env.LIVE_VIEW_SEED_CLIPPED === '1';
/** `_MAX_TEXT_CHARS` in `progress.py` — the bound `live_view_url` used to share. */
const PRE_FIX_CLIP_CHARS = 400;

/** What the pre-fix `_safe_url(value, limit=400)` would have stored for `url`. */
function preFixClip(url: string): string {
  return url.slice(0, PRE_FIX_CLIP_CHARS - 1) + '…';
}

interface Seeded {
  companyId: string;
  userId: string;
  boardUrl: string;
  liveViewUrl: string;
  urlChars: number;
  storedChars: number;
}

/** Arrange the discovering row through the product's own writers. */
function seedDiscoveringRow(liveViewUrl: string): Seeded {
  const stdout = execFileSync(PYTHON, [SEED, '--live-view-url', liveViewUrl], {
    cwd: REPO_ROOT,
    encoding: 'utf-8',
  });
  return JSON.parse(stdout.trim()) as Seeded;
}

function writeEvidence(name: string, body: string): void {
  fs.mkdirSync(ARTIFACTS, { recursive: true });
  fs.writeFileSync(path.join(ARTIFACTS, name), body);
}

test('[@live-view] the live-view URL reaches the iframe whole, and the frame is alive', async ({
  signedInPage,
}) => {
  const rawUrl = browserbaseShapedUrl();
  const expectedWss = new URL(rawUrl).searchParams.get('wss') ?? '';
  // Hard, because it is a check on the FIXTURE rather than on the product: a padded URL
  // of the wrong length would silently stop reproducing the regression.
  expect(rawUrl.length, 'the fixture URL must be the measured Browserbase length').toBe(
    BROWSERBASE_URL_CHARS,
  );

  // The frame is answered before DNS; nothing leaves the machine and no session is
  // opened. This is the ONLY seam — the list endpoint stays real.
  await serveVendorLikeStandIn(signedInPage, expectedWss);

  const seeded = seedDiscoveringRow(SEED_CLIPPED ? preFixClip(rawUrl) : rawUrl);
  // Layer 1: the ledger's own WRITE bound, before a browser is involved.
  expect
    .soft(
      seeded.storedChars,
      `progress.py stored ${seeded.storedChars} of ${seeded.urlChars} characters — ` +
        'the live-view URL was clipped on WRITE (see _MAX_LIVE_VIEW_URL_CHARS)',
    )
    .toBe(seeded.urlChars);

  // Layer 2: what the REAL backend hands the browser. This is the literal question —
  // "is the live-view URL that reaches the client intact?" — so it is read off the
  // response the page received, not re-fetched with a different client.
  const payloads: Array<string | null> = [];
  signedInPage.on('response', (response) => {
    if (new URL(response.url()).pathname !== '/api/users/companies') return;
    if (response.request().method() !== 'GET') return;
    void response
      .json()
      .then(
        (body: {
          companies?: Array<{ id: string; discovery?: { liveViewUrl?: string | null } }>;
        }) => {
          const row = body.companies?.find((c) => c.id === seeded.companyId);
          if (row) payloads.push(row.discovery?.liveViewUrl ?? null);
        },
      )
      .catch(() => {
        /* a response we could not parse is not evidence either way */
      });
  });

  await signedInPage.goto(ADD_COMPANIES);

  // Layer 3: the iframe React actually mounted. `liveViewSrc()` appends `&navbar=false`
  // and changes nothing else, so the mounted src is the stored URL plus that suffix —
  // an equality, not a prefix match, so a clip cannot hide inside it.
  const frame = signedInPage.getByTestId('discovery-live-view');
  await expect(frame, 'the live view never mounted for the seeded discovering row').toBeVisible({
    timeout: 30_000,
  });
  const src = (await frame.getAttribute('src')) ?? '';

  expect
    .soft(src, 'the iframe src lost characters between progress.py and React')
    .toBe(`${rawUrl}&navbar=false`);
  expect
    .soft(src.includes('…'), `the iframe src carries a truncation ellipsis:\n  ${src}`)
    .toBe(false);
  expect
    .soft(
      src.includes(TAIL_MARKER),
      'the TAIL of the signed ?wss= parameter did not survive — this is the exact shape ' +
        "of the 400-char clip that killed the frame's socket ~700ms after load",
    )
    .toBe(true);

  expect
    .soft(payloads.length, 'no GET /api/users/companies response was observed')
    .toBeGreaterThan(0);
  for (const carried of payloads) {
    expect.soft(carried, 'a poll carried a clipped liveViewUrl').toBe(rawUrl);
  }

  // Layer 4 — LIVENESS. What the frame PAINTED, which is the question a presence
  // percentage cannot answer: at b86f5b1f the frame was on screen 98.7% of the session
  // and dead the whole time.
  const painted = await signedInPage
    .frameLocator('[data-testid="discovery-live-view"]')
    .locator('#paint')
    .textContent({ timeout: 15_000 });
  expect
    .soft(
      painted,
      'the live view is MOUNTED BUT DEAD — it is painting the vendor disconnect dialog, ' +
        'which is what a mangled live-view URL looks like on screen',
    )
    .toBe(ALIVE_TEXT);

  // Still alive several real polls later. This is the cheap guard that a good URL does
  // not get retired by something else while the backend keeps publishing it — NOT the
  // lease test, which `e2e/live-view` LV-03 owns with a scripted slow poll.
  await signedInPage.waitForTimeout(13_000);
  await expect(
    frame,
    'the frame went away while the backend was still publishing the URL',
  ).toBeVisible();
  const stillPainted = await signedInPage
    .frameLocator('[data-testid="discovery-live-view"]')
    .locator('#paint')
    .textContent({ timeout: 15_000 });
  expect.soft(stillPainted, 'the frame died partway through the session').toBe(ALIVE_TEXT);

  writeEvidence(
    'live-view-url.meta.json',
    JSON.stringify(
      {
        companyId: seeded.companyId,
        seededChars: seeded.urlChars,
        storedChars: seeded.storedChars,
        iframeSrcChars: src.length,
        srcHasEllipsis: src.includes('…'),
        pollsObserved: payloads.length,
        allPollsIntact: payloads.every((p) => p === rawUrl),
        framePainted: painted,
        framePaintedLate: stillPainted,
      },
      null,
      2,
    ),
  );
  const section = signedInPage.getByTestId('discovery-live-view-section');
  writeEvidence('live-view-url.aria.txt', await section.ariaSnapshot());
  await signedInPage.screenshot({ path: path.join(ARTIFACTS, 'live-view-url.png') });
});
