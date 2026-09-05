// THE REAL RUN. One genuine `POST /api/users/companies` against a careers page with no
// ATS behind it, which starts a real Browserbase capture, opens a real hosted session,
// and mounts Browserbase's own iframe into the real page.
//
// It bills one browser-minute. It is opt-in (`e2e/run.sh live-view --live`) and is not
// part of the default gate, which is deterministic and $0. What it buys that the
// deterministic gate cannot: proof that the frame survives a session the PRODUCT
// created, on the product's own timing, against the third-party page whose undocumented
// `postMessage` is the reason this component is complicated.
//
// It asserts the same one thing: continuously on screen from first appearance until the
// session really ends. What "really ends" means here is not a number we chose — it is
// whichever of the server's own retraction or the frame's own disconnect happens, and
// the timeline says which.

import fs from 'node:fs';
import path from 'node:path';
import { test, expect } from '../../shared/playwright/fixtures';
import { instrument, gapsBeforeEnd, everPresent, FRAME_TESTID } from '../timeline';

/**
 * A careers page with no ATS behind it, so the add endpoint reaches `no_ats_detected`
 * and hands it to discovery — which is the only path that opens a browser.
 *
 * Atlassian, because the owner's own stack ran exactly this URL on 2026-09-04 and it
 * discovered cleanly (235 jobs off `/endpoint/careers/listings`). A board that refuses
 * would still exercise the live view, but a run that fails for a board reason reads as
 * a live-view failure, and this suite must never do that.
 */
const BOARD_URL = 'https://www.atlassian.com/company/careers/all-jobs';

/** Discovery is capped at 240s server-side; the capture itself is ~31s. */
const WATCH_MS = 150_000;

