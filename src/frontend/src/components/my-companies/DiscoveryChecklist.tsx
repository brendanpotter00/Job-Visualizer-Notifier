import { useState } from 'react';
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
 * Presentational and flag-free: the caller decides whether the feature is on. It reads
 * only `company`, whose `discovery` blob arrives on the list poll the page already runs
 * — there is no second polling channel and no fetching here.
 *
 * The live view is OPTIONAL and degrades silently (DECISION D4): only a Browserbase
 * capture has one and our default is our own Chromium, so on almost every run there is
 * no iframe, no toggle, and a checklist that renders exactly as it always has — no
 * empty box, no reserved space, no layout shift.
 *
 * When there IS one it opens EXPANDED, because the thing it shows lasts about a minute:
 * a hosted session is watchable only while the capture is running, and a run that ends
 * before the user notices a "Watch live" button showed them nothing. The toggle stays
 * so it can be collapsed, and the frame is `pointer-events: none` either way — this is
 * someone else's browser, here to be watched and never driven.
 */
export function DiscoveryChecklist({ company }: DiscoveryChecklistProps) {
  const [liveOpen, setLiveOpen] = useState(true);
  const discovery = company.discovery;
  if (!discovery) {
    return null;
  }

  const outcome = resolveDiscoveryOutcome(company);
  const failed = failedDiscoveryStep(discovery);
  const liveViewUrl = outcome === 'running' ? discovery.liveViewUrl : null;

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

      {liveViewUrl ? (
        <Box sx={{ mt: 1.5 }}>
          <Button
            size="small"
            onClick={() => setLiveOpen((open) => !open)}
            aria-expanded={liveOpen}
            data-testid="discovery-live-view-toggle"
          >
            {liveOpen ? 'Hide live view' : 'Watch live'}
          </Button>
          <Collapse in={liveOpen}>
            <Box
              // `pointer-events: none` — read-only by construction. This is someone
              // else's hosted browser session; it is here to be watched, never driven.
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
              <Box
                component="iframe"
                src={liveViewSrc(liveViewUrl)}
                title="Live view of the setup session"
                sandbox="allow-scripts allow-same-origin"
                data-testid="discovery-live-view"
                sx={{ width: '100%', height: '100%', border: 0 }}
              />
            </Box>
          </Collapse>
        </Box>
      ) : null}
    </Paper>
  );
}
