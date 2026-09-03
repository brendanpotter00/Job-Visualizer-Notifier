import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import ButtonBase from '@mui/material/ButtonBase';
import CircularProgress from '@mui/material/CircularProgress';
import Collapse from '@mui/material/Collapse';
import Link from '@mui/material/Link';
import Paper from '@mui/material/Paper';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import { ROUTES } from '../../config/routes';
import { DiscoveryNetworkLog } from './DiscoveryNetworkLog';
import type {
  DiscoveryOutcomeState,
  DiscoveryStep,
  UserCompany,
} from '../../features/userCompanies/userCompaniesApi';
import {
  DISCOVERY_POLL_INTERVAL_MS,
  describeDiscoveryOutcome,
  describeDiscoveryStep,
  describePartialScope,
  failedDiscoveryStep,
  resolveDiscoveryOutcome,
  shouldExpandDiscovery,
  watchableLiveViewUrl,
} from './companyHealth';

/**
 * How a rung DRAWS, which is the wire status plus one state the wire has no word for.
 *
 * `partial` is "this rung did its job, and its job was not all of the board" — a ✓ that
 * is true about the work and false about the coverage. It is a rendering fact, not a
 * step status: the backend settles `first_scan` as plain `done` (the harvest ran, it
 * stored what it could) and the shortfall is a property of the whole RUN. Keeping it out
 * of `DiscoveryStepStatus` keeps that union the backend's contract.
 */
type RenderedStatus = DiscoveryStep['status'] | 'partial' | 'waiting';

/**
 * Status glyph per step. Text, not icons, so the state survives a screenshot.
 *
 * `◐` for partial, and the shape is the whole message: a half-filled circle beside four
 * ✓s reads as "this one got some of the way" without a legend, and — unlike a ✕ — makes
 * no claim that anything failed. Nothing here did.
 *
 * `waiting` borrows `pending`'s empty circle because that is what it is: a rung we have
 * not got past yet, which will be tried again tonight without anyone doing anything. Its
 * caption is the difference — "not yet, and here's why" rather than a silent ○.
 */
const STEP_MARK: Record<RenderedStatus, string> = {
  pending: '○',
  active: '',
  done: '✓',
  partial: '◐',
  waiting: '○',
  failed: '✕',
};

/**
 * `partial` stays in the SUCCESS colour, same as `done`. The board is being tracked and
 * there is nothing to fix — Amazon's API hard-refuses `offset + limit > 10000` — so the
 * shortfall is carried by the glyph's shape and the sentence under it, never by an alarm
 * colour. Same decision as the chip on the row above (see `describeCompanyHealth`).
 *
 * `waiting` is grey for the same reason in the other direction: a first harvest that
 * failed on a TRACKED board is not an error the reader owns. See `renderedStatus`.
 */
const STEP_COLOR: Record<RenderedStatus, string> = {
  pending: 'text.disabled',
  active: 'text.primary',
  done: 'success.main',
  partial: 'success.main',
  waiting: 'text.disabled',
  failed: 'error.main',
};

/**
 * Colour for the ONE line a rung is allowed under it — and the whole point is that only
 * a genuine ✕ gets `error.main`.
 *
 * The rule this encodes: alarm colour is for a state the reader can do something about.
 * A refusal qualifies (the pasted URL was probably the wrong page, and `NextActions`
 * says so). A partial board and a first scan that will retry tonight do not, and
 * dressing them in red or amber is telling someone to act when there is no act.
 */
const STEP_DETAIL_COLOR: Record<RenderedStatus, string> = {
  pending: 'text.secondary',
  active: 'text.secondary',
  done: 'text.secondary',
  partial: 'text.secondary',
  waiting: 'text.secondary',
  failed: 'error.main',
};

/**
 * A read-only, iframe-embeddable view of the capture session, appended so the hosted
 * page renders without its own chrome. Only ever applied to an https URL the backend
 * already vetted.
 */
function liveViewSrc(url: string): string {
  return url.includes('navbar=') ? url : `${url}${url.includes('?') ? '&' : '?'}navbar=false`;
}

/**
 * The ONE thing the hosted frame ever says to us, and the only signal in this component
 * that arrives at the instant of the disconnect rather than a poll later.
 *
 * A bare 24-character string, not an object, and it carries NO REASON — three different
 * paths in the frame send identical bytes (`detached`, `targetCrashed`, and the raw
 * socket's own `onclose`), so it says "my socket is gone" and nothing else. Verified
 * against the live bundle, all 48 chunks: there is no other `browserbase-*` message and
 * no other `postMessage` to a parent anywhere in it, so there is nothing here we could
 * mistake it for. It is emitted before their disconnect dialog is constructed, in the
 * same synchronous call — which is why unmounting on it BEATS THE PAINT rather than
 * merely shortening it. Nothing suppresses that dialog; only not being there does.
 *
 * IT IS A FAST PATH AND NOTHING MORE, and the reason is not that it might fail to fire:
 * the socket's own `onclose` needs nothing from the server, so even a SIGKILLed worker
 * trips it. The reason is that it is UNVERSIONED, UNNAMESPACED, SENT WITH
 * `targetOrigin: "*"`, and absent from every Browserbase SDK's typed surface — an
 * undocumented string from someone else's page is not something a UI should be correct
 * BECAUSE of. So every other closer in this file stays exactly as load-bearing as it was;
 * this one only makes the common case close in milliseconds instead of at the next poll.
 * If it silently stops arriving, the lease still ends the frame and the only symptom is
 * the old few-second window coming back.
 */
