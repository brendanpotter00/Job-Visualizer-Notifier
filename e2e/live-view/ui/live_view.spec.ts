// THE GATE. Four sessions, one question each, and the same assertion behind all of
// them: **the frame is continuously on screen from the moment it first appears until
// the server says the session is over.** A gap is a failure, and the failure message
// names the closer that caused it and the millisecond it fired.
//
// This exists because the live view has now been declared fixed twice and was not.
// Both times the reasoning was sound and the evidence was a person describing a
// screen. A unit test could not have caught either one: they were about a real
// cross-origin iframe, a real `postMessage`, and the real gap between two fulfilled
// polls — three things jsdom does not have.
//
// $0. No Browserbase session is opened; see `standin.ts` for what is faked and why.

import { test, expect } from '../../shared/playwright/fixtures';
import {
  instrument,
  gapsBeforeEnd,
  everPresent,
  absentFrom,
  presentRunsAfter,
  waitForLine,
  type Recorder,
  type Sample,
} from '../timeline';
import { serveStandIn, standInUrl, scriptListEndpoint, type SessionScript } from '../standin';

const ADD_COMPANIES = '/add-companies';

/**
 * The shape of a real run, compressed only where compression cannot change the answer.
 *
 * Measured against the owner's stack: the session is created, the URL is published
 * before the capture child even spawns, and the browser dies ~31s later when
 * `_capture_main.py` calls `browser.close()`. The URL therefore reaches the first poll
 * a second or two in, and the frame should be watchable for the rest of it.
 */
const URL_AT_MS = 2_000;
const RETRACT_AT_MS = 26_000;
/** How long after the retraction we keep watching, to prove the frame really went. */
const TAIL_MS = 10_000;

interface Verdict {
  recorder: Recorder;
  samples: Sample[];
}

async function runSession(
  page: import('@playwright/test').Page,
  script: SessionScript,
  totalMs: number
): Promise<Verdict> {
  const recorder = await instrument(page);
  await serveStandIn(page);
  await scriptListEndpoint(page, script);
  await page.goto(ADD_COMPANIES);
  await page.waitForTimeout(totalMs);
  const samples = await recorder.samples();
  return { recorder, samples };
}

/**
 * The one assertion. Everything else in this file is scenario setup.
 *
 * `until` is the moment the SERVER retracted the URL. Before it, a browser really was
 * open and there was really something to watch, so an absent frame is the bug — no
 * matter which closer took it away or how briefly.
 */
function assertContinuous(v: Verdict, until: number, tolerateMs = 0): void {
  const report = v.recorder.report(v.samples);
  expect(everPresent(v.samples), `the frame never appeared at all\n${report}`).toBe(true);

  const gaps = gapsBeforeEnd(v.samples, until).filter((g) => g.durationMs > tolerateMs);
  if (gaps.length > 0) {
    const first = gaps[0];
    const closer = v.recorder.closerNear(first.from);
    const which = closer ? `${closer.fields.which} (sticky=${closer.fields.sticky})` : 'UNKNOWN';
    throw new Error(
      `The live view went blank while the session was still open.\n` +
        `  first gap: ${first.durationMs}ms from t=${first.from}ms` +
        `${first.to === null ? ' (never came back)' : ` to t=${first.to}ms`}\n` +
        `  gaps total: ${gaps.length}\n` +
        `  CLOSER THAT FIRED: ${which}` +
        `${closer ? ` at t=${closer.at}ms` : ''}\n\n${report}`
    );
  }
}

test.describe('LV-01 a healthy session', () => {
  test('the frame is on screen for the whole session, then goes when the server says so', async ({
    signedInPage,
  }) => {
    const v = await runSession(
      signedInPage,
      {
        urlAtMs: URL_AT_MS,
        retractAtMs: RETRACT_AT_MS,
        liveViewUrl: standInUrl(),
      },
      RETRACT_AT_MS + TAIL_MS
    );
    assertContinuous(v, RETRACT_AT_MS);
    // ...and it must really go. A frame that outlives its session paints Browserbase's
    // "Debugging connection was closed" into our layout, which is the failure the
    // closers exist to prevent.
    expect(
      absentFrom(v.samples, RETRACT_AT_MS + 8_000),
      `the frame was still mounted 8s after the server retracted the URL\n${v.recorder.report(v.samples)}`
    ).toBe(true);
  });
});

test.describe('LV-02 the hosted frame posts a transient disconnect', () => {
  test('a socket blip does not end a session that is still running', async ({ signedInPage }) => {
    // The frame says `browserbase-disconnected` 1.2s after it loads and then carries
    // on painting — an early reconnect, a target swap, a renderer change. The server
    // keeps carrying the URL, which is the evidence that the browser is still there.
    const v = await runSession(
      signedInPage,
      {
        urlAtMs: URL_AT_MS,
        retractAtMs: RETRACT_AT_MS,
        liveViewUrl: standInUrl({ blipAfterMs: 1_200 }),
      },
      RETRACT_AT_MS + TAIL_MS
    );
    // The tolerance is ONE POLL, because that is exactly what recovery costs: the frame
    // comes back on the next payload that still carries the URL, and the cadence is
    // `DISCOVERY_POLL_INTERVAL_MS` (4s). Anything longer is the closer being sticky,
    // which is the bug — against HEAD this gap measured 21.9s and never closed.
    assertContinuous(v, RETRACT_AT_MS, 5_500);
  });
});

