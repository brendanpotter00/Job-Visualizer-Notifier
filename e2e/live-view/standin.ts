// The two things this section fakes, and NOTHING else: the hosted iframe, and what the
// list endpoint says about a live session. Everything between them — the frontend, RTK
// Query's poll, React's timers, the browser's iframe and its `postMessage` — is real.
//
// WHY FAKE THESE TWO. A real Browserbase session costs money, lasts about 31 seconds,
// and is not reproducible: you cannot ask it to drop its socket at t=1.2s and then keep
// painting. Both bugs in this component so far were about the ORDER of a poll and a
// disconnect, so a harness that cannot place those two in a chosen order cannot test
// for them. These two seams are exactly the ones that make the order choosable, and
// they are the only ones that are not the code under test.

import type { Page, Route } from '@playwright/test';
import type {
  DiscoveryProgress,
  GetUserCompaniesResponse,
  UserCompany,
} from '../../src/frontend/src/features/userCompanies/userCompaniesApi';

/**
 * The stand-in's origin. Deliberately a real https origin on a `.test` name that
 * cannot resolve: `page.route` answers it before DNS, and the frame therefore gets a
 * genuine cross-origin document — which is the only way `event.origin` is a real check
 * rather than a formality. `liveViewOrigin()` derives its allowlist from this URL, so
 * a stand-in on the wrong origin would be ignored exactly as an impostor would.
 */
export const STANDIN_ORIGIN = 'https://live-view.stand-in.test';

export interface StandInOptions {
  /**
   * A SPURIOUS BLIP: post `browserbase-disconnected` this long after the frame's first
   * load, ONCE for the whole session, and then never again however often the frame is
   * remounted.
   *
   * EARLY IS THE WHOLE POINT, and the reason is worth writing down because the comment
   * here used to get it wrong. It cited `artifacts/20260904T150614Z` — the frame posting
   * two seconds into a thirty-one second session — as proof the message is routinely
   * spurious. That run predates the truncated-URL fix (`047db740`): the URL was clipped
   * at 400 chars, so the socket really was dead. Four `--live` runs since post the
   * message exactly once each, ~26s after load, at the genuine end.
   *
   * So this models the case the product must SURVIVE rather than one it must expect: a
   * frame that has not settled yet claiming its socket is gone. The component keeps that
   * disprovable on purpose (`LIVE_VIEW_DISCONNECT_GRACE`), because the message is an
   * undocumented string from someone else's page and must not be able to end a session
   * by itself. Measured with the frame remounted four times over a healthy session (~8s
   * each), it posted NOTHING. So: once, early, and never again.
   */
  blipAfterMs?: number;
  /**
   * A GENUINE END: this long after the frame's first load, the session dies. The frame
   * posts immediately, and from then on posts ~600ms after EVERY load, because a frame
   * mounted onto a dead session cannot connect.
   *
   * The 600ms is measured too: remounting onto a session whose browser had been closed
   * produced the message 626ms after that mount's `load`.
   */
  dieAfterMs?: number;
  /** ms the frame stalls before it finishes loading — for the load watchdog. */
  paintDelayMs?: number;
}

/** The URL to put in the payload. Its query is the frame's script. */
export function standInUrl(options: StandInOptions = {}): string {
  const q = new URLSearchParams();
  if (options.blipAfterMs !== undefined) q.set('blipAfterMs', String(options.blipAfterMs));
  if (options.dieAfterMs !== undefined) q.set('dieAfterMs', String(options.dieAfterMs));
  if (options.paintDelayMs !== undefined) q.set('paintDelayMs', String(options.paintDelayMs));
  return `${STANDIN_ORIGIN}/devtools-fullscreen/inspector.html?${q.toString()}`;
}

/** How long a frame mounted onto a dead session takes to give up. Measured: 626ms. */
const DEAD_RECONNECT_MS = 600;

/**
 * The frame itself. It paints (so `load` fires and the user has "seen" it), it keeps
 * painting (so a still-alive session is visibly still alive), and it posts the one
 * 24-character string Browserbase's real frame posts — on the two schedules that
 * frame was actually measured to use.
 *
 * STATE LIVES IN `sessionStorage`, which is per-origin and survives the iframe being
 * unmounted and remounted inside the same tab. That is the whole reason a blip can be
 * "once per session" rather than "once per mount": the difference between those two is
 * exactly the difference between a fix that works and one that does not, so the
 * stand-in has to be able to express both.
 *
 * `targetOrigin: '*'` because that is what the real one does — the component's origin
 * check is the only thing standing between it and any page on the internet, and a
 * stand-in that used a tight targetOrigin would test a kinder world than the one we
 * are in.
 */
const FRAME_HTML = `<!doctype html>
<html><head><meta charset="utf-8"><title>stand-in live view</title></head>
<body style="margin:0;background:#101418;color:#9fb;font:13px ui-monospace,monospace">
<div id="paint" style="padding:12px">stand-in live view: connecting…</div>
<script>
  var q = new URLSearchParams(location.search);
  var blipAfter = q.get('blipAfterMs');
  var dieAfter = q.get('dieAfterMs');
  var el = document.getElementById('paint');
  var frames = 0;
  setInterval(function () {
    frames += 1;
    el.textContent = 'stand-in live view: painting frame ' + frames;
  }, 250);

  function post() { parent.postMessage('browserbase-disconnected', '*'); }
  function flag(k) { return sessionStorage.getItem(k) === '1'; }
  function set(k) { sessionStorage.setItem(k, '1'); }

  // First mount of this session establishes the session clock; later mounts inherit it.
  var firstLoadAt = Number(sessionStorage.getItem('firstLoadAt') || 0);
  if (!firstLoadAt) {
    firstLoadAt = Date.now();
    sessionStorage.setItem('firstLoadAt', String(firstLoadAt));
  }
  var sinceFirst = Date.now() - firstLoadAt;

  if (flag('dead')) {
    setTimeout(post, ${DEAD_RECONNECT_MS});
  } else {
    if (blipAfter !== null && !flag('blipped')) {
      setTimeout(function () { set('blipped'); post(); }, Math.max(0, Number(blipAfter) - sinceFirst));
    }
    if (dieAfter !== null) {
      setTimeout(function () { set('dead'); post(); }, Math.max(0, Number(dieAfter) - sinceFirst));
    }
  }
</script>
</body></html>`;

