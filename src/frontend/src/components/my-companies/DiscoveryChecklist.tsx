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
  scope: string | null,
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
export function DiscoveryChecklist({ company }: DiscoveryChecklistProps) {
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
      </Collapse>
    </Paper>
  );
}