test.describe('LV-LIVE a real Browserbase discovery', () => {
  test.setTimeout(WATCH_MS + 120_000);

  test('the hosted frame stays on screen for the whole capture', async ({ signedInPage }) => {
    const recorder = await instrument(signedInPage);
    await signedInPage.goto('/add-companies');

    await expect(signedInPage.getByRole('heading', { name: 'Add Companies' })).toBeVisible();
    await signedInPage.getByLabel('Careers page link').fill(BOARD_URL);
    await signedInPage.getByRole('button', { name: 'Add company' }).click();

    // The frame only exists once a poll has carried `liveViewUrl`, which is a second or
    // two after the capture opens its session.
    await signedInPage
      .getByTestId(FRAME_TESTID)
      .waitFor({ state: 'attached', timeout: 90_000 });
    const appearedAt = recorder.now();

    // Watch until the frame has been gone for a while, or the budget runs out.
    // Watch until the SERVER has retracted (the authoritative end) and the frame has
    // been gone for a while after it. Deliberately not "until the frame disappears" —
    // that is what the bug looks like, so breaking on it would end the run at the moment
    // of the failure and report a short, clean-looking timeline.
    // Shots of the frame itself, every 4s. The timeline says whether the frame was
    // MOUNTED; only a picture says whether it was PAINTING A BROWSER or painting
    // Browserbase's "Debugging connection was closed". Those are opposite verdicts on the
    // same DOM, and the whole question of what to do about the disconnect message turns
    // on which one it is. Cross-origin, so a screenshot is the only way to look.
    const shotDir = path.join(
      process.env.E2E_ARTIFACTS_DIR ?? path.join(__dirname, '..', 'artifacts', 'local'),
      'frame-shots'
    );
    fs.mkdirSync(shotDir, { recursive: true });
    let shots = 0;

    const deadline = Date.now() + WATCH_MS;
    let retractedAt: number | null = null;
    let nextShotAt = 0;
    while (Date.now() < deadline) {
      await signedInPage.waitForTimeout(500);
      if (recorder.now() >= nextShotAt) {
        nextShotAt = recorder.now() + 4_000;
        const frame = signedInPage.getByTestId(FRAME_TESTID);
        if ((await frame.count()) > 0) {
          shots += 1;
          await frame
            .screenshot({
              path: path.join(shotDir, `t${String(recorder.now()).padStart(6, '0')}ms.png`),
            })
            .catch(() => undefined);
        }
      }
      if (
        retractedAt === null &&
        recorder.closers().some((l) => l.fields.which === 'server-retraction')
      ) {
        retractedAt = recorder.now();
      }
      if (retractedAt !== null && recorder.now() - retractedAt > 10_000) break;
    }
    // eslint-disable-next-line no-console
    console.log(`LV-LIVE: ${shots} frame screenshot(s) in ${shotDir}`);

    const samples = await recorder.samples();
    const report = recorder.report(samples);
    // eslint-disable-next-line no-console
    console.log(`\n=== LV-LIVE timeline (frame first seen at ${appearedAt}ms) ===\n${report}\n`);

    expect(everPresent(samples), `the frame never appeared\n${report}`).toBe(true);

    // WHEN THE SESSION REALLY ENDED, and getting this right is the difference between a
    // gate and a formality.
    //
    // `server-retraction` is the only authoritative answer: the backend nulls
    // `live_view_url` in the same write that releases the session. Prefer it always.
    //
    // A `postMessage` is explicitly NOT taken as the end, because that is the whole
    // finding this suite exists for — on a real capture the frame posted one two seconds
    // into a thirty-one second session. Using the first one as "the end" would make every
    // assertion below vacuous on exactly the run that has the bug. Only if the server
    // never retracted (the run was cut short) do we fall back to the LAST closer, which
    // is the sticky one.
    const closers = recorder.closers();
    expect(
      closers.length > 0,
      `nothing ever ended the session — the capture may not have run at all\n${report}`
    ).toBe(true);
    const retraction = closers.find((l) => l.fields.which === 'server-retraction');
    const endedAt = retraction ? retraction.at : closers[closers.length - 1].at;

    // The frame is ALLOWED to close before the server's null, and that is the entire
    // point of the fast path: `browser.close()` kills its socket, the frame says so
    // immediately, and the backend's write is one poll behind. A gap that starts at that
    // last disconnect and runs to the retraction is the mechanism working, not a bug.
    //
    // The window is what stops this excusing the real bug. In the broken build the
    // disconnect fired at t=10s and the server retracted at t=50s — forty seconds apart.
    // A disconnect that is genuinely the end lands within a poll or two of it.
    const lastDisconnect = [...closers].reverse().find((l) => l.fields.which === 'postMessage');
    const closedEarly =
      lastDisconnect !== undefined && endedAt - lastDisconnect.at <= 15_000
        ? lastDisconnect.at
        : endedAt;
    const continuousUntil = Math.min(closedEarly, endedAt) - 500;

    const gaps = gapsBeforeEnd(samples, continuousUntil);
    if (gaps.length > 0) {
      const first = gaps[0];
      const closer = recorder.closerNear(first.from);
      throw new Error(
        `The live view went blank while the real session was still open.\n` +
          `  frame first seen: t=${appearedAt}ms\n` +
          `  session ended:    t=${endedAt}ms\n` +
          `  first gap:        ${first.durationMs}ms from t=${first.from}ms\n` +
          `  CLOSER THAT FIRED: ${closer ? `${closer.fields.which} (sticky=${closer.fields.sticky}) at t=${closer.at}ms` : 'UNKNOWN'}\n\n` +
          report
      );
    }

    // THE ASSERTION THAT CANNOT BE ARGUED WITH, and the reason it is here as well as the
    // gap check above: coverage. However the edges are defined, if the live view is
    // working then the frame was on screen for most of the time there was a browser to
    // watch. In the broken build this was 1.98s out of ~28s — 7%.
    const watchable = endedAt - appearedAt;
    const onScreen = samples.filter((s) => s.present && s.at >= appearedAt && s.at <= endedAt);
    const coverage = watchable > 0 ? (onScreen.length * 50) / watchable : 0;
    // eslint-disable-next-line no-console
    console.log(
      `LV-LIVE: frame on screen for ${Math.round(coverage * 100)}% of the ${watchable}ms ` +
        `there was a session to watch`
    );
    expect(
      watchable,
      `the session was only watchable for ${watchable}ms — too short to be evidence\n${report}`
    ).toBeGreaterThan(8_000);
    expect(
      coverage,
      `the frame was on screen for only ${Math.round(coverage * 100)}% of the session\n${report}`
    ).toBeGreaterThan(0.7);
  });
});