const LIVE_VIEW_DISCONNECT_MESSAGE = 'browserbase-disconnected';

/**
 * The origin a live-view frame is allowed to speak from — DERIVED from the URL we
 * actually mounted rather than hard-coded to `https://www.browserbase.com`.
 *
 * Hard-coding it would be a second place that has to be right about a host we do not
 * own. Derived, the guard is the strictly correct statement — "only the frame we put
 * there may retire it" — and it follows Browserbase to a new host for free.
 *
 * Null on a URL that will not parse, which disables the fast path rather than widening
 * it. Note that the iframe's `sandbox` MUST keep `allow-same-origin` for this to work at
 * all: without it the frame gets an opaque origin and `event.origin` arrives as the
 * literal string `"null"`, which no allowlist should ever match.
 */
function liveViewOrigin(url: string): string | null {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

/** How long a live-view frame may show nothing before we take its space back. */
const FRAME_LOAD_TIMEOUT_MS = 10_000;

/**
 * HOW LONG A `liveViewUrl` STAYS BELIEVABLE — the lease, and the point of this file.
 *
 * `watchableLiveViewUrl` reports what the last payload said, and the payload is
 * structurally behind the socket: the browser dies inside the capture child
 * (`_capture_main.py`'s `await browser.close()` is its last act), the parent only
 * regains control once that child has exited, and only then writes `live_view_url:
 * null`. Browserbase's DevTools frame has already painted "Debugging connection was
 * closed. Reason: WebSocket disconnected" by then. NO POLL CAN WIN THAT RACE — the
 * disconnect is observable in the iframe strictly before it is observable in our data —
 * so the retraction is at best one poll late, and the interesting question is what
 * happens when it is late WITHOUT BOUND. Three ways it is:
 *
 *  - the poll is FAILING. RTK Query deliberately keeps serving the last good payload
 *    (that is the "We couldn't refresh just now" banner, working as designed), and that
 *    payload still carries the URL. Nothing ever retracts it.
 *  - the row has aged out of the fast cadence (`isDiscoveryLive` in `MyCompaniesList`),
 *    so the next chance to hear the null is 15s away, not 4s.
 *  - the worker was SIGKILLed mid-capture, so the `finally` that retracts never ran and
 *    the row carries a live-looking URL until something reconciles it.
 *
 * So the URL is treated as a CLAIM WITH AN EXPIRY rather than a standing fact: it is
 * good for one poll interval plus a round trip, and every fresh payload renews it. Miss
 * that and we stop asserting there is a browser open, because we no longer have anything
 * recent enough to assert it WITH. This does not shorten the healthy-path gap (nothing
 * client-side can — see above); it removes every case where that gap is unbounded, which
 * is the one a user actually sits and stares at.
 *
 * Derived from `DISCOVERY_POLL_INTERVAL_MS` rather than written as a number, so a
 * cadence change cannot silently turn this into a flicker (window < cadence) or a no-op
 * (window >> cadence). The 2s is the round-trip allowance: the list endpoint counts jobs
 * per row, and a poll that lands slow is not a poll that failed.
 */
const LIVE_VIEW_TRUST_MS = DISCOVERY_POLL_INTERVAL_MS + 2_000;

/**
 * The hosted session's own hard ceiling, mirrored from the backend that sets it:
 * `api/services/capture/network_capture.py`'s `_BROWSERBASE_SESSION_TTL_S = 300`, handed
 * to Browserbase as the session's `timeout`. Past it Browserbase kills the session
 * whatever we do, so a frame still mounted then is watching something that cannot exist.
 *
 * A BACKSTOP, not the mechanism: measured from when this client first saw the URL, which
 * is strictly after the session opened, so it always fires late — and it is dwarfed by
 * the capture subprocess's own 120s cap (`_SUBPROCESS_TIMEOUT_S`), which means on any
 * run that is merely slow the lease above has already closed the frame minutes earlier.
 * It exists for the one case the lease cannot see: polls that keep SUCCEEDING while
 * serving a URL nobody will ever retract (the SIGKILLed-worker row). Being conservative
 * is the right failure here — a backstop that fires early would delete live sessions.
 */
const LIVE_VIEW_SESSION_TTL_MS = 300_000;

/**
 * How long "Live view ended" holds before the section closes itself.
 *
 * The panel vanishing mid-setup is its own small jolt — 375px of frame disappearing from
 * under a checklist the user is reading — so the close is two beats rather than one: the
 * frame's box slides shut (~300ms of MUI `Collapse`) leaving one line that says what
 * happened, and then that line goes too. Long enough to read six words, short enough
 * that nobody is waiting on it.
 */
const LIVE_VIEW_ENDED_HOLD_MS = 1_400;

/**
 * The one thing worth animating on the way out here, and it is deliberately the SAME
 * motion as `DiscoveryNetworkLog`'s `ROW_ANIMATION` — 260ms, a 3px rise, a fade. These
 * two panels sit one above the other during a run and must read as one system rather
 * than two components that each invented their own easing. Reduced motion gets the text
 * with no movement, which is all it ever needed to say.
 */
const ENDED_NOTE_ANIMATION = {
  '@keyframes discoveryLiveViewEnded': {
    from: { opacity: 0, transform: 'translateY(-3px)' },
    to: { opacity: 1, transform: 'none' },
  },
  animation: 'discoveryLiveViewEnded 260ms ease-out',
  '@media (prefers-reduced-motion: reduce)': { animation: 'none' },
} as const;

/**
 * What the live-view section is doing right now.
 *
 * `ending` is the state this component grew for: the session is over, the iframe is
 * already GONE, and the space it held is being handed back on purpose instead of being
 * deleted between two frames.
 */
type LiveViewPhase = 'live' | 'ending' | 'gone';

/**
 * The optional "watch it happen" panel, and — more importantly — the thing that takes
 * itself away again.
 *
 * `url` is `watchableLiveViewUrl`, which is non-null only while the last payload said a
 * browser was open — the backend clears `live_view_url` in the same write that releases
 * the session, so that much is a published fact rather than something inferred from step
 * state. (It was inferred once, from `open_page` being `active`, and a screenshot killed
 * it: that step was still bold and spinning while the frame under it already read
 * "WebSocket disconnected". The socket dies with the browser, before the step ticks.)
 *
 * WHAT THAT FACT CANNOT DO IS ARRIVE IN TIME, and that is the whole reason this
 * component is more than one boolean. The browser dies inside the capture child; the
 * parent writes the null only after that child has exited; a poll then has to carry it.
 * The frame has been painting Browserbase's "Debugging connection was closed" since
 * before the first of those. So the URL is treated as a CLAIM WITH AN EXPIRY, and four
 * independent closers can retire it — whichever is first:
 *
 * - the FRAME says its socket is gone (`LIVE_VIEW_DISCONNECT_MESSAGE`) — the only one
 *   that beats the paint, and the only one that is someone else's undocumented string;
 * - the SERVER retracts it (correct, and the only one that is authoritative);
 * - the LEASE runs out because no fresh payload has confirmed it — `LIVE_VIEW_TRUST_MS`,
 *   and the one that matters, because it is the only closer that survives the poll
 *   itself failing (which is exactly the state the "We couldn't refresh just now" banner
 *   describes, and exactly when a dead frame used to sit there indefinitely);
 * - the SESSION CEILING passes — `LIVE_VIEW_SESSION_TTL_MS`, for the row nobody will
 *   ever retract because the worker that would have was killed.
 *
 * ...plus the LOAD WATCHDOG, which is about a frame that never showed anything at all.
 * Every one of these is recorded as the URL it refers to rather than as a boolean, so no
 * verdict can outlive its own session and suppress the next one.
 *
 * The two gates then differ ON PURPOSE:
 *
 * - The IFRAME is gated directly, so it unmounts in the very same render the session is
 *   retired. Not hidden, not zero-height, not `display: none` — GONE. While it is
 *   mounted it is Browserbase's page, free to paint whatever it likes into our layout,
 *   and what it paints over a released session is "WebSocket disconnected" in their
 *   voice. There is no styling that answers that; only unmounting does.
 * - The SECTION is gated through a `Collapse`, so ~375px of frame does not vanish from
 *   under a checklist the user is mid-read. `unmountOnExit` is what makes the collapsed
 *   state truly nothing rather than a 0px box: react-transition-group returns `null`
 *   once the exit settles, so the common case — our own Chromium, which has no hosted
 *   view at all — renders not one node and reserves not one pixel.
 *
 * The sized wrapper stays mounted through the exit while the frame inside it does not.
 * That is deliberate and it is what makes the two gates cooperate: `Collapse` measures
 * the wrapper to know what height to animate down FROM, so dropping the frame without
 * it would collapse 375px→36px instantly and then animate the leftover — a jump, then
 * a slide. Empty, it holds the shape for ~300ms and closes.
 *
 * And mid-run it says goodbye rather than just going: `ending` swaps the toggle for one
 * line, lets the frame's box slide shut under it, and then closes that too. A panel that
 * disappears while the checklist above it is still ticking reads as something breaking;
 * the same panel that says "Live view ended — still setting up" and then folds reads as
 * us finishing with it.
 */
function LiveView({
  url,
  running,
  receivedAt,
}: {
  url: string | null;
  /**
   * Is the RUN still going? Only the phrasing of the goodbye depends on it: a live view
   * that ends while the checklist is still ticking needs to say the setup carries on
   * without it, and a live view that ends BECAUSE the run ended does not — the checklist
   * right above has just said how the whole thing turned out, and a second line under it
   * saying the video stopped is noise on top of the answer.
   */
  running: boolean;
  /**
   * When the payload carrying `url` landed — RTK Query's `fulfilledTimeStamp`, threaded
   * down from `MyCompaniesList` (the same value the freshness line and the poll cadence
   * already use, and for the same reason: no component may read the clock during
   * render). This is the ONLY thing that renews the live view's lease. `0` means no
   * payload has ever been fulfilled, which is the sentinel `MyCompaniesList` already
   * passes; the lease is not armed for it, and the load watchdog and session ceiling
   * still are.
   */
  receivedAt: number;
}) {
  const [open, setOpen] = useState(true);
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  // WHY THESE ARE URLs AND NOT BOOLEANS: every one of them is a verdict ABOUT A SESSION,
  // and a boolean verdict outlives its session — the next capture would mount into a
  // component that had already decided the frame was dead. Recording which URL the
  // verdict was about makes it impossible for one session's ending to suppress the next
  // one's beginning.
  //
  // `retiredUrl` is "this session is no longer showable", from any of the three closers
  // below. They are one piece of state because the renderer does not care WHICH fired:
  // the frame comes out of the DOM either way, and the difference between "it never
  // loaded", "we stopped hearing about it" and "Browserbase has certainly killed it by
  // now" is a comment, not a rendering decision.
  const [retiredUrl, setRetiredUrl] = useState<string | null>(null);
  // ...and `closedUrl` is "we have already said goodbye to this session", so the ending
  // note plays exactly once and then the section is genuinely gone.
  const [closedUrl, setClosedUrl] = useState<string | null>(null);

  // LOAD WATCHDOG — the only way to notice a frame that never arrives.
  //
  // `onError` on an <iframe> is DEAD CODE in React and looks like it works: react-dom
  // 19 registers non-delegated listeners per tag, and its `iframe` case attaches `load`
  // and nothing else (`error` is wired for img/image/embed/source/link only). So the
  // obvious guard never fires — not rarely, never — and neither would a hand-rolled one
  // in the general case, because a cross-origin host that answers with an error PAGE
  // fires `load` like any successful navigation. There is no reachable signal that says
  // "this failed".
  //
  // What is reachable is `load` itself, so the question is inverted: not "did it fail?"
  // but "has anything arrived at all?" A frame that has produced no `load` by the time
  // the capture it is narrating is a third over has nothing in it, and an empty 16:10
  // box is the dead space this whole component is about. It gets taken away.
  //
  // The window is generous ON PURPOSE. A slow frame that lands at 11s loses the rest of
  // a ~30s session, which costs the user some of a garnish; a window tight enough to
  // fire on a merely-slow load would delete the feature on every slow connection.
  useEffect(() => {
    if (url === null || url === loadedUrl) {
      return undefined;
    }
    const timer = setTimeout(() => setRetiredUrl(url), FRAME_LOAD_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [url, loadedUrl]);

  // THE LEASE — see `LIVE_VIEW_TRUST_MS`. Re-armed by every payload that lands carrying
  // this URL, because `receivedAt` changes on every fulfilled poll even when nothing
  // else in the row did; a poll that FAILS leaves it exactly where it was, which is the
  // whole mechanism. Measured from this effect rather than from `receivedAt` itself so
  // that nothing here reads a clock — the few milliseconds of render lag are noise
  // against a six-second window.
  //
  // A retired session is NOT un-retired by a poll that recovers and still carries the
  // URL. That is deliberate: the recovered payload is itself one poll behind, so
  // remounting on it would be guessing again, and the visible result of guessing wrong
  // is the frame flickering back to show someone else's error. The live view is a
  // garnish; losing the tail of one on a run that already had a network hiccup costs
  // nothing worth a flicker.
  useEffect(() => {
    if (url === null || receivedAt === 0) {
      return undefined;
    }
    const timer = setTimeout(() => setRetiredUrl(url), LIVE_VIEW_TRUST_MS);
    return () => clearTimeout(timer);
  }, [url, receivedAt]);

  // THE SESSION CEILING — see `LIVE_VIEW_SESSION_TTL_MS`. Armed once per URL and never
  // renewed, because it is a fact about the hosted session rather than about us: no
  // amount of polling makes a Browserbase session outlive the `timeout` we opened it
  // with.
  useEffect(() => {
    if (url === null) {
      return undefined;
    }
    const timer = setTimeout(() => setRetiredUrl(url), LIVE_VIEW_SESSION_TTL_MS);
    return () => clearTimeout(timer);
  }, [url]);

  const liveUrl = url !== null && url !== retiredUrl ? url : null;

  // THE FAST PATH — see `LIVE_VIEW_DISCONNECT_MESSAGE`. The frame announces its own dead
  // socket, and this is the only closer in the component that fires AT the disconnect
  // rather than at the next poll: it is what stops the user reading "Debugging connection
  // was closed" at all on the ordinary run, instead of reading it for a second or two.
  //
  // Everything about it is deliberately paranoid, because it is a message from someone
  // else's page and it is sent with `targetOrigin: "*"` — i.e. anything that can post
  // into our window can imitate it. So: the origin must equal the origin of the frame WE
  // mounted (derived, not an allowlist, and never `*`), the payload must be that exact
  // string — a strict `!==` against a string literal, which is also the `typeof` check —
  // and the listener exists only while there is a frame to retire. Anything failing
  // either test is ignored silently, with no logging and no second interpretation,
  // because the cost of acting on a wrong message is deleting a live view somebody is
  // watching.
  //
  // `event.source` is deliberately NOT also checked: the origin test already means the
  // sender is a browserbase.com document inside our page, there is exactly one of those
  // and we put it there, and a ref read purely to re-prove that buys nothing.
  //
  // NOT AUTHORITATIVE, and this file does not lean on it — see
  // `LIVE_VIEW_DISCONNECT_MESSAGE` for why. If it stops arriving the lease below still
  // closes the frame; the only thing lost is the milliseconds.
  useEffect(() => {
    if (liveUrl === null) {
      return undefined;
    }
    const origin = liveViewOrigin(liveUrl);
    if (origin === null) {
      return undefined;
    }
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== origin || event.data !== LIVE_VIEW_DISCONNECT_MESSAGE) {
        return;
      }
      setRetiredUrl(liveUrl);
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [liveUrl]);

  // THE GOODBYE, and it is owed only to a session the user actually SAW. `loadedUrl` is
  // set by the iframe's own `load`, so a frame that never painted anything gets no note
  // — there is nothing for "it ended" to refer to, and the empty box just goes.
  const ending = liveUrl === null && running && loadedUrl !== null && loadedUrl !== closedUrl;

  // The hold, then the section closes itself. The write is in the TIMER's callback and
  // not in this effect's body: `react-hooks/set-state-in-effect` forbids the synchronous
  // form, and it is right to — the same rule `DiscoveryNetworkLog`'s narrowing follows.
  useEffect(() => {
    if (!ending) {
      return undefined;
    }
    const timer = setTimeout(() => setClosedUrl(loadedUrl), LIVE_VIEW_ENDED_HOLD_MS);
    return () => clearTimeout(timer);
  }, [ending, loadedUrl]);

  const phase: LiveViewPhase = liveUrl !== null ? 'live' : ending ? 'ending' : 'gone';

  // `unmountOnExit` keeps the section's children alive for the ~300ms the outer
  // `Collapse` takes to close, so "which line heads this section" is a question that
  // outlives `phase` and has to be answered for the exit too. A run that ends without a
  // goodbye collapses with its toggle, exactly as it always did; a run that said goodbye
  // collapses with the goodbye, rather than flashing the toggle back for the last frames
  // of a session that is over.
  const headedByGoodbye =
    phase === 'ending' || (phase === 'gone' && closedUrl !== null && closedUrl === loadedUrl);

  return (
    <Collapse in={phase !== 'gone'} unmountOnExit>
      <Box sx={{ mt: 1.5 }} data-testid="discovery-live-view-section">
        {!headedByGoodbye ? (
          <Button
            size="small"
            onClick={() => setOpen((isOpen) => !isOpen)}
            aria-expanded={open}
            data-testid="discovery-live-view-toggle"
          >
            {open ? 'Hide live view' : 'Watch live'}
          </Button>
        ) : (
          // IN THE TOGGLE'S PLACE, not under it: a "Hide live view" button for a frame
          // that no longer exists is a control over nothing, and swapping one line for
          // another keeps the row height steady while the box below it slides shut.
          <Typography
            variant="caption"
            color="text.secondary"
            role="status"
            data-testid="discovery-live-view-ended"
            sx={{ ...ENDED_NOTE_ANIMATION, display: 'block', px: 0.5, py: 0.75 }}
          >
            Live view ended — still setting up.
          </Typography>
        )}
        {/* `phase !== 'ending'` rather than `phase === 'live'`, which is not the same
            thing on the last beat: when the run itself ends there is no note, so the box
            must HOLD its height and let the outer `Collapse` perform the whole close in
            one movement. Closing both at once there would collapse 375px twice as fast
            as everything else this panel does. During `ending` the inner one closes
            first on purpose — the video slides away, the line stays behind to say why. */}
        <Collapse in={open && phase !== 'ending'}>
          <Box
            // `pointer-events: none` — read-only by construction. This is someone
            // else's hosted browser session; it is here to be watched, never driven.
            data-testid="discovery-live-view-frame"
            sx={{
              mt: 1,
              pointerEvents: 'none',
              position: 'relative',
              width: '100%',
              aspectRatio: '16 / 10',
              overflow: 'hidden',
              borderRadius: 1,
            }}
          >
            {liveUrl ? (
              <Box
                component="iframe"
                src={liveViewSrc(liveUrl)}
                title="Live view of the setup session"
                sandbox="allow-scripts allow-same-origin"
                onLoad={() => setLoadedUrl(liveUrl)}
                data-testid="discovery-live-view"
                sx={{ width: '100%', height: '100%', border: 0 }}
              />
            ) : null}
          </Box>
        </Collapse>
      </Box>
    </Collapse>
  );
}

/**
 * The status to RENDER for a step, given how the whole run ended.
 *
 * A discovery TIMEOUT deliberately writes no terminal checklist — the last live snapshot
 * survives beside `health_state='refused'`, because how far we got is the useful part.
 * That snapshot still names a step `active`, and an animated spinner on a run that has
 * already terminated makes one row read as finished and still working at the same time.
 * A terminal run therefore draws a leftover `active` step as `pending`: the rung we never
 * got past, not a rung still in flight.
 */
function renderedStatus(step: DiscoveryStep, outcome: DiscoveryOutcomeState): RenderedStatus {
  // `first_scan` is settled by the FIRST HARVEST, a different run that starts after
  // discovery has already reached its terminal outcome ('tracking'/'partial'). So it is
  // the one rung that is legitimately `active` while the outcome is not `running`, and
  // downgrading it would draw a grey circle over the only thing still happening.
  if (step.key === 'first_scan') {
    // THE RUNG THE CHIP WAS ARGUING WITH. On a partial board this one says "Fetching all
    // current jobs" and it did not fetch all of them — a plain ✓ here is the reason five
    // green ticks sat under a chip saying we only read part of the board, and the reason
    // the chip read as a malfunction. ONLY this rung: the four above it are about
    // CAPABILITY (we opened the page, we read jobs, we built a scraper, we're ready) and
    // every one of them fully succeeded. This one is about COVERAGE, and coverage is what
    // is partial. Marking all five would qualify four true things to fix one false one,
    // and would cost the list the scannability it was cut back to get.
    if (step.status === 'done' && outcome === 'partial') return 'partial';
    // A FIRST HARVEST THAT FAILED IS NOT AN ERROR THE READER OWNS, and it used to draw
    // the same red ✕ a refusal draws — under a chip that said "Successfully tracking",
    // which is the badge-versus-rungs contradiction again, pointing the other way. The
    // board is tracked, the scheduler retries tonight, and there is no button, no URL to
    // change, nothing. So it renders as the rung we have not got past yet, with the
    // backend's own "we will try again" underneath it in plain grey.
    //
    // ONLY on a run that was not refused: a refusal genuinely is red, and its ✕ is the
    // one thing that tells the reader their pasted URL was the wrong page.
    if (step.status === 'failed' && outcome !== 'refused') return 'waiting';
    return step.status;
  }
  return outcome !== 'running' && step.status === 'active' ? 'pending' : step.status;
}

/**
 * The ONE line a rung may carry under its label, or null for the usual silence.
 *
 * Three sources, one slot, so no rung can ever show two:
 *  - `failed` / `waiting` — the step's own `result`, which is the reason. On the ✕ it
 *    says whether the board is unreadable or the pasted URL was the wrong page; on the ○
 *    it says why tonight's harvest came back empty.
 *  - `partial` — the board's own numbers (`describePartialScope`), which is the entire
 *    content of the claim the chip above makes.
 *  - everything else — nothing. A ✓'s `result` is engine telemetry ("recorded 14 JSON
 *    request(s)", "found 3 candidate feed(s)"): it names our internals rather than
 *    anything the reader can act on, and one under every rung turned a 5-line list into
 *    a 10-line one.
 */
function stepDetail(
  step: DiscoveryStep,
  status: RenderedStatus,
  scope: string | null
): string | null {
  if (status === 'partial') return scope;
  if (status === 'failed' || status === 'waiting') return step.result;
  return null;
}

function StepRow({
  step,
  status,
  detail,
}: {
  step: DiscoveryStep;
  status: RenderedStatus;
  detail?: string | null;
}) {
  const mark = STEP_MARK[status] ?? '○';
  return (
    <Stack
      direction="row"
      spacing={1}
      alignItems="flex-start"
      data-testid={`discovery-step-${step.key}`}
    >
      <Box sx={{ width: 20, flexShrink: 0, textAlign: 'center', lineHeight: '1.5rem' }}>
        {status === 'active' ? (
          <CircularProgress size={12} aria-label="in progress" />
        ) : (
          <Typography component="span" color={STEP_COLOR[status] ?? 'text.disabled'}>
            {mark}
          </Typography>
        )}
      </Box>
      <Box sx={{ minWidth: 0 }}>
        <Typography
          variant="body2"
          color={status === 'pending' ? 'text.disabled' : 'text.primary'}
          sx={{ fontWeight: status === 'active' ? 600 : 400 }}
        >
          {describeDiscoveryStep(step)}
        </Typography>
        {/* One slot, one line, whatever fed it — see `stepDetail`. The COLOUR is the
            decision here: alarm red only on a genuine ✕, because that is the only one of
            these the reader can do anything about. */}
        {detail ? (
          <Typography
            variant="caption"
            color={STEP_DETAIL_COLOR[status] ?? 'text.secondary'}
            sx={{ display: 'block', overflowWrap: 'anywhere' }}
            data-testid={`discovery-result-${step.key}`}
          >
            {detail}
          </Typography>
        ) : null}
      </Box>
    </Stack>
  );
}

/**
 * The one thing that changes the answer when we could not read a board.
 *
 * Deliberately NOT a retry button. Discovery is deterministic: the same URL runs the
 * same capture and reaches the same refusal, so "try again" spends a browser session
 * and an LLM call to reproduce the answer the user already has.
 *
 * ONE action, not the three this used to list. "Remove it" restated the Remove button
 * sitting a few pixels above; "tell us about this board" survives as a caption because
 * it is the only escape hatch for a board we genuinely cannot support, but it is not a
 * peer of the action that actually fixes most refusals — the pasted URL being a
 * marketing careers page rather than the job listings themselves.
 */
function NextActions({ boardUrl }: { boardUrl: string }) {
  return (
    <Box sx={{ mt: 1.5 }} data-testid="discovery-next-actions">
      <Typography variant="body2">
        Careers pages often hide the real board behind a “See open roles” link. Open{' '}
        <Link href={boardUrl} target="_blank" rel="noopener noreferrer">
          the page you pasted
        </Link>
        , click into a job, and paste that address instead.
      </Typography>
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
        Or{' '}
        <Link component={RouterLink} to={ROUTES.VOTE_FEATURES}>
          tell us about this board
        </Link>
        .
      </Typography>
    </Box>
  );
}

interface DiscoveryChecklistProps {
  company: UserCompany;
  /**
   * When the payload carrying `company` landed — RTK Query's `fulfilledTimeStamp`, the
   * same value the row's freshness line and the poll cadence already take, and for the
   * same reason: reading the clock during render is impure and lint-blocked.
   *
   * REQUIRED rather than optional, even though only the live view consumes it. It is the
   * heartbeat that keeps the live view mounted (`LIVE_VIEW_TRUST_MS`), so a caller that
   * forgot to pass it would silently get a frame that outlives its session — the exact
   * bug this prop exists to close. A type error is the right way to find that out.
   */
  receivedAt: number;
}

/**
 * The 5-step discovery checklist that replaced the "Setting up…" spinner — now an
 * ACCORDION, headed by the one sentence that says how the board turned out.
 *
 * Because the capture engine's steps are deterministic and known before the run
 * starts, they can be named up front and ticked off as they land: opening the page →
 * reading jobs → building web scraper → ready to track → fetching all current jobs.
 *
 * ONE heading, five rungs, and — on a refusal only — the reason and the one action
 * that changes it. The version before this said the same thing four times over: a
 * headline, a one-line ✓/✕ chain of the same steps, the steps themselves with a line
 * of engine telemetry under each, and a three-bullet "What you can do". Everything a
 * reader cannot act on has been cut; what is left is the narration and the error.
 *
 * THE ACCORDION IS WHAT LETS THE EVIDENCE STAY. This panel used to delete itself the
 * moment the first harvest landed, because a permanent setup receipt on every row is
 * clutter — and it was, while it was always expanded. Folded, a settled row costs one
 * line, and in exchange the record of HOW we read a board (which request we picked out
 * of sixteen, the JSON it returned) stops vanishing. It never was deleted server-side;
 * it is 5 KB sitting in `provider_config->'discovery'` surviving every reload, and a
 * panel that disappears is indistinguishable from data that was thrown away.
 *
 * OPEN while something is still happening or something went wrong, CLOSED once the row
 * has settled — `shouldExpandDiscovery` is the whole of that rule, and it is read once
 * on mount so nothing snaps shut under a reader.
 *
 * Then, in order: the live view while there is a browser to watch, and under it the
 * network log (`DiscoveryNetworkLog`) — open, streaming, and narrowing to the one
 * request we picked as soon as there is one. The log used to sit above the frame and
 * start closed; both were wrong. Above, it pushed the only watchable thing on the page
 * down as rows arrived; closed, it hid the arriving rows, which are the streaming.
 * Narrowing is what keeps that affordable: many rows while we are working, one row and
 * its JSON once we are done.
 *
 * Presentational and flag-free: the caller decides whether the feature is on. It reads
 * only `company`, whose `discovery` blob arrives on the list poll the page already runs
 * — there is no second polling channel and no fetching here.
 *
 * The live view is OPTIONAL and degrades silently (DECISION D4): only a Browserbase
 * capture has one and our default is our own Chromium, so on almost every run there is
 * no iframe, no toggle, and a checklist that renders exactly as it always has — no
 * empty box, no reserved space, no layout shift.
 *
 * When there IS one it opens EXPANDED, because the thing it shows lasts about thirty
 * seconds: a hosted session is watchable only while the capture is running, and a run
 * that ends before the user notices a "Watch live" button showed them nothing. The
 * toggle stays so it can be collapsed, and the frame is `pointer-events: none` either
 * way — this is someone else's browser, here to be watched and never driven.
 *
 * And it is watchable for the CAPTURE, not for the run: the browser is handed back
 * roughly a third of the way through, and the backend nulls the URL in the same write.
 * `watchableLiveViewUrl` is the whole of that rule; see it for why we consume that null
 * instead of guessing at it from the checklist.
 */
export function DiscoveryChecklist({ company, receivedAt }: DiscoveryChecklistProps) {
  // READ ONCE, on mount. `shouldExpandDiscovery` flips when the first harvest lands, and
  // a panel that slammed shut under a reader mid-sentence — while they watched the rung
  // it belongs to tick over — would be the worst possible moment to take it away. The
  // initial value decides; after that the panel is the reader's.
  const [open, setOpen] = useState(() => shouldExpandDiscovery(company));
  const discovery = company.discovery;
  if (!discovery) {
    return null;
  }

  const outcome = resolveDiscoveryOutcome(company);
  const failed = failedDiscoveryStep(discovery);
  const scope = describePartialScope(company);

  return (
    <Paper
      variant="outlined"
      sx={{ mt: 1.5, p: 1.5, bgcolor: 'action.hover' }}
      data-testid="discovery-checklist"
      data-outcome={outcome}
      data-open={open ? 'true' : 'false'}
    >
      {/* THE SUMMARY, and the whole of a settled row. Same caret and same ButtonBase as
          `DiscoveryNetworkLog`'s own toggle one level down, so the panel reads as one
          system of disclosures rather than two components that each invented a chevron.
          The heading is the summary — there is no second "Setup details" vocabulary to
          learn, and the line a collapsed row keeps forever is the one sentence that says
          how this board turned out. */}
      <ButtonBase
        onClick={() => setOpen((isOpen) => !isOpen)}
        aria-expanded={open}
        data-testid="discovery-toggle"
        sx={{
          width: '100%',
          justifyContent: 'flex-start',
          alignItems: 'flex-start',
          borderRadius: 1,
          px: 0.5,
          py: 0.25,
          textAlign: 'left',
          // On a settled row this line IS the panel, so it has to read as pressable. The
          // caret alone is the affordance one level down, where the log sits inside an
          // already-open box; out here it is the only control and gets a hover ground
          // too. `action.selected` because the Paper under it is already `action.hover`.
          '&:hover': { bgcolor: 'action.selected' },
        }}
      >
        <Typography
          component="span"
          aria-hidden
          sx={{ mr: 0.75, color: 'text.secondary', fontSize: '0.7rem', lineHeight: 1.9 }}
        >
          {open ? '▾' : '▸'}
        </Typography>
        <Typography variant="subtitle2" data-testid="discovery-headline">
          {describeDiscoveryOutcome(company)}
        </Typography>
      </ButtonBase>

      {/* `unmountOnExit`: a closed row is NOTHING, not a hidden checklist plus forty
          hidden request nodes plus an iframe still holding someone else's browser
          session. That is what makes it affordable to keep the evidence on every tracked
          row forever (`shouldShowDiscovery`) — the cost of a settled row is one line. */}
      <Collapse in={open} unmountOnExit>
        <Stack spacing={0.75} sx={{ mt: 0.75 }}>
          {discovery.steps.map((step) => {
            const status = renderedStatus(step, outcome);
            return (
              <StepRow
                key={step.key}
                step={step}
                status={status}
                detail={stepDetail(step, status, scope)}
              />
            );
          })}
        </Stack>

        {outcome === 'refused' ? (
          <>
            {/* A timeout fails no step, so there is nothing to name — say that plainly
                rather than leaving the user staring at four unresolved rungs. */}
            {failed === null ? (
              <Typography
                variant="body2"
                color="error.main"
                sx={{ mt: 1.5 }}
                data-testid="discovery-stalled"
              >
                This setup stopped before it could finish.
              </Typography>
            ) : null}
            <NextActions boardUrl={company.boardToken} />
          </>
        ) : null}

        {/* Rendered UNCONDITIONALLY, and empty until there is something to watch. The
          section owns its own exit animation, so it has to outlive the URL that feeds
          it by the length of that animation — a `{url ? <LiveView/> : null}` here would
          tear the whole subtree out before it could play, which is the snap it exists
            to avoid. With no URL it renders nothing at all. */}
        <LiveView
          url={watchableLiveViewUrl(company)}
          running={outcome === 'running'}
          receivedAt={receivedAt}
        />

        {/* THE EVIDENCE, UNDER the live view — which is the ordering, not an accident.
          While a browser is open the frame is the headline (it is the thing the user
          can literally watch) and the requests are what that browser is producing, so
          they read as the record beneath it. With the log above, the frame kept getting
          pushed down the page by rows arriving underneath the reader's eye.

            Below the refusal copy for the same reason: on a refusal there is no live view
            at all, the reader needs the verdict and the one action that changes it first,
            and the log is what they read when that action does not obviously apply to
            their board. It renders nothing until the capture has recorded a request, so a
            run that has not opened the page yet — and a page that never fetched any JSON
            — adds no line and reserves no space. */}
        <DiscoveryNetworkLog company={company} />
      </Collapse>
    </Paper>
  );
}
