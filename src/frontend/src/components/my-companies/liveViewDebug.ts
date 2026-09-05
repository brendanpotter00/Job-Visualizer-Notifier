/**
 * The live view's flight recorder — one greppable line per state transition, so that
 * "why did the frame disappear?" is answered by a log tail instead of by watching a
 * video of a screen.
 *
 * WHY THIS EXISTS. `LiveView` has five ways to retire a frame and no way to say which
 * one fired. Twice now the panel has been reported fixed and was not, because the
 * evidence available was a person describing what they saw ("it goes in and out
 * extremely fast"). A jsdom test with fake timers cannot see a real cross-origin
 * iframe, a real `postMessage`, or a real poll cadence — which is precisely where both
 * bugs lived. So the component narrates itself, and `e2e/live-view/` reads the
 * narration.
 *
 * IT CANNOT SHIP ON. Two independent gates, and the first is the important one:
 *
 *  - `import.meta.env.DEV` is statically `false` in a production build, so Rollup drops
 *    every call and the strings never reach the bundle. No flag, no header and no
 *    console incantation can turn this on in production, because there is nothing there
 *    to turn on.
 *  - a window switch the page must set BEFORE React mounts. That keeps the dev server
 *    and the 3,200-test unit suite silent by default — both run with `DEV === true` —
 *    and it is what Playwright's `addInitScript` sets, which is the only place that
 *    reliably runs before any page script.
 *
 * THE FIELD THAT MATTERS IS `which=`. Everything else is context; that one answers the
 * question the whole file exists for. Keep its values exact and keep them a closed set —
 * `e2e/live-view/timeline.ts` parses them, and a renamed value is a silently weakened
 * gate rather than a compile error.
 */

/** The switch a harness sets on `window` before the app boots. */
export const LIVE_VIEW_DEBUG_FLAG = '__JVN_LIVE_VIEW_DEBUG__';

/** Prefix every line carries, so a tail is `grep '\[live-view\]'` and nothing else. */
export const LIVE_VIEW_LOG_PREFIX = '[live-view]';

/**
 * Which closer retired a frame. A CLOSED union because the e2e timeline asserts on
 * these exact strings: `server-retraction` is the backend's own null arriving on a
 * poll (the authoritative one), `postMessage` is the hosted frame's undocumented
 * `browserbase-disconnected`, and the other three are this component's own timers.
 */
export type LiveViewCloser =
  | 'postMessage'
  | 'frame-load-timeout'
  | 'lease'
  | 'session-ttl'
  | 'server-retraction';

type Fields = Record<string, string | number | boolean | null>;

interface DebugWindow extends Window {
  [LIVE_VIEW_DEBUG_FLAG]?: unknown;
}

function enabled(): boolean {
  if (!import.meta.env.DEV) return false;
  if (typeof window === 'undefined') return false;
  return (window as DebugWindow)[LIVE_VIEW_DEBUG_FLAG] === true;
}

/**
 * Host only, never the whole URL. A live-view URL carries the session's signed
 * websocket address as a query value, and this line ends up in CI artifacts.
 */
export function liveViewLogUrl(url: string | null): string {
  if (url === null) return 'none';
  try {
    return new URL(url).host;
  } catch {
    return 'unparseable';
  }
}

/**
 * One line: `[live-view] <event> k=v k=v t=<ms since page load>`.
 *
 * `t` is `performance.now()`, and every call site is an effect body, a timer callback
 * or an event handler — never render. Reading a clock during render is impure and
 * lint-blocked here for the same reason it is everywhere else in this feature.
 */
export function liveViewLog(event: string, fields: Fields = {}): void {
  if (!enabled()) return;
  const parts = Object.entries(fields).map(([key, value]) => `${key}=${value}`);
  parts.push(`t=${Math.round(performance.now())}`);
  console.log(`${LIVE_VIEW_LOG_PREFIX} ${event} ${parts.join(' ')}`);
}