test.describe('LV-03 one slow poll', () => {
  test('a poll slower than the trust lease costs a blink, not the session', async ({
    signedInPage,
  }) => {
    // 13.5s with no fulfilled payload is longer than LIVE_VIEW_TRUST_MS (12s), so the
    // lease genuinely expires — that is correct and this test does not fight it. What
    // it pins is the half that was a bug: expiry is SOFT, so the payload that finally
    // lands puts the frame back.
    const v = await runSession(
      signedInPage,
      {
        urlAtMs: URL_AT_MS,
        retractAtMs: RETRACT_AT_MS,
        liveViewUrl: standInUrl(),
        slowPoll: { afterMs: 6_000, delayMs: 13_500 },
      },
      RETRACT_AT_MS + TAIL_MS
    );
    const report = v.recorder.report(v.samples);
    expect(everPresent(v.samples), `the frame never appeared\n${report}`).toBe(true);
    // It must be back — and back for good — well before the session ends.
    const late = v.samples.filter((s) => s.at >= 22_000 && s.at <= RETRACT_AT_MS);
    expect(
      late.length > 0 && late.every((s) => s.present),
      `the frame did not recover after the slow poll landed\n${report}`
    ).toBe(true);
    // And the blink must be bounded by the poll, not open-ended.
    const gaps = gapsBeforeEnd(v.samples, RETRACT_AT_MS);
    for (const gap of gaps) {
      expect(gap.durationMs, `a ${gap.durationMs}ms blank at t=${gap.from}ms\n${report}`).toBeLessThan(
        6_000
      );
    }
  });
});

/**
 * The two ways a session really ends, and they differ only in how late the server's own
 * null is. Both hang the retraction off the OBSERVED disconnect rather than a clock,
 * because that is how the backend does it: `on_live_view_closed` fires in the `finally`
 * that runs once the capture child has exited, i.e. a beat after `browser.close()` killed
 * the frame's socket.
 */
async function endingSession(
  page: import('@playwright/test').Page,
  serverLagMs: number
): Promise<{ v: Verdict; disconnectAt: number }> {
  const recorder = await instrument(page);
  await serveStandIn(page);
  const handle = await scriptListEndpoint(page, {
    urlAtMs: URL_AT_MS,
    // Far away: the retraction that matters is the one `retractIn` schedules below.
    retractAtMs: 10 * 60_000,
    liveViewUrl: standInUrl({ dieAfterMs: 18_000 }),
  });
  await page.goto(ADD_COMPANIES);
  const line = await waitForLine(
    recorder,
    (l) => l.event === 'closer-fired' && l.fields.which === 'postMessage',
    60_000
  );
  handle.retractIn(serverLagMs);
  await page.waitForTimeout(serverLagMs + 14_000);
  return { v: { recorder, samples: await recorder.samples() }, disconnectAt: line.at };
}

test.describe('LV-04 the session genuinely ends, and the server says so promptly', () => {
  test('the frame goes at the disconnect and does not come back', async ({ signedInPage }) => {
    const { v, disconnectAt } = await endingSession(signedInPage, 800);
    const report = v.recorder.report(v.samples);
    expect(everPresent(v.samples), `the frame never appeared\n${report}`).toBe(true);
    assertContinuous(v, disconnectAt - 500);
    expect(
      absentFrom(v.samples, disconnectAt + 1_500),
      `the frame outlived a genuine disconnect — the dead-iframe case the closers exist ` +
        `to prevent\n${report}`
    ).toBe(true);
  });
});

test.describe('LV-05 the session ends and the server is a poll behind', () => {
  test('at most one short flicker, then gone for good', async ({ signedInPage }) => {
    // THE PRICE OF A SOFT CLOSER, written down rather than left to be discovered.
    //
    // The frame's disconnect is not authoritative, so a payload that still carries the
    // URL can disprove it — and for one poll after a genuine end, the server's payload
    // does still carry it (its null is structurally late; see LIVE_VIEW_TRUST_MS). So
    // the frame may come back once. `LIVE_VIEW_DISCONNECT_GRACE` is what stops that
    // becoming a flap once per poll for the whole 12s lease.
    //
    // What it must never do is SIT there. Browserbase paints "Debugging connection was
    // closed" into a frame whose socket is gone, and a long re-appearance is that.
    const { v, disconnectAt } = await endingSession(signedInPage, 6_000);
    const report = v.recorder.report(v.samples);
    expect(everPresent(v.samples), `the frame never appeared\n${report}`).toBe(true);
    assertContinuous(v, disconnectAt - 500);

    const back = presentRunsAfter(v.samples, disconnectAt + 300);
    expect(
      back.length,
      `the frame came back ${back.length} times after a genuine disconnect — a soft ` +
        `closer must be soft ONCE, not once per poll\n${report}`
    ).toBeLessThanOrEqual(1);
    for (const run of back) {
      expect(
        run.durationMs,
        `the frame sat on a dead session for ${run.durationMs}ms from t=${run.from}ms\n${report}`
      ).toBeLessThan(4_000);
    }
    expect(
      absentFrom(v.samples, disconnectAt + 12_000),
      `the frame never settled after the session ended\n${report}`
    ).toBe(true);
  });
});
