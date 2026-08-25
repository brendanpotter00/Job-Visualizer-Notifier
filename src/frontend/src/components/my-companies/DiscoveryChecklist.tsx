import { useEffect, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
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
  describeDiscoveryOutcome,
  describeDiscoveryStep,
  failedDiscoveryStep,
  resolveDiscoveryOutcome,
  watchableLiveViewUrl,
} from './companyHealth';

/** Status glyph per step. Text, not icons, so the state survives a screenshot. */
const STEP_MARK: Record<DiscoveryStep['status'], string> = {
  pending: '○',
  active: '',
  done: '✓',
  failed: '✕',
};

const STEP_COLOR: Record<DiscoveryStep['status'], string> = {
  pending: 'text.disabled',
  active: 'text.primary',
  done: 'success.main',
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

/** How long a live-view frame may show nothing before we take its space back. */
const FRAME_LOAD_TIMEOUT_MS = 10_000;

/**
 * The optional "watch it happen" panel, and — more importantly — the thing that takes
 * itself away again.
 *
 * `url` is `watchableLiveViewUrl`, which is non-null only while a browser is genuinely
 * open — the backend now clears `live_view_url` in the same write that releases the
 * session, so that is a published fact rather than something inferred from step state.
 * (It was inferred once, from `open_page` being `active`, and a screenshot killed it:
 * that step was still bold and spinning while the frame under it already read "WebSocket
 * disconnected". The socket dies with the browser, before the step ticks.) Everything
 * here keys off that ONE fact, in two different ways on purpose:
 *
 * - The IFRAME is gated on it directly, so it unmounts in the very same render the
 *   session ends. Not hidden, not zero-height, not `display: none` — GONE. While it is
 *   mounted it is Browserbase's page, free to paint whatever it likes into our layout,
 *   and what it paints over a released session is "WebSocket disconnected" in their
 *   voice. There is no styling that answers that; only unmounting does.
 * - The SECTION is gated on it through a `Collapse`, so ~375px of frame does not
 *   vanish from under a checklist the user is mid-read. `unmountOnExit` is what makes
 *   the collapsed state truly nothing rather than a 0px box: react-transition-group
 *   returns `null` once the exit settles, so the common case — our own Chromium, which
 *   has no hosted view at all — renders not one node and reserves not one pixel.
 *
 * The sized wrapper stays mounted through the exit while the frame inside it does not.
 * That is deliberate and it is what makes the two gates cooperate: `Collapse` measures
 * the wrapper to know what height to animate down FROM, so dropping the frame without
 * it would collapse 375px→36px instantly and then animate the leftover — a jump, then
 * a slide. Empty, it holds the shape for ~300ms and closes.
 *
 * A frame that never loads is treated as a session that ended — see LOAD WATCHDOG. All
 * three "nothing to show" states are recorded as the URL they refer to rather than as a
 * boolean, so no verdict can outlive its own session and suppress the next one.
 */
function LiveView({ url }: { url: string | null }) {
  const [open, setOpen] = useState(true);
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null);
  const [deadUrl, setDeadUrl] = useState<string | null>(null);

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
    const timer = setTimeout(() => setDeadUrl(url), FRAME_LOAD_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [url, loadedUrl]);

  const liveUrl = url !== null && url !== deadUrl ? url : null;

  return (
    <Collapse in={liveUrl !== null} unmountOnExit>
      <Box sx={{ mt: 1.5 }} data-testid="discovery-live-view-section">
        <Button
          size="small"
          onClick={() => setOpen((isOpen) => !isOpen)}
          aria-expanded={open}
          data-testid="discovery-live-view-toggle"
        >
          {open ? 'Hide live view' : 'Watch live'}
        </Button>
        <Collapse in={open}>
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
function renderedStatus(
  step: DiscoveryStep,
  outcome: DiscoveryOutcomeState,
): DiscoveryStep['status'] {
  // `first_scan` is settled by the FIRST HARVEST, a different run that starts after
  // discovery has already reached its terminal outcome ('tracking'/'partial'). So it is
  // the one rung that is legitimately `active` while the outcome is not `running`, and
  // downgrading it would draw a grey circle over the only thing still happening.
  if (step.key === 'first_scan') return step.status;
  return outcome !== 'running' && step.status === 'active' ? 'pending' : step.status;
}

function StepRow({ step, status }: { step: DiscoveryStep; status: DiscoveryStep['status'] }) {
  const mark = STEP_MARK[status] ?? '○';
  return (
    <Stack direction="row" spacing={1} alignItems="flex-start" data-testid={`discovery-step-${step.key}`}>
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
        {/* The step's `result` is rendered ONLY on the ✕, where it is the error message.
            On a ✓ it is engine telemetry — "recorded 14 JSON request(s)", "found 3
            candidate feed(s)" — which named our internals rather than anything the reader
            can act on, and put a second line of jargon under every rung of a list whose
            whole job is being scannable. On the failed step it is the one thing that says
            whether this board is unreadable or the pasted URL was the wrong page. */}
        {status === 'failed' && step.result ? (
          <Typography
            variant="caption"
            color="error.main"
            sx={{ display: 'block', overflowWrap: 'anywhere' }}
            data-testid={`discovery-result-${step.key}`}
          >
            {step.result}
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
}

/**
 * The 4-step discovery checklist that replaced the "Setting up…" spinner.
 *
 * Because the capture engine's steps are deterministic and known before the run
 * starts, they can be named up front and ticked off as they land: opening the page →
 * reading jobs → building web scraper → ready to track.
 *
 * ONE heading, four rungs, and — on a refusal only — the reason and the one action
 * that changes it. The version before this said the same thing four times over: a
 * headline, a one-line ✓/✕ chain of the same steps, the steps themselves with a line
 * of engine telemetry under each, and a three-bullet "What you can do". Everything a
 * reader cannot act on has been cut; what is left is the narration and the error.
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
export function DiscoveryChecklist({ company }: DiscoveryChecklistProps) {
  const discovery = company.discovery;
  if (!discovery) {
    return null;
  }

  const outcome = resolveDiscoveryOutcome(company);
  const failed = failedDiscoveryStep(discovery);

  return (
    <Paper
      variant="outlined"
      sx={{ mt: 1.5, p: 1.5, bgcolor: 'action.hover' }}
      data-testid="discovery-checklist"
      data-outcome={outcome}
    >
      <Typography variant="subtitle2" gutterBottom data-testid="discovery-headline">
        {describeDiscoveryOutcome(company)}
      </Typography>

      <Stack spacing={0.75}>
        {discovery.steps.map((step) => (
          <StepRow key={step.key} step={step} status={renderedStatus(step, outcome)} />
        ))}
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
      <LiveView url={watchableLiveViewUrl(company)} />

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
    </Paper>
  );
}