/**
 * Answer every request to the stand-in origin. `paintDelayMs` is honoured HERE, on the
 * document response, rather than in page script: the load watchdog is about a frame
 * that never fires `load`, and script that runs has already loaded.
 */
export async function serveStandIn(page: Page): Promise<void> {
  await page.route(`${STANDIN_ORIGIN}/**`, async (route: Route) => {
    const delay = Number(new URL(route.request().url()).searchParams.get('paintDelayMs') ?? 0);
    if (delay > 0) await new Promise((resolve) => setTimeout(resolve, delay));
    await route.fulfill({
      status: 200,
      contentType: 'text/html; charset=utf-8',
      body: FRAME_HTML,
    });
  });
}

// --- the list endpoint ----------------------------------------------------

export const COMPANY_ID = 'u-liveview01';

function progress(liveViewUrl: string | null): DiscoveryProgress {
  return {
    steps: [
      { key: 'open_page', status: 'active', result: null },
      { key: 'find_feed', status: 'pending', result: null },
      { key: 'verify_read', status: 'pending', result: null },
      { key: 'ready', status: 'pending', result: null },
      { key: 'first_scan', status: 'pending', result: null },
    ],
    outcome: 'running',
    liveViewUrl,
    // Stamped NOW on every payload, because `isDiscoveryLive` is what buys the 4s
    // cadence and a frozen timestamp would silently drop the poll to 15s — which is
    // longer than the trust lease, i.e. it would manufacture a failure the product
    // does not have.
    updatedAt: new Date().toISOString(),
    network: { requests: [], recorded: 0, sample: null },
  };
}

function company(liveViewUrl: string | null): UserCompany {
  return {
    id: COMPANY_ID,
    displayName: 'Stand-In Co',
    ats: 'discovered',
    boardToken: 'https://careers.stand-in.test/jobs',
    boardUrl: 'https://careers.stand-in.test/jobs',
    sourceId: `custom:${COMPANY_ID}`,
    healthState: 'discovering',
    openJobCount: 0,
    lastSuccessAt: null,
    trackingStartedAt: null,
    discovery: progress(liveViewUrl),
  };
}

export interface SessionScript {
  /** ms (from `scriptListEndpoint`) at which the first payload carries the URL. */
  urlAtMs: number;
  /** ms at which the server retracts it — the session genuinely ending. */
  retractAtMs: number;
  /** The stand-in URL to serve while the session is "open". */
  liveViewUrl: string;
  /**
   * One slow poll. `afterMs` is when the delay starts applying, `delayMs` how long that
   * single response is held. This is the failing/slow-poll case the trust lease exists
   * for, and the only way to test it is to actually be slow.
   */
  slowPoll?: { afterMs: number; delayMs: number };
}

export interface ScriptHandle {
  /** ms since the script was installed — the clock every assertion is in. */
  now(): number;
  /** How many list polls the page has actually made. */
  polls(): number;
  /**
   * Retract the URL from `delayMs` from now, overriding `retractAtMs`.
   *
   * The real server retracts in the `finally` that follows the capture child's exit —
   * i.e. a beat after the frame's socket dies, not at a wall-clock time chosen in
   * advance. A test that wants to model "the session genuinely ended" has to hang the
   * retraction off the DISCONNECT, which only the test can see.
   */
  retractIn(delayMs: number): void;
}

/**
 * Intercept `GET /api/users/companies` and answer it from the script.
 *
 * Only that exact path and only GET: the signed-in fixture's sweep talks to the REAL
 * backend over `DELETE /api/users/companies/{id}` from python, and the page's other
 * calls (auth, quota) must stay real — the point of running against the e2e stack is
 * that everything except this one seam is the product.
 */
export async function scriptListEndpoint(
  page: Page,
  script: SessionScript
): Promise<ScriptHandle> {
  const t0 = Date.now();
  let pollCount = 0;
  let slowPollUsed = false;
  let retractAt = script.retractAtMs;

  await page.route(
    (url) => url.pathname === '/api/users/companies',
    async (route: Route) => {
      if (route.request().method() !== 'GET') {
        await route.fallback();
        return;
      }
      pollCount += 1;
      const elapsed = Date.now() - t0;
      if (script.slowPoll && !slowPollUsed && elapsed >= script.slowPoll.afterMs) {
        slowPollUsed = true;
        await new Promise((resolve) => setTimeout(resolve, script.slowPoll!.delayMs));
      }
      const at = Date.now() - t0;
      const live = at >= script.urlAtMs && at < retractAt ? script.liveViewUrl : null;
      const body: GetUserCompaniesResponse = {
        companies: [company(live)],
        quota: { used: 1, limit: 20, resetsAt: '2026-10-01T00:00:00Z' },
      };
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    }
  );

  return {
    now: () => Date.now() - t0,
    polls: () => pollCount,
    retractIn: (delayMs: number) => {
      retractAt = Date.now() - t0 + delayMs;
    },
  };
}
